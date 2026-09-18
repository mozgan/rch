#!/usr/bin/env python3
# ----------------------------------------------------------------------------
# run_cgal_appendix.py — CGAL spatial_sort appendix sanity runner
#
# References:
#   - CGAL Project, spatial_sort reference manual, accessed 2026-07-27.
# ----------------------------------------------------------------------------
"""Run a minimal CGAL spatial_sort appendix sanity fixture.

Algorithm: load finite fixture points and declared policies, run the optional
CGAL adapter per policy, require a complete permutation, hash it, and emit CSV
plus CGAL provenance metadata.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import subprocess
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]

A7_FIXTURE_PATH = REPO_ROOT / "experiments/configs/fixtures/a7_cgal_appendix.yaml"


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


def load_fixture(path: Path) -> tuple[list[tuple[float, float, float]], list[str]]:
    """Load the recorded appendix fixture; fail closed on malformed config."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if (
        not isinstance(data, dict)
        or data.get("schema") != "rch.fixture.a7_cgal_appendix.v1"
    ):
        raise ValueError(f"unexpected A7 fixture schema in {path}")
    raw_points = data.get("points")
    if not isinstance(raw_points, list) or not raw_points:
        raise ValueError(f"A7 fixture must list points: {path}")
    points: list[tuple[float, float, float]] = []
    for row in raw_points:
        if not isinstance(row, list) or len(row) != 3:
            raise ValueError(f"A7 fixture point must have 3 coordinates: {row!r}")
        coords = (float(row[0]), float(row[1]), float(row[2]))
        if not all(math.isfinite(value) for value in coords):
            raise ValueError(f"A7 fixture point must be finite: {row!r}")
        points.append(coords)
    policies = data.get("policies")
    if (
        not isinstance(policies, list)
        or not policies
        or not all(isinstance(policy, str) and policy for policy in policies)
        or len(set(policies)) != len(policies)
    ):
        raise ValueError(f"A7 fixture must list unique non-empty policies: {path}")
    return points, list(policies)


def resolve_adapter(candidate: Path | None) -> Path:
    """Find the optional `rch_cgal_spatial_sort` executable."""
    candidates = []
    if candidate is not None:
        candidates.append(candidate)
    candidates.extend(
        [
            REPO_ROOT / "build/cgal-adapter/adapters/cgal/rch_cgal_spatial_sort",
            REPO_ROOT / "build/bench/adapters/cgal/rch_cgal_spatial_sort",
        ]
    )
    for path in candidates:
        if path.exists() and path.is_file():
            return path
    raise FileNotFoundError("rch_cgal_spatial_sort not found; run `make cgal-adapter`")


def write_points(path: Path, points: list[tuple[float, float, float]]) -> None:
    """Write the deterministic appendix fixture as x,y,z CSV."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerows(points)


def read_order(path: Path, point_count: int) -> list[int]:
    """Read adapter order.csv and fail closed on malformed rows."""
    order: list[int] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            order.append(int(row["raw_index"]))
    expected = list(range(point_count))
    if sorted(order) != expected:
        raise ValueError(f"A7 adapter did not emit a permutation: {order}")
    return order


def order_hash(order: list[int]) -> str:
    """Hash the emitted permutation for deterministic appendix reporting."""
    digest = hashlib.sha256()
    for value in order:
        digest.update(int(value).to_bytes(8, byteorder="little", signed=False))
    return digest.hexdigest()


def read_cgal_metadata(path: Path) -> dict[str, Any]:
    """Read required adapter provenance fields."""
    if not path.exists():
        raise ValueError(f"A7 adapter did not emit metadata: {path}")
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
        raise ValueError(f"A7 metadata missing required fields: {missing}")
    return metadata


def run_policy(
    adapter: Path, points: Path, output_dir: Path, policy: str, point_count: int
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run one CGAL policy and return one CSV row."""
    policy_component = safe_path_component(policy, "CGAL policy")
    order_path = output_dir / f"a7_cgal_spatial_sort_{policy_component}.order.csv"
    metadata_path = (
        output_dir / f"a7_cgal_spatial_sort_{policy_component}.metadata.json"
    )
    subprocess.run(
        [
            str(adapter),
            "--input",
            str(points),
            "--output",
            str(order_path),
            "--policy",
            policy,
            "--metadata-output",
            str(metadata_path),
        ],
        check=True,
        cwd=REPO_ROOT,
    )
    order = read_order(order_path, point_count)
    return (
        {
            "algorithm_id": "A7_cgal_spatial_sort",
            "policy": policy,
            "point_count": point_count,
            "order_path": display_path(order_path),
            "permutation_hash": order_hash(order),
            "permutation": " ".join(str(value) for value in order),
        },
        read_cgal_metadata(metadata_path),
    )


def write_results(path: Path, rows: list[dict[str, Any]]) -> None:
    """Write appendix sanity rows."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "algorithm_id",
        "policy",
        "point_count",
        "order_path",
        "permutation_hash",
        "permutation",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def run_cgal_appendix(args: argparse.Namespace) -> Path:
    """Facade: run the declared fixture policies and emit CSV + manifest."""
    fixture_points, policies = load_fixture(
        Path(getattr(args, "fixture", None) or A7_FIXTURE_PATH)
    )
    adapter = resolve_adapter(args.adapter_bin)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    points = args.output_dir / "a7_fixture_points.csv"
    write_points(points, fixture_points)
    policy_results = [
        run_policy(adapter, points, args.output_dir, policy, len(fixture_points))
        for policy in policies
    ]
    rows = [row for row, _metadata in policy_results]
    results = args.output_dir / "a7_cgal_spatial_sort.csv"
    write_results(results, rows)
    manifest = {
        "schema": "rch.a7_cgal_appendix.v1",
        "adapter": display_path(adapter),
        "fixture_points": display_path(points),
        "rows": len(rows),
        "policies": policies,
        "cgal_metadata_by_policy": {
            row["policy"]: metadata for row, metadata in policy_results
        },
        "status": "ok",
    }
    (args.output_dir / "a7_cgal_spatial_sort.manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    return results


def parse_args() -> argparse.Namespace:
    """Parse CLI paths for the A7 appendix runner."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapter-bin", type=Path, default=None)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "experiments/outputs/a7_cgal_appendix",
    )
    parser.add_argument(
        "--fixture",
        type=Path,
        default=A7_FIXTURE_PATH,
        help="Recorded appendix fixture (points + policies) YAML.",
    )
    return parser.parse_args()


def main() -> int:
    """CLI entry point."""
    print(run_cgal_appendix(parse_args()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
