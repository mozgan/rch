"""Shared application layout IDs and policies.

A6_rch is the fixed C0 control. Native rules have distinct IDs; adding
these arms does not turn native policies into a matched-resolution ablation.
"""

from __future__ import annotations

CONTROL_LAYOUTS = ("A0_input", "A0_full_scan", "A3_isotropic_hilbert", "A6_rch")
NATIVE_LAYOUTS = ("A6_rch_C2", "A6_rch_C3", "A6_rch_C4")
LAYOUTS = CONTROL_LAYOUTS + NATIVE_LAYOUTS
RULES = {
    "A0_input": {"bit_rule": None, "bit_allocator": None},
    "A0_full_scan": {"bit_rule": None, "bit_allocator": None},
    "A3_isotropic_hilbert": {"bit_rule": "C0_uniform", "bit_allocator": "uniform"},
    "A6_rch": {"bit_rule": "C0_uniform", "bit_allocator": "uniform"},
    "A6_rch_C2": {
        "bit_rule": "C2_occupancy_floor1",
        "bit_allocator": "occupancy_floor1",
    },
    "A6_rch_C3": {
        "bit_rule": "C3_frame_core_occupancy",
        "bit_allocator": "frame_core_occupancy",
    },
    "A6_rch_C4": {"bit_rule": "C4_hybrid", "bit_allocator": "hybrid_occupancy"},
}


APPLICATION_OUTPUT_ROOT = "experiments/outputs/application_query/full_benchmark"
APPLICATION_SCHEMA = "rch.application_query"
APPLICATION_PROTOCOL = "application_window_query"


def expected_layouts(manifest):
    if manifest.get("schema") != APPLICATION_SCHEMA:
        raise ValueError("unsupported application manifest schema; regenerate the shared application run")
    if manifest.get("protocol") != APPLICATION_PROTOCOL:
        raise ValueError("application protocol mismatch")
    ordering = manifest["ordering"]
    if ordering.get("layout_rules") != RULES:
        raise ValueError("native-rule layout policy mismatch")
    ids = ordering.get("layouts", [])
    if set(ids) != set(LAYOUTS) or len(ids) != len(LAYOUTS):
        raise ValueError("native layout IDs are incomplete or duplicated")
    return LAYOUTS


def is_application_source(manifest):
    if (manifest.get("schema"), manifest.get("protocol")) != (APPLICATION_SCHEMA, APPLICATION_PROTOCOL):
        return False
    expected_layouts(manifest)
    return True
