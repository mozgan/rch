#!/usr/bin/env python3
"""Analyze the independent-sample synthetic replication at cloud level.

Bit rules and contamination levels are averaged within each independently
generated cloud before bootstrap intervals and sign tests are computed.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from collections import defaultdict
from pathlib import Path
from statistics import median
from typing import Any

from scipy.stats import binomtest


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def stratified_bootstrap_median(
    values: dict[str, list[float]], *, draws: int = 20000, seed: int = 20261103
) -> tuple[float, float]:
    """Percentile interval for a median, resampling clouds within geometry."""
    rng = random.Random(seed)
    estimates: list[float] = []
    for _ in range(draws):
        sample = [
            rng.choice(stratum)
            for geometry in sorted(values)
            for stratum in [values[geometry]]
            for _ in range(len(stratum))
        ]
        estimates.append(median(sample))
    estimates.sort()
    return estimates[int(0.025 * draws)], estimates[min(draws - 1, int(0.975 * draws))]


def summarize_cloud_effects(
    name: str, values: dict[tuple[str, int], list[float]],
    *, alternative: str, draws_seed: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    per_cloud = {
        key: sum(effects) / len(effects)
        for key, effects in values.items()
        if effects
    }
    by_geometry: dict[str, list[float]] = defaultdict(list)
    for (geometry, _seed), effect in per_cloud.items():
        by_geometry[geometry].append(effect)
    pooled = [value for geometry in sorted(by_geometry) for value in by_geometry[geometry]]
    lower, upper = stratified_bootstrap_median(
        by_geometry, seed=draws_seed
    )
    positive = sum(value > 0.0 for value in pooled)
    negative = sum(value < 0.0 for value in pooled)
    ties = sum(value == 0.0 for value in pooled)
    if alternative == "greater":
        sign_p = float(binomtest(positive, positive + negative, 0.5, alternative="greater").pvalue)
    else:
        sign_p = float(binomtest(negative, positive + negative, 0.5, alternative="greater").pvalue)
    summary = {
        "comparison": name,
        "unit": "one independently generated cloud; repeated bit rules/contamination averaged within cloud",
        "n_clouds": len(pooled),
        "n_geometries": len(by_geometry),
        "clouds_per_geometry": {g: len(v) for g, v in sorted(by_geometry.items())},
        "median_delta_by_geometry": {
            g: median(v) for g, v in sorted(by_geometry.items())
        },
        "median_cloud_mean_delta": median(pooled),
        "stratified_cloud_bootstrap_95_percentile_ci": [lower, upper],
        "positive_clouds": positive,
        "negative_clouds": negative,
        "tied_clouds": ties,
        "one_sided_exact_sign_test_p": sign_p,
        "sign_test_alternative": "RCH greater" if alternative == "greater" else "RCH lower",
        "bootstrap_resamples": 20000,
        "bootstrap_seed": draws_seed,
    }
    rows = [
        {"comparison": name, "geometry_id": geometry, "replicate": seed, "mean_paired_delta": effect}
        for (geometry, seed), effect in sorted(per_cloud.items())
    ]
    return summary, rows


def analyze_locality(rows: list[dict[str, str]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    methods = {row["algorithm_id"]: row["method"] for row in rows}
    keyed: dict[tuple[str, str, str, str], float] = {}
    for row in rows:
        if row["bit_rule"] not in {"C2_occupancy_floor1", "C3_frame_core_occupancy", "C4_hybrid"}:
            continue
        if row["contamination_id"] != "D0" or row["point_count"] != "384":
            continue
        key = (row["geometry_id"], row["seed"], row["bit_rule"], row["algorithm_id"])
        keyed[key] = float(row["miad"])
    summaries: list[dict[str, Any]] = []
    detail: list[dict[str, Any]] = []
    baselines = ["A3_isotropic_hilbert", "A2_morton", "A7_cgal_spatial_sort"]
    for baseline in baselines:
        effects: dict[tuple[str, int], list[float]] = defaultdict(list)
        for geometry in ("E1", "E2", "E9", "E10"):
            for seed in range(20):
                for rule in ("C2_occupancy_floor1", "C3_frame_core_occupancy", "C4_hybrid"):
                    rk = (geometry, str(seed), rule, "A6_rch")
                    bk = (geometry, str(seed), rule, baseline)
                    if rk not in keyed or bk not in keyed:
                        raise ValueError(f"missing locality pair for {geometry} seed {seed} {rule} {baseline}")
                    effects[(geometry, seed)].append(keyed[rk] - keyed[bk])
        summary, block_rows = summarize_cloud_effects(
            f"RCH MIAD - {methods[baseline]} MIAD",
            effects,
            alternative="less",
            draws_seed=20261103 + len(summaries),
        )
        summaries.append(summary)
        detail.extend(block_rows)
    # Descriptive geometry-stratified summaries are needed because E1 and E2
    # are distinct strata even though their samples are independently drawn.
    return summaries, detail


def analyze_stability(rows: list[dict[str, str]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    effects: dict[tuple[str, int], list[float]] = defaultdict(list)
    keyed: dict[tuple[str, str, str, str, str], float] = {}
    for row in rows:
        if row["bit_rule"] not in {"C2_occupancy_floor1", "C3_frame_core_occupancy", "C4_hybrid"}:
            continue
        if row["contamination_id"] == "D0":
            continue
        key = (row["geometry_id"], row["seed"], row["bit_rule"], row["contamination_id"], row["algorithm_id"])
        keyed[key] = float(row["kendall_tau_clean"])
    for geometry in (
        "E0", "E1", "E2", "E5", "E6", "E7", "E8", "E9", "E10", "E11", "E12"
    ):
        for seed in range(20):
            for rule in ("C2_occupancy_floor1", "C3_frame_core_occupancy", "C4_hybrid"):
                for contamination in ("D1", "D2", "D3", "D4"):
                    rch = (geometry, str(seed), rule, contamination, "A6_rch")
                    pca = (geometry, str(seed), rule, contamination, "A5_pca_compact_hilbert")
                    if rch not in keyed or pca not in keyed:
                        raise ValueError(f"missing stability pair: {rch}")
                    effects[(geometry, seed)].append(keyed[rch] - keyed[pca])
    return summarize_cloud_effects(
        "RCH Kendall tau - sample-covariance frame Kendall tau",
        effects,
        alternative="greater",
        draws_seed=20261110,
    )


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise ValueError(f"refusing to write empty CSV: {path}")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--locality-results", type=Path, required=True)
    parser.add_argument("--stability-results", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    locality, locality_blocks = analyze_locality(read_csv(args.locality_results))
    stability, stability_blocks = analyze_stability(read_csv(args.stability_results))
    ordered = sorted(
        enumerate(locality), key=lambda item: item[1]["one_sided_exact_sign_test_p"]
    )
    running_max = 0.0
    holm: dict[int, float] = {}
    for rank, (index, summary) in enumerate(ordered):
        adjusted = min(1.0, (len(ordered) - rank) * summary["one_sided_exact_sign_test_p"])
        running_max = max(running_max, adjusted)
        holm[index] = running_max
    for index, summary in enumerate(locality):
        summary["holm_adjusted_sign_test_p"] = holm[index]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "schema": "rch.independent_sample_analysis.v1",
        "sampling": "geometry-specific SHA-256 seed derivation; IID point sampling for surface parameterizations",
        "replicates_per_geometry": 20,
        "locality": locality,
        "stability": stability,
        "interpretation": "Inference uses independently generated cloud as the unit. Bit rules and contamination levels are within-cloud repeated measures, not independent observations.",
    }
    (args.output_dir / "independent_sample_summary.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    write_csv(args.output_dir / "locality_cloud_effects.csv", locality_blocks)
    write_csv(args.output_dir / "stability_cloud_effects.csv", stability_blocks)
    print(json.dumps({"locality": locality, "stability": stability}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
