#!/usr/bin/env python3
# ----------------------------------------------------------------------------
# run_real_datasets.py — real-dataset benchmark Facade
#
# References:
#   - Craig Gotsman, Michael Lindenbaum, On the Metric Properties of Discrete
#     Space-Filling Curves, 1996, DOI: 10.1109/83.499920.
#   - Maurice G. Kendall, A New Measure of Rank Correlation, 1938,
#     DOI: 10.1093/biomet/30.1-2.81.
#   - Greg Turk, The PLY Polygon File Format, 1994.
# ----------------------------------------------------------------------------
"""Run processed real datasets through the C++ `rch_order` CLI.

Algorithm: expand real dataset cells, read canonical point-only PLY, run
ordering backends, compute requested metrics over all points by default, then
write CSV/provenance manifest. Explicit sampled proxies remain available only
for direct helper tests or caller-specified sample sizes.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import subprocess
import sys
import time
from dataclasses import dataclass
from itertools import product
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data.synthetic.generators.common import write_xyz_csv  # noqa: E402
from experiments.runners.run_matrix import (  # noqa: E402
    PerfCounters,
    block_read_locality,
    effective_refinement_for_method,
    exact_knn_indices,
    frame_angle_rad,
    is_permutation_of_size,
    kendall_tau_against_clean,
    l1_locality,
    l2_locality,
    mean_inter_adjacent_distance,
    measure_block_read_perf,
    method_uses_frame,
    parse_frame_axes,
    prepare_perf_adapter,
    read_order_csv,
    recall_at_k_window,
    recall_at_k_window_from_knn,
    resolve_cgal_adapter,
    resolve_block_read_probe,
    safe_path_component,
    display_path,
    run_cgal_ordering,
)
from scripts.convert_dataset import Point, read_ply_points  # noqa: E402


@dataclass(frozen=True)
class RealCase:
    """One dataset × algorithm × bit-rule Real benchmark cell."""

    dataset: dict[str, Any]
    geometry_id: str
    algorithm: dict[str, Any]
    bit_rule: dict[str, Any]
    contamination: dict[str, Any]
    seed: int


def load_yaml(path: Path) -> dict[str, Any]:
    """Load YAML mappings for runlists, manifests, and algorithm configs."""
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"expected mapping YAML at {path}")
    return data


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


def load_algorithm_configs(config_dir: Path) -> dict[str, dict[str, Any]]:
    """Load algorithm Strategy configs shared with Synthetic."""
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


def load_manifest_datasets(path: Path) -> dict[str, dict[str, Any]]:
    """Load dataset metadata from the Real manifest."""
    manifest = load_yaml(path)
    datasets = manifest.get("datasets")
    if not isinstance(datasets, list):
        raise ValueError(f"manifest has no dataset list: {path}")
    keyed: dict[str, dict[str, Any]] = {}
    for item in datasets:
        if not isinstance(item, dict):
            raise ValueError(f"manifest dataset must be a mapping in {path}: {item!r}")
        dataset_id = item.get("id")
        if not isinstance(dataset_id, str) or not dataset_id:
            raise ValueError(f"manifest dataset id must be a non-empty string: {path}")
        if dataset_id in keyed:
            raise ValueError(f"duplicate manifest dataset id {dataset_id!r}: {path}")
        keyed[dataset_id] = dict(item)
    return keyed


def resolve_rch_order(candidate: Path | None) -> Path:
    """Find the `rch_order` executable built with RCH_BUILD_TOOLS=ON."""
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


def expand_cases(
    runlist: dict[str, Any],
    datasets: dict[str, dict[str, Any]],
    algorithms: dict[str, dict[str, Any]],
    contamination: dict[str, dict[str, Any]] | None = None,
) -> list[RealCase]:
    """Expand dataset × algorithm × bit_rule × contamination × seed cells."""
    bit_rules = runlist.get("bit_rules", [])
    if not isinstance(bit_rules, list) or not bit_rules:
        raise ValueError("real runlist requires a non-empty bit_rules list")
    contamination_items = contamination or {
        "D0": {"id": "D0", "mode": "clean", "fraction": 0.0}
    }
    contamination_ids = runlist.get("contamination_ids", ["D0"])
    seeds = runlist.get("seeds", [0])
    geometry_ids = runlist.get("geometry_ids", {})
    cases: list[RealCase] = []
    for dataset_id, algorithm_id, bit_rule, contamination_id, seed in product(
        runlist["dataset_ids"],
        runlist["algorithm_ids"],
        bit_rules,
        contamination_ids,
        seeds,
    ):
        algorithm = algorithms[str(algorithm_id)]
        supported_bit_rules = algorithm.get("supported_bit_rules")
        if isinstance(supported_bit_rules, list) and str(bit_rule["id"]) not in {
            str(item) for item in supported_bit_rules
        }:
            continue
        cases.append(
            RealCase(
                datasets[str(dataset_id)],
                str(geometry_ids.get(str(dataset_id), "")),
                algorithm,
                dict(bit_rule),
                contamination_items[str(contamination_id)],
                int(seed),
            )
        )
    return cases


def validate_real_contamination(cases: list[RealCase]) -> None:
    """Reject synthetic D-axis outlier injection in the Real benchmark path."""
    invalid: list[str] = []
    for case in cases:
        contamination_id = str(case.contamination.get("id", ""))
        mode = str(case.contamination.get("mode", ""))
        fraction = case.contamination.get("fraction", 0.0)
        try:
            fraction_value = float(fraction)
        except (TypeError, ValueError):
            fraction_value = math.nan
        if (
            contamination_id != "D0"
            or mode != "clean"
            or not math.isfinite(fraction_value)
            or fraction_value != 0.0
        ):
            invalid.append(
                f"{contamination_id or '<missing>'}"
                f"(mode={mode or '<missing>'}, fraction={fraction!r})"
            )
    if invalid:
        requested = ", ".join(sorted(set(invalid)))
        raise ValueError(
            "real runlists must use only clean D0 contamination; "
            "synthetic D-axis outlier injection belongs to synthetic runlists. "
            f"Invalid real contamination levels: {requested}"
        )


def read_processed_points(path: Path) -> list[Point]:
    """Read processed ASCII PLY points and reject non-finite coordinates."""
    points, _ = read_ply_points(path.read_bytes())
    if not all(all(math.isfinite(value) for value in point) for point in points):
        raise ValueError(f"non-finite processed point in {path}")
    return points


def bbox_diagonal(points: list[Point]) -> float:
    """Return Euclidean axis-aligned bbox diagonal length.

    Used to scale-normalize MIAD: `normalized_miad = miad / bbox_diagonal`.
    Empty cloud ⇒ 0.0 (degenerate baseline; downstream divides only when
    the diagonal is strictly positive).
    """
    if not points:
        return 0.0
    lo = [min(point[axis] for point in points) for axis in range(3)]
    hi = [max(point[axis] for point in points) for axis in range(3)]
    return math.sqrt(sum((hi[axis] - lo[axis]) ** 2 for axis in range(3)))


def case_stem(case: RealCase) -> str:
    """Create a filesystem-safe real-dataset case stem."""
    dataset_id = safe_path_component(case.dataset["id"], "dataset id")
    algorithm_id = safe_path_component(case.algorithm["id"], "algorithm id")
    bit_rule_id = safe_path_component(case.bit_rule["id"], "bit rule id")
    contamination_id = safe_path_component(case.contamination["id"], "contamination id")
    return (
        f"{dataset_id}__{algorithm_id}__{bit_rule_id}__{contamination_id}__s{case.seed}"
    )


def is_external_cgal_case(case: RealCase) -> bool:
    """Return whether this real-data cell must be delegated to the A7 adapter."""
    return case.algorithm.get("method") == "external_cgal_spatial_sort"


def sampled_indices(count: int, sample_size: int | None) -> list[int]:
    """Return full-cloud indices unless an explicit coverage sample is requested."""
    if count <= 0:
        return []
    if sample_size is None:
        return list(range(count))
    if sample_size <= 0:
        return []
    if count <= sample_size:
        return list(range(count))
    if sample_size == 1:
        return [0]
    return sorted(
        {(idx * (count - 1)) // (sample_size - 1) for idx in range(sample_size)}
    )


def sampled_l1_locality(
    points: list[Point], order: list[int], sample_size: int | None
) -> tuple[float, int]:
    """M1 L1 over the full cloud, or over an explicit deterministic sample."""
    if sample_size is None:
        return l1_locality(points, order), len(points)
    sample = sampled_indices(len(points), sample_size)
    if not is_permutation_of_size(order, len(points)):
        return 0.0, len(sample)
    if len(sample) < 2:
        return 0.0, len(sample)
    rank = {raw_index: pos for pos, raw_index in enumerate(order)}
    worst = 0.0
    for left, raw_left in enumerate(sample):
        for raw_right in sample[left + 1 :]:
            rank_gap = abs(rank[raw_left] - rank[raw_right])
            if rank_gap == 0:
                continue
            value = math.sqrt(
                sum(
                    (points[raw_left][axis] - points[raw_right][axis]) ** 2
                    for axis in range(3)
                )
            ) ** 3 / float(rank_gap)
            worst = max(worst, value)
    return worst, len(sample)


def sampled_l2_locality(
    points: list[Point], order: list[int], sample_size: int | None
) -> tuple[float, int]:
    """M1 L2 over the full cloud, or over an explicit deterministic sample.

    L2 is the minimum ratio (Gotsman & Lindenbaum); restricting to a sampled
    subset can only keep or raise that minimum, so this is an upper-bound proxy
    (the L1 sampled counterpart is a lower-bound proxy on the maximum).
    """
    if sample_size is None:
        return l2_locality(points, order), len(points)
    sample = sampled_indices(len(points), sample_size)
    if not is_permutation_of_size(order, len(points)):
        return 0.0, len(sample)
    if len(sample) < 2:
        return 0.0, len(sample)
    rank = {raw_index: pos for pos, raw_index in enumerate(order)}
    best: float | None = None
    for left, raw_left in enumerate(sample):
        for raw_right in sample[left + 1 :]:
            rank_gap = abs(rank[raw_left] - rank[raw_right])
            if rank_gap == 0:
                continue
            value = math.sqrt(
                sum(
                    (points[raw_left][axis] - points[raw_right][axis]) ** 2
                    for axis in range(3)
                )
            ) ** 3 / float(rank_gap)
            best = value if best is None else min(best, value)
    return (best if best is not None else 0.0), len(sample)


def sampled_recall_at_k_window(
    points: list[Point],
    order: list[int],
    sample_size: int | None,
    k: int = 8,
    window: int = 64,
) -> tuple[float, int]:
    """M2 recall over the full cloud, or over an explicit deterministic sample."""
    if sample_size is None:
        return recall_at_k_window(points, order, k, window), len(points)
    sample = sampled_indices(len(points), sample_size)
    if not is_permutation_of_size(order, len(points)):
        return 0.0, len(sample)
    if len(sample) <= 1:
        return 1.0, len(sample)
    sample_set = set(sample)
    rank = {raw_index: pos for pos, raw_index in enumerate(order)}
    half = max(1, window // 2)
    k_eff = min(k, len(sample) - 1)
    if k_eff <= 0:
        return 1.0, len(sample)
    total = 0.0
    for raw in sample:
        exact = sorted(
            (
                sum(
                    (points[raw][axis] - points[other][axis]) ** 2 for axis in range(3)
                ),
                other,
            )
            for other in sample
            if other != raw
        )[:k_eff]
        exact_set = {index for _, index in exact}
        left = max(0, rank[raw] - half)
        right = min(len(order), rank[raw] + half + 1)
        window_set = {
            order[pos]
            for pos in range(left, right)
            if order[pos] in sample_set and order[pos] != raw
        }
        total += len(exact_set & window_set) / float(k_eff)
    return total / float(len(sample)), len(sample)


def real_metric_status(point_count: int, sampled_count: int) -> str:
    """State whether a Real metric covers the full cloud or a deterministic sample."""
    return "exact" if sampled_count == point_count else "deterministic_sampled_proxy"


def run_ordering(
    rch_order: Path,
    cgal_adapter: Path | None,
    case: RealCase,
    points_path: Path,
    order_path: Path,
    manifest_path: Path,
    refinement: str = "off",
) -> float:
    """Invoke the C++ ordering CLI and return elapsed wall-clock seconds."""
    if is_external_cgal_case(case):
        if cgal_adapter is None:
            raise FileNotFoundError(
                "A7 requested but rch_cgal_spatial_sort was not found"
            )
        return run_cgal_ordering(
            cgal_adapter,
            case,
            points_path,
            order_path,
            manifest_path,
            timing_repeats=1,
        )
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
    ]
    start = time.perf_counter()
    subprocess.run(command, check=True, cwd=REPO_ROOT)
    return time.perf_counter() - start


def output_row(
    case: RealCase,
    points: list[Point],
    order: list[int],
    manifest: dict[str, Any],
    sort_seconds: float,
    metrics: set[str],
    clean_count: int,
    perf_counters: PerfCounters | None = None,
    clean_order: list[int] | None = None,
    clean_frame_axes: list[list[float]] | None = None,
    sampled_metric_size: int | None = None,
    knn_cache: dict[int, list[tuple[int, ...]]] | None = None,
) -> dict[str, Any]:
    """Assemble one Real CSV row from ordering output and metrics."""
    need_miad = "miad" in metrics or "normalized_miad" in metrics
    miad = mean_inter_adjacent_distance(points, order) if need_miad else ""
    diagonal = bbox_diagonal(points)
    normalized = (miad / diagonal) if isinstance(miad, float) and diagonal > 0.0 else ""
    row = {
        "runlist": "table_2_dataset_summary",
        "dataset_id": case.dataset["id"],
        "dataset_label": case.dataset.get("label", case.dataset["id"]),
        "geometry_id": case.geometry_id,
        "expected_vertices": case.dataset.get("expected_vertices", ""),
        "algorithm_id": case.algorithm["id"],
        "method": case.algorithm["method"],
        "bit_rule": case.bit_rule["id"],
        "bit_allocator": case.bit_rule["bit_allocator"],
        "point_count": len(points),
        "clean_point_count": clean_count,
        "contamination_id": case.contamination["id"],
        "contamination_mode": case.contamination["mode"],
        "seed": case.seed,
        "frame_estimator": manifest.get("frame_estimator", ""),
        "refinement": manifest.get("refinement", ""),
        "sort_seconds": sort_seconds if "sort_seconds" in metrics else "",
        "output_hash": manifest["hash"],
        "bits_axis": " ".join(str(value) for value in manifest["bits_axis"]),
        "robust_fallback_used": manifest["robust_fallback_used"],
        "miad": miad if "miad" in metrics else "",
        "normalized_miad": normalized if "normalized_miad" in metrics else "",
    }
    # --- M1 L1 (Gotsman-Lindenbaum L1 = max ratio): full if sample covers all ---
    wants_m1_l1 = "m1_l1_locality" in metrics or "l1_locality" in metrics
    wants_m1_l1_sampled = "m1_l1_sampled" in metrics
    if wants_m1_l1 or wants_m1_l1_sampled:
        m1_value, m1_count = sampled_l1_locality(points, order, sampled_metric_size)
        m1_status = real_metric_status(len(points), m1_count)
    else:
        m1_value, m1_count, m1_status = "", "", ""
    row["m1_l1_locality"] = m1_value if "m1_l1_locality" in metrics else ""
    row["l1_locality"] = m1_value if "l1_locality" in metrics else ""
    row["m1_l1_status"] = m1_status if wants_m1_l1 else ""
    row["m1_l1_sampled"] = m1_value if wants_m1_l1_sampled else ""
    row["m1_l1_sample_size"] = m1_count if wants_m1_l1_sampled else ""
    row["m1_l1_sampled_status"] = m1_status if wants_m1_l1_sampled else ""

    # --- M1 L2 (Gotsman-Lindenbaum L2 = min ratio): full if sample covers all ---
    wants_m1_l2 = "m1_l2_locality" in metrics or "l2_locality" in metrics
    wants_m1_l2_sampled = "m1_l2_sampled" in metrics
    if wants_m1_l2 or wants_m1_l2_sampled:
        m1_l2_value, m1_l2_count = sampled_l2_locality(
            points, order, sampled_metric_size
        )
        m1_l2_status = real_metric_status(len(points), m1_l2_count)
    else:
        m1_l2_value, m1_l2_count, m1_l2_status = "", "", ""
    row["m1_l2_locality"] = m1_l2_value if "m1_l2_locality" in metrics else ""
    row["l2_locality"] = m1_l2_value if "l2_locality" in metrics else ""
    row["m1_l2_status"] = m1_l2_status if wants_m1_l2 else ""
    row["m1_l2_sampled"] = m1_l2_value if wants_m1_l2_sampled else ""
    row["m1_l2_sample_size"] = m1_l2_count if wants_m1_l2_sampled else ""
    row["m1_l2_sampled_status"] = m1_l2_status if wants_m1_l2_sampled else ""

    wants_recall = "recall_8_64" in metrics
    wants_recall_sampled = "recall_8_64_sampled" in metrics
    if wants_recall or wants_recall_sampled:
        if sampled_metric_size is None and knn_cache is not None:
            neighbors = knn_cache.get(8)
            if neighbors is None:
                neighbors = exact_knn_indices(points, 8)
                knn_cache[8] = neighbors
            recall_value = recall_at_k_window_from_knn(neighbors, order, 64)
            recall_count = len(points)
        else:
            recall_value, recall_count = sampled_recall_at_k_window(
                points, order, sampled_metric_size, 8, 64
            )
        recall_status = real_metric_status(len(points), recall_count)
    else:
        recall_value, recall_count, recall_status = "", "", ""
    row["recall_8_64"] = recall_value if wants_recall else ""
    row["recall_8_64_status"] = recall_status if wants_recall else ""
    row["recall_8_64_sampled"] = recall_value if wants_recall_sampled else ""
    row["recall_8_64_sample_size"] = recall_count if wants_recall_sampled else ""
    row["recall_8_64_sampled_status"] = (
        recall_status if wants_recall_sampled else ""
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

    counters = perf_counters or PerfCounters(status="not_requested")
    row["cache_references"] = (
        counters.cache_references
        if "cache_references" in metrics and counters.cache_references is not None
        else ""
    )
    row["cache_misses"] = (
        counters.cache_misses
        if "cache_misses" in metrics and counters.cache_misses is not None
        else ""
    )
    miss_rate = counters.miss_rate
    row["cache_miss_rate"] = (
        miss_rate if "cache_miss_rate" in metrics and miss_rate is not None else ""
    )
    row["perf_status"] = counters.status if "perf_status" in metrics else ""

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
    """Write deterministic Real result rows for analysis scripts."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "runlist",
        "dataset_id",
        "dataset_label",
        "geometry_id",
        "expected_vertices",
        "algorithm_id",
        "method",
        "bit_rule",
        "bit_allocator",
        "point_count",
        "clean_point_count",
        "contamination_id",
        "contamination_mode",
        "seed",
        "frame_estimator",
        "refinement",
        "sort_seconds",
        "output_hash",
        "bits_axis",
        "robust_fallback_used",
        "miad",
        "normalized_miad",
        "m1_l1_locality",
        "l1_locality",
        "m1_l1_status",
        "m1_l1_sampled",
        "m1_l1_sample_size",
        "m1_l1_sampled_status",
        "m1_l2_locality",
        "l2_locality",
        "m1_l2_status",
        "m1_l2_sampled",
        "m1_l2_sample_size",
        "m1_l2_sampled_status",
        "recall_8_64",
        "recall_8_64_status",
        "recall_8_64_sampled",
        "recall_8_64_sample_size",
        "recall_8_64_sampled_status",
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


def run_real_datasets(args: argparse.Namespace) -> Path:
    """Facade executing the Real real-dataset runlist."""
    refinement_modes, default_refinement = load_refinement_modes()
    refinement = str(getattr(args, "refinement", default_refinement))
    if refinement not in refinement_modes:
        raise ValueError(
            f"unknown refinement mode {refinement!r}; expected one of "
            f"{refinement_modes} (declared in {REFINEMENT_SWEEP_PATH})"
        )
    runlist = load_yaml(args.runlist)
    algorithms = load_algorithm_configs(REPO_ROOT / "experiments/configs/algorithms")
    contamination = load_yaml(
        REPO_ROOT / "experiments/configs/sweeps/contamination.yaml"
    )
    contamination_items = {
        str(item["id"]): dict(item) for item in contamination.get("levels", [])
    }
    manifest_path = REPO_ROOT / str(runlist["dataset_manifest"])
    datasets = load_manifest_datasets(manifest_path)
    cases = expand_cases(runlist, datasets, algorithms, contamination_items)
    validate_real_contamination(cases)
    if bool(getattr(args, "exclude_external_baselines", False)):
        cases = [
            case for case in cases if not bool(case.algorithm.get("external_baseline"))
        ]
    if args.max_runs is not None:
        cases = cases[: args.max_runs]

    rch_order = resolve_rch_order(args.rch_order_bin)
    cgal_adapter = (
        resolve_cgal_adapter(getattr(args, "cgal_adapter_bin", None))
        if any(is_external_cgal_case(case) for case in cases)
        else None
    )
    processed_dir = Path(str(runlist["processed_dir"]))
    if processed_dir.is_absolute():
        try:
            processed_dir = processed_dir.resolve().relative_to(REPO_ROOT)
        except ValueError:
            pass
    output_dir = args.output_dir
    order_dir = output_dir / "orders"
    manifest_dir = output_dir / "manifests"
    data_dir = output_dir / "data"
    order_dir.mkdir(parents=True, exist_ok=True)
    manifest_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    metrics = set(runlist.get("metrics", []))
    perf_status, perf_probe = prepare_perf_adapter(
        metrics,
        resolve_block_read_probe(args.block_read_probe_bin),
        output_dir,
    )

    point_cache: dict[str, list[Point]] = {}
    case_point_cache: dict[tuple[str, str, int], tuple[list[Point], Path]] = {}
    metric_knn_cache: dict[tuple[str, str, int], dict[int, list[tuple[int, ...]]]] = {}
    clean_cache: dict[
        tuple[str, str, str, int], tuple[list[int], list[list[float]] | None]
    ] = {}
    rows: list[dict[str, Any]] = []
    total_cases = len(cases)
    runlist_name = safe_path_component(runlist["name"], "runlist name")
    for case_index, case in enumerate(cases, start=1):
        dataset_id = safe_path_component(case.dataset["id"], "dataset id")
        contamination_id = safe_path_component(
            case.contamination["id"], "contamination id"
        )
        clean_path = processed_dir / f"{dataset_id}.ply"
        clean_points = point_cache.setdefault(
            dataset_id, read_processed_points(clean_path)
        )
        point_key = (dataset_id, contamination_id, case.seed)
        cached_points = case_point_cache.get(point_key)
        if cached_points is None:
            points = clean_points
            points_path = clean_path
            cached_points = (points, points_path)
            case_point_cache[point_key] = cached_points
        points, points_path = cached_points
        stem = case_stem(case)
        order_path = order_dir / f"{stem}.order.csv"
        manifest_path_out = manifest_dir / f"{stem}.manifest.json"
        # print(
        #    f"{case_index}/{total_cases} dataset={dataset_id} "
        #    f"algorithm={case.algorithm['id']} bit_rule={case.bit_rule['id']} "
        #    f"contamination={case.contamination['id']} seed={case.seed} "
        #    f"n={len(points)}",
        #    file=sys.stderr,
        #    flush=True,
        # )
        ordering_points_path = points_path
        if (
            is_external_cgal_case(case)
            and ordering_points_path.suffix.lower() != ".csv"
        ):
            ordering_points_path = (
                data_dir / f"{dataset_id}__{contamination_id}__s{case.seed}.csv"
            )
            if not ordering_points_path.exists():
                write_xyz_csv(ordering_points_path, points)
        sort_seconds = run_ordering(
            rch_order,
            cgal_adapter,
            case,
            ordering_points_path,
            order_path,
            manifest_path_out,
            refinement,
        )
        order = read_order_csv(order_path)
        manifest = json.loads(manifest_path_out.read_text(encoding="utf-8"))
        perf_counters = PerfCounters(status=perf_status)
        if perf_status == "available":
            probe_points_path = points_path
            if probe_points_path.suffix.lower() != ".csv":
                probe_points_path = (
                    data_dir
                    / f"{dataset_id}__{contamination_id}__s{case.seed}.csv"
                )
                if not probe_points_path.exists():
                    write_xyz_csv(probe_points_path, points)
            perf_counters = measure_block_read_perf(
                perf_probe, probe_points_path, order_path
            )

        clean_key = (
            dataset_id,
            str(case.algorithm["id"]),
            str(case.bit_rule["id"]),
            case.seed,
        )
        current_frame_axes = parse_frame_axes(manifest)
        if case.contamination["id"] == "D0":
            clean_cache[clean_key] = (order, current_frame_axes)
            clean_order = order
            clean_frame_axes = current_frame_axes
        else:
            cached_clean = clean_cache.get(clean_key)
            clean_order = cached_clean[0] if cached_clean is not None else None
            clean_frame_axes = cached_clean[1] if cached_clean is not None else None
        rows.append(
            output_row(
                case,
                points,
                order,
                manifest,
                sort_seconds,
                metrics,
                len(clean_points),
                perf_counters,
                clean_order,
                clean_frame_axes,
                getattr(args, "sampled_metric_size", None),
                metric_knn_cache.setdefault(point_key, {}),
            )
        )

    results_path = output_dir / f"{runlist_name}.csv"
    write_results_csv(results_path, rows)
    metadata = {
        "schema": "rch.real.real_run.v1",
        "runlist": display_path(args.runlist),
        "rows": len(rows),
        "rch_order": display_path(rch_order),
        "cgal_adapter": display_path(cgal_adapter),
        "external_baselines_excluded": bool(
            getattr(args, "exclude_external_baselines", False)
        ),
        "refinement": refinement,
        "metric_coverage": "full_cloud"
        if getattr(args, "sampled_metric_size", None) is None
        else "deterministic_sampled_proxy",
    }
    (output_dir / f"{runlist_name}.manifest.json").write_text(
        json.dumps(metadata, indent=2) + "\n",
        encoding="utf-8",
    )
    return results_path


def parse_args() -> argparse.Namespace:
    """Parse the Real real-runner CLI."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runlist",
        type=Path,
        default=REPO_ROOT / "experiments/runlists/table_2_dataset_summary.yaml",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "experiments/outputs/real_dataset",
    )
    parser.add_argument("--rch-order-bin", type=Path, default=None)
    parser.add_argument("--cgal-adapter-bin", type=Path, default=None)
    parser.add_argument("--block-read-probe-bin", type=Path, default=None)
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
    parser.add_argument(
        "--exclude-external-baselines",
        action="store_true",
        help=(
            "Skip external baselines such as A7; used for refinement sweeps where "
            "the in-repo refinement axis is not meaningful for external adapters."
        ),
    )
    parser.add_argument("--max-runs", type=int, default=None)
    return parser.parse_args()


def main() -> int:
    """CLI entry point used by Real verification commands."""
    print(run_real_datasets(parse_args()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
