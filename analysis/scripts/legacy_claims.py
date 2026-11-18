"""Interpretation of the dependent, submitted synthetic benchmark design.

Keep historical numerical gates reproducible without treating them as calibrated
inference. Independent-cloud studies have their own analysis and are not loaded
or silently substituted here.
"""
from __future__ import annotations

import math
from typing import Any

LEGACY_SCOPE = (
    "Descriptive legacy evidence only. Bit rules reuse clouds; E1/E2 share draws "
    "within seed, and surface seeds/contamination conditions can reuse points. "
    "Reported p-values and intervals do not account for all dependencies and "
    "are nominal, not calibrated evidence of general superiority."
)
STRATIFIED_SCOPE = (
    "Per-rule summaries of the legacy design; removing repeated bit rules does "
    "not remove shared E1/E2 draws, overlapping surface samples or repeated "
    "contamination conditions. The 10 geometry-seed cells are not established "
    "as independent clouds. Historical passed flags are nominal regression "
    "gates only; use the separate independent-cloud analysis for inference."
)
CLAIM_CAPTION = (
    "Legacy claim directions on recorded configurations. Synthetic p-values "
    "are nominal under shared inputs; statuses do not confirm hypotheses. "
    "Real-data status is a descriptive direction check on fixed datasets."
)


def annotate_legacy_statistics(stats: dict[str, Any]) -> None:
    """Add scope without changing any measured value, p-value or legacy gate."""
    stats["inference_status"] = "descriptive_legacy"
    stats["inference_scope"] = LEGACY_SCOPE
    stats["stratified_scope"] = STRATIFIED_SCOPE
    stats["definition_of_done_metric_scope"] = (
        "Historical nominal H1/H2 MIAD gate; definition_of_done_passed is kept "
        "for numerical regression compatibility, not scientific confirmation. "
        "H3 is diagnostic. " + LEGACY_SCOPE
    )
    stats["definition_of_done_is_calibrated_inference"] = False
    for field in ("hypotheses", "stratified_by_bit_rule"):
        for item in stats.get(field, []):
            item["inference_status"] = "descriptive_legacy"
            item["p_value_scope"] = "nominal_under_incomplete_dependence_blocking"
            item["passed_scope"] = "historical_nominal_gate_only"
    if "bootstrap" in stats:
        stats["bootstrap"]["scope"] = "nominal legacy intervals; shared inputs not fully preserved"


def legacy_direction(item: dict[str, Any]) -> str:
    """Describe the paired median direction, never infer it from a p/gate flag."""
    delta = item.get("median_delta_rch_minus_baseline")
    if not item.get("n_pairs") or not isinstance(delta, (int, float)) or not math.isfinite(delta):
        return "Not assessed"
    if delta == 0:
        return "No median difference (descriptive)"
    favorable = delta > 0 if item.get("alternative") == "greater" else delta < 0
    return "Favorable direction (descriptive)" if favorable else "Unfavorable direction (descriptive)"


def claim_status_rows(synthetic: dict[str, Any], real: dict[str, Any]) -> list[dict[str, Any]]:
    """One source of truth for TeX/CSV/JSON, including old unannotated inputs."""
    hypotheses = {r.get("hypothesis"): r for r in synthetic.get("hypotheses", [])}
    rows = []
    for name, title in (("H1", "H1 synthetic MIAD"), ("H2", "H2 synthetic MIAD"),
                        ("H3", "H3 contamination stability"), ("H7_A7", "A7 CGAL baseline comparison")):
        item = hypotheses.get(name, {})
        p_key = "p_adj" if "p_adj" in item else "p"
        rows.append(dict(claim=title, status=legacy_direction(item), evidence=(
            f"nominal {p_key}={item.get(p_key, 'NA')}; "
            f"median_delta={item.get('median_delta_rch_minus_baseline', 'NA')}; shared inputs")))
    h1 = next((r for r in real.get("hypotheses", []) if r.get("hypothesis") == "H1_real_directional"), {})
    outcome = h1.get("outcome", "confirmed" if h1.get("passed") else "insufficient_data")
    status = {"confirmed": "Favorable on recorded cells", "failed": "Failed",
              "insufficient_data": "Not verified"}.get(outcome, "Not verified")
    failed = sum(not r.get("passed") for r in h1.get("comparisons", []))
    rows.append(dict(claim="H1 real-data direction", status=status,
                     evidence=f"comparisons={h1.get('comparison_count', 'NA')}; failed={failed}; fixed datasets only"))
    return rows
