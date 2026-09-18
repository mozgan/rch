#!/usr/bin/env python3
"""Create real-dataset tables and directional H1 stats.

Algorithm:
  1. Read table_2 real-runner CSV rows and coerce finite numeric fields.
  2. Emit deterministic TeX/CSV/JSON table bundles.
  3. Evaluate the directional Real H1 gate per dataset/bit-rule cell.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]


def parse_finite_numeric_cell(value: Any, field: str, path: Path) -> float | None:
    """Parse an optional numeric CSV cell; fail closed on invalid non-empty values."""
    if value in ("", None):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid numeric field {field!r} in {path}: {value!r}") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"non-finite numeric field {field!r} in {path}: {value!r}")
    return parsed


def read_rows(results_dir: Path) -> list[dict[str, Any]]:
    """Read Real CSV rows and coerce numeric fields."""
    path = results_dir / "table_2_dataset_summary.csv"
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            parsed: dict[str, Any] = dict(row)
            for key in (
                "expected_vertices",
                "point_count",
                "clean_point_count",
                "seed",
                "sort_seconds",
                "miad",
                "normalized_miad",
                "m1_l1_locality",
                "l1_locality",
                "m1_l1_sampled",
                "m1_l1_sample_size",
                "m1_l2_locality",
                "l2_locality",
                "m1_l2_sampled",
                "m1_l2_sample_size",
                "recall_8_64",
                "recall_8_64_sampled",
                "recall_8_64_sample_size",
                "peak_rss_kb",
                "block_read_mean",
                "block_read_p95",
                "cache_references",
                "cache_misses",
                "cache_miss_rate",
                "kendall_tau_clean",
                "frame_angle_rad",
            ):
                number = parse_finite_numeric_cell(parsed.get(key), key, path)
                if number is not None:
                    parsed[key] = number
            rows.append(parsed)
    if not rows:
        raise ValueError(f"no Real rows found in {path}")
    return rows


def latex_escape(value: Any) -> str:
    """Escape minimal LaTeX special characters for fallback tables."""
    return (
        str(value)
        .replace("\\", "\\textbackslash{}")
        .replace("_", "\\_")
        .replace("%", "\\%")
        .replace("&", "\\&")
    )


def dataframe_to_latex(
    rows: list[dict[str, Any]], columns: list[str], caption: str, label: str
) -> tuple[str, bool]:
    """Render via pandas when available, otherwise deterministic booktabs."""
    try:
        import pandas as pd  # type: ignore

        frame = pd.DataFrame(rows, columns=columns)
        return (
            frame.to_latex(index=False, escape=False, caption=caption, label=label),
            True,
        )
    except Exception:
        lines = [
            "\\begin{table}",
            f"\\caption{{{latex_escape(caption)}}}",
            f"\\label{{{latex_escape(label)}}}",
            "\\begin{tabular}{" + "l" * len(columns) + "}",
            "\\toprule",
            " & ".join(latex_escape(column) for column in columns) + " \\\\",
            "\\midrule",
        ]
        for row in rows:
            lines.append(
                " & ".join(latex_escape(row.get(column, "")) for column in columns)
                + " \\\\"
            )
        lines.extend(["\\bottomrule", "\\end{tabular}", "\\end{table}", ""])
        return "\n".join(lines), False


def write_table_bundle(
    tables_dir: Path,
    tex_filename: str,
    rows: list[dict[str, Any]],
    columns: list[str],
    caption: str,
    label: str,
    latex: str,
) -> dict[str, str]:
    """Write one generated table as TeX plus machine-readable CSV and JSON."""
    stem = Path(tex_filename).with_suffix("")
    paths = {
        "tex": tables_dir / f"{stem.name}.tex",
        "csv": tables_dir / f"{stem.name}.csv",
        "json": tables_dir / f"{stem.name}.json",
    }
    paths["tex"].write_text(latex, encoding="utf-8")
    with paths["csv"].open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows({column: row.get(column, "") for column in columns} for row in rows)
    paths["json"].write_text(
        json.dumps(
            {
                "schema": "rch.generated_table.v1",
                "caption": caption,
                "label": label,
                "columns": columns,
                "rows": rows,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return {name: str(path) for name, path in paths.items()}


def table_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Format Real rows for the paper-facing real dataset summary table."""
    formatted: list[dict[str, Any]] = []
    for row in sorted(
        rows, key=lambda item: (item["dataset_id"], item["algorithm_id"])
    ):
        formatted.append(
            {
                "dataset_id": row["dataset_id"],
                "geometry_id": row.get("geometry_id", ""),
                "algorithm_id": row["algorithm_id"],
                "bit_rule": row.get("bit_rule", ""),
                "contamination_id": row.get("contamination_id", "D0"),
                "seed": int(row.get("seed", 0)),
                "point_count": int(row["point_count"]),
                "bits_axis": row["bits_axis"],
                "miad": f"{float(row['miad']):.9g}",
                "normalized_miad": f"{float(row['normalized_miad']):.9g}",
                "m1_l1_locality": (
                    f"{float(row['m1_l1_locality']):.9g}"
                    if row.get("m1_l1_locality") not in ("", None)
                    else ""
                ),
                "m1_l1_status": row.get("m1_l1_status", ""),
                "m1_l1_sampled": (
                    f"{float(row['m1_l1_sampled']):.9g}"
                    if row.get("m1_l1_sampled") not in ("", None)
                    else ""
                ),
                "m1_l1_sampled_status": row.get("m1_l1_sampled_status", ""),
                "m1_l2_locality": (
                    f"{float(row['m1_l2_locality']):.9g}"
                    if row.get("m1_l2_locality") not in ("", None)
                    else ""
                ),
                "m1_l2_status": row.get("m1_l2_status", ""),
                "m1_l2_sampled": (
                    f"{float(row['m1_l2_sampled']):.9g}"
                    if row.get("m1_l2_sampled") not in ("", None)
                    else ""
                ),
                "m1_l2_sampled_status": row.get("m1_l2_sampled_status", ""),
                "recall_8_64": (
                    f"{float(row['recall_8_64']):.9g}"
                    if row.get("recall_8_64") not in ("", None)
                    else ""
                ),
                "recall_8_64_status": row.get("recall_8_64_status", ""),
                "recall_8_64_sampled": (
                    f"{float(row['recall_8_64_sampled']):.9g}"
                    if row.get("recall_8_64_sampled") not in ("", None)
                    else ""
                ),
                "recall_8_64_sampled_status": row.get("recall_8_64_sampled_status", ""),
                "peak_rss_kb": (
                    f"{float(row['peak_rss_kb']):.0f}"
                    if row.get("peak_rss_kb") not in ("", None)
                    else ""
                ),
                "cache_miss_rate": (
                    f"{float(row['cache_miss_rate']):.6g}"
                    if row.get("cache_miss_rate") not in ("", None)
                    else ""
                ),
                "block_read_p95": (
                    f"{float(row['block_read_p95']):.9g}"
                    if row.get("block_read_p95") not in ("", None)
                    else ""
                ),
                "perf_status": row.get("perf_status", ""),
                "kendall_tau_clean": (
                    f"{float(row['kendall_tau_clean']):.9g}"
                    if row.get("kendall_tau_clean") not in ("", None)
                    else ""
                ),
                "frame_angle_rad": (
                    f"{float(row['frame_angle_rad']):.9g}"
                    if row.get("frame_angle_rad") not in ("", None)
                    else ""
                ),
                "sort_seconds": f"{float(row['sort_seconds']):.6g}",
                "robust_fallback_used": row["robust_fallback_used"],
            }
        )
    return formatted


def directional_h1(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Evaluate Real H1 directionally by mean MIAD per dataset+bit_rule+D cell.

    Bit-rule awareness: runlist may include multiple
    bit_rules (e.g., C0_uniform and C3_frame_core_occupancy). Without bit_rule in the
    grouping key, the function silently kept only the last-written row per
    (dataset, algorithm), masking the A6/C0 vs A6/C2 distinction in Real
    `real_statistics.json`. The key now includes `bit_rule` and the
    `comparisons` array reports one row per (dataset, bit_rule); the
    `passed` aggregate requires *every* (dataset, bit_rule) cell to satisfy
    A6 < A3.

    Returns a dict with:
      * `comparisons`: one entry per (dataset_id, bit_rule) that has both
        A3 and A6 rows.
      * `outcome`: "confirmed", "failed", or "insufficient_data".
      * `passed`: True iff ≥ 2 comparisons exist AND every delta is finite
        AND strictly negative.
    Edge cases:
      * Missing A3 or A6 row in a (dataset, bit_rule) cell ⇒ skipped.
      * Fewer than 2 cells in comparisons                   ⇒ passed=False.
      * Non-finite delta (NaN/Inf)                          ⇒ passed=False.
    """
    by_cell: dict[tuple[str, str, str], dict[str, list[float]]] = {}
    for row in rows:
        if row["algorithm_id"] not in ("A3_isotropic_hilbert", "A6_rch"):
            continue
        cell = (
            str(row["dataset_id"]),
            str(row.get("bit_rule", "")),
            str(row.get("contamination_id", "D0")),
        )
        by_cell.setdefault(cell, {}).setdefault(str(row["algorithm_id"]), []).append(
            float(row["miad"])
        )
    comparisons: list[dict[str, Any]] = []
    for (dataset_id, bit_rule, contamination_id), values in sorted(by_cell.items()):
        if "A3_isotropic_hilbert" not in values or "A6_rch" not in values:
            continue
        a6_miad = sum(values["A6_rch"]) / float(len(values["A6_rch"]))
        a3_miad = sum(values["A3_isotropic_hilbert"]) / float(
            len(values["A3_isotropic_hilbert"])
        )
        delta = a6_miad - a3_miad
        comparisons.append(
            {
                "dataset_id": dataset_id,
                "bit_rule": bit_rule,
                "contamination_id": contamination_id,
                "a6_miad": a6_miad,
                "a3_miad": a3_miad,
                "delta_a6_minus_a3": delta,
                "seed_count_a6": len(values["A6_rch"]),
                "seed_count_a3": len(values["A3_isotropic_hilbert"]),
                "passed": math.isfinite(delta) and delta < 0.0,
            }
        )
    enough_data = len(comparisons) >= 2
    passed = enough_data and all(item["passed"] for item in comparisons)
    outcome = (
        "confirmed" if passed else ("failed" if enough_data else "insufficient_data")
    )
    return {
        "hypothesis": "H1_real_directional",
        "description": "A6/RCH lower mean MIAD than A3/isotropic Hilbert per (dataset, bit_rule, contamination_id)",
        "primary_metric": "miad",
        "statistical_significance": "Real specifies two real datasets, so this gate is directional rather than Wilcoxon-significance based.",
        "comparisons": comparisons,
        "comparison_count": len(comparisons),
        "outcome": outcome,
        "passed": passed,
    }


def make_real_tables(args: argparse.Namespace) -> dict[str, Any]:
    """Create Real real-data table and stats JSON."""
    rows = read_rows(args.results_dir)
    args.tables_dir.mkdir(parents=True, exist_ok=True)
    args.stats_dir.mkdir(parents=True, exist_ok=True)
    columns = [
        "dataset_id",
        "geometry_id",
        "algorithm_id",
        "bit_rule",
        "contamination_id",
        "seed",
        "point_count",
        "bits_axis",
        "miad",
        "normalized_miad",
        "m1_l1_locality",
        "m1_l1_status",
        "m1_l1_sampled",
        "m1_l1_sampled_status",
        "m1_l2_locality",
        "m1_l2_status",
        "m1_l2_sampled",
        "m1_l2_sampled_status",
        "recall_8_64",
        "recall_8_64_status",
        "recall_8_64_sampled",
        "recall_8_64_sampled_status",
        "kendall_tau_clean",
        "frame_angle_rad",
        "peak_rss_kb",
        "cache_miss_rate",
        "block_read_p95",
        "perf_status",
        "sort_seconds",
        "robust_fallback_used",
    ]
    formatted_rows = table_rows(rows)
    latex, pandas_used = dataframe_to_latex(
        formatted_rows,
        columns,
        "Real dataset summary",
        "tab:real_dataset_summary",
    )
    table_outputs = {
        "table_real_dataset_summary.tex": write_table_bundle(
            args.tables_dir,
            "table_real_dataset_summary.tex",
            formatted_rows,
            columns,
            "Real dataset summary",
            "tab:real_dataset_summary",
            latex,
        )
    }
    h1 = directional_h1(rows)
    h1_rows = h1.get("comparisons", [])
    h1_latex, h1_pandas_used = dataframe_to_latex(
        h1_rows,
        [
            "dataset_id",
            "bit_rule",
            "contamination_id",
            "a6_miad",
            "a3_miad",
            "delta_a6_minus_a3",
            "seed_count_a6",
            "seed_count_a3",
            "passed",
        ],
        "Real directional H1 comparison cells",
        "tab:real_directional_h1",
    )
    table_outputs["table_real_directional_h1_comparisons.tex"] = write_table_bundle(
        args.tables_dir,
        "table_real_directional_h1_comparisons.tex",
        h1_rows,
        [
            "dataset_id",
            "bit_rule",
            "contamination_id",
            "a6_miad",
            "a3_miad",
            "delta_a6_minus_a3",
            "seed_count_a6",
            "seed_count_a3",
            "passed",
        ],
        "Real directional H1 comparison cells",
        "tab:real_directional_h1",
        h1_latex,
    )
    stats = {
        "schema": "rch.real.statistics.v1",
        "pandas_to_latex_used": pandas_used and h1_pandas_used,
        "pandas_available": pandas_used or h1_pandas_used,
        "tables": table_outputs,
        "definition_of_done_metric_scope": "Real H1 real-data gate uses MIAD direction on Bunny and Armadillo; statistical significance is not claimed for n=2.",
        "hypotheses": [h1],
        "definition_of_done_passed": h1["passed"],
    }
    (args.stats_dir / "real_statistics.json").write_text(
        json.dumps(stats, indent=2) + "\n", encoding="utf-8"
    )
    if args.require_h1 and not stats["definition_of_done_passed"]:
        raise SystemExit(
            "Real directional H1 gate failed; see analysis/generated/stats/real_statistics.json"
        )
    return stats


def parse_args() -> argparse.Namespace:
    """Parse the Real table-generation CLI."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=REPO_ROOT / "experiments/outputs/real_dataset/off",
    )
    parser.add_argument(
        "--tables-dir", type=Path, default=REPO_ROOT / "analysis/generated/tables"
    )
    parser.add_argument(
        "--stats-dir", type=Path, default=REPO_ROOT / "analysis/generated/stats"
    )
    parser.add_argument("--require-h1", action="store_true")
    return parser.parse_args()


def main() -> int:
    """CLI entry point for the real dataset summary-table generation."""
    stats = make_real_tables(parse_args())
    print(json.dumps(stats["hypotheses"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
