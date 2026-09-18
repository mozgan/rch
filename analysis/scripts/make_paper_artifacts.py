#!/usr/bin/env python3
"""Generate paper figures/tables from existing RCH experiment artifacts.

Public API: `make_paper_artifacts(args)`.

Outputs (named `fig_<scope>_<test>_<metric>` / `table_<scope>_<content>`,
scope in {synthetic, real, mixed, cgal, meta}; the two `schema` diagrams are
hand-managed TikZ sources in paper/figures/*.tex and are not generated here):
  * analysis/generated/figures/fig_schema_method_pipeline.pdf
  * analysis/generated/figures/fig_schema_rch_implementation_flow.pdf
  * analysis/generated/figures/fig_synthetic_clean_l1_locality_vs_n.pdf
  * analysis/generated/figures/fig_mixed_recall_heatmap.pdf
  * analysis/generated/figures/fig_synthetic_contamination_kendall_tau.pdf
  * analysis/generated/figures/fig_synthetic_contamination_tau_by_bit_rule.pdf
  * analysis/generated/figures/fig_synthetic_clean_runtime_vs_n.pdf
  * analysis/generated/figures/fig_synthetic_block_read_cache_miss.pdf
  * analysis/generated/figures/fig_mixed_bit_allocation_by_rule.pdf
  * analysis/generated/figures/fig_mixed_ablation_a5_vs_a6_miad.pdf
  * analysis/generated/figures/fig_synthetic_clean_l2_locality_vs_n.pdf
  * analysis/generated/figures/fig_real_refinement_ablation_miad.pdf
  * analysis/generated/tables/table_meta_determinism_by_preset.tex
  * analysis/generated/tables/table_mixed_claim_status.tex
  * analysis/generated/tables/table_mixed_metric_leaders.tex
  * analysis/generated/tables/table_mixed_rch_quantization_summary.tex
  * analysis/generated/tables/table_cgal_a7_fixture.tex
  * analysis/generated/tables/table_real_dataset_catalog.tex
  * analysis/generated/stats/synthetic_refinement_effects.csv
  * analysis/generated/stats/real_refinement_effects.csv
  * analysis/generated/stats/paper_artifacts_manifest.json
  * analysis/generated/outputs/output_snapshot_manifest.json
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
import textwrap
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any, Callable, Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


def display_path(path: Path | None) -> str:
    """Return repo-relative paths for generated CSV/JSON metadata."""
    if path is None:
        return ""
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return path.name if path.is_absolute() else str(path)


ALGORITHM_LABELS = {
    "A0_input": "A0 input order",
    "A1_lexicographic": "A1 lexicographic",
    "A2_morton": "A2 Morton (AABB)",
    "A3_isotropic_hilbert": "A3 isotropic Hilbert (AABB)",
    "A4_compact_hilbert_aabb": "A4 compact Hilbert (AABB)",
    "A5_pca_compact_hilbert": "A5 compact Hilbert (PCA frame)",
    "A5b_robust_frame_morton": "A5b Morton (robust frame)",
    "A6_rch": "A6 RCH (robust frame + Hilbert)",
    "A6_rch_b2_mrcd": "A6 RCH (MRCD frame)",
    "A6_rch_b3_ogk": "A6 RCH (OGK frame)",
    "A7_cgal_spatial_sort": "A7 CGAL spatial_sort",
}

GEOMETRY_LABELS = {
    "E0": "E0 isotropic",
    "E1": "E1 prolate 5:1:1",
    "E2": "E2 prolate 10:1:1",
    "E3": "E3 Bunny",
    "E4": "E4 Armadillo",
    "E5": "E5 surface patch",
    "E6": "E6 torus",
    "E7": "E7 cylinder",
    "E8": "E8 mixed-density",
}
GEOMETRY_ORDER = tuple(GEOMETRY_LABELS)

CONTAMINATION_LABELS = {
    "D0": "D0 clean",
    "D1": "D1 5%",
    "D2": "D2 15%",
    "D3": "D3 25%",
    "D4": "D4 clustered",
}

STABILITY_ALGORITHMS = (
    "A5_pca_compact_hilbert",  # B0: sample covariance / classical PCA frame.
    "A6_rch",  # B1: DetMCD robust frame.
    "A6_rch_b2_mrcd",  # B2: MRCD robust frame.
    "A6_rch_b3_ogk",  # B3: OGK robust frame.
    "A7_cgal_spatial_sort",  # External baseline; no frame-angle claim.
)

PRIMARY_BIT_RULES = (
    "C2_occupancy_floor1",
    "C3_frame_core_occupancy",
    "C4_hybrid",
)
ALL_RECORDED_BIT_RULES = (
    "C0_uniform",
    "C1_monotone_half",
) + PRIMARY_BIT_RULES

MAIN_COMPARISON_BIT_RULE = "C3_frame_core_occupancy"

# Main-result figures compare the algorithm ladder at one representative
# occupancy rule. A0/A1 have no C2 allocator, so their native C0 rows are kept
# as order-only references. Bit-rule comparisons live in the dedicated
# bit-allocation artifact instead of every metric figure.
MAIN_METHOD_COMPARISON_SERIES = (
    ("A0_input", "C0_uniform"),
    ("A1_lexicographic", "C0_uniform"),
    ("A2_morton", MAIN_COMPARISON_BIT_RULE),
    ("A3_isotropic_hilbert", MAIN_COMPARISON_BIT_RULE),
    ("A4_compact_hilbert_aabb", MAIN_COMPARISON_BIT_RULE),
    ("A5_pca_compact_hilbert", MAIN_COMPARISON_BIT_RULE),
    ("A5b_robust_frame_morton", MAIN_COMPARISON_BIT_RULE),
    ("A6_rch", MAIN_COMPARISON_BIT_RULE),
    ("A7_cgal_spatial_sort", MAIN_COMPARISON_BIT_RULE),
)
MAIN_METHOD_COMPARISON_SET = set(MAIN_METHOD_COMPARISON_SERIES)
STABILITY_COMPARISON_SERIES = tuple(
    (algorithm, MAIN_COMPARISON_BIT_RULE) for algorithm in STABILITY_ALGORITHMS
)
STABILITY_COMPARISON_SET = set(STABILITY_COMPARISON_SERIES)

# C-axis (bit-rule) effect figure: algorithms held fixed, occupancy rule
# varied. A5/A5b/A6 are the three frame-curve ablations that actually consume
# the allocated bits; A7 is rule-invariant (identical outputs per rule in the
# recorded artifacts) and A0/A1 have no quantization, so they are omitted.
BIT_RULE_EFFECT_ALGORITHMS = (
    "A5_pca_compact_hilbert",
    "A5b_robust_frame_morton",
    "A6_rch",
)
BIT_RULE_FIGURE_RULES = ("C0_uniform",) + PRIMARY_BIT_RULES
BIT_RULE_STYLES: dict[str, dict[str, Any]] = {
    "C0_uniform": {"color": "#5278a6", "marker": "s", "linestyle": "--"},
    "C2_occupancy_floor1": {"color": "#7f7f7f", "marker": "o", "linestyle": ":"},
    "C3_frame_core_occupancy": {"color": "#2f7d52", "marker": "^", "linestyle": "-"},
    "C4_hybrid": {"color": "#c78b42", "marker": "D", "linestyle": "-."},
}
DEPRECATED_GENERATED_FIGURES = (
    "fig_mixed_c2_bit_allocation.pdf",
    "fig_mixed_c2_bit_allocation.eps",
)

# The 256 clean base and the MRCD/OGK variants were added to the locality
# runlist to enrich the descriptive L1/L2 locality figures only. The
# recall heatmap and the bit-allocation figure stay on the
# original scope (384 clean base, baseline ladder) so their reported numbers
# are unchanged.
DESCRIPTIVE_LOCALITY_CLEAN_SIZE = 384.0
DESCRIPTIVE_EXCLUDED_ALGORITHMS = ("A6_rch_b2_mrcd", "A6_rch_b3_ogk")


def _is_baseline_locality_clean_size(row: dict[str, Any]) -> bool:
    """True for a table_3_locality row at the original (384) clean base."""
    try:
        return float(row.get("clean_point_count")) == DESCRIPTIVE_LOCALITY_CLEAN_SIZE
    except (TypeError, ValueError):
        return False


def _series_key(row: dict[str, Any]) -> tuple[str, str]:
    """Return the algorithm/bit-rule pair for comparison-scope filters."""
    return (str(row.get("algorithm_id", "")), str(row.get("bit_rule", "")))


def distinct_series_colors(count: int) -> list[tuple[float, float, float, float]]:
    """Return a list of visually distinct colors for line series."""
    palettes = ("tab20", "tab20b", "tab20c")
    colors: list[tuple[float, float, float, float]] = []
    for name in palettes:
        cmap = matplotlib.colormaps[name]
        if hasattr(cmap, "colors"):
            colors.extend(list(cmap.colors))
        else:
            colors.extend([cmap(i) for i in range(cmap.N)])
    if count <= len(colors):
        return colors[:count]
    hsv = matplotlib.colormaps["hsv"]
    return [hsv(i / count) for i in range(count)]


def series_style_map(
    series: Iterable[tuple[str, str]],
) -> dict[tuple[str, str], dict[str, Any]]:
    """Map each selected algorithm/bit-rule source to a color+marker."""
    ordered_series = list(series)
    colors = distinct_series_colors(len(ordered_series))
    markers = ["o", "s", "^", "D", "v", "P", "X", "<", ">", "*", "h", "8"]
    linestyles = ["-", "--", "-.", ":"]
    styles: dict[tuple[str, str], dict[str, Any]] = {}
    for index, (key, color) in enumerate(zip(ordered_series, colors)):
        # Alternate filled/open markers with two sizes so series that coincide
        # numerically (e.g. A3 and A4 under equal per-axis bit budgets) stay
        # individually visible instead of one marker hiding the other.
        open_face = index % 2 == 1
        styles[key] = {
            "color": color,
            "marker": markers[index % len(markers)],
            "linestyle": linestyles[index % len(linestyles)],
            "markerfacecolor": "none" if open_face else color,
            "markersize": 7.5 if open_face else 5.0,
        }
    return styles


def default_series_style(index: int = 0) -> dict[str, Any]:
    """Fallback style for rows absent from the locality figure, same vocabulary."""
    colors = distinct_series_colors(index + 1)
    markers = ["o", "s", "^", "D", "v", "P", "X", "<", ">", "*", "h", "8"]
    linestyles = ["-", "--", "-.", ":"]
    open_face = index % 2 == 1
    return {
        "color": colors[index],
        "marker": markers[index % len(markers)],
        "linestyle": linestyles[index % len(linestyles)],
        "markerfacecolor": "none" if open_face else colors[index],
        "markersize": 7.5 if open_face else 5.0,
    }


def line_kwargs(style: dict[str, Any]) -> dict[str, Any]:
    """Shared `ax.plot` keyword set for one metric-line series style."""
    return {
        "color": style["color"],
        "marker": style["marker"],
        "linestyle": style["linestyle"],
        "markerfacecolor": style.get("markerfacecolor", style["color"]),
        "markersize": style.get("markersize", 5.5),
        "markeredgecolor": (
            style["color"] if style.get("markerfacecolor") == "none" else "#1a1a1a"
        ),
        "markeredgewidth": 1.1 if style.get("markerfacecolor") == "none" else 0.5,
        "alpha": 0.9,
    }


def series_label(algorithm: str, bit_rule: str) -> str:
    """Human-readable label for one algorithm/bit-rule data source."""
    return f"{ALGORITHM_LABELS.get(algorithm, algorithm)} / {bit_rule}"


def place_legend_outside(
    fig: matplotlib.figure.Figure,
    handles: list[matplotlib.artist.Artist],
    labels: list[str],
    *,
    fontsize: int = 8,
    ncol: int = 1,
    anchor_x: float = 0.98,
    anchor_y: float = 0.5,
) -> None:
    """Place a shared legend outside the axes area to avoid overlap."""
    if not handles:
        return
    fig.legend(
        handles,
        labels,
        loc="center left",
        bbox_to_anchor=(anchor_x, anchor_y),
        fontsize=fontsize,
        ncol=ncol,
        frameon=False,
    )


def place_legend_below(
    fig: matplotlib.figure.Figure,
    handles: list[matplotlib.artist.Artist],
    labels: list[str],
    *,
    fontsize: int = 7,
    ncol: int = 2,
) -> None:
    """Place a shared legend under the axes; `bbox_inches='tight'` crops to it.

    Unlike the right-hand `place_legend_outside`, this wastes no horizontal
    space, which matters for the single-axes metric-vs-N line figures.
    """
    if not handles:
        return
    fig.legend(
        handles,
        labels,
        loc="upper center",
        bbox_to_anchor=(0.5, 0.0),
        fontsize=fontsize,
        ncol=ncol,
        frameon=False,
        columnspacing=1.2,
        handletextpad=0.6,
    )


@dataclass(frozen=True)
class FigureSpec:
    """Bind one figure filename to one renderer strategy."""

    filename: str
    renderer: Callable[["PaperArtifactContext", Path], dict[str, Any]]


@dataclass(frozen=True)
class PaperArtifactContext:
    """Read-only paths and rows shared by all renderers."""

    synthetic_rows: list[dict[str, Any]]
    synthetic_refinement_rows: list[dict[str, Any]]
    real_rows: list[dict[str, Any]]
    real_refinement_rows: list[dict[str, Any]]
    a7_rows: list[dict[str, Any]]
    synthetic_stats: dict[str, Any]
    real_stats: dict[str, Any]
    test_logs: list[dict[str, Any]]
    dataset_catalog: list[dict[str, Any]]
    figures_dir: Path
    tables_dir: Path
    stats_dir: Path


def numeric(value: Any) -> float | None:
    """Parse a finite float, returning None for empty/non-finite cells."""
    if value in ("", None):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


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


def read_csv_rows(path: Path) -> list[dict[str, Any]]:
    """Read one CSV file and coerce known numeric fields."""
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            parsed: dict[str, Any] = dict(row)
            for key in (
                "point_count",
                "clean_point_count",
                "seed",
                "expected_vertices",
                "sort_seconds",
                "peak_rss_kb",
                "block_read_mean",
                "block_read_p95",
                "cache_references",
                "cache_misses",
                "cache_miss_rate",
                "miad",
                "normalized_miad",
                "m1_l1_locality",
                "l1_locality",
                "m1_l2_locality",
                "l2_locality",
                "recall_8_64",
                "recall_8_64_sampled",
                "kendall_tau_clean",
                "frame_angle_rad",
            ):
                number = parse_finite_numeric_cell(parsed.get(key), key, path)
                if number is not None:
                    parsed[key] = number
            rows.append(parsed)
    return rows


def read_synthetic_rows(results_dir: Path) -> list[dict[str, Any]]:
    """Read all present Synthetic summary CSVs."""
    rows: list[dict[str, Any]] = []
    for filename in (
        "table_3_locality.csv",
        "table_4_outlier.csv",
        "table_5_runtime.csv",
    ):
        path = results_dir / filename
        if path.exists():
            rows.extend(read_csv_rows(path))
    if not rows:
        raise ValueError(f"no Synthetic rows found under {results_dir}")
    return rows


def read_optional_csv(path: Path) -> list[dict[str, Any]]:
    """Read an optional CSV; missing files mean the artifact is absent."""
    if not path.exists():
        return []
    return read_csv_rows(path)


# Refinement-ablation arms, in plotting order (none -> all non-input methods).
# Must stay in sync with experiments/configs/sweeps/refinement.yaml, the
# declared source of the R-axis arms run by `make bench-real`.
REFINEMENT_MODES = ("off", "all")
REAL_REFINEMENT_MODES = REFINEMENT_MODES


def read_synthetic_refinement_rows(base_dir: Path) -> list[dict[str, Any]]:
    """Read the synthetic refinement-ablation arms written by `make bench-synthetic`."""
    rows: list[dict[str, Any]] = []
    for mode in REFINEMENT_MODES:
        arm_dir = base_dir / mode
        if arm_dir.exists():
            for filename in (
                "table_3_locality.csv",
                "table_4_outlier.csv",
                "table_5_runtime.csv",
            ):
                for row in read_optional_csv(arm_dir / filename):
                    row["refinement"] = mode
                    rows.append(row)
    return rows


def read_real_refinement_rows(base_dir: Path) -> list[dict[str, Any]]:
    """Read the real-data refinement-ablation arms written by `make bench-real`.

    Each mode lives in its own self-contained arm at
    `<base_dir>/<mode>/table_2_dataset_summary.csv`. The `refinement` field is
    re-stamped from the arm directory so the tag is authoritative regardless of
    what the per-row CSV column happens to hold.
    """
    rows: list[dict[str, Any]] = []
    for mode in REAL_REFINEMENT_MODES:
        arm = read_optional_csv(base_dir / mode / "table_2_dataset_summary.csv")
        for row in arm:
            row["refinement"] = mode
            rows.append(row)
    return rows


def read_json(path: Path) -> dict[str, Any]:
    """Read a JSON object, returning an empty object when absent."""
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def read_dataset_catalog(path: Path) -> list[dict[str, Any]]:
    """Read optional real-dataset scope catalog without implying measurement."""
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return []
    datasets = data.get("datasets", [])
    return datasets if isinstance(datasets, list) else []


def read_test_logs(logs_dir: Path) -> list[dict[str, Any]]:
    """Read timestamped test logs used for Table 4 determinism evidence."""
    logs: list[dict[str, Any]] = []
    for path in sorted(logs_dir.glob("test_*.json")):
        data = read_json(path)
        if data:
            data["path"] = path.name
            logs.append(data)
    return logs


def mean_by(
    rows: Iterable[dict[str, Any]], keys: tuple[str, ...], metric: str
) -> dict[tuple[Any, ...], float]:
    """Group finite metric values by a key tuple and return mean values."""
    buckets: dict[tuple[Any, ...], list[float]] = defaultdict(list)
    for row in rows:
        value = numeric(row.get(metric))
        if value is None:
            continue
        buckets[tuple(row.get(key) for key in keys)].append(value)
    return {key: mean(values) for key, values in buckets.items() if values}


def mean_count_by(
    rows: Iterable[dict[str, Any]], keys: tuple[str, ...], metric: str
) -> dict[tuple[Any, ...], tuple[float, int]]:
    """Group finite metric values by key and return (mean, n)."""
    buckets: dict[tuple[Any, ...], list[float]] = defaultdict(list)
    for row in rows:
        value = numeric(row.get(metric))
        if value is None:
            continue
        buckets[tuple(row.get(key) for key in keys)].append(value)
    return {key: (mean(values), len(values)) for key, values in buckets.items() if values}


def short_float(value: float | None) -> str:
    """Format compact paper-table estimates without hiding scientific scale."""
    if value is None:
        return ""
    return f"{value:.6g}"


def metric_leader_row(
    *,
    scope: str,
    metric: str,
    direction: str,
    rows: Iterable[dict[str, Any]],
    note: str,
) -> dict[str, Any]:
    """Return the best algorithm/bit-rule mean for one metric scope."""
    grouped = mean_count_by(rows, ("algorithm_id", "bit_rule"), metric)
    if not grouped:
        return {
            "scope": scope,
            "metric": metric,
            "direction": direction,
            "algorithm_id": "not_available",
            "bit_rule": "",
            "estimate": "",
            "n": 0,
            "note": note,
        }
    selector = min if direction == "lower" else max
    best_value = selector(value for value, _ in grouped.values())
    winners = sorted(
        key for key, (value, _) in grouped.items() if math.isclose(value, best_value)
    )
    algorithm_id, bit_rule = winners[0]
    _, count = grouped[winners[0]]
    suffix = f"; {len(winners)} tied" if len(winners) > 1 else ""
    return {
        "scope": scope,
        "metric": metric,
        "direction": direction,
        "algorithm_id": algorithm_id,
        "bit_rule": bit_rule,
        "estimate": short_float(best_value),
        "n": count,
        "note": note + suffix,
    }


def metric_leader_rows(ctx: PaperArtifactContext) -> list[dict[str, Any]]:
    """Build compact metric-leader rows for a paper results overview."""
    synthetic_clean = [
        row
        for row in ctx.synthetic_rows
        if row.get("runlist") == "table_3_locality"
        and row.get("contamination_id") == "D0"
    ]
    synthetic_runtime = [
        row
        for row in ctx.synthetic_rows
        if row.get("runlist") == "table_5_runtime"
        and row.get("contamination_id") == "D0"
    ]
    synthetic_stability = [
        row
        for row in ctx.synthetic_rows
        if row.get("runlist") == "table_4_outlier"
        and row.get("contamination_id") != "D0"
        and row.get("algorithm_id") in STABILITY_ALGORITHMS
    ]
    real_rows = [
        row for row in ctx.real_rows if row.get("contamination_id", "D0") == "D0"
    ]
    return [
        metric_leader_row(
            scope="synthetic clean",
            metric="miad",
            direction="lower",
            rows=synthetic_clean,
            note="table_3 D0 mean",
        ),
        metric_leader_row(
            scope="synthetic clean",
            metric="m1_l1_locality",
            direction="lower",
            rows=synthetic_clean,
            note="table_3 D0 mean",
        ),
        metric_leader_row(
            scope="synthetic clean",
            metric="m1_l2_locality",
            direction="higher",
            rows=synthetic_clean,
            note="table_3 D0 mean",
        ),
        metric_leader_row(
            scope="synthetic clean",
            metric="recall_8_64",
            direction="higher",
            rows=synthetic_clean,
            note="table_3 D0 mean",
        ),
        metric_leader_row(
            scope="synthetic D1-D4",
            metric="kendall_tau_clean",
            direction="higher",
            rows=synthetic_stability,
            note="frame/curve stability set",
        ),
        metric_leader_row(
            scope="synthetic runtime",
            metric="sort_seconds",
            direction="lower",
            rows=synthetic_runtime,
            note="table_5 D0 mean",
        ),
        metric_leader_row(
            scope="synthetic runtime",
            metric="cache_miss_rate",
            direction="lower",
            rows=synthetic_runtime,
            note="table_5 D0 mean",
        ),
        metric_leader_row(
            scope="real D0",
            metric="normalized_miad",
            direction="lower",
            rows=real_rows,
            note="full-cloud exact rows",
        ),
        metric_leader_row(
            scope="real D0",
            metric="m1_l1_locality",
            direction="lower",
            rows=real_rows,
            note="full-cloud exact rows",
        ),
        metric_leader_row(
            scope="real D0",
            metric="m1_l2_locality",
            direction="higher",
            rows=real_rows,
            note="minimum-ratio diagnostic",
        ),
        metric_leader_row(
            scope="real D0",
            metric="recall_8_64",
            direction="higher",
            rows=real_rows,
            note="full-cloud exact rows",
        ),
    ]


def rch_quantization_summary_rows(ctx: PaperArtifactContext) -> list[dict[str, Any]]:
    """Summarize A6/RCH metric means by bit rule for paper discussion."""
    output: list[dict[str, Any]] = []
    scopes = [
        (
            "synthetic clean",
            [
                row
                for row in ctx.synthetic_rows
                if row.get("algorithm_id") == "A6_rch"
                and row.get("runlist") == "table_3_locality"
                and row.get("contamination_id") == "D0"
            ],
            [
                row
                for row in ctx.synthetic_rows
                if row.get("algorithm_id") == "A6_rch"
                and row.get("runlist") == "table_5_runtime"
                and row.get("contamination_id") == "D0"
            ],
        ),
        (
            "real D0",
            [
                row
                for row in ctx.real_rows
                if row.get("algorithm_id") == "A6_rch"
                and row.get("contamination_id", "D0") == "D0"
            ],
            [
                row
                for row in ctx.real_rows
                if row.get("algorithm_id") == "A6_rch"
                and row.get("contamination_id", "D0") == "D0"
            ],
        ),
    ]
    for scope, metric_rows, runtime_rows in scopes:
        metric_means = {
            metric: mean_count_by(metric_rows, ("bit_rule",), metric)
            for metric in (
                "miad",
                "normalized_miad",
                "m1_l1_locality",
                "m1_l2_locality",
                "recall_8_64",
            )
        }
        runtime_means = mean_count_by(runtime_rows, ("bit_rule",), "sort_seconds")
        for rule in ALL_RECORDED_BIT_RULES:
            key = (rule,)
            n_metric = max(
                (values[key][1] for values in metric_means.values() if key in values),
                default=0,
            )
            output.append(
                {
                    "scope": scope,
                    "bit_rule": rule,
                    "miad": short_float(metric_means["miad"].get(key, (None, 0))[0]),
                    "normalized_miad": short_float(
                        metric_means["normalized_miad"].get(key, (None, 0))[0]
                    ),
                    "m1_l1": short_float(
                        metric_means["m1_l1_locality"].get(key, (None, 0))[0]
                    ),
                    "m1_l2": short_float(
                        metric_means["m1_l2_locality"].get(key, (None, 0))[0]
                    ),
                    "recall_8_64": short_float(
                        metric_means["recall_8_64"].get(key, (None, 0))[0]
                    ),
                    "sort_seconds": short_float(runtime_means.get(key, (None, 0))[0]),
                    "n_metric": n_metric,
                    "n_runtime": runtime_means.get(key, (None, 0))[1],
                }
            )
    return output


def parse_bits_axis(value: Any) -> tuple[int, int, int] | None:
    """Parse `bits_axis` strings like '8 7 5' into a 3-tuple."""
    if not isinstance(value, str):
        return None
    parts = value.split()
    if len(parts) != 3:
        return None
    try:
        bits = tuple(int(part) for part in parts)
    except ValueError:
        return None
    return bits if all(bit >= 0 for bit in bits) else None


def latex_escape(value: Any) -> str:
    """Escape minimal LaTeX special characters for generated tables."""
    return (
        str(value)
        .replace("\\", "\\textbackslash{}")
        .replace("_", "\\_")
        .replace("%", "\\%")
        .replace("&", "\\&")
    )


def latex_table(
    rows: list[dict[str, Any]], columns: list[str], caption: str, label: str
) -> str:
    """Render a compact deterministic booktabs table."""
    align = "l" * len(columns)
    lines = [
        "\\begin{table}",
        f"\\caption{{{latex_escape(caption)}}}",
        f"\\label{{{label}}}",
        f"\\begin{{tabular}}{{{align}}}",
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
    return "\n".join(lines)


def write_table_bundle(
    tables_dir: Path,
    filename: str,
    rows: list[dict[str, Any]],
    columns: list[str],
    caption: str,
    label: str,
) -> dict[str, Any]:
    """Write one generated table as TeX plus CSV and JSON."""
    stem = Path(filename).with_suffix("")
    paths = {
        "tex": tables_dir / f"{stem.name}.tex",
        "csv": tables_dir / f"{stem.name}.csv",
        "json": tables_dir / f"{stem.name}.json",
    }
    paths["tex"].write_text(
        latex_table(rows, columns, caption, label), encoding="utf-8"
    )
    with paths["csv"].open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(
            {column: row.get(column, "") for column in columns} for row in rows
        )
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
    return {
        "path": display_path(paths["tex"]),
        "status": "generated",
        "formats": {name: str(path) for name, path in paths.items()},
        "row_count": len(rows),
    }


def remove_deprecated_generated_figures(figures_dir: Path) -> None:
    """Remove old generated figure aliases that would otherwise survive reruns."""
    for filename in DEPRECATED_GENERATED_FIGURES:
        path = figures_dir / filename
        if path.exists():
            path.unlink()


def save_text_figure(
    output: Path, title: str, lines: list[str], *, status: str
) -> dict[str, Any]:
    """Create a vector PDF that records absent/unsupported evidence honestly."""
    output.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    ax.axis("off")
    ax.text(0.02, 0.92, title, fontsize=14, fontweight="bold", va="top")
    ax.text(0.02, 0.82, "\n".join(lines), fontsize=10.5, va="top", linespacing=1.35)
    ax.text(
        0.02, 0.08, f"Status: {status}", fontsize=10, fontweight="bold", color="#8a4b00"
    )
    fig.tight_layout()
    fig.savefig(output, bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
    return {"path": display_path(output), "status": status}


def render_schema_method_pipeline(
    ctx: PaperArtifactContext, output: Path
) -> dict[str, Any]:
    """Render the RCH method-pipeline schema from `include/rch/orderings/orderer.hpp`."""
    steps = [
        (r"$N \times 3$ input", "row-major span"),
        ("Validate", "shape + finite"),
        ("Frame model", "DetMCD/MRCD/OGK\nor sample fallback"),
        ("Project + domain", r"$y_i = R^{T}(x_i - c)$" + "\n" + r"$[-a_j, +a_j]$"),
        ("Allocate\nbits", "C0-C4 bit rules\n" + r"$\sum_j m_j \leq 63$"),
        ("Encode key", "compact Hilbert\nor Morton"),
        (
            "Sort/refine + hash",
            r"$\mathrm{CurveKey}$ order" + "\noptional local MIAD" + "\nSHA-256",
        ),
    ]
    fig, ax = plt.subplots(figsize=(14.8, 3.25))
    ax.axis("off")
    left = 0.030
    box_width = 0.125
    gap = (1.0 - (2.0 * left) - (len(steps) * box_width)) / (len(steps) - 1)
    xs = [left + (box_width / 2.0) + i * (box_width + gap) for i in range(len(steps))]
    y = 0.52
    for i, (x, (title, subtitle)) in enumerate(zip(xs, steps)):
        ax.text(
            x,
            y,
            f"{title}\n{subtitle}",
            ha="center",
            va="center",
            fontsize=9.6,
            linespacing=1.24,
            bbox={
                "boxstyle": "round,pad=0.55",
                "facecolor": "#eef4fb",
                "edgecolor": "#2f5f8f",
            },
        )
        if i < len(xs) - 1:
            start_x = x + (box_width / 2.0)
            end_x = xs[i + 1] - (box_width / 2.0)
            ax.annotate(
                "",
                xy=(end_x, y),
                xytext=(start_x, y),
                arrowprops={"arrowstyle": "->", "lw": 1.2, "color": "#2f5f8f"},
            )
    ax.set_xlim(0.0, 1.0)
    ax.set_ylim(0.0, 1.0)
    fig.tight_layout(rect=(0.0, 0.0, 1.0, 0.96))
    fig.savefig(output, bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
    return {"path": display_path(output), "status": "generated_conceptual"}


def render_schema_rch_implementation_flow(
    ctx: PaperArtifactContext, output: Path
) -> dict[str, Any]:
    """Render an implementation-oriented RCH flow diagram."""
    nodes = [
        ("1. dispatch + validation", "method selected; size%3==0; finite-only gate"),
        (
            "2. prepare frame",
            "RCH: robust scatter via DetMCD/MRCD/OGK; A5: sample covariance",
        ),
        (
            "3. fallback semantics",
            "tiny/rank-deficient robust model -> sample frame + telemetry",
        ),
        (
            "4. project to frame",
            r"$y_i = R^{T}(x_i - c)$; AABB methods skip this branch",
        ),
        (
            "5. domain + bit allocation",
            "half-extents [-a_j,+a_j]; C0-C4; sum_j m_j <= 63",
        ),
        (
            "6. quantize + encode",
            "per-axis quantization; compact Hilbert or Morton key",
        ),
        (
            "7. total-order sort + optional refinement",
            r"$\mathrm{CurveKey}\{h, y_x, y_y, y_z, \mathrm{raw\_idx}\}$"
            + "; local MIAD pass when enabled",
        ),
        (
            "8. reproducibility digest",
            r"$\mathrm{SHA256}(\mathrm{method},\mathrm{bits},\mathrm{fallback},P,K)$",
        ),
    ]
    fig, ax = plt.subplots(figsize=(12.6, 9.2))
    ax.axis("off")
    x = 0.5
    top_y = 0.89
    step = 0.110
    box_height = 0.088
    for i, (title, subtitle) in enumerate(nodes):
        y = top_y - i * step
        readable_subtitle = "\n".join(
            textwrap.wrap(subtitle, width=76, break_long_words=False)
        )
        ax.text(
            x,
            y,
            f"{title}\n{readable_subtitle}",
            ha="center",
            va="center",
            fontsize=10.5,
            linespacing=1.24,
            bbox={
                "boxstyle": "round,pad=0.62",
                "facecolor": "#f6f3e8",
                "edgecolor": "#826b2f",
            },
        )
        if i < len(nodes) - 1:
            next_y = top_y - (i + 1) * step
            ax.annotate(
                "",
                xy=(x, next_y + box_height / 2.0),
                xytext=(x, y - box_height / 2.0),
                arrowprops={"arrowstyle": "->", "lw": 1.15, "color": "#826b2f"},
            )
    ax.set_xlim(0.0, 1.0)
    ax.set_ylim(0.0, 1.0)
    fig.tight_layout(rect=(0.0, 0.0, 1.0, 0.97))
    fig.savefig(output, bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
    return {"path": display_path(output), "status": "generated_conceptual"}


def render_synthetic_clean_l1_locality_vs_n(
    ctx: PaperArtifactContext, output: Path
) -> dict[str, Any]:
    """Render the synthetic clean exact-M1-L1-locality-vs-N figure (table_3 rows)."""
    rows = [
        row
        for row in ctx.synthetic_rows
        if row.get("contamination_id") == "D0"
        and row.get("runlist") == "table_3_locality"
        and _series_key(row) in MAIN_METHOD_COMPARISON_SET
    ]
    grouped = mean_by(
        rows, ("algorithm_id", "bit_rule", "point_count"), "m1_l1_locality"
    )
    if not grouped:
        return save_text_figure(
            output,
            "Synthetic clean L1 locality vs N",
            ["No finite m1_l1_locality values were found in table_3_locality rows."],
            status="not_available",
        )
    series = [
        key
        for key in MAIN_METHOD_COMPARISON_SERIES
        if any(group_key[:2] == key for group_key in grouped)
    ]
    styles = series_style_map(series)
    fig, ax = plt.subplots(figsize=(7.0, 4.0))
    all_ns = sorted({point_count for _, _, point_count in grouped})
    for index, (algorithm, bit_rule) in enumerate(series):
        xs = sorted(
            point_count
            for name, rule, point_count in grouped
            if name == algorithm and rule == bit_rule
        )
        ys = [grouped[(algorithm, bit_rule, point_count)] for point_count in xs]
        style = styles.get((algorithm, bit_rule), default_series_style(index))
        ax.plot(
            xs,
            ys,
            label=series_label(algorithm, bit_rule),
            **line_kwargs(style),
        )
    ax.set_xscale("log", base=2)
    ax.set_yscale("log")
    # The clean locality runlist records only these N values; label them
    # directly (384 is not a power of two, so log2 auto-ticks would skip it).
    ax.set_xticks(all_ns, [str(int(n)) for n in all_ns])
    ax.set_xlabel("N (points)")
    ax.set_ylabel("Exact M1 L1 locality")
    ax.grid(True, alpha=0.25)
    handles, labels = ax.get_legend_handles_labels()
    place_legend_below(fig, handles, labels, fontsize=7, ncol=2)
    fig.tight_layout()
    fig.savefig(output, bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
    return {"path": display_path(output), "status": "generated_from_synthetic"}


def render_synthetic_clean_l2_locality_vs_n(
    ctx: PaperArtifactContext, output: Path
) -> dict[str, Any]:
    """Render the synthetic clean exact-M1-L2-locality-vs-N figure (table_3 rows).

    L2 is the Gotsman-Lindenbaum *minimum* ratio (best-case locality), the
    companion of the L1 (worst-case) measure in the L1 figure.
    """
    rows = [
        row
        for row in ctx.synthetic_rows
        if row.get("contamination_id") == "D0"
        and row.get("runlist") == "table_3_locality"
        and _series_key(row) in MAIN_METHOD_COMPARISON_SET
    ]
    grouped = mean_by(
        rows, ("algorithm_id", "bit_rule", "point_count"), "m1_l2_locality"
    )
    if not grouped:
        return save_text_figure(
            output,
            "Synthetic clean L2 locality vs N",
            ["No finite m1_l2_locality values were found in table_3_locality rows."],
            status="not_available",
        )
    series = [
        key
        for key in MAIN_METHOD_COMPARISON_SERIES
        if any(group_key[:2] == key for group_key in grouped)
    ]
    styles = series_style_map(series)
    fig, ax = plt.subplots(figsize=(7.0, 4.0))
    all_ns = sorted({point_count for _, _, point_count in grouped})
    for index, (algorithm, bit_rule) in enumerate(series):
        xs = sorted(
            point_count
            for name, rule, point_count in grouped
            if name == algorithm and rule == bit_rule
        )
        ys = [grouped[(algorithm, bit_rule, point_count)] for point_count in xs]
        style = styles.get((algorithm, bit_rule), default_series_style(index))
        ax.plot(
            xs,
            ys,
            label=series_label(algorithm, bit_rule),
            **line_kwargs(style),
        )
    ax.set_xscale("log", base=2)
    ax.set_yscale("log")
    ax.set_xticks(all_ns, [str(int(n)) for n in all_ns])
    ax.set_xlabel("N (points)")
    ax.set_ylabel("Exact M1 L2 locality")
    ax.grid(True, alpha=0.25)
    handles, labels = ax.get_legend_handles_labels()
    place_legend_below(fig, handles, labels, fontsize=7, ncol=2)
    fig.tight_layout()
    fig.savefig(output, bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
    return {"path": display_path(output), "status": "generated_from_synthetic"}


def render_mixed_recall_heatmap(
    ctx: PaperArtifactContext, output: Path
) -> dict[str, Any]:
    """Render recall heatmap from synthetic and real recall artifacts."""
    synthetic_rows = [
        row
        for row in ctx.synthetic_rows
        if row.get("runlist") == "table_3_locality"
        and _is_baseline_locality_clean_size(row)
        and _series_key(row) in MAIN_METHOD_COMPARISON_SET
    ]
    real_rows = [
        row
        for row in ctx.real_rows
        if _series_key(row) in MAIN_METHOD_COMPARISON_SET
        and row.get("geometry_id") in ("E3", "E4")
    ]
    synthetic_grouped = mean_by(
        synthetic_rows, ("algorithm_id", "bit_rule", "geometry_id"), "recall_8_64"
    )
    grouped = dict(synthetic_grouped)
    real_metric = (
        "recall_8_64"
        if any(numeric(row.get("recall_8_64")) is not None for row in real_rows)
        else "recall_8_64_sampled"
    )
    real_status_field = f"{real_metric}_status"
    real_grouped = mean_by(
        real_rows,
        ("algorithm_id", "bit_rule", "geometry_id"),
        real_metric,
    )
    real_status_counts: dict[str, int] = defaultdict(int)
    for row in real_rows:
        status = str(row.get(real_status_field, "")).strip()
        if status:
            real_status_counts[status] += 1
    grouped.update(real_grouped)
    if not grouped:
        return save_text_figure(
            output,
            "Mixed recall@8 within 64-window",
            [
                f"No finite synthetic recall_8_64 or real {real_metric} values",
                "were found in the selected artifact rows.",
            ],
            status="not_available",
        )
    algorithms = [
        key
        for key in MAIN_METHOD_COMPARISON_SERIES
        if any(group_key[:2] == key for group_key in grouped)
    ]
    geometries = [
        geometry
        for geometry in GEOMETRY_ORDER
        if any(group_key[2] == geometry for group_key in grouped)
    ]
    # Synthetic and real recall (window 64 over very different point-count
    # scales) live on incomparable scales: on one
    # shared [0, 1] colour axis the real columns are uniformly near-black and
    # carry no within-column contrast. Render them as two panels with
    # independent colour normalisation; the annotated absolute values remain
    # the primary record in both panels.
    real_geometries = [g for g in geometries if g in ("E3", "E4")]
    synthetic_geometries = [g for g in geometries if g not in ("E3", "E4")]
    panels = [
        (synthetic_geometries, "exact recall@8_64 (synthetic)", 1.0),
    ]
    if real_geometries:
        real_max = max(
            (
                value
                for (alg, rule, geo), value in grouped.items()
                if geo in real_geometries and math.isfinite(value)
            ),
            default=1.0,
        )
        panels.append(
            (real_geometries, f"{real_metric} (real)", max(real_max * 1.1, 0.01))
        )
    fig_width = max(9.6, 1.05 * len(geometries) + 0.72 * len(algorithms))
    fig_height = max(5.4, 0.42 * len(algorithms) + 2.0)
    fig, axes = plt.subplots(
        1,
        len(panels),
        figsize=(fig_width, fig_height),
        width_ratios=[max(len(p[0]), 1) for p in panels],
    )
    axes = list(np.atleast_1d(axes))
    cmap = matplotlib.colormaps["viridis"].copy()
    cmap.set_bad("#efefef")
    for panel_index, (ax, (panel_geometries, colorbar_label, vmax)) in enumerate(
        zip(axes, panels)
    ):
        matrix = [
            [
                grouped.get((algorithm, bit_rule, geometry), math.nan)
                for geometry in panel_geometries
            ]
            for algorithm, bit_rule in algorithms
        ]
        matrix_array = np.ma.masked_invalid(np.asarray(matrix, dtype=float))
        image = ax.imshow(matrix_array, cmap=cmap, vmin=0.0, vmax=vmax, aspect="auto")
        ax.set_xticks(
            range(len(panel_geometries)),
            [GEOMETRY_LABELS.get(item, item) for item in panel_geometries],
        )
        if panel_index == 0:
            ax.set_yticks(
                range(len(algorithms)),
                [
                    f"{ALGORITHM_LABELS.get(item[0], item[0])} / {item[1]}"
                    for item in algorithms
                ],
            )
        else:
            ax.set_yticks(range(len(algorithms)), [""] * len(algorithms))
        ax.tick_params(axis="x", labelrotation=30, labelsize=9)
        ax.tick_params(axis="y", labelsize=9)
        for i, (algorithm, bit_rule) in enumerate(algorithms):
            for j, geometry in enumerate(panel_geometries):
                value = grouped.get((algorithm, bit_rule, geometry))
                if value is None or not math.isfinite(value):
                    ax.text(
                        j,
                        i,
                        "n/a",
                        ha="center",
                        va="center",
                        color="#555555",
                        fontsize=7,
                    )
                    continue
                text_color = "black" if value >= 0.6 * vmax else "white"
                ax.text(
                    j,
                    i,
                    f"{value:.3f}",
                    ha="center",
                    va="center",
                    color=text_color,
                    fontsize=9,
                )
        fig.colorbar(
            image,
            ax=ax,
            label=colorbar_label,
            shrink=0.88,
            pad=0.04 if panel_index else 0.02,
        )
    fig.tight_layout()
    fig.savefig(output, bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
    return {
        "path": display_path(output),
        "status": "generated_from_synthetic_real",
        "synthetic_exact_cells": len(synthetic_grouped),
        "real_metric_column": real_metric,
        "real_metric_cells": len(real_grouped),
        "real_metric_status_counts": dict(sorted(real_status_counts.items())),
    }


def render_synthetic_contamination_kendall_tau(
    ctx: PaperArtifactContext, output: Path
) -> dict[str, Any]:
    """Render synthetic Kendall tau under contamination for the B-axis rows."""
    rows = [
        row
        for row in ctx.synthetic_rows
        if row.get("runlist") == "table_4_outlier"
        and _series_key(row) in STABILITY_COMPARISON_SET
    ]
    grouped = mean_by(
        rows,
        ("algorithm_id", "bit_rule", "geometry_id", "contamination_id"),
        "kendall_tau_clean",
    )
    if not grouped:
        return save_text_figure(
            output,
            "Synthetic stability under contamination",
            ["No finite kendall_tau_clean values were found in table_4_outlier rows."],
            status="not_available",
        )
    geometries = sorted({key[2] for key in grouped})
    series = [
        key
        for key in STABILITY_COMPARISON_SERIES
        if any(group_key[:2] == key for group_key in grouped)
    ]
    styles = series_style_map(series)
    all_values = [
        value for key, value in grouped.items() if key[0] in STABILITY_ALGORITHMS
    ]
    y_min = min(all_values) if all_values else 0.0
    y_max = max(all_values) if all_values else 1.0
    y_lower = min(-0.05, y_min - 0.05)
    y_upper = max(1.0, y_max) + 0.05
    columns = min(3, max(len(geometries), 1))
    rows_count = math.ceil(max(len(geometries), 1) / columns)
    fig, axes = plt.subplots(
        rows_count, columns, figsize=(4.25 * columns, 2.6 * rows_count), sharey=True
    )
    axes = list(axes.flat) if hasattr(axes, "flat") else [axes]
    legend_items: dict[str, matplotlib.artist.Artist] = {}
    for ax, geometry in zip(axes, geometries):
        for index, (algorithm, bit_rule) in enumerate(series):
            xs = sorted(
                {
                    key[3]
                    for key in grouped
                    if key[0] == algorithm and key[1] == bit_rule and key[2] == geometry
                }
            )
            if not xs:
                continue
            ys = [
                grouped[(algorithm, bit_rule, geometry, contamination)]
                for contamination in xs
            ]
            label = series_label(algorithm, bit_rule)
            style = styles.get((algorithm, bit_rule), default_series_style(index))
            line = ax.plot(
                xs,
                ys,
                label=label,
                **line_kwargs(style),
            )[0]
            if label not in legend_items:
                legend_items[label] = line
        ax.set_title(GEOMETRY_LABELS.get(geometry, geometry))
        ax.set_xlabel("contamination")
        ax.set_ylim(y_lower, y_upper)
        ax.axhline(0.0, color="#555555", linewidth=0.8)
        ax.grid(True, alpha=0.25)
    spare_axes = axes[len(geometries) :]
    for ax in spare_axes:
        ax.axis("off")
    axes[0].set_ylabel("Kendall tau vs clean")
    fig.tight_layout()
    handles = list(legend_items.values())
    labels = list(legend_items.keys())
    if spare_axes:
        boxes = [ax.get_position() for ax in spare_axes]
        x_centre = (min(b.x0 for b in boxes) + max(b.x1 for b in boxes)) / 2.0
        y_centre = (min(b.y0 for b in boxes) + max(b.y1 for b in boxes)) / 2.0
        fig.legend(
            handles,
            labels,
            loc="center",
            bbox_to_anchor=(x_centre, y_centre),
            fontsize=8,
            ncol=1,
            frameon=False,
        )
    else:
        place_legend_outside(
            fig, handles, labels, fontsize=8, ncol=2, anchor_x=0.5, anchor_y=0.02
        )
    fig.savefig(output, bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
    return {"path": display_path(output), "status": "generated_from_synthetic"}


def render_synthetic_contamination_tau_by_bit_rule(
    ctx: PaperArtifactContext, output: Path
) -> dict[str, Any]:
    """Render Kendall tau under contamination per occupancy bit rule (C axis).

    Companion of the B-axis contamination figure: there the bit rule is held
    fixed and the frame estimator varies; here the three frame-curve ablations
    A5 / A5b / A6 are each held fixed and the occupancy rule varies over the
    four primary rules. Each point pools the inlier-only kendall_tau_clean
    mean over the synthetic geometries and seeds of table_4_outlier. This is
    the only figure that shows the effect of the C3 frame-core clamp and the
    C4 covering hybrid on ordering stability, which is where the bit-rule
    split is expected to matter (the tau metric scores inlier positions only).
    """
    rows = [
        row
        for row in ctx.synthetic_rows
        if row.get("runlist") == "table_4_outlier"
        and row.get("algorithm_id") in BIT_RULE_EFFECT_ALGORITHMS
        and row.get("bit_rule") in BIT_RULE_FIGURE_RULES
    ]
    grouped = mean_by(
        rows, ("algorithm_id", "bit_rule", "contamination_id"), "kendall_tau_clean"
    )
    if not grouped:
        return save_text_figure(
            output,
            "Synthetic tau by bit rule",
            [
                "No finite kendall_tau_clean values were found for the",
                "A5/A5b/A6 primary-bit-rule rows of table_4_outlier.",
            ],
            status="not_available",
        )
    contaminations = sorted({key[2] for key in grouped})
    algorithms = [
        algorithm
        for algorithm in BIT_RULE_EFFECT_ALGORITHMS
        if any(key[0] == algorithm for key in grouped)
    ]
    fig, axes = plt.subplots(
        1,
        max(len(algorithms), 1),
        figsize=(3.4 * max(len(algorithms), 1), 3.1),
        sharey=True,
        squeeze=False,
    )
    legend_items: dict[str, matplotlib.artist.Artist] = {}
    for index, (ax, algorithm) in enumerate(zip(axes[0], algorithms)):
        for rule in BIT_RULE_FIGURE_RULES:
            xs = [c for c in contaminations if (algorithm, rule, c) in grouped]
            ys = [grouped[(algorithm, rule, c)] for c in xs]
            if not ys:
                continue
            style = BIT_RULE_STYLES.get(rule, default_series_style(0))
            line = ax.plot(
                xs,
                ys,
                markersize=5.0,
                markeredgecolor="#1a1a1a",
                markeredgewidth=0.45,
                color=style["color"],
                marker=style["marker"],
                linestyle=style["linestyle"],
                label=rule,
            )[0]
            if rule not in legend_items:
                legend_items[rule] = line
        ax.set_title(ALGORITHM_LABELS.get(algorithm, algorithm), fontsize=9)
        ax.set_xlabel("contamination")
        ax.axhline(0.0, color="#555555", linewidth=0.8)
        ax.grid(True, alpha=0.25)
        if index == 0:
            ax.set_ylabel("Kendall tau vs clean")
    place_legend_below(
        fig,
        list(legend_items.values()),
        list(legend_items.keys()),
        fontsize=7,
        ncol=min(len(legend_items), 4),
    )
    fig.tight_layout()
    fig.savefig(output, bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
    return {"path": display_path(output), "status": "generated_from_synthetic"}


def render_synthetic_clean_runtime_vs_n(
    ctx: PaperArtifactContext, output: Path
) -> dict[str, Any]:
    """Render synthetic sort runtime vs N on clean primary occupancy rows."""
    rows = [
        row
        for row in ctx.synthetic_rows
        if row.get("runlist") == "table_5_runtime"
        and row.get("contamination_id") == "D0"
        and _series_key(row) in MAIN_METHOD_COMPARISON_SET
    ]
    grouped = mean_by(
        rows, ("algorithm_id", "bit_rule", "geometry_id", "point_count"), "sort_seconds"
    )
    if not grouped:
        return save_text_figure(
            output,
            "Synthetic clean runtime vs N",
            ["No finite sort_seconds values were found in clean table_5_runtime rows."],
            status="not_available",
        )
    series = [
        key
        for key in MAIN_METHOD_COMPARISON_SERIES
        if any(group_key[:2] == key for group_key in grouped)
    ]
    styles = series_style_map(series)
    fig, ax = plt.subplots(figsize=(7.0, 4.0))
    all_xs = sorted({float(key[3]) for key in grouped})
    for index, (algorithm, bit_rule) in enumerate(series):
        by_n: dict[float, list[float]] = defaultdict(list)
        for key, value in grouped.items():
            if key[0] == algorithm and key[1] == bit_rule:
                by_n[float(key[3])].append(value)
        xs = sorted(by_n)
        ys = [mean(by_n[x]) for x in xs]
        style = styles.get((algorithm, bit_rule), default_series_style(index))
        ax.plot(
            xs,
            ys,
            label=series_label(algorithm, bit_rule),
            **line_kwargs(style),
        )
    ax.set_xscale("log", base=2)
    ax.set_yscale("log")
    if all_xs:
        ax.set_xlim(all_xs[0] / 1.15, all_xs[-1] * 1.15)
        ax.set_xticks(all_xs, [str(int(x)) for x in all_xs])
    ax.set_xlabel("N (points)")
    ax.set_ylabel("sort seconds")
    handles, labels = ax.get_legend_handles_labels()
    place_legend_below(fig, handles, labels, fontsize=7, ncol=2)
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(output, bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
    return {"path": display_path(output), "status": "generated_from_synthetic"}


def render_synthetic_block_read_cache_miss(
    ctx: PaperArtifactContext, output: Path
) -> dict[str, Any]:
    """Render the synthetic block-read cache-miss figure strictly from M8 counters."""
    rows = [
        row
        for row in ctx.synthetic_rows
        if row.get("runlist") == "table_5_runtime"
        and row.get("contamination_id") == "D0"
        and _series_key(row) in MAIN_METHOD_COMPARISON_SET
    ]
    cache_grouped = mean_by(
        rows, ("algorithm_id", "bit_rule", "point_count"), "cache_miss_rate"
    )
    if not cache_grouped:
        raise RuntimeError(
            "The block-read cache figure requires finite M8 cache-miss-rate measurements from "
            "table_5_runtime (D0, primary occupancy rules). None were found. Run "
            "`make bench-synthetic` in an environment with `perf stat -e "
            "cache-references,cache-misses` access (Linux perf, "
            "kernel.perf_event_paranoid <= 1) and re-run paper-artifacts. "
            "No M9 fallback is permitted."
        )
    series = [
        key
        for key in MAIN_METHOD_COMPARISON_SERIES
        if any(group_key[:2] == key for group_key in cache_grouped)
    ]
    styles = series_style_map(series)
    fig, ax = plt.subplots(figsize=(7.0, 4.0))
    all_ns = sorted({point_count for _, _, point_count in cache_grouped})
    for index, (algorithm, bit_rule) in enumerate(series):
        xs = sorted(
            point_count
            for name, rule, point_count in cache_grouped
            if name == algorithm and rule == bit_rule
        )
        ys = [cache_grouped[(algorithm, bit_rule, point_count)] for point_count in xs]
        style = styles.get((algorithm, bit_rule), default_series_style(index))
        ax.plot(
            xs,
            ys,
            label=series_label(algorithm, bit_rule),
            **line_kwargs(style),
        )
    ax.set_xscale("log", base=2)
    ax.set_xticks(all_ns, [str(int(n)) for n in all_ns])
    ax.set_xlabel("N (points)")
    ax.set_ylabel("cache misses / cache references")
    handles, labels = ax.get_legend_handles_labels()
    place_legend_below(fig, handles, labels, fontsize=7, ncol=2)
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(output, bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
    return {
        "path": display_path(output),
        "status": "generated_from_synthetic_m8_cache_miss_rate",
    }


def render_mixed_bit_allocation_by_rule(
    ctx: PaperArtifactContext, output: Path
) -> dict[str, Any]:
    """Render A6 bit allocation by primary bit rule, averaged across datasets."""
    rows = [
        row
        for row in ctx.synthetic_rows
        if row.get("algorithm_id") == "A6_rch"
        and row.get("runlist") in ("table_3_locality", "table_5_runtime")
        and row.get("bit_rule") in BIT_RULE_FIGURE_RULES
        and (
            row.get("runlist") != "table_3_locality"
            or _is_baseline_locality_clean_size(row)
        )
    ]
    rows.extend(
        row
        for row in ctx.real_rows
        if row.get("algorithm_id") == "A6_rch"
        and row.get("bit_rule") in BIT_RULE_FIGURE_RULES
    )
    grouped_bits: dict[str, list[tuple[int, int, int]]] = defaultdict(list)
    for row in rows:
        bits = parse_bits_axis(row.get("bits_axis"))
        if bits is not None:
            grouped_bits[str(row.get("bit_rule", "unknown"))].append(bits)
    labels = [rule for rule in BIT_RULE_FIGURE_RULES if rule in grouped_bits]
    if not labels:
        return save_text_figure(
            output,
            "A6 bit allocation by bit rule",
            ["No parseable A6 bits_axis values were found in Synthetic/Real rows."],
            status="not_available",
        )
    means = [
        tuple(mean(bit[axis] for bit in grouped_bits[label]) for axis in range(3))
        for label in labels
    ]
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    xs = list(range(len(labels)))
    bottoms = [0.0] * len(labels)
    axis_names = ("frame axis 1", "frame axis 2", "frame axis 3")
    colors = ("#5278a6", "#69a36f", "#c78b42")
    for axis, (axis_name, color) in enumerate(zip(axis_names, colors)):
        values = [item[axis] for item in means]
        ax.bar(xs, values, bottom=bottoms, label=axis_name, color=color)
        bottoms = [left + value for left, value in zip(bottoms, values)]
    ax.set_xticks(xs, [label.replace("_", "\n") for label in labels], rotation=0)
    ax.tick_params(axis="x", labelsize=8)
    ax.set_ylabel("mean allocated bits (A6)")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(output, bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
    return {"path": display_path(output), "status": "generated_from_synthetic_real"}


def render_mixed_ablation_a5_vs_a6_miad(
    ctx: PaperArtifactContext, output: Path
) -> dict[str, Any]:
    """Render A5-vs-A6 marginal MIAD benefit from synthetic and real artifacts."""
    rows = [
        row
        for row in ctx.synthetic_rows
        if row.get("runlist") == "table_4_outlier"
        and row.get("bit_rule") == MAIN_COMPARISON_BIT_RULE
    ]
    rows.extend(
        row
        for row in ctx.real_rows
        if row.get("bit_rule") == MAIN_COMPARISON_BIT_RULE
        and row.get("geometry_id") in ("E3", "E4")
    )
    grouped = mean_by(
        rows,
        ("algorithm_id", "bit_rule", "geometry_id", "contamination_id", "seed"),
        "miad",
    )
    benefits: dict[str, list[float]] = defaultdict(list)
    keys = {
        (bit_rule, geometry, contamination, seed)
        for _, bit_rule, geometry, contamination, seed in grouped
    }
    for bit_rule, geometry, contamination, seed in sorted(keys):
        a5 = grouped.get(
            ("A5_pca_compact_hilbert", bit_rule, geometry, contamination, seed)
        )
        a6 = grouped.get(("A6_rch", bit_rule, geometry, contamination, seed))
        if a5 is not None and a6 is not None and a5 > 0.0:
            # Relative benefit: raw MIAD scales differ by ~100x across the
            # datasets (e.g. Bunny ~0.02 vs Armadillo ~2.3 in raw
            # coordinates), so an absolute A5-A6 bar chart hides every
            # small-scale dataset. (A5-A6)/A5 is scale-free and comparable.
            benefits[geometry].append((a5 - a6) / a5)
    labels = [geometry for geometry in GEOMETRY_ORDER if geometry in benefits]
    if not labels:
        return save_text_figure(
            output,
            "Mixed A5 vs A6 marginal MIAD benefit",
            ["No paired A5/A6 MIAD rows were found in synthetic or real artifacts."],
            status="not_available",
        )
    values = [100.0 * mean(benefits[label]) for label in labels]
    colors = ["#2f7d52" if value >= 0 else "#a64242" for value in values]
    fig, ax = plt.subplots(figsize=(8.6, 4.6))
    ax.axhline(0.0, color="black", linewidth=0.8)
    x_labels = [GEOMETRY_LABELS.get(label, label) for label in labels]
    bars = ax.bar(x_labels, values, color=colors)
    for bar, value in zip(bars, values):
        ax.annotate(
            f"{value:.1f}%",
            (bar.get_x() + bar.get_width() / 2.0, bar.get_height()),
            xytext=(0, 3 if value >= 0 else -11),
            textcoords="offset points",
            ha="center",
            fontsize=8,
        )
    ax.set_ylabel("mean relative MIAD benefit (A5 $-$ A6) / A5 [%]")
    ax.tick_params(axis="x", labelrotation=30, labelsize=8)
    ax.grid(True, axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(output, bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
    return {"path": display_path(output), "status": "generated_from_synthetic_real"}


# Per-method drawing style for the refinement-axis crossing figure. The two
# H1 protagonists (RCH and isotropic Hilbert) are emphasized; Morton and the
# PCA-frame compact-Hilbert order are drawn thinner as context.
REAL_REFINEMENT_METHOD_STYLE: dict[str, dict[str, Any]] = {
    "A6_rch": {"color": "#1f4e79", "marker": "o", "linewidth": 2.4, "alpha": 1.0},
    "A3_isotropic_hilbert": {
        "color": "#a64242",
        "marker": "s",
        "linewidth": 2.4,
        "alpha": 1.0,
    },
    "A2_morton": {
        "color": "#7f7f7f",
        "marker": "^",
        "linewidth": 1.3,
        "alpha": 0.85,
        "linestyle": "--",
    },
    "A5_pca_compact_hilbert": {
        "color": "#2f7d52",
        "marker": "D",
        "linewidth": 1.3,
        "alpha": 0.85,
        "linestyle": "--",
    },
}


def render_real_refinement_ablation_miad(
    ctx: PaperArtifactContext, output: Path
) -> dict[str, Any]:
    """Render the real-data refinement-axis ablation as MIAD crossing lines.

    For each Stanford model, the mean raw-coordinate MIAD (primary occupancy
    rules, averaged over D0--D4 and the five seeds) of four orderings under the
    two equal-treatment refinement modes off / all. Lower is better. The figure
    makes the mechanism explicit: under `off` the refinement pass is removed
    from every method, while under `all` every non-input in-repo method receives
    the same pass. The slope from off to all therefore exposes how much the
    refinement pass changes each algorithm's real-data MIAD.
    """
    rows = [
        row
        for row in ctx.real_refinement_rows
        if _series_key(row) in MAIN_METHOD_COMPARISON_SET
        and row.get("algorithm_id") in REAL_REFINEMENT_METHOD_STYLE
    ]
    grouped = mean_by(
        rows, ("dataset_id", "algorithm_id", "bit_rule", "refinement"), "miad"
    )
    datasets = sorted({dataset for dataset, _, _, _ in grouped})
    if not datasets:
        return save_text_figure(
            output,
            "Real-data refinement ablation",
            [
                "No primary-rule MIAD rows were found under the off / all arms.",
                "Run `make bench-real` to populate experiments/outputs/real_dataset/.",
            ],
            status="not_available",
        )
    mode_labels = ["off", "all"]
    x_positions = list(range(len(REAL_REFINEMENT_MODES)))
    series = [
        (method, bit_rule)
        for method in REAL_REFINEMENT_METHOD_STYLE
        for bit_rule in (MAIN_COMPARISON_BIT_RULE, "C0_uniform")
        if any(
            (dataset, method, bit_rule, refinement) in grouped
            for dataset in datasets
            for refinement in REAL_REFINEMENT_MODES
        )
    ]
    fig, axes = plt.subplots(1, len(datasets), figsize=(8.0, 4.4), squeeze=False)
    legend_items: dict[str, matplotlib.artist.Artist] = {}
    for index, (ax, dataset) in enumerate(zip(axes[0], datasets)):
        for method, bit_rule in series:
            values = [
                grouped.get((dataset, method, bit_rule, mode))
                for mode in REAL_REFINEMENT_MODES
            ]
            xs = [x for x, value in zip(x_positions, values) if value is not None]
            ys = [value for value in values if value is not None]
            if not ys:
                continue
            style = REAL_REFINEMENT_METHOD_STYLE[method]
            label = series_label(method, bit_rule)
            line = ax.plot(
                xs,
                ys,
                color=style["color"],
                marker=style["marker"],
                linewidth=style["linewidth"],
                alpha=style["alpha"],
                linestyle=style.get("linestyle", "-"),
                label=label,
            )[0]
            if label not in legend_items:
                legend_items[label] = line
        ax.set_xticks(x_positions)
        ax.set_xticklabels(mode_labels)
        ax.set_xlim(-0.25, len(REAL_REFINEMENT_MODES) - 0.75)
        nice = dataset.replace("stanford_", "").replace("_", " ").title()
        ax.set_title(nice, fontsize=10)
        ax.set_xlabel("refinement mode")
        ax.grid(True, alpha=0.25)
        if index == 0:
            # Each line is one (method, bit rule) pair, so the label must name a
            # single rule; "primary rules" wrongly implied pooling over all four.
            ax.set_ylabel("mean MIAD (per bit rule, D0-D4)")
    place_legend_below(
        fig,
        list(legend_items.values()),
        list(legend_items.keys()),
        fontsize=7,
        ncol=2,
    )
    fig.tight_layout()
    fig.savefig(output, bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
    return {"path": display_path(output), "status": "generated_from_real_refinement"}


def table_meta_determinism_by_preset(ctx: PaperArtifactContext) -> str:
    """Create the determinism/test matrix table from test log JSON files."""
    latest_by_preset: dict[str, dict[str, Any]] = {}
    for log in ctx.test_logs:
        preset = str(log.get("preset", ""))
        timestamp = str(log.get("timestamp_utc", ""))
        previous = latest_by_preset.get(preset)
        if previous is None or timestamp >= str(previous.get("timestamp_utc", "")):
            latest_by_preset[preset] = log
    rows: list[dict[str, Any]] = []
    for log in sorted(
        latest_by_preset.values(), key=lambda item: str(item.get("preset", ""))
    ):
        rows.append(
            {
                "preset": log.get("preset", ""),
                "configure": (
                    "PASS"
                    if log.get("configure_exit") == 0
                    else f"FAIL({log.get('configure_exit')})"
                ),
                "build": (
                    "PASS"
                    if log.get("build_exit") == 0
                    else f"FAIL({log.get('build_exit')})"
                ),
                "ctest": (
                    "PASS"
                    if log.get("ctest_exit") == 0
                    else f"FAIL({log.get('ctest_exit')})"
                ),
                "log": log.get("path", ""),
            }
        )
    if not rows:
        rows = [
            {
                "preset": "no logs",
                "configure": "Not verified",
                "build": "Not verified",
                "ctest": "Not verified",
                "log": "",
            }
        ]
    return latex_table(
        rows,
        ["preset", "configure", "build", "ctest", "log"],
        "Determinism/test matrix evidence",
        "tab:determinism_matrix",
    )


def table_cgal_a7_fixture(ctx: PaperArtifactContext) -> str:
    """Create appendix-only A7 CGAL spatial_sort sanity table."""
    rows: list[dict[str, Any]] = []
    for row in ctx.a7_rows:
        rows.append(
            {
                "algorithm_id": row.get("algorithm_id", ""),
                "policy": row.get("policy", ""),
                "point_count": row.get("point_count", ""),
                "permutation_hash": row.get("permutation_hash", ""),
            }
        )
    if not rows:
        rows = [
            {
                "algorithm_id": "A7_cgal_spatial_sort",
                "policy": "not run",
                "point_count": "",
                "permutation_hash": "Not verified",
            }
        ]
    return latex_table(
        rows,
        ["algorithm_id", "policy", "point_count", "permutation_hash"],
        "A7 CGAL appendix sanity",
        "tab:a7_cgal_appendix",
    )


def table_real_dataset_catalog(ctx: PaperArtifactContext) -> str:
    """Create real-dataset family scope table without inventing measurements."""
    rows: list[dict[str, Any]] = []
    measured = {str(row.get("dataset_id", "")) for row in ctx.real_rows}
    for item in ctx.dataset_catalog:
        dataset_id = str(item.get("id", ""))
        rows.append(
            {
                "dataset": dataset_id,
                "family": item.get("family", ""),
                "status": (
                    "measured"
                    if dataset_id in measured
                    else item.get("status", "not_measured")
                ),
                "source": item.get("source_url", ""),
            }
        )
    if not rows:
        rows = [
            {
                "dataset": "catalog missing",
                "family": "",
                "status": "Not verified",
                "source": "",
            }
        ]
    return latex_table(
        rows,
        ["dataset", "family", "status", "source"],
        "Real-dataset family scope and measurement status",
        "tab:real_dataset_catalog",
    )


def table_mixed_claim_status(ctx: PaperArtifactContext) -> str:
    """Create claim-status table from Synthetic/Real stats and Synthetic contamination rows."""
    synthetic_hypotheses = {
        item.get("hypothesis"): item
        for item in ctx.synthetic_stats.get("hypotheses", [])
    }
    real_hypotheses = {
        item.get("hypothesis"): item for item in ctx.real_stats.get("hypotheses", [])
    }
    h1 = synthetic_hypotheses.get("H1", {})
    h2 = synthetic_hypotheses.get("H2", {})
    h3 = synthetic_hypotheses.get("H3", {})
    h7 = synthetic_hypotheses.get("H7_A7", {})
    h1_real = real_hypotheses.get("H1_real_directional", {})
    h1_real_outcome = h1_real.get(
        "outcome", "confirmed" if h1_real.get("passed") else "insufficient_data"
    )
    h1_real_status = {
        "confirmed": "Confirmed",
        "failed": "Failed",
        "insufficient_data": "Not verified",
    }.get(str(h1_real_outcome), "Not verified")
    failed_real = sum(
        1 for item in h1_real.get("comparisons", []) if not item.get("passed")
    )
    rows = [
        {
            "claim": "H1 synthetic MIAD",
            "status": "Confirmed" if h1.get("passed") else "Not verified",
            "evidence": f"p_adj={h1.get('p_adj', 'NA')}",
        },
        {
            "claim": "H2 synthetic MIAD",
            "status": "Confirmed" if h2.get("passed") else "Not verified",
            "evidence": f"p_adj={h2.get('p_adj', 'NA')}",
        },
        {
            "claim": "H3 contamination stability",
            "status": "Confirmed" if h3.get("passed") else "Not verified",
            "evidence": (
                f"p={h3.get('p', 'NA')}; "
                f"median_delta={h3.get('median_delta_rch_minus_baseline', 'NA')}"
            ),
        },
        {
            "claim": "A7 CGAL baseline comparison",
            "status": "Confirmed" if h7.get("passed") else "Not verified",
            "evidence": (
                f"p_adj={h7.get('p_adj', 'NA')}; "
                f"median_delta={h7.get('median_delta_rch_minus_baseline', 'NA')}"
            ),
        },
        {
            "claim": "H1 real-data direction",
            "status": h1_real_status,
            "evidence": f"comparisons={h1_real.get('comparison_count', 'NA')}; failed={failed_real}",
        },
    ]
    return latex_table(
        rows,
        ["claim", "status", "evidence"],
        "Claim status summary",
        "tab:claim_status",
    )


def table_artifact_specs(
    ctx: PaperArtifactContext,
) -> list[tuple[str, list[dict[str, Any]], list[str], str, str]]:
    """Build paper-facing table rows before rendering to any file format."""
    latest_by_preset: dict[str, dict[str, Any]] = {}
    for log in ctx.test_logs:
        preset = str(log.get("preset", ""))
        timestamp = str(log.get("timestamp_utc", ""))
        previous = latest_by_preset.get(preset)
        if previous is None or timestamp >= str(previous.get("timestamp_utc", "")):
            latest_by_preset[preset] = log
    determinism_rows: list[dict[str, Any]] = []
    for log in sorted(
        latest_by_preset.values(), key=lambda item: str(item.get("preset", ""))
    ):
        determinism_rows.append(
            {
                "preset": log.get("preset", ""),
                "configure": (
                    "PASS"
                    if log.get("configure_exit") == 0
                    else f"FAIL({log.get('configure_exit')})"
                ),
                "build": (
                    "PASS"
                    if log.get("build_exit") == 0
                    else f"FAIL({log.get('build_exit')})"
                ),
                "ctest": (
                    "PASS"
                    if log.get("ctest_exit") == 0
                    else f"FAIL({log.get('ctest_exit')})"
                ),
                "log": log.get("path", ""),
            }
        )
    if not determinism_rows:
        determinism_rows = [
            {
                "preset": "no logs",
                "configure": "Not verified",
                "build": "Not verified",
                "ctest": "Not verified",
                "log": "",
            }
        ]

    cgal_rows = [
        {
            "algorithm_id": row.get("algorithm_id", ""),
            "policy": row.get("policy", ""),
            "point_count": row.get("point_count", ""),
            "permutation_hash": row.get("permutation_hash", ""),
        }
        for row in ctx.a7_rows
    ] or [
        {
            "algorithm_id": "A7_cgal_spatial_sort",
            "policy": "not run",
            "point_count": "",
            "permutation_hash": "Not verified",
        }
    ]

    measured = {str(row.get("dataset_id", "")) for row in ctx.real_rows}
    catalog_rows = []
    for item in ctx.dataset_catalog:
        dataset_id = str(item.get("id", ""))
        catalog_rows.append(
            {
                "dataset": dataset_id,
                "family": item.get("family", ""),
                "status": (
                    "measured"
                    if dataset_id in measured
                    else item.get("status", "not_measured")
                ),
                "source": item.get("source_url", ""),
            }
        )
    if not catalog_rows:
        catalog_rows = [
            {
                "dataset": "catalog missing",
                "family": "",
                "status": "Not verified",
                "source": "",
            }
        ]

    synthetic_hypotheses = {
        item.get("hypothesis"): item
        for item in ctx.synthetic_stats.get("hypotheses", [])
    }
    real_hypotheses = {
        item.get("hypothesis"): item for item in ctx.real_stats.get("hypotheses", [])
    }
    h1 = synthetic_hypotheses.get("H1", {})
    h2 = synthetic_hypotheses.get("H2", {})
    h3 = synthetic_hypotheses.get("H3", {})
    h7 = synthetic_hypotheses.get("H7_A7", {})
    h1_real = real_hypotheses.get("H1_real_directional", {})
    h1_real_outcome = h1_real.get(
        "outcome", "confirmed" if h1_real.get("passed") else "insufficient_data"
    )
    h1_real_status = {
        "confirmed": "Confirmed",
        "failed": "Failed",
        "insufficient_data": "Not verified",
    }.get(str(h1_real_outcome), "Not verified")
    failed_real = sum(
        1 for item in h1_real.get("comparisons", []) if not item.get("passed")
    )
    claim_rows = [
        {
            "claim": "H1 synthetic MIAD",
            "status": "Confirmed" if h1.get("passed") else "Not verified",
            "evidence": f"p_adj={h1.get('p_adj', 'NA')}",
        },
        {
            "claim": "H2 synthetic MIAD",
            "status": "Confirmed" if h2.get("passed") else "Not verified",
            "evidence": f"p_adj={h2.get('p_adj', 'NA')}",
        },
        {
            "claim": "H3 contamination stability",
            "status": "Confirmed" if h3.get("passed") else "Not verified",
            "evidence": (
                f"p={h3.get('p', 'NA')}; "
                f"median_delta={h3.get('median_delta_rch_minus_baseline', 'NA')}"
            ),
        },
        {
            "claim": "A7 CGAL baseline comparison",
            "status": "Confirmed" if h7.get("passed") else "Not verified",
            "evidence": (
                f"p_adj={h7.get('p_adj', 'NA')}; "
                f"median_delta={h7.get('median_delta_rch_minus_baseline', 'NA')}"
            ),
        },
        {
            "claim": "H1 real-data direction",
            "status": h1_real_status,
            "evidence": f"comparisons={h1_real.get('comparison_count', 'NA')}; failed={failed_real}",
        },
    ]

    return [
        (
            "table_meta_determinism_by_preset.tex",
            determinism_rows,
            ["preset", "configure", "build", "ctest", "log"],
            "Determinism/test matrix evidence",
            "tab:determinism_matrix",
        ),
        (
            "table_mixed_claim_status.tex",
            claim_rows,
            ["claim", "status", "evidence"],
            "Claim status summary",
            "tab:claim_status",
        ),
        (
            "table_mixed_metric_leaders.tex",
            metric_leader_rows(ctx),
            [
                "scope",
                "metric",
                "direction",
                "algorithm_id",
                "bit_rule",
                "estimate",
                "n",
                "note",
            ],
            "Metric-specific leaders in the generated benchmark artifacts",
            "tab:mixed_metric_leaders",
        ),
        (
            "table_mixed_rch_quantization_summary.tex",
            rch_quantization_summary_rows(ctx),
            [
                "scope",
                "bit_rule",
                "miad",
                "normalized_miad",
                "m1_l1",
                "m1_l2",
                "recall_8_64",
                "sort_seconds",
                "n_metric",
                "n_runtime",
            ],
            "A6/RCH quantization summary by metric orientation",
            "tab:rch_quantization_summary",
        ),
        (
            "table_cgal_a7_fixture.tex",
            cgal_rows,
            ["algorithm_id", "policy", "point_count", "permutation_hash"],
            "A7 CGAL appendix sanity",
            "tab:a7_cgal_appendix",
        ),
        (
            "table_real_dataset_catalog.tex",
            catalog_rows,
            ["dataset", "family", "status", "source"],
            "Real-dataset family scope and measurement status",
            "tab:real_dataset_catalog",
        ),
    ]


def write_tables(ctx: PaperArtifactContext) -> dict[str, Any]:
    """Write the generated evidence tables and return manifest entries.

    Filenames follow `table_<scope>_<content>`; see
    audits/artifacts/002_artifact_naming_redesign.md for the rename map.
    """
    ctx.tables_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {}
    for filename, rows, columns, caption, label in table_artifact_specs(ctx):
        manifest[filename] = write_table_bundle(
            ctx.tables_dir, filename, rows, columns, caption, label
        )
    return manifest


def format_metric(value: float | None) -> str:
    """Format optional numeric CSV fields deterministically."""
    return "" if value is None else f"{value:.12g}"


def write_synthetic_refinement_effects(ctx: PaperArtifactContext) -> dict[str, Any]:
    """Write paired off/all refinement effects for synthetic rows."""
    key_fields = [
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
    ]
    metric_fields = [
        "sort_seconds",
        "miad",
        "m1_l1_locality",
        "l1_locality",
        "m1_l2_locality",
        "l2_locality",
        "recall_8_64",
        "block_read_mean",
        "block_read_p95",
        "cache_miss_rate",
        "kendall_tau_clean",
        "frame_angle_rad",
    ]
    paired: dict[tuple[str, ...], dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in ctx.synthetic_refinement_rows:
        refinement = str(row.get("refinement", ""))
        if refinement not in REFINEMENT_MODES:
            continue
        key = tuple(str(row.get(field, "")) for field in key_fields)
        paired[key][refinement] = row

    output_rows: list[dict[str, Any]] = []
    for key in sorted(paired):
        modes = paired[key]
        off = modes.get("off")
        all_refined = modes.get("all")
        if off is None or all_refined is None:
            continue
        row = {field: value for field, value in zip(key_fields, key)}
        for metric in metric_fields:
            off_value = numeric(off.get(metric))
            all_value = numeric(all_refined.get(metric))
            delta = (
                all_value - off_value
                if off_value is not None and all_value is not None
                else None
            )
            percent = (
                (delta / off_value) * 100.0
                if delta is not None and off_value not in (None, 0.0)
                else None
            )
            row[f"{metric}_off"] = format_metric(off_value)
            row[f"{metric}_all"] = format_metric(all_value)
            row[f"{metric}_all_minus_off"] = format_metric(delta)
            row[f"{metric}_all_minus_off_percent"] = format_metric(percent)
        output_rows.append(row)

    output = ctx.stats_dir / "synthetic_refinement_effects.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    fields = key_fields + [
        f"{metric}_{suffix}"
        for metric in metric_fields
        for suffix in ("off", "all", "all_minus_off", "all_minus_off_percent")
    ]
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(output_rows)
    return {
        "path": display_path(output),
        "status": "generated",
        "row_count": len(output_rows),
        "comparison": "all_minus_off",
    }


def write_real_refinement_effects(ctx: PaperArtifactContext) -> dict[str, Any]:
    """Write paired off/all refinement effects for real-data rows."""
    key_fields = [
        "dataset_id",
        "dataset_label",
        "geometry_id",
        "algorithm_id",
        "method",
        "bit_rule",
        "bit_allocator",
        "contamination_id",
        "contamination_mode",
        "seed",
        "frame_estimator",
    ]
    metric_fields = ["miad", "normalized_miad"]
    paired: dict[tuple[str, ...], dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in ctx.real_refinement_rows:
        refinement = str(row.get("refinement", ""))
        if refinement not in REAL_REFINEMENT_MODES:
            continue
        key = tuple(str(row.get(field, "")) for field in key_fields)
        paired[key][refinement] = row

    output_rows: list[dict[str, Any]] = []
    for key in sorted(paired):
        modes = paired[key]
        off = modes.get("off")
        all_refined = modes.get("all")
        if off is None or all_refined is None:
            continue
        row = {field: value for field, value in zip(key_fields, key)}
        for metric in metric_fields:
            off_value = numeric(off.get(metric))
            all_value = numeric(all_refined.get(metric))
            delta = (
                all_value - off_value
                if off_value is not None and all_value is not None
                else None
            )
            percent = (
                (delta / off_value) * 100.0
                if delta is not None and off_value not in (None, 0.0)
                else None
            )
            row[f"{metric}_off"] = format_metric(off_value)
            row[f"{metric}_all"] = format_metric(all_value)
            row[f"{metric}_all_minus_off"] = format_metric(delta)
            row[f"{metric}_all_minus_off_percent"] = format_metric(percent)
        output_rows.append(row)

    output = ctx.stats_dir / "real_refinement_effects.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    fields = key_fields + [
        "miad_off",
        "miad_all",
        "miad_all_minus_off",
        "miad_all_minus_off_percent",
        "normalized_miad_off",
        "normalized_miad_all",
        "normalized_miad_all_minus_off",
        "normalized_miad_all_minus_off_percent",
    ]
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(output_rows)
    return {
        "path": display_path(output),
        "status": "generated",
        "row_count": len(output_rows),
        "comparison": "all_minus_off",
    }


def figure_specs() -> list[FigureSpec]:
    """Return figure renderer strategies in paper order.

    Filenames follow `fig_<scope>_<test/condition>_<metric>`, where scope is
    `schema` (data-free diagrams), `synthetic`, `real`, `mixed` (both
    datasets), or `meta` (repo-level evidence). The map from the old numbered
    names is recorded in audits/artifacts/002_artifact_naming_redesign.md.
    """
    return [
        FigureSpec("fig_schema_method_pipeline.pdf", render_schema_method_pipeline),
        FigureSpec(
            "fig_schema_rch_implementation_flow.pdf",
            render_schema_rch_implementation_flow,
        ),
        FigureSpec(
            "fig_synthetic_clean_l1_locality_vs_n.pdf",
            render_synthetic_clean_l1_locality_vs_n,
        ),
        FigureSpec(
            "fig_mixed_recall_heatmap.pdf",
            render_mixed_recall_heatmap,
        ),
        FigureSpec(
            "fig_synthetic_contamination_kendall_tau.pdf",
            render_synthetic_contamination_kendall_tau,
        ),
        FigureSpec(
            "fig_synthetic_contamination_tau_by_bit_rule.pdf",
            render_synthetic_contamination_tau_by_bit_rule,
        ),
        FigureSpec(
            "fig_synthetic_clean_runtime_vs_n.pdf",
            render_synthetic_clean_runtime_vs_n,
        ),
        FigureSpec(
            "fig_synthetic_block_read_cache_miss.pdf",
            render_synthetic_block_read_cache_miss,
        ),
        FigureSpec(
            "fig_mixed_bit_allocation_by_rule.pdf",
            render_mixed_bit_allocation_by_rule,
        ),
        FigureSpec(
            "fig_mixed_ablation_a5_vs_a6_miad.pdf",
            render_mixed_ablation_a5_vs_a6_miad,
        ),
        FigureSpec(
            "fig_synthetic_clean_l2_locality_vs_n.pdf",
            render_synthetic_clean_l2_locality_vs_n,
        ),
        FigureSpec(
            "fig_real_refinement_ablation_miad.pdf",
            render_real_refinement_ablation_miad,
        ),
    ]


def build_context(args: argparse.Namespace) -> PaperArtifactContext:
    """Read all input artifacts once and share one immutable renderer context."""
    return PaperArtifactContext(
        synthetic_rows=read_synthetic_rows(args.synthetic_results_dir),
        synthetic_refinement_rows=read_synthetic_refinement_rows(
            args.synthetic_refinement_results_dir
        ),
        real_rows=read_optional_csv(
            args.real_results_dir / "table_2_dataset_summary.csv"
        ),
        real_refinement_rows=read_real_refinement_rows(
            args.real_refinement_results_dir
        ),
        a7_rows=read_optional_csv(args.a7_results_dir / "a7_cgal_spatial_sort.csv"),
        synthetic_stats=read_json(args.stats_dir / "synthetic_statistics.json"),
        real_stats=read_json(args.stats_dir / "real_statistics.json"),
        test_logs=read_test_logs(args.logs_dir),
        dataset_catalog=read_dataset_catalog(args.dataset_catalog),
        figures_dir=args.figures_dir,
        tables_dir=args.tables_dir,
        stats_dir=args.stats_dir,
    )


def copy_selected_output_files(
    source: Path, destination: Path, relative_paths: Iterable[Path]
) -> dict[str, Any]:
    """Copy only paper-facing benchmark summaries into analysis/generated/outputs."""
    entry: dict[str, Any] = {
        "source": display_path(source),
        "destination": display_path(destination),
        "status": "missing",
        "file_count": 0,
        "total_bytes": 0,
        "files": [],
        "missing_files": [],
    }
    if not source.exists():
        return entry
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)
    copied_files: list[dict[str, Any]] = []
    missing_files: list[str] = []
    total_bytes = 0
    for relative in relative_paths:
        source_file = source / relative
        if not source_file.exists():
            missing_files.append(str(relative))
            continue
        destination_file = destination / relative
        destination_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, destination_file)
        size = destination_file.stat().st_size
        total_bytes += size
        copied_files.append({"path": str(relative), "bytes": size})
    entry.update(
        {
            "status": "copied" if copied_files else "empty",
            "file_count": len(copied_files),
            "total_bytes": total_bytes,
            "files": copied_files,
            "missing_files": missing_files,
        }
    )
    return entry


def selected_output_files() -> dict[str, list[Path]]:
    """Return the small set of benchmark summaries needed downstream."""
    synthetic_runlists = (
        "table_3_locality",
        "table_4_outlier",
        "table_5_runtime",
    )
    synthetic_files = [
        Path(mode) / filename
        for mode in REFINEMENT_MODES
        for stem in synthetic_runlists
        for filename in (f"{stem}.csv", f"{stem}.manifest.json")
    ]
    synthetic_files.extend(Path(mode) / "perf_status.json" for mode in REFINEMENT_MODES)
    real_files = [
        Path(mode) / filename
        for mode in REAL_REFINEMENT_MODES
        for filename in (
            "table_2_dataset_summary.csv",
            "table_2_dataset_summary.manifest.json",
        )
    ]
    return {
        "synthetic_dataset": synthetic_files,
        "real_dataset": real_files,
        "a7_cgal_appendix": [
            Path("a7_cgal_spatial_sort.csv"),
            Path("a7_cgal_spatial_sort.manifest.json"),
        ],
    }


def mirror_benchmark_outputs(args: argparse.Namespace) -> dict[str, Any]:
    """Snapshot paper-facing benchmark summaries under analysis/generated."""
    outputs_dir = getattr(args, "outputs_dir", REPO_ROOT / "analysis/generated/outputs")
    outputs_dir.mkdir(parents=True, exist_ok=True)
    sources = {
        "synthetic_dataset": args.synthetic_refinement_results_dir,
        "real_dataset": args.real_refinement_results_dir,
        "a7_cgal_appendix": args.a7_results_dir,
    }
    for obsolete in ("synthetic_refinement", "real_refinement"):
        obsolete_dir = outputs_dir / obsolete
        if obsolete_dir.exists():
            shutil.rmtree(obsolete_dir)
    selected_files = selected_output_files()
    trees = {
        name: copy_selected_output_files(
            Path(source), outputs_dir / name, selected_files[name]
        )
        for name, source in sources.items()
    }
    manifest = {
        "schema": "rch.output_snapshot.v1",
        "destination": display_path(outputs_dir),
        "trees": trees,
        "summary": {
            "tree_count": len(trees),
            "copied_tree_count": sum(
                1 for tree in trees.values() if tree["status"] == "copied"
            ),
            "file_count": sum(int(tree["file_count"]) for tree in trees.values()),
            "total_bytes": sum(int(tree["total_bytes"]) for tree in trees.values()),
        },
    }
    manifest_path = outputs_dir / "output_snapshot_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return {
        "path": display_path(manifest_path),
        "status": "generated",
        **manifest["summary"],
        "trees": {
            name: {
                "source": tree["source"],
                "destination": tree["destination"],
                "status": tree["status"],
                "file_count": tree["file_count"],
                "total_bytes": tree["total_bytes"],
                "missing_file_count": len(tree.get("missing_files", [])),
            }
            for name, tree in trees.items()
        },
    }


def make_paper_artifacts(args: argparse.Namespace) -> dict[str, Any]:
    """Generate all paper-facing figure/table artifacts and a manifest JSON."""
    output_snapshot = mirror_benchmark_outputs(args)
    ctx = build_context(args)
    ctx.figures_dir.mkdir(parents=True, exist_ok=True)
    remove_deprecated_generated_figures(ctx.figures_dir)
    ctx.stats_dir.mkdir(parents=True, exist_ok=True)
    figures: dict[str, Any] = {}
    for spec in figure_specs():
        output = ctx.figures_dir / spec.filename
        figures[spec.filename] = spec.renderer(ctx, output)
    tables = write_tables(ctx)
    stats = {
        "synthetic_refinement_effects.csv": write_synthetic_refinement_effects(ctx),
        "real_refinement_effects.csv": write_real_refinement_effects(ctx),
    }
    manifest = {
        "schema": "rch.paper_artifacts.v1",
        "figures": figures,
        "tables": tables,
        "stats": stats,
        "outputs": output_snapshot,
        "inputs": {
            "synthetic_rows": len(ctx.synthetic_rows),
            "synthetic_refinement_rows": len(ctx.synthetic_refinement_rows),
            "real_rows": len(ctx.real_rows),
            "real_refinement_rows": len(ctx.real_refinement_rows),
            "a7_rows": len(ctx.a7_rows),
            "test_logs": len(ctx.test_logs),
            "dataset_catalog_rows": len(ctx.dataset_catalog),
            "synthetic_statistics_present": bool(ctx.synthetic_stats),
            "real_statistics_present": bool(ctx.real_stats),
        },
        "scope_notes": [
            "fig_synthetic_block_read_cache_miss requires finite M8 cache-miss-rate measurements; the generator fails closed (RuntimeError) when no perf counters are present — no M9 fallback.",
            "fig_mixed_recall_heatmap uses synthetic recall_8_64 and prefers Real recall_8_64 when that exact full-cloud column is present; the figure manifest records the Real metric column and status counts.",
            "Mesh-quality/application-scope material is intentionally not generated as a figure; downstream mesh quality belongs in future work unless a measured artifact is added.",
        ],
    }
    manifest_path = ctx.stats_dir / "paper_artifacts_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def parse_args() -> argparse.Namespace:
    """Parse CLI paths for paper artifact generation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--synthetic-results-dir",
        type=Path,
        default=REPO_ROOT / "experiments/outputs/synthetic_dataset/off",
    )
    parser.add_argument(
        "--synthetic-refinement-results-dir",
        type=Path,
        default=REPO_ROOT / "experiments/outputs/synthetic_dataset",
        help=(
            "Base dir holding synthetic refinement-ablation arms "
            "(<dir>/off, <dir>/all). Optional; the synthetic effect CSV is "
            "empty when the arms are absent."
        ),
    )
    parser.add_argument(
        "--real-results-dir",
        type=Path,
        default=REPO_ROOT / "experiments/outputs/real_dataset/off",
    )
    parser.add_argument(
        "--real-refinement-results-dir",
        type=Path,
        default=REPO_ROOT / "experiments/outputs/real_dataset",
        help=(
            "Base dir holding the real-data refinement-ablation arms "
            "(<dir>/off, <dir>/all). Optional; the refinement "
            "figure falls back to a placeholder when the arms are absent."
        ),
    )
    parser.add_argument(
        "--a7-results-dir",
        type=Path,
        default=REPO_ROOT / "experiments/outputs/a7_cgal_appendix",
    )
    parser.add_argument("--logs-dir", type=Path, default=REPO_ROOT / "experiments/logs")
    parser.add_argument(
        "--figures-dir", type=Path, default=REPO_ROOT / "analysis/generated/figures"
    )
    parser.add_argument(
        "--tables-dir", type=Path, default=REPO_ROOT / "analysis/generated/tables"
    )
    parser.add_argument(
        "--stats-dir", type=Path, default=REPO_ROOT / "analysis/generated/stats"
    )
    parser.add_argument(
        "--outputs-dir", type=Path, default=REPO_ROOT / "analysis/generated/outputs"
    )
    parser.add_argument(
        "--dataset-catalog",
        type=Path,
        default=REPO_ROOT / "data/manifests/real_dataset_catalog.yml",
    )
    return parser.parse_args()


def main() -> int:
    """CLI entry point."""
    manifest = make_paper_artifacts(parse_args())
    print(
        json.dumps(
            {
                "figures": sorted(manifest["figures"]),
                "tables": sorted(manifest["tables"]),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
