#!/usr/bin/env python3
# ----------------------------------------------------------------------------
# run_matrix.py — synthetic benchmark matrix
#
# References:
#   - Craig Gotsman, Michael Lindenbaum, On the Metric Properties of Discrete
#     Space-Filling Curves, 1996, DOI: 10.1109/83.499920.
#   - Maurice G. Kendall, A New Measure of Rank Correlation, 1938,
#     DOI: 10.1093/biomet/30.1-2.81.
#   - Linux man-pages project, perf-stat command documentation, 2026.
# ----------------------------------------------------------------------------
"""Run synthetic benchmark matrices through the C++ `rch_order` CLI.

Public API: `run_matrix(args)` Facade returns the results CSV path; helper
functions are exported for unit-testing in `tests/python/test_synthetic_pipeline.py`.

Algorithm:
  1. Expand runlists into A x C x D x E x N x seed cells.
  2. Generate clean/contaminated point clouds and invoke ordering backends.
  3. Read emitted permutations/manifests, compute requested locality/stability
     metrics, and write deterministic CSV plus provenance manifest.
"""

from __future__ import annotations

import argparse
import csv
import heapq
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import product
from pathlib import Path
from typing import Any

import yaml

try:
    import resource
except ImportError:  # pragma: no cover - non-POSIX fallback
    resource = None  # type: ignore[assignment]

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data.synthetic.generators.contamination import contaminate  # noqa: E402
from data.synthetic.generators.gaussian_ellipsoid import (
    GEOMETRY_AXES,
    ellipsoid_points,
)  # noqa: E402
from data.synthetic.generators.common import Point, write_xyz_csv  # noqa: E402
from data.synthetic.generators.surface_patch import patch_points  # noqa: E402
from data.synthetic.generators.torus import torus_points  # noqa: E402
from data.synthetic.generators.cylinder import cylinder_points  # noqa: E402
from data.synthetic.generators.mixed_density import mixture_points  # noqa: E402


def display_path(path: Path | None) -> str:
    """Return repo-relative paths for generated CSV/JSON metadata."""
    if path is None:
        return ""
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return path.name if path.is_absolute() else str(path)


def safe_path_component(value: object, field_name: str) -> str:
    """Return one YAML id as a single filesystem path component."""
    component = str(value)
    if (
        not component
        or component in {".", ".."}
        or "/" in component
        or "\\" in component
        or Path(component).is_absolute()
        or len(Path(component).parts) != 1
    ):
        raise ValueError(f"{field_name} must be a single path component: {component!r}")
    return component


@dataclass(frozen=True)
class MatrixCase:
    """One A × C × D × E × N × seed benchmark cell."""

    algorithm: dict[str, Any]
    bit_rule: dict[str, Any]
    contamination: dict[str, Any]
    geometry: dict[str, Any]
    point_count: int
    seed: int


@dataclass(frozen=True)
class PerfCounters:
    """M8 perf-stat result for one block-read probe run."""

    status: str
    cache_references: int | None = None
    cache_misses: int | None = None

    @property
    def miss_rate(self) -> float | None:
        """Return cache_misses/cache_references when both counters are usable."""
        if (
            self.cache_references is None
            or self.cache_misses is None
            or self.cache_references <= 0
        ):
            return None
        return self.cache_misses / float(self.cache_references)


def load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML artifact and fail closed on non-mapping roots."""
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"expected mapping YAML at {path}")
    return data


def load_algorithm_configs(config_dir: Path) -> dict[str, dict[str, Any]]:
    """Load Synthetic algorithm configs from experiments/configs/algorithms."""
    algorithms: dict[str, dict[str, Any]] = {}
    for path in sorted(config_dir.glob("*.yaml")):
        data = load_yaml(path)
        algorithm_id = data.get("id")
        if not isinstance(algorithm_id, str) or not algorithm_id:
            raise ValueError(f"algorithm config id must be a non-empty string: {path}")
        if algorithm_id in algorithms:
            raise ValueError(f"duplicate algorithm config id {algorithm_id!r}: {path}")
        algorithms[algorithm_id] = data
    return algorithms


def load_sweep_items(path: Path, key: str) -> dict[str, dict[str, Any]]:
    """Load E-axis or D-axis items from a sweep YAML file."""
    data = load_yaml(path)
    items = data.get(key)
    if not isinstance(items, list):
        raise ValueError(f"expected list key {key!r} in {path}")
    keyed: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            raise ValueError(f"sweep item must be a mapping in {path}: {item!r}")
        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id:
            raise ValueError(f"sweep item id must be a non-empty string in {path}")
        if item_id in keyed:
            raise ValueError(f"duplicate sweep item id {item_id!r} in {path}")
        keyed[item_id] = item
    return keyed


REFINEMENT_SWEEP_PATH = REPO_ROOT / "experiments/configs/sweeps/refinement.yaml"


def load_refinement_modes(path: Path = REFINEMENT_SWEEP_PATH) -> tuple[list[str], str]:
    """Load the R-axis refinement-ablation arms and their default mode."""
    config = load_yaml(path)
    if config.get("schema") != "rch.sweep.refinement.v1":
        raise ValueError(f"unexpected refinement sweep schema in {path}")
    entries = config.get("modes")
    if not isinstance(entries, list) or not entries:
        raise ValueError(f"refinement sweep must list modes: {path}")
    modes: list[str] = []
    for entry in entries:
        mode_id = entry.get("id") if isinstance(entry, dict) else None
        # YAML parses an unquoted `off` as a boolean, so the id type matters.
        if not isinstance(mode_id, str) or not mode_id:
            raise ValueError(
                f"refinement mode ids must be non-empty strings (quote 'off'): {path}"
            )
        modes.append(mode_id)
    if len(set(modes)) != len(modes):
        raise ValueError(f"refinement mode ids must be unique: {path}")
    default = config.get("default_mode")
    if default not in modes:
        raise ValueError(f"default_mode {default!r} is not a declared mode: {path}")
    return modes, default


def effective_refinement_for_method(method: str, refinement: str) -> str:
    """Return the CLI refinement mode for one method in the R-axis sweep."""
    if method == "input":
        return "off"
    return refinement


def resolve_rch_order(candidate: Path | None) -> Path:
    """Find the `rch_order` executable built from src/cli/rch_order.cpp."""
    if candidate is not None:
        if not (candidate.exists() and candidate.is_file()):
            raise FileNotFoundError(
                f"rch_order not found at explicit path: {candidate}"
            )
        return candidate
    for path in [
        REPO_ROOT / "build/release-clang/src/cli/rch_order",
        REPO_ROOT / "build/release/src/cli/rch_order",
        REPO_ROOT / "build/debug/src/cli/rch_order",
    ]:
        if path.exists() and path.is_file():
            return path
    raise FileNotFoundError("rch_order not found; build with -DRCH_BUILD_TOOLS=ON")


def resolve_block_read_probe(candidate: Path | None) -> Path | None:
    """Find the optional C++ block-read probe used by M8 perf counters."""
    if candidate is not None:
        if not (candidate.exists() and candidate.is_file()):
            raise FileNotFoundError(
                f"rch_block_read_probe not found at explicit path: {candidate}"
            )
        return candidate
    for path in [
        REPO_ROOT / "build/bench/src/cli/rch_block_read_probe",
        REPO_ROOT / "build/release-clang/src/cli/rch_block_read_probe",
        REPO_ROOT / "build/release/src/cli/rch_block_read_probe",
        REPO_ROOT / "build/debug/src/cli/rch_block_read_probe",
    ]:
        if path.exists() and path.is_file():
            return path
    return None


def resolve_cgal_adapter(candidate: Path | None) -> Path | None:
    """Find the optional A7 CGAL spatial_sort adapter executable."""
    if candidate is not None:
        if not (candidate.exists() and candidate.is_file()):
            raise FileNotFoundError(
                f"rch_cgal_spatial_sort not found at explicit path: {candidate}"
            )
        return candidate
    for path in [
        REPO_ROOT / "build/cgal-adapter/adapters/cgal/rch_cgal_spatial_sort",
        REPO_ROOT / "build/bench/adapters/cgal/rch_cgal_spatial_sort",
    ]:
        if path.exists() and path.is_file():
            return path
    return None


def parse_perf_stat(stderr: str) -> PerfCounters:
    """Parse `perf stat -x,` stderr for cache reference/miss counters."""
    counters: dict[str, int] = {}
    for line in stderr.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 3:
            continue
        event = parts[2]
        if "cache-references" in event:
            normalized_event = "cache-references"
        elif "cache-misses" in event:
            normalized_event = "cache-misses"
        else:
            continue
        raw_count = parts[0].replace(" ", "")
        if not raw_count or raw_count.startswith("<"):
            continue
        try:
            counters[normalized_event] = counters.get(normalized_event, 0) + int(
                raw_count
            )
        except ValueError:
            continue
    references = counters.get("cache-references")
    misses = counters.get("cache-misses")
    if references is None or misses is None:
        return PerfCounters(status="unparsed")
    return PerfCounters(status="ok", cache_references=references, cache_misses=misses)


def perf_unavailable_reason(stderr: str, returncode: int) -> str:
    """Compress perf stderr into a stable fail-closed status token."""
    text = stderr.lower()
    if "perf_event_paranoid" in text or "permission" in text or "not permitted" in text:
        return "perf_permission_denied"
    if returncode != 0:
        return f"perf_failed_{returncode}"
    return "perf_unavailable"


def prepare_perf_adapter(
    metrics: set[str],
    block_read_probe: Path | None,
    output_dir: Path,
) -> tuple[str, Path | None]:
    """Preflight optional M8 perf measurement and persist availability."""
    output_dir.mkdir(parents=True, exist_ok=True)
    wants_perf = bool({"cache_references", "cache_misses", "cache_miss_rate"} & metrics)
    status = "not_requested"
    perf_path = shutil.which("perf")
    if wants_perf:
        if block_read_probe is None:
            status = "block_read_probe_missing"
        elif perf_path is None:
            status = "perf_missing"
        else:
            completed = subprocess.run(
                [
                    perf_path,
                    "stat",
                    "-x,",
                    "-e",
                    "cache-references,cache-misses",
                    "true",
                ],
                check=False,
                cwd=REPO_ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            status = (
                "available"
                if completed.returncode == 0
                else perf_unavailable_reason(completed.stderr, completed.returncode)
            )
    (output_dir / "perf_status.json").write_text(
        json.dumps(
            {
                "schema": "rch.perf_status.v1",
                "status": status,
                "perf": display_path(Path(perf_path)) if perf_path else "",
                "block_read_probe": (
                    display_path(block_read_probe)
                    if block_read_probe is not None
                    else ""
                ),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return status, block_read_probe if status == "available" else None


def measure_block_read_perf(
    probe: Path | None,
    points_path: Path,
    order_path: Path,
    block_size: int = 32,
) -> PerfCounters:
    """Run the block-read probe under `perf stat` when available."""
    if probe is None:
        return PerfCounters(status="not_available")
    perf_path = shutil.which("perf")
    if perf_path is None:
        return PerfCounters(status="perf_missing")
    completed = subprocess.run(
        [
            perf_path,
            "stat",
            "-x,",
            "-e",
            "cache-references,cache-misses",
            "--",
            str(probe),
            "--points",
            str(points_path),
            "--order",
            str(order_path),
            "--block-size",
            str(block_size),
        ],
        check=False,
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        return PerfCounters(
            status=perf_unavailable_reason(completed.stderr, completed.returncode)
        )
    parsed = parse_perf_stat(completed.stderr)
    return parsed if parsed.status == "ok" else PerfCounters(status="perf_unparsed")


def expand_runlist(
    runlist: dict[str, Any],
    algorithms: dict[str, dict[str, Any]],
    contamination: dict[str, dict[str, Any]],
    geometries: dict[str, dict[str, Any]],
) -> list[MatrixCase]:
    """Expand a runlist into the A × C × D × E × N × seed matrix."""
    bit_rules = runlist.get("bit_rules", [])
    if not isinstance(bit_rules, list) or not bit_rules:
        raise ValueError("runlist requires a non-empty bit_rules list")
    cases: list[MatrixCase] = []
    for (
        algorithm_id,
        bit_rule,
        contamination_id,
        geometry_id,
        point_count,
        seed,
    ) in product(
        runlist["algorithm_ids"],
        bit_rules,
        runlist["contamination_ids"],
        runlist["geometry_ids"],
        runlist["point_counts"],
        runlist["seeds"],
    ):
        algorithm = algorithms[str(algorithm_id)]
        supported_bit_rules = algorithm.get("supported_bit_rules")
        if isinstance(supported_bit_rules, list) and str(bit_rule["id"]) not in {
            str(item) for item in supported_bit_rules
        }:
            continue
        cases.append(
            MatrixCase(
                algorithm,
                bit_rule,
                contamination[str(contamination_id)],
                geometries[str(geometry_id)],
                int(point_count),
                int(seed),
            )
        )
    return cases


def make_clean_points(
    geometry: dict[str, Any], point_count: int, seed: int
) -> list[Point]:
    """Generate an E-axis clean point cloud for a matrix case"""
    generator = geometry.get("generator")
    if generator == "gaussian_ellipsoid":
        axes = tuple(
            float(value)
            for value in geometry.get("axes", GEOMETRY_AXES[geometry["geometry"]])
        )
        if len(axes) != 3:
            raise ValueError(f"geometry {geometry['id']} must define three axes")
        return ellipsoid_points(point_count, axes, seed)
    if generator == "surface_patch":
        family = str(geometry.get("family", "paraboloid_low"))
        return patch_points(point_count, family, seed)
    if generator == "torus":
        family = str(geometry.get("family", "standard"))
        return torus_points(point_count, family, seed)
    if generator == "cylinder":
        family = str(geometry.get("family", "standard"))
        return cylinder_points(point_count, family, seed)
    if generator == "mixed_density":
        family = str(geometry.get("family", "three_blobs"))
        return mixture_points(point_count, family, seed)
    raise ValueError(f"unsupported Synthetic geometry generator: {generator}")


def case_stem(case: MatrixCase) -> str:
    """Create a filesystem-safe case stem for points/orders/manifests."""
    algorithm_id = safe_path_component(case.algorithm["id"], "algorithm id")
    bit_rule_id = safe_path_component(case.bit_rule["id"], "bit rule id")
    contamination_id = safe_path_component(case.contamination["id"], "contamination id")
    geometry_id = safe_path_component(case.geometry["id"], "geometry id")
    return (
        f"{algorithm_id}__{bit_rule_id}__{contamination_id}__"
        f"{geometry_id}__n{case.point_count}__s{case.seed}"
    )


def run_ordering(
    rch_order: Path,
    case: MatrixCase,
    points_path: Path,
    order_path: Path,
    manifest_path: Path,
    timing_repeats: int = 1,
    refinement: str = "off",
) -> float:
    """Invoke the C++ ordering facade and return its reported sort time."""
    if timing_repeats < 1:
        raise ValueError("timing_repeats must be >= 1")
    method = str(case.algorithm["method"])
    command = [
        str(rch_order),
        "--input",
        str(points_path),
        "--method",
        method,
        "--frame-estimator",
        str(case.algorithm.get("frame_estimator", "det_mcd")),
        "--refinement",
        effective_refinement_for_method(method, str(refinement)),
        "--output",
        str(order_path),
        "--manifest",
        str(manifest_path),
        "--bit-allocator",
        str(case.bit_rule["bit_allocator"]),
        "--uniform-bits",
        str(case.bit_rule.get("uniform_bits", 10)),
        "--min-axis-bits",
        str(case.bit_rule.get("min_axis_bits", 1)),
        "--timing-repeats",
        str(timing_repeats),
    ]
    subprocess.run(command, check=True, cwd=REPO_ROOT)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    sort_seconds = manifest.get("sort_seconds")
    if not isinstance(sort_seconds, (int, float)) or not math.isfinite(
        float(sort_seconds)
    ):
        raise ValueError(
            f"manifest {manifest_path} does not contain finite sort_seconds"
        )
    return float(sort_seconds)


def permutation_hash(order: list[int]) -> str:
    """Hash an emitted permutation for external-adapter manifests."""
    digest = hashlib.sha256()
    for raw in order:
        digest.update(int(raw).to_bytes(8, byteorder="little", signed=False))
    return digest.hexdigest()


def run_process_with_peak_rss(command: list[str]) -> tuple[float, int | None]:
    """Run a subprocess and return elapsed seconds plus child peak RSS in KiB.

    Linux `wait4` reports `ru_maxrss` in KiB; macOS reports bytes. If the
    platform lacks per-child rusage, the command still runs but RSS is unknown
    rather than fabricated.
    """
    start = time.perf_counter()
    if resource is None or not hasattr(os, "wait4"):
        subprocess.run(command, check=True, cwd=REPO_ROOT)
        return time.perf_counter() - start, None

    proc = subprocess.Popen(command, cwd=REPO_ROOT)
    _pid, status, usage = os.wait4(proc.pid, 0)
    elapsed = time.perf_counter() - start
    if os.WIFEXITED(status):
        returncode = os.WEXITSTATUS(status)
    elif os.WIFSIGNALED(status):
        returncode = -os.WTERMSIG(status)
    else:  # defensive: wait4 should return exited/signaled children here.
        returncode = proc.poll()
    proc.returncode = returncode
    if returncode:
        raise subprocess.CalledProcessError(int(returncode), command)
    peak = int(getattr(usage, "ru_maxrss", 0))
    if sys.platform == "darwin":
        peak = math.ceil(peak / 1024)
    return elapsed, peak if peak > 0 else None


def run_cgal_ordering(
    cgal_adapter: Path,
    case: MatrixCase,
    points_path: Path,
    order_path: Path,
    manifest_path: Path,
    timing_repeats: int = 1,
) -> float:
    """Invoke the optional A7 CGAL adapter and emit an rch_order-like manifest."""
    if timing_repeats < 1:
        raise ValueError("timing_repeats must be >= 1")
    policy = str(case.algorithm.get("cgal_policy", "median"))
    metadata_path = manifest_path.with_suffix(
        manifest_path.suffix + ".cgal_metadata.json"
    )
    elapsed: list[float] = []
    peak_rss_values: list[int] = []
    for _ in range(timing_repeats):
        seconds, peak_rss_kb = run_process_with_peak_rss(
            [
                str(cgal_adapter),
                "--input",
                str(points_path),
                "--output",
                str(order_path),
                "--policy",
                policy,
                "--metadata-output",
                str(metadata_path),
            ],
        )
        elapsed.append(seconds)
        if peak_rss_kb is not None:
            peak_rss_values.append(peak_rss_kb)
    order = read_order_csv(order_path)
    validate_permutation(order, count_point_rows(points_path), "A7 CGAL adapter")
    cgal_metadata = read_cgal_metadata(metadata_path)
    elapsed_sorted = sorted(elapsed)
    mid = len(elapsed_sorted) // 2
    sort_seconds = (
        elapsed_sorted[mid]
        if len(elapsed_sorted) % 2 == 1
        else 0.5 * (elapsed_sorted[mid - 1] + elapsed_sorted[mid])
    )
    manifest = {
        "status": "ok",
        "input": display_path(points_path),
        "method": "external_cgal_spatial_sort",
        "frame_estimator": "none",
        "bit_allocator": "external",
        "refinement": "external",
        "uniform_bits": 0,
        "min_axis_bits": 0,
        "timing_repeats": timing_repeats,
        "sort_seconds": sort_seconds,
        "peak_rss_kb": max(peak_rss_values) if peak_rss_values else None,
        "point_count": len(order),
        "hash": permutation_hash(order),
        "bits_axis": [0, 0, 0],
        "frame_axes": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
        "robust_fallback_used": False,
        "adapter": display_path(cgal_adapter),
        "cgal_policy": policy,
        "cgal": {
            "version": str(cgal_metadata["cgal_version"]),
            "version_nr": cgal_metadata["cgal_version_nr"],
            "git_hash": str(cgal_metadata["cgal_git_hash"]),
            "spatial_sort_dimension": cgal_metadata["spatial_sort_dimension"],
            "policy": str(cgal_metadata["spatial_sort_policy"]),
            "threshold_hilbert": cgal_metadata["threshold_hilbert"],
            "threshold_multiscale": cgal_metadata["threshold_multiscale"],
            "ratio": cgal_metadata["ratio"],
        },
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return sort_seconds


def execute_ordering(
    rch_order: Path,
    cgal_adapter: Path | None,
    case: MatrixCase,
    points_path: Path,
    order_path: Path,
    manifest_path: Path,
    timing_repeats: int,
    refinement: str = "off",
) -> float:
    """Dispatch one ordering case to the in-repo CLI or external A7 adapter."""
    if case.algorithm.get("method") == "external_cgal_spatial_sort":
        if cgal_adapter is None:
            raise FileNotFoundError(
                "A7 requested but rch_cgal_spatial_sort was not found"
            )
        return run_cgal_ordering(
            cgal_adapter, case, points_path, order_path, manifest_path, timing_repeats
        )
    return run_ordering(
        rch_order,
        case,
        points_path,
        order_path,
        manifest_path,
        timing_repeats,
        refinement,
    )


def read_order_csv(path: Path) -> list[int]:
    """Read rank/raw_index rows emitted by rch_order."""
    order: list[int] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            order.append(int(row["raw_index"]))
    return order


def count_point_rows(path: Path) -> int:
    """Count non-empty point rows in an adapter input file."""
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


def validate_permutation(order: list[int], expected_count: int, label: str) -> None:
    """Fail closed unless an external order is exactly 0..N-1."""
    if len(order) != expected_count or sorted(order) != list(range(expected_count)):
        raise ValueError(
            f"{label} did not emit a complete permutation of 0..{expected_count - 1}: "
            f"{order}"
        )


def is_permutation_of_size(order: list[int], size: int) -> bool:
    """Return True iff `order` is exactly a permutation of \(0,\ldots,n-1\)."""
    return size >= 0 and len(order) == size and sorted(order) == list(range(size))


def read_cgal_metadata(path: Path) -> dict[str, Any]:
    """Read required adapter provenance fields for A7 manifests."""
    if not path.exists():
        raise ValueError(f"A7 CGAL adapter did not emit metadata: {path}")
    metadata = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "cgal_version",
        "cgal_version_nr",
        "cgal_git_hash",
        "spatial_sort_dimension",
        "spatial_sort_policy",
        "threshold_hilbert",
        "threshold_multiscale",
        "ratio",
    }
    missing = sorted(required - set(metadata))
    if missing:
        raise ValueError(f"A7 CGAL metadata missing required fields: {missing}")
    return metadata


def dist2(lhs: Point, rhs: Point) -> float:
    """Squared Euclidean distance for locality metrics."""
    return (
        (lhs[0] - rhs[0]) * (lhs[0] - rhs[0])
        + (lhs[1] - rhs[1]) * (lhs[1] - rhs[1])
        + (lhs[2] - rhs[2]) * (lhs[2] - rhs[2])
    )


def _ratio_from_dist2(distance2: float, rank_gap: int) -> float:
    """Return ``distance^3 / rank_gap`` without recomputing a square root."""
    if rank_gap <= 0:
        return 0.0
    return (distance2 * math.sqrt(distance2)) / float(rank_gap)


def _all_points_finite(points: list[Point]) -> bool:
    """Return whether every coordinate is finite."""
    return all(all(math.isfinite(value) for value in point) for point in points)


def _bbox_diagonal(points: list[Point]) -> float:
    """Return an axis-aligned bbox diagonal upper bound on all pair distances."""
    if not points:
        return 0.0
    lo = [min(point[axis] for point in points) for axis in range(3)]
    hi = [max(point[axis] for point in points) for axis in range(3)]
    return math.sqrt(sum((hi[axis] - lo[axis]) ** 2 for axis in range(3)))


def mean_inter_adjacent_distance(points: list[Point], order: list[int]) -> float:
    """Compute M3 MIAD.

    Edge cases:
      * `len(order) < 2` ⇒ 0.0 (no inter-adjacent pair). This guards
        downstream divide-by-zero; downstream consumers treat 0 as
        "undefined for this run".
    """
    if not is_permutation_of_size(order, len(points)):
        return 0.0
    if len(order) < 2:
        return 0.0
    total = 0.0
    for left, right in zip(order, order[1:]):
        total += math.sqrt(dist2(points[left], points[right]))
    return total / float(len(order) - 1)


def l1_locality(points: list[Point], order: list[int]) -> float:
    """Compute exact finite M1 L₁ locality over all point pairs.

    Definition (Gotsman & Lindenbaum 1996), measure L₁ (the worst-case ratio;
    their L₂ is the *minimum* ratio, which this function does not compute):
        L₁ = max_{i<j}  ‖p_i - p_j‖₂³ / |rank_i - rank_j|
    Edge cases:
      * `len(order) < 2` ⇒ 0.0 (no admissible pair).
      * Pairs with `rank_gap == 0` are skipped (cannot happen for valid
        permutations but guards user-supplied rankings).
    The implementation is exact and sweeps rank gaps in increasing order. Once
    the bbox-diameter upper bound for all remaining larger gaps cannot beat the
    current maximum, the scan stops. Worst case is still O(N²), but easy cases no
    longer pay for every raw-index pair.
    """
    if not is_permutation_of_size(order, len(points)) or not _all_points_finite(points):
        return 0.0
    if len(order) < 2:
        return 0.0
    ordered_points = [points[raw_index] for raw_index in order]
    bbox = _bbox_diagonal(points)
    if bbox <= 0.0:
        return 0.0
    bbox3 = bbox * bbox * bbox
    worst = 0.0
    n = len(ordered_points)
    for rank_gap in range(1, n):
        upper = math.nextafter(bbox3 / float(rank_gap), math.inf)
        if worst > 0.0 and upper <= worst:
            break
        for left in range(0, n - rank_gap):
            value = _ratio_from_dist2(
                dist2(ordered_points[left], ordered_points[left + rank_gap]),
                rank_gap,
            )
            worst = max(worst, value)
    return worst


@dataclass(slots=True)
class _MetricKdNode:
    """Small exact branch-and-bound tree for pairwise metric pruning."""

    bbox_lo: Point
    bbox_hi: Point
    rank_min: int
    rank_max: int
    indices: list[int] | None = None
    left: "_MetricKdNode | None" = None
    right: "_MetricKdNode | None" = None


def _build_metric_kd_node(
    points: list[Point],
    indices: list[int],
    rank: list[int],
    leaf_size: int = 32,
) -> _MetricKdNode:
    """Build a deterministic kd-tree whose nodes also store rank ranges."""
    bbox_lo = tuple(min(points[index][axis] for index in indices) for axis in range(3))
    bbox_hi = tuple(max(points[index][axis] for index in indices) for axis in range(3))
    rank_min = min(rank[index] for index in indices)
    rank_max = max(rank[index] for index in indices)
    if len(indices) <= leaf_size:
        return _MetricKdNode(bbox_lo, bbox_hi, rank_min, rank_max, list(indices))

    spreads = [bbox_hi[axis] - bbox_lo[axis] for axis in range(3)]
    axis = max(range(3), key=lambda item: (spreads[item], -item))
    ordered = sorted(indices, key=lambda index: (points[index][axis], index))
    mid = len(ordered) // 2
    if mid <= 0 or mid >= len(ordered):
        return _MetricKdNode(bbox_lo, bbox_hi, rank_min, rank_max, list(indices))
    return _MetricKdNode(
        bbox_lo,
        bbox_hi,
        rank_min,
        rank_max,
        None,
        _build_metric_kd_node(points, ordered[:mid], rank, leaf_size),
        _build_metric_kd_node(points, ordered[mid:], rank, leaf_size),
    )


def _min_dist2_to_bbox(point: Point, lo: Point, hi: Point) -> float:
    """Squared distance from a point to an axis-aligned bounding box."""
    total = 0.0
    for axis in range(3):
        if point[axis] < lo[axis]:
            delta = lo[axis] - point[axis]
        elif point[axis] > hi[axis]:
            delta = point[axis] - hi[axis]
        else:
            delta = 0.0
        total += delta * delta
    return total


def _l2_node_lower_bound(
    point: Point, point_rank: int, node: _MetricKdNode
) -> float:
    """Lower-bound ``distance^3 / rank_gap`` for all pairs in one kd-node."""
    max_gap = max(abs(point_rank - node.rank_min), abs(point_rank - node.rank_max))
    if max_gap <= 0:
        return math.inf
    return _ratio_from_dist2(
        _min_dist2_to_bbox(point, node.bbox_lo, node.bbox_hi),
        max_gap,
    )


def _l2_initial_candidate(points: list[Point], order: list[int]) -> float:
    """Find a deterministic finite L2 candidate before branch-and-bound search."""
    n = len(order)
    best = math.inf
    gaps: set[int] = {1, n - 1}
    gap = 2
    while gap < n:
        gaps.add(gap)
        gap *= 2
    ordered_points = [points[raw_index] for raw_index in order]
    for rank_gap in sorted(gaps):
        for left in range(0, n - rank_gap):
            value = _ratio_from_dist2(
                dist2(ordered_points[left], ordered_points[left + rank_gap]),
                rank_gap,
            )
            if value < best:
                best = value
                if best == 0.0:
                    return 0.0
    return best


def _l2_locality_bruteforce(points: list[Point], order: list[int]) -> float:
    """Exact O(N²) fallback used for small clouds and tests."""
    rank = {raw_index: pos for pos, raw_index in enumerate(order)}
    best: float | None = None
    for i in range(len(points)):
        for j in range(i + 1, len(points)):
            rank_gap = abs(rank[i] - rank[j])
            if rank_gap == 0:
                continue
            value = _ratio_from_dist2(dist2(points[i], points[j]), rank_gap)
            best = value if best is None else min(best, value)
    return best if best is not None else 0.0


def l2_locality(points: list[Point], order: list[int]) -> float:
    """Compute exact finite M1 L₂ locality over all point pairs.

    Definition (Gotsman & Lindenbaum 1996), measure L₂ (the best-case ratio;
    their L₁ is the *maximum* ratio, computed by ``l1_locality``):
        L₂ = min_{i<j}  ‖p_i - p_j‖₂³ / |rank_i - rank_j|
    Edge cases:
      * `len(order) < 2` ⇒ 0.0 (no admissible pair).
      * Pairs with `rank_gap == 0` are skipped (cannot happen for valid
        permutations but guards user-supplied rankings).
    Small clouds use the direct O(N²) scan. Larger clouds use an exact kd-tree
    branch-and-bound: each spatial node stores its rank range, giving a safe lower
    bound on ``distance^3 / rank_gap``. Worst case is still O(N²), but the common
    case avoids visiting most far-away nodes once a small candidate is known.
    """
    if not is_permutation_of_size(order, len(points)) or not _all_points_finite(points):
        return 0.0
    if len(order) < 2:
        return 0.0
    if len({tuple(point) for point in points}) < len(points):
        return 0.0
    if len(points) <= 2048:
        return _l2_locality_bruteforce(points, order)

    rank = [0] * len(points)
    for pos, raw_index in enumerate(order):
        rank[raw_index] = pos
    best = _l2_initial_candidate(points, order)
    if best == 0.0:
        return 0.0
    root = _build_metric_kd_node(points, list(range(len(points))), rank)
    counter = 0
    for raw_index, point in enumerate(points):
        point_rank = rank[raw_index]
        heap: list[tuple[float, int, _MetricKdNode]] = []
        lower = _l2_node_lower_bound(point, point_rank, root)
        if lower < best:
            heapq.heappush(heap, (lower, counter, root))
            counter += 1
        while heap:
            lower, _, node = heapq.heappop(heap)
            if lower >= best:
                continue
            if node.indices is not None:
                for other in node.indices:
                    if other == raw_index:
                        continue
                    rank_gap = abs(point_rank - rank[other])
                    if rank_gap == 0:
                        continue
                    value = _ratio_from_dist2(dist2(point, points[other]), rank_gap)
                    if value < best:
                        best = value
                        if best == 0.0:
                            return 0.0
                continue
            for child in (node.left, node.right):
                if child is None:
                    continue
                child_lower = _l2_node_lower_bound(point, point_rank, child)
                if child_lower < best:
                    heapq.heappush(heap, (child_lower, counter, child))
                    counter += 1
    return best if math.isfinite(best) else 0.0


def exact_knn_indices(points: list[Point], k: int) -> list[tuple[int, ...]]:
    """Return exact raw-index kNN lists for every point using all points.

    SciPy's cKDTree supplies the candidate radius. The final neighbor list is
    still sorted by the repository contract ``(squared_distance, raw_index)``, so
    equal-distance ties match the old O(N²) implementation exactly.
    """
    n = len(points)
    if n == 0:
        return []
    k_eff = min(k, n - 1)
    if k_eff <= 0:
        return [tuple() for _ in range(n)]
    if not _all_points_finite(points):
        return [tuple() for _ in range(n)]
    try:
        import numpy as np
        from scipy.spatial import cKDTree
    except ImportError:  # pragma: no cover - requirements.txt includes SciPy.
        return [
            tuple(
                index
                for _, index in sorted(
                    (dist2(points[i], points[j]), j) for j in range(n) if j != i
                )[:k_eff]
            )
            for i in range(n)
        ]

    data = np.asarray(points, dtype=float)
    tree = cKDTree(data)
    query_k = min(n, k_eff + 1)
    distances, _ = tree.query(data, k=query_k, workers=-1)
    distances = np.asarray(distances)
    if distances.ndim == 1:
        radii = distances
    else:
        radii = distances[:, -1]
    eps = np.maximum(1.0e-12, np.asarray(radii) * 1.0e-12)
    balls = tree.query_ball_point(data, np.asarray(radii) + eps, workers=-1)
    neighbors: list[tuple[int, ...]] = []
    for i, candidates in enumerate(balls):
        radius2 = float((radii[i] + eps[i]) * (radii[i] + eps[i]))
        ranked = [
            (distance, int(j))
            for j in candidates
            if int(j) != i
            for distance in (dist2(points[i], points[int(j)]),)
            if distance <= radius2
        ]
        if len(ranked) < k_eff:
            ranked = [
                (dist2(points[i], points[j]), j) for j in range(n) if j != i
            ]
        ranked.sort()
        neighbors.append(tuple(index for _, index in ranked[:k_eff]))
    return neighbors


def recall_at_k_window_from_knn(
    neighbors: list[tuple[int, ...]], order: list[int], window: int = 64
) -> float:
    """Compute exact window recall from precomputed all-point kNN lists."""
    n = len(neighbors)
    if not is_permutation_of_size(order, n):
        return 0.0
    if n <= 1:
        return 1.0
    rank = {raw_index: pos for pos, raw_index in enumerate(order)}
    half = max(1, window // 2)
    total = 0.0
    for raw, exact in enumerate(neighbors):
        k_eff = len(exact)
        if k_eff <= 0:
            total += 1.0
            continue
        left = max(0, rank[raw] - half)
        right = min(n, rank[raw] + half + 1)
        window_set = {order[pos] for pos in range(left, right) if order[pos] != raw}
        total += len(set(exact) & window_set) / float(k_eff)
    return total / float(n)


def recall_at_k_window(
    points: list[Point], order: list[int], k: int = 8, window: int = 64
) -> float:
    """Compute M2 kNN sort-window recall.

    Definition:
        recall@(k, w) = (1/N) Σ_i  |kNN_w(i, w/2) ∩ kNN_exact(i, k)| / k_eff
    where `k_eff = min(k, n-1)` clamps to small clouds. Edge cases:
      * `n <= 1`         ⇒ 1.0 (vacuous; matches `union of empty sets`).
      * `window` is even ⇒ effective half is `max(1, window//2)`; small
        windows still admit at least one candidate.
    """
    n = len(points)
    if not is_permutation_of_size(order, n) or not _all_points_finite(points):
        return 0.0
    if n <= 1:
        return 1.0
    k_eff = min(k, n - 1)
    if k_eff <= 0:
        return 1.0
    return recall_at_k_window_from_knn(exact_knn_indices(points, k), order, window)


def block_read_locality(
    points: list[Point], order: list[int], block_size: int = 32
) -> tuple[float, float]:
    """Compute M9 block-read locality as mean and p95 block diameter."""
    if block_size < 2:
        raise ValueError("block_size must be >= 2")
    if not is_permutation_of_size(order, len(points)):
        return 0.0, 0.0
    if len(order) < 2:
        return 0.0, 0.0
    diameters: list[float] = []
    for start in range(0, len(order), block_size):
        block = order[start : start + block_size]
        if len(block) < 2:
            continue
        worst2 = 0.0
        for i in range(len(block)):
            for j in range(i + 1, len(block)):
                worst2 = max(worst2, dist2(points[block[i]], points[block[j]]))
        diameters.append(math.sqrt(worst2))
    if not diameters:
        return 0.0, 0.0
    sorted_diameters = sorted(diameters)
    p95_index = min(
        len(sorted_diameters) - 1, math.ceil(0.95 * len(sorted_diameters)) - 1
    )
    return sum(diameters) / float(len(diameters)), sorted_diameters[p95_index]


def kendall_tau_against_clean(
    clean_order: list[int], contaminated_order: list[int], clean_count: int
) -> float:
    """Compute Kendall \(\tau\) of original-point order under contamination."""
    if clean_count < 0:
        return 0.0
    if clean_count < 2:
        return 1.0
    if not is_permutation_of_size(clean_order, clean_count):
        return 0.0
    filtered = [raw for raw in contaminated_order if raw < clean_count]
    if not is_permutation_of_size(filtered, clean_count):
        return 0.0
    clean_rank = {raw: pos for pos, raw in enumerate(clean_order)}
    ranks = [clean_rank[raw] for raw in filtered]
    discordant = inversion_count(ranks)
    denom = len(ranks) * (len(ranks) - 1) // 2
    concordant = denom - discordant
    return 1.0 if denom == 0 else (concordant - discordant) / float(denom)


def inversion_count(values: list[int]) -> int:
    """Count pair inversions in O(N log N) for tie-free rank permutations."""
    if len(values) < 2:
        return 0
    work = list(values)
    scratch = [0] * len(work)

    def sort_count(lo: int, hi: int) -> int:
        if hi - lo <= 1:
            return 0
        mid = (lo + hi) // 2
        total = sort_count(lo, mid) + sort_count(mid, hi)
        left = lo
        right = mid
        out = lo
        while left < mid and right < hi:
            if work[left] <= work[right]:
                scratch[out] = work[left]
                left += 1
            else:
                scratch[out] = work[right]
                total += mid - left
                right += 1
            out += 1
        while left < mid:
            scratch[out] = work[left]
            left += 1
            out += 1
        while right < hi:
            scratch[out] = work[right]
            right += 1
            out += 1
        work[lo:hi] = scratch[lo:hi]
        return total

    return sort_count(0, len(work))


def parse_frame_axes(manifest: dict[str, Any]) -> list[list[float]] | None:
    """Read a 3×3 frame-axis matrix from an rch_order manifest."""
    axes = manifest.get("frame_axes")
    if not isinstance(axes, list) or len(axes) != 3:
        return None
    parsed: list[list[float]] = []
    for row in axes:
        if not isinstance(row, list) or len(row) != 3:
            return None
        parsed_row: list[float] = []
        for value in row:
            if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                return None
            parsed_row.append(float(value))
        parsed.append(parsed_row)
    return parsed


def frame_angle_rad(
    clean_axes: list[list[float]] | None, perturbed_axes: list[list[float]] | None
) -> float | None:
    """Return max sign-invariant corresponding-axis angle in radians"""
    if clean_axes is None or perturbed_axes is None:
        return None
    worst = 0.0
    for axis in range(3):
        dot = 0.0
        clean_norm2 = 0.0
        perturbed_norm2 = 0.0
        for row in range(3):
            clean_value = clean_axes[row][axis]
            perturbed_value = perturbed_axes[row][axis]
            dot += clean_value * perturbed_value
            clean_norm2 += clean_value * clean_value
            perturbed_norm2 += perturbed_value * perturbed_value
        if clean_norm2 <= 0.0 or perturbed_norm2 <= 0.0:
            return None
        cosine = abs(dot) / math.sqrt(clean_norm2 * perturbed_norm2)
        cosine = min(1.0, max(-1.0, cosine))
        worst = max(worst, math.acos(cosine))
    return worst


def method_uses_frame(method: str) -> bool:
    """Return whether a run_matrix method has a PCA/robust frame to compare."""
    return method in {"pca_compact_hilbert", "robust_frame_morton", "rch"}


def output_row(
    runlist_name: str,
    case: MatrixCase,
    points: list[Point],
    order: list[int],
    manifest: dict[str, Any],
    sort_seconds: float,
    perf_counters: PerfCounters,
    clean_order: list[int] | None,
    clean_frame_axes: list[list[float]] | None,
    clean_count: int,
    metrics: set[str],
) -> dict[str, Any]:
    """Assemble one CSV result row from ordering output and requested metrics."""
    row: dict[str, Any] = {
        "runlist": runlist_name,
        "algorithm_id": case.algorithm["id"],
        "method": case.algorithm["method"],
        "bit_rule": case.bit_rule["id"],
        "bit_allocator": case.bit_rule["bit_allocator"],
        "contamination_id": case.contamination["id"],
        "contamination_mode": case.contamination["mode"],
        "geometry_id": case.geometry["id"],
        "point_count": len(points),
        "clean_point_count": clean_count,
        "seed": case.seed,
        "frame_estimator": manifest.get("frame_estimator", ""),
        "refinement": manifest.get("refinement", ""),
        "sort_seconds": sort_seconds,
        "output_hash": manifest["hash"],
        "bits_axis": " ".join(str(value) for value in manifest["bits_axis"]),
        "robust_fallback_used": manifest["robust_fallback_used"],
    }
    row["miad"] = (
        mean_inter_adjacent_distance(points, order) if "miad" in metrics else ""
    )
    if "m1_l1_locality" in metrics or "l1_locality" in metrics:
        exact_m1 = l1_locality(points, order)
    else:
        exact_m1 = ""
    row["m1_l1_locality"] = exact_m1 if "m1_l1_locality" in metrics else ""
    row["l1_locality"] = exact_m1 if "l1_locality" in metrics else ""
    if "m1_l2_locality" in metrics or "l2_locality" in metrics:
        exact_m1_l2 = l2_locality(points, order)
    else:
        exact_m1_l2 = ""
    row["m1_l2_locality"] = exact_m1_l2 if "m1_l2_locality" in metrics else ""
    row["l2_locality"] = exact_m1_l2 if "l2_locality" in metrics else ""
    row["recall_8_64"] = (
        recall_at_k_window(points, order, 8, 64) if "recall_8_64" in metrics else ""
    )
    peak_rss = manifest.get("peak_rss_kb")
    row["peak_rss_kb"] = (
        float(peak_rss)
        if "peak_rss_kb" in metrics
        and isinstance(peak_rss, (int, float))
        and math.isfinite(float(peak_rss))
        else ""
    )
    if "block_read_mean" in metrics or "block_read_p95" in metrics:
        block_mean, block_p95 = block_read_locality(points, order)
    else:
        block_mean, block_p95 = "", ""
    row["block_read_mean"] = block_mean if "block_read_mean" in metrics else ""
    row["block_read_p95"] = block_p95 if "block_read_p95" in metrics else ""
    row["cache_references"] = (
        perf_counters.cache_references
        if "cache_references" in metrics and perf_counters.cache_references is not None
        else ""
    )
    row["cache_misses"] = (
        perf_counters.cache_misses
        if "cache_misses" in metrics and perf_counters.cache_misses is not None
        else ""
    )
    miss_rate = perf_counters.miss_rate
    row["cache_miss_rate"] = (
        miss_rate if "cache_miss_rate" in metrics and miss_rate is not None else ""
    )
    row["perf_status"] = perf_counters.status if "perf_status" in metrics else ""
    row["kendall_tau_clean"] = (
        kendall_tau_against_clean(clean_order or order, order, clean_count)
        if "kendall_tau_clean" in metrics
        else ""
    )
    if "frame_angle_rad" in metrics and method_uses_frame(
        str(case.algorithm["method"])
    ):
        current_frame_axes = parse_frame_axes(manifest)
        reference_frame_axes = (
            current_frame_axes if case.contamination["id"] == "D0" else clean_frame_axes
        )
        angle = frame_angle_rad(reference_frame_axes, current_frame_axes)
        row["frame_angle_rad"] = angle if angle is not None else ""
    else:
        row["frame_angle_rad"] = ""
    return row


def write_results_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    """Write deterministic Synthetic results as CSV for analysis/scripts."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "runlist",
        "algorithm_id",
        "method",
        "bit_rule",
        "bit_allocator",
        "contamination_id",
        "contamination_mode",
        "geometry_id",
        "point_count",
        "clean_point_count",
        "seed",
        "frame_estimator",
        "refinement",
        "sort_seconds",
        "output_hash",
        "bits_axis",
        "robust_fallback_used",
        "miad",
        "m1_l1_locality",
        "l1_locality",
        "m1_l2_locality",
        "l2_locality",
        "recall_8_64",
        "peak_rss_kb",
        "block_read_mean",
        "block_read_p95",
        "cache_references",
        "cache_misses",
        "cache_miss_rate",
        "perf_status",
        "kendall_tau_clean",
        "frame_angle_rad",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def run_matrix(args: argparse.Namespace) -> Path:
    """Execute a runlist and return the results CSV path."""
    refinement_modes, default_refinement = load_refinement_modes()
    refinement = str(getattr(args, "refinement", default_refinement))
    if refinement not in refinement_modes:
        raise ValueError(
            f"unknown refinement mode {refinement!r}; expected one of "
            f"{refinement_modes} (declared in {REFINEMENT_SWEEP_PATH})"
        )
    algorithms = load_algorithm_configs(REPO_ROOT / "experiments/configs/algorithms")
    contamination = load_sweep_items(
        REPO_ROOT / "experiments/configs/sweeps/contamination.yaml", "levels"
    )
    geometries = load_sweep_items(
        REPO_ROOT / "experiments/configs/sweeps/anisotropy.yaml", "geometries"
    )
    runlist = load_yaml(args.runlist)
    cases = expand_runlist(runlist, algorithms, contamination, geometries)
    if args.max_runs is not None:
        cases = cases[: args.max_runs]
    timing_repeats = int(runlist.get("timing_repeats", 1))
    if timing_repeats < 1:
        raise ValueError("runlist timing_repeats must be >= 1")

    rch_order = resolve_rch_order(args.rch_order_bin)
    cgal_adapter = (
        resolve_cgal_adapter(args.cgal_adapter_bin)
        if any(
            case.algorithm.get("method") == "external_cgal_spatial_sort"
            for case in cases
        )
        else None
    )
    output_dir = args.output_dir
    data_dir = output_dir / "data"
    order_dir = output_dir / "orders"
    manifest_dir = output_dir / "manifests"
    order_dir.mkdir(parents=True, exist_ok=True)
    manifest_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    clean_cache: dict[tuple[str, str, str, int, int], list[int]] = {}
    clean_frame_cache: dict[tuple[str, str, str, int, int], list[list[float]]] = {}
    metrics = set(runlist.get("metrics", []))
    perf_status, perf_probe = prepare_perf_adapter(
        metrics,
        resolve_block_read_probe(args.block_read_probe_bin),
        output_dir,
    )

    for case in cases:
        # print(f"Running case: algorithm={case.algorithm['id']} contamination={case.contamination['id']} geometry={case.geometry['id']} points={case.point_count} seed={case.seed}")
        clean_points = make_clean_points(case.geometry, case.point_count, case.seed)
        points = contaminate(
            clean_points,
            str(case.contamination["mode"]),
            float(case.contamination["fraction"]),
            case.seed,
        )
        stem = case_stem(case)
        points_path = data_dir / f"{stem}.csv"
        order_path = order_dir / f"{stem}.order.csv"
        manifest_path = manifest_dir / f"{stem}.manifest.json"
        write_xyz_csv(points_path, points)
        sort_seconds = execute_ordering(
            rch_order,
            cgal_adapter,
            case,
            points_path,
            order_path,
            manifest_path,
            timing_repeats,
            refinement,
        )
        order = read_order_csv(order_path)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        perf_counters = (
            measure_block_read_perf(perf_probe, points_path, order_path)
            if perf_status == "available"
            else PerfCounters(status=perf_status)
        )

        clean_key = (
            str(case.algorithm["id"]),
            str(case.bit_rule["id"]),
            str(case.geometry["id"]),
            case.point_count,
            case.seed,
        )
        if case.contamination["id"] == "D0":
            clean_cache[clean_key] = order
            frame_axes = parse_frame_axes(manifest)
            if frame_axes is not None:
                clean_frame_cache[clean_key] = frame_axes
        clean_order = clean_cache.get(clean_key)
        clean_frame_axes = clean_frame_cache.get(clean_key)
        rows.append(
            output_row(
                str(runlist["name"]),
                case,
                points,
                order,
                manifest,
                sort_seconds,
                perf_counters,
                clean_order,
                clean_frame_axes,
                len(clean_points),
                metrics,
            )
        )

    runlist_name = safe_path_component(runlist["name"], "runlist name")
    results_path = output_dir / f"{runlist_name}.csv"
    write_results_csv(results_path, rows)
    metadata = {
        "schema": "rch.synthetic.run_matrix.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "runlist": display_path(args.runlist),
        "rows": len(rows),
        "timing_repeats": timing_repeats,
        "refinement": refinement,
        "rch_order": display_path(rch_order),
        "cgal_adapter": display_path(cgal_adapter),
        "perf_status": perf_status,
        "block_read_probe": display_path(perf_probe),
    }
    (output_dir / f"{runlist_name}.manifest.json").write_text(
        json.dumps(metadata, indent=2) + "\n",
        encoding="utf-8",
    )
    return results_path


def parse_args() -> argparse.Namespace:
    """Parse the Synthetic run-matrix CLI."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runlist", type=Path, required=True)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "experiments/outputs/synthetic_dataset",
    )
    parser.add_argument("--rch-order-bin", type=Path, default=None)
    parser.add_argument("--block-read-probe-bin", type=Path, default=None)
    parser.add_argument("--cgal-adapter-bin", type=Path, default=None)
    parser.add_argument("--max-runs", type=int, default=None)
    refinement_modes, default_refinement = load_refinement_modes()
    parser.add_argument(
        "--refinement",
        choices=tuple(refinement_modes),
        default=default_refinement,
        help=(
            "Local MIAD-refinement axis applied to in-repo orderings: "
            "off (default; no method refined), all (every method except the "
            "input-order baseline refined). Automatic arms are declared in "
            "experiments/configs/sweeps/refinement.yaml."
        ),
    )
    return parser.parse_args()


def main() -> int:
    """CLI entry point used by Synthetic verification commands."""
    results_path = run_matrix(parse_args())
    print(results_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
