#!/usr/bin/env python3
"""Summarize repeated per-phase ordering timings from cost-decomposition runs."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from pathlib import Path


SUBPHASES = tuple("robust_" + key for key in ("pilot", "guard", "starts", "concentration", "finalization", "remainder"))

PHASES = (
    "robust_estimator",
    "frame_construction",
    "domain_bit_allocation",
    "quantization_encoding",
    "key_sort",
    "diagnostics",
    "refinement",
)


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    pos = (len(ordered) - 1) * p
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--off", type=Path, required=True)
    parser.add_argument("--all", dest="all_refinement", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    grouped: dict[tuple[str, str, int], list[dict[str, float]]] = {}
    for mode, source in (("off", args.off), ("all", args.all_refinement)):
        with source.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                phases = json.loads(row["timing_breakdown_seconds"])
                counts = json.loads(row.get("robust_work_counts") or "{}")
                key = (mode, row["algorithm_id"], int(row["point_count"]))
                grouped.setdefault(key, []).append(
                    {"total": float(row["sort_seconds"]), **phases, **{"count_" + k: v for k, v in counts.items()}}
                )

    summary: list[dict[str, object]] = []
    for (mode, algorithm, count), records in sorted(grouped.items()):
        if len(records) != 10:
            raise ValueError(f"expected 10 independent records per cell, got {len(records)} for {(mode, algorithm, count)}")
        cell: dict[str, object] = {
            "refinement": mode,
            "algorithm_id": algorithm,
            "point_count": count,
            "independent_clouds": len(records),
        }
        for phase in ("total", *PHASES, *SUBPHASES):
            if not all(phase in record for record in records):
                for stat in ("median", "q1", "q3", "min", "max"):
                    cell[f"{phase}_{stat}_seconds"] = ""
                continue
            values = [record[phase] for record in records]
            cell[f"{phase}_median_seconds"] = statistics.median(values)
            cell[f"{phase}_q1_seconds"] = percentile(values, 0.25)
            cell[f"{phase}_q3_seconds"] = percentile(values, 0.75)
            cell[f"{phase}_min_seconds"] = min(values)
            cell[f"{phase}_max_seconds"] = max(values)
        for counter in ("starts", "concentration_iterations"):
            values = [record.get("count_" + counter) for record in records]
            cell[counter + "_median_count"] = statistics.median(values) if all(x is not None for x in values) else ""
        summary.append(cell)

    for records in grouped.values():
        for record in records:
            for key, value in record.items():
                if not __import__("math").isfinite(value) or value < 0:
                    raise ValueError(f"invalid timing: {key}")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    csv_path = args.out.with_suffix(".csv")
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary[0]))
        writer.writeheader()
        writer.writerows(summary)
    md_path = args.out.with_suffix(".md")
    with md_path.open("w", encoding="utf-8") as handle:
        handle.write("# Stage 2 cost decomposition summary\n\n")
        handle.write("Each cell aggregates 10 independently generated clouds (2 geometries × 5 seeds). Values are medians across cloud-level medians of five in-process timing repeats; parentheses show the interquartile range. Units are milliseconds. `frame` excludes measured DetMCD pilot/estimation time. `total` is end-to-end ordering wall time, including diagnostics and hashing.\n\n")
        handle.write("| Refinement | Algorithm | N | Total | Robust | Frame | Domain/bits | Encode | Key sort | Diagnostics | Refinement |\n")
        handle.write("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|\n")
        for cell in summary:
            def fmt(phase: str) -> str:
                med = float(cell[f"{phase}_median_seconds"]) * 1000
                q1 = float(cell[f"{phase}_q1_seconds"]) * 1000
                q3 = float(cell[f"{phase}_q3_seconds"]) * 1000
                return f"{med:.3f} ({q1:.3f}–{q3:.3f})"
            handle.write(
                f"| {cell['refinement']} | {cell['algorithm_id']} | {cell['point_count']} | "
                + " | ".join(fmt(phase) for phase in ("total", *PHASES))
                + " |\n"
            )
        handle.write("\nNested estimator subphases (pilot, guard, starts, concentration, finalization, remainder) are reported separately in the CSV; never add them again to the top-level robust total. Old inputs lacking subphases have empty cells, not fabricated zeros. The estimator implementation applies consistency/cutoff finalization; no unimplemented reweighting phase is claimed.\n")
        handle.write("\nQ1/Q3 are empirical 25th/75th percentiles over the 10 independent clouds. The separately aggregated phase medians need not sum to the total median. The unassigned wall-time remainder includes input validation, allocations, output hashing, and timer/dispatch overhead.\n")
    print(csv_path)
    print(md_path)


if __name__ == "__main__":
    main()
