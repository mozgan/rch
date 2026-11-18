#!/usr/bin/env python3
"""Analyze matched-domain frame and frame-by-bit-rule ablations."""

from __future__ import annotations

import argparse
import csv
import json
import random
from collections import Counter
from collections import defaultdict
from pathlib import Path
from statistics import median
from typing import Any


RULES = ("C2_occupancy_floor1", "C3_frame_core_occupancy", "C4_hybrid")
FRAMES = {
    "A5_pca_compact_hilbert": "sample covariance / PCA",
    "A6_rch": "DetMCD robust frame",
}


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def bootstrap_interval(
    by_geometry: dict[str, list[float]], *, seed: int, draws: int = 20000
) -> list[float]:
    rng = random.Random(seed)
    estimates: list[float] = []
    for _ in range(draws):
        sample = [
            rng.choice(values)
            for geometry in sorted(by_geometry)
            for values in (by_geometry[geometry],)
            for _ in range(len(values))
        ]
        estimates.append(median(sample))
    estimates.sort()
    return [estimates[int(0.025 * draws)], estimates[min(draws - 1, int(0.975 * draws))]]


def summarize(
    name: str, effects: dict[tuple[str, int], float], *, seed: int
) -> dict[str, Any]:
    by_geometry: dict[str, list[float]] = defaultdict(list)
    for (geometry, _replicate), value in effects.items():
        by_geometry[geometry].append(value)
    pooled = [value for geometry in sorted(by_geometry) for value in by_geometry[geometry]]
    return {
        "contrast": name,
        "unit": "one independently sampled geometry/replicate cloud",
        "n_clouds": len(pooled),
        "n_geometries": len(by_geometry),
        "median_cloud_effect": median(pooled),
        "stratified_cloud_bootstrap_95_percentile_ci": bootstrap_interval(
            by_geometry, seed=seed
        ),
        "median_effect_by_geometry": {
            geometry: median(values) for geometry, values in sorted(by_geometry.items())
        },
        "positive_clouds": sum(value > 0.0 for value in pooled),
        "negative_clouds": sum(value < 0.0 for value in pooled),
        "tied_clouds": sum(value == 0.0 for value in pooled),
        "bootstrap_resamples": 20000,
        "bootstrap_seed": seed,
    }


def index_miad(rows: list[dict[str, str]], *, fixed_domain: bool) -> dict[tuple[str, int, str, str], float]:
    indexed: dict[tuple[str, int, str, str], float] = {}
    for row in rows:
        if row["contamination_id"] != "D0":
            continue
        key = (
            row["geometry_id"],
            int(row["seed"]),
            row["algorithm_id"],
            row["bit_rule"],
        )
        if key in indexed:
            raise ValueError(f"duplicate result row for {key}")
        indexed[key] = float(row["miad"])
        if fixed_domain:
            if tuple(int(value) for value in row["bits_axis"].split()) != (8, 8, 8):
                raise ValueError(f"fixed-domain run did not use 8/8/8 bits: {key}")
            if float(row["fixed_frame_domain_half_extent"]) <= 0.0:
                raise ValueError(f"fixed-domain run lacks a domain extent: {key}")
    return indexed


def analyze_fixed_domain(rows: list[dict[str, str]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    values = index_miad(rows, fixed_domain=True)
    effects: dict[tuple[str, int], float] = {}
    for geometry, replicate, algorithm, rule in values:
        if rule != "C0_uniform":
            continue
        if algorithm == "A6_rch":
            key = (geometry, replicate)
            sample = values.get((geometry, replicate, "A5_pca_compact_hilbert", rule))
            if sample is None:
                raise ValueError(f"missing paired PCA row for {(geometry, replicate)}")
            effects[key] = values[(geometry, replicate, algorithm, rule)] - sample
    summary = summarize("DetMCD robust frame − sample-covariance PCA; shared domain, C0 8 bits/axis", effects, seed=20261104)
    half_widths = sorted(
        float(row["fixed_frame_domain_half_extent"])
        for row in rows
        if row["algorithm_id"] == "A6_rch"
    )
    summary["shared_cube_half_width"] = {
        "median": median(half_widths),
        "minimum": half_widths[0],
        "maximum": half_widths[-1],
    }
    summary["effective_cell_width"] = {
        "formula": "2 * shared_cube_half_width / 2^8; equal for PCA and DetMCD within each cloud",
        "median": median([2.0 * value / 256.0 for value in half_widths]),
    }
    effect_rows = [
        {"experiment": "fixed_domain", "contrast": summary["contrast"], "geometry_id": g, "replicate": s, "effect": value}
        for (g, s), value in sorted(effects.items())
    ]
    return summary, effect_rows


def analyze_policy_factorial(rows: list[dict[str, str]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    values = index_miad(rows, fixed_domain=False)
    blocks: dict[tuple[str, int], dict[tuple[str, str], float]] = defaultdict(dict)
    for (geometry, replicate, algorithm, rule), value in values.items():
        if rule in RULES and algorithm in FRAMES:
            blocks[(geometry, replicate)][(algorithm, rule)] = value

    effects: dict[str, dict[tuple[str, int], float]] = defaultdict(dict)
    for cloud, measurements in blocks.items():
        expected = {(algorithm, rule) for algorithm in FRAMES for rule in RULES}
        if set(measurements) != expected:
            raise ValueError(f"incomplete 2x3 frame/rule block for {cloud}")
        frame_delta = {
            rule: measurements[("A6_rch", rule)] - measurements[("A5_pca_compact_hilbert", rule)]
            for rule in RULES
        }
        for rule in RULES:
            effects[f"Frame contrast at {rule}: DetMCD − PCA"][cloud] = frame_delta[rule]
        for algorithm, frame_name in FRAMES.items():
            for rule in RULES[1:]:
                effects[f"Rule effect within {frame_name}: {rule} − C2"][cloud] = (
                    measurements[(algorithm, rule)] - measurements[(algorithm, RULES[0])]
                )
        for rule in RULES[1:]:
            effects[f"Frame×rule interaction: ({rule}−C2) in DetMCD minus PCA"][cloud] = (
                frame_delta[rule] - frame_delta[RULES[0]]
            )

    summaries: list[dict[str, Any]] = []
    effect_rows: list[dict[str, Any]] = []
    for index, (name, cloud_effects) in enumerate(sorted(effects.items())):
        summaries.append(summarize(name, cloud_effects, seed=20261200 + index))
        effect_rows.extend(
            {
                "experiment": "C2_C3_C4_factorial",
                "contrast": name,
                "geometry_id": geometry,
                "replicate": replicate,
                "effect": value,
            }
            for (geometry, replicate), value in sorted(cloud_effects.items())
        )
    return summaries, effect_rows


def allocation_summary(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    summaries = []
    for algorithm in FRAMES:
        for rule in RULES:
            selected = [
                row
                for row in rows
                if row["algorithm_id"] == algorithm and row["bit_rule"] == rule
                and row["contamination_id"] == "D0"
            ]
            allocations = Counter(row["bits_axis"] for row in selected)
            totals = [sum(int(value) for value in row["bits_axis"].split()) for row in selected]
            summaries.append(
                {
                    "algorithm_id": algorithm,
                    "bit_rule": rule,
                    "n_clouds": len(selected),
                    "median_total_bits": median(totals),
                    "distinct_axis_allocations": len(allocations),
                    "axis_allocation_counts": dict(sorted(allocations.items())),
                }
            )
    return summaries


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixed-domain-results", type=Path, required=True)
    parser.add_argument("--policy-results", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    fixed_summary, fixed_effects = analyze_fixed_domain(read_rows(args.fixed_domain_results))
    policy_rows = read_rows(args.policy_results)
    policy_summaries, policy_effects = analyze_policy_factorial(policy_rows)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "rch.frame_ablation.analysis.v1",
        "fixed_domain_experiment": fixed_summary,
        "C2_C3_C4_factorial": policy_summaries,
        "bit_allocation_summaries": allocation_summary(policy_rows),
        "interpretation": (
            "These are CLEAN-DATA MIAD effects, not contaminated Kendall stability effects. "
            "The separate frame_stability report evaluates that question. "
            "Effects are conditional on the tested geometries. "
            "The fixed-domain contrast holds the cube and 8-bit axis depth constant; "
            "the factorial contrasts estimate rule-specific differences and interactions."
        ),
    }
    (args.output_dir / "frame_ablation_summary.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    with (args.output_dir / "frame_ablation_cloud_effects.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        fields = ("experiment", "contrast", "geometry_id", "replicate", "effect")
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(fixed_effects + policy_effects)
    print(args.output_dir / "frame_ablation_summary.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
