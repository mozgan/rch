#!/usr/bin/env python3
"""Summarize frame-domain clamping/collision diagnostics with MIAD and tau."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from statistics import median
from typing import Any


DIAGNOSTIC_FIELDS = (
    "frame_core_outside_point_fraction",
    "frame_core_outside_coordinate_fraction",
    "domain_clipped_point_fraction",
    "domain_clipped_coordinate_fraction",
    "domain_saturated_point_fraction",
    "domain_saturated_coordinate_fraction",
    "boundary_code_coordinate_fraction",
    "duplicate_quantized_tuple_point_fraction",
    "duplicate_hilbert_key_point_fraction",
    "miad_delta_from_D0",
    "kendall_tau_clean",
    "kendall_tau_change_from_clean",
)


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def summarize(values: list[float]) -> dict[str, float]:
    return {
        "median": median(values),
        "q25": percentile(values, 0.25),
        "q75": percentile(values, 0.75),
        "minimum": min(values),
        "maximum": max(values),
    }


def prepare_effects(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    clean_miad: dict[tuple[str, str, str, int], float] = {}
    seen: set[tuple[str, str, str, int, str]] = set()
    for row in rows:
        key = (
            row["algorithm_id"], row["bit_rule"], row["geometry_id"], int(row["seed"])
        )
        condition = (*key, row["contamination_id"])
        if condition in seen:
            raise ValueError(f"duplicate row for {condition}")
        seen.add(condition)
        if row["contamination_id"] == "D0":
            clean_miad[key] = float(row["miad"])

    prepared: list[dict[str, Any]] = []
    for row in rows:
        required = (
            "frame_core_outside_point_fraction",
            "domain_clipped_point_fraction",
            "domain_saturated_point_fraction",
            "duplicate_quantized_tuple_point_fraction",
            "duplicate_hilbert_key_point_fraction",
        )
        if any(not row.get(field) for field in required):
            raise ValueError("runner CSV row is missing quantization diagnostics")
        key = (
            row["algorithm_id"], row["bit_rule"], row["geometry_id"], int(row["seed"])
        )
        item: dict[str, Any] = {
            "algorithm_id": key[0],
            "bit_rule": key[1],
            "geometry_id": key[2],
            "seed": key[3],
            "contamination_id": row["contamination_id"],
            "point_count": int(row["point_count"]),
            "miad": float(row["miad"]),
            "miad_delta_from_D0": float(row["miad"]) - clean_miad[key],
            "kendall_tau_clean": float(row["kendall_tau_clean"]),
            "kendall_tau_change_from_clean": float(row["kendall_tau_clean"]) - 1.0,
            "bits_axis": row["bits_axis"],
        }
        for field in DIAGNOSTIC_FIELDS:
            if field in {"miad_delta_from_D0", "kendall_tau_clean", "kendall_tau_change_from_clean"}:
                continue
            item[field] = float(row[field])
        for diagnostic in (
            "frame_core_outside", "domain_clipped", "domain_saturated", "boundary_code"
        ):
            for axis in ("x", "y", "z"):
                name = f"{diagnostic}_{axis}_coordinate_fraction"
                item[name] = float(row[name])
        prepared.append(item)
    return prepared


def aggregate(rows: list[dict[str, Any]], keys: tuple[str, ...]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[tuple(str(row[key]) for key in keys)].append(row)
    summaries = []
    for key, group in sorted(groups.items()):
        summary: dict[str, Any] = {name: value for name, value in zip(keys, key)}
        summary["n_clouds"] = len(group)
        for field in DIAGNOSTIC_FIELDS:
            summary[field] = summarize([float(row[field]) for row in group])
        for diagnostic in ("frame_core_outside", "domain_clipped", "boundary_code"):
            for axis in ("x", "y", "z"):
                field = f"{diagnostic}_{axis}_coordinate_fraction"
                summary[field] = summarize([float(row[field]) for row in group])
        summaries.append(summary)
    return summaries


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    rows = prepare_effects(read_rows(args.results))
    condition = aggregate(rows, ("algorithm_id", "bit_rule", "contamination_id"))
    geometry = aggregate(
        rows, ("algorithm_id", "bit_rule", "contamination_id", "geometry_id")
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "clamping_summary.json").write_text(
        json.dumps(
            {
                "schema": "rch.clamping_diagnostics.v1",
                "unit": "one independently sampled geometry/replicate cloud",
                "condition_summaries": condition,
                "geometry_summaries": geometry,
                "definitions": {
                    "frame_core_outside_point_fraction": "fraction of input points outside at least one frame-core axis",
                    "domain_clipped_point_fraction": "fraction of points strictly outside a quantization-domain bound and therefore saturated to an edge code",
                    "domain_saturated_point_fraction": "fraction of points with at least one coordinate at or beyond a bound; exactly the quantizer's low/high saturation branches",
                    "boundary_code_coordinate_fraction": "fraction of axis coordinates encoded as code 0 or max; includes ordinary edge-bin points and is not itself a clipping rate",
                    "duplicate_*_point_fraction": "fraction of input points belonging to a non-singleton quantized-tuple or curve-key group",
                    "miad_delta_from_D0": "current MIAD minus D0 MIAD for the same algorithm/rule/geometry/seed",
                    "kendall_tau_change_from_clean": "reported clean-order Kendall tau minus 1",
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    per_row_fields = (
        "algorithm_id", "bit_rule", "geometry_id", "seed", "contamination_id",
        "point_count", "bits_axis", "frame_core_outside_point_fraction",
        "frame_core_outside_coordinate_fraction", "frame_core_outside_x_coordinate_fraction",
        "frame_core_outside_y_coordinate_fraction", "frame_core_outside_z_coordinate_fraction",
        "domain_clipped_point_fraction", "domain_clipped_coordinate_fraction",
        "domain_clipped_x_coordinate_fraction", "domain_clipped_y_coordinate_fraction",
        "domain_clipped_z_coordinate_fraction", "boundary_code_coordinate_fraction",
        "domain_saturated_point_fraction", "domain_saturated_coordinate_fraction",
        "domain_saturated_x_coordinate_fraction", "domain_saturated_y_coordinate_fraction",
        "domain_saturated_z_coordinate_fraction",
        "boundary_code_x_coordinate_fraction", "boundary_code_y_coordinate_fraction",
        "boundary_code_z_coordinate_fraction", "duplicate_quantized_tuple_point_fraction",
        "duplicate_hilbert_key_point_fraction", "miad", "miad_delta_from_D0",
        "kendall_tau_clean", "kendall_tau_change_from_clean",
    )
    with (args.output_dir / "clamping_cloud_effects.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=per_row_fields)
        writer.writeheader()
        writer.writerows(rows)
    print(args.output_dir / "clamping_summary.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
