#!/usr/bin/env python3
"""Paired, per-geometry summary for the fixed-bit-depth PCA-Hilbert control."""

from __future__ import annotations

import argparse
import csv
import random
import statistics
from collections import defaultdict
from pathlib import Path

ALGORITHMS = (
    "A3_isotropic_hilbert",
    "A5_pca_compact_hilbert",
    "A6_rch",
)
PAIRS = (
    ("A5_pca_compact_hilbert", "A3_isotropic_hilbert"),
    ("A6_rch", "A5_pca_compact_hilbert"),
    ("A6_rch", "A3_isotropic_hilbert"),
)


def bootstrap_median_ci(values: list[float], rng: random.Random, reps: int = 10_000) -> tuple[float, float]:
    draws = sorted(
        statistics.median(rng.choices(values, k=len(values))) for _ in range(reps)
    )
    return draws[int(0.025 * reps)], draws[int(0.975 * reps) - 1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    grouped: dict[str, dict[str, dict[int, float]]] = defaultdict(
        lambda: defaultdict(dict)
    )
    with args.input.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            grouped[row["geometry_id"]][row["algorithm_id"]][int(row["seed"])] = float(
                row["miad"]
            )

    rng = random.Random(20261103)
    rows: list[dict[str, object]] = []
    for geometry, methods in sorted(grouped.items()):
        seeds_by_method = [set(methods[algorithm]) for algorithm in ALGORITHMS]
        common_seeds = set.intersection(*seeds_by_method)
        if len(common_seeds) != 20:
            raise ValueError(f"expected 20 matched independent seeds for {geometry}, got {len(common_seeds)}")
        for algorithm in ALGORITHMS:
            values = [methods[algorithm][seed] for seed in sorted(common_seeds)]
            rows.append({
                "geometry_id": geometry,
                "comparison": "median_miad",
                "left_algorithm": algorithm,
                "right_algorithm": "",
                "n_independent_clouds": len(values),
                "median_difference": statistics.median(values),
                "ci95_low": "",
                "ci95_high": "",
            })
        for left, right in PAIRS:
            differences = [methods[left][seed] - methods[right][seed] for seed in sorted(common_seeds)]
            low, high = bootstrap_median_ci(differences, rng)
            rows.append({
                "geometry_id": geometry,
                "comparison": "paired_median_difference",
                "left_algorithm": left,
                "right_algorithm": right,
                "n_independent_clouds": len(differences),
                "median_difference": statistics.median(differences),
                "ci95_low": low,
                "ci95_high": high,
            })

    args.output.parent.mkdir(parents=True, exist_ok=True)
    csv_path = args.output.with_suffix(".csv")
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    md_path = args.output.with_suffix(".md")
    with md_path.open("w", encoding="utf-8") as handle:
        handle.write("# PCA-frame fixed-resolution Hilbert control\n\n")
        handle.write("A5 uses the existing sample-covariance PCA frame with C0 uniform allocation (10 bits per axis; 30 total bits). A3 is the isotropic fixed 10-bit-per-axis Hilbert reference. A6 is RCH under the same C0 bit rule. Covering boxes and frames differ: equal bit counts do not fix physical cell widths or isolate rotation alone. Each geometry has 20 paired independent clouds (384 points each); differences are left minus right, so negative values favor the left algorithm. Intervals are percentile bootstrap 95% CIs over the independent cloud seeds, computed separately per geometry.\n\n")
        handle.write("| Geometry | Comparison | Median MIAD or paired difference | 95% bootstrap CI | n |\n|---|---|---:|---:|---:|\n")
        for row in rows:
            value = float(row["median_difference"])
            interval = "—" if row["comparison"] == "median_miad" else f"[{float(row['ci95_low']):.6g}, {float(row['ci95_high']):.6g}]"
            comparison = str(row["left_algorithm"])
            if row["right_algorithm"]:
                comparison += f" − {row['right_algorithm']}"
            handle.write(f"| {row['geometry_id']} | {row['comparison']}: {comparison} | {value:.6g} | {interval} | {row['n_independent_clouds']} |\n")
        handle.write("\nThe bootstrap unit is the independently generated cloud seed, not algorithm/run rows. This is a synthetic ordering comparison; it does not measure database query or storage performance.\n")
    print(csv_path)
    print(md_path)


if __name__ == "__main__":
    main()
