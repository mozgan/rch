#!/usr/bin/env python3
# ----------------------------------------------------------------------------
# quantization_stress.py — quantization-bit-budget stress fixture.
#
# References:
#   - IEEE Computer Society, IEEE Standard for Floating-Point Arithmetic,
#     2019, DOI: 10.1109/IEEESTD.2019.8766229.
#   - David Goldberg, What Every Computer Scientist Should Know About
#     Floating-Point Arithmetic, 1991, DOI: 10.1145/103162.103163.
# ----------------------------------------------------------------------------
"""Synthetic quantization-stress fixture generator (NOT a locality input).

`stress_points(count, scenario, seed)` returns a deterministic 3D point cloud
designed to stress the C2 occupancy bit allocator + uint64 bit budget along a
named scenario axis. See module header for the scope discipline: this
generator is intentionally excluded from the main locality runlists.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Callable

from data.synthetic.generators.common import Point, SplitMix64, write_xyz_csv


def _extreme_aspect(rng: SplitMix64, count: int) -> list[Point]:
    """Stress: bbox aspect 1 : 1e6 : 1e-3 — maximum anisotropy regime."""
    scale_x = 1.0
    scale_y = 1.0e6
    scale_z = 1.0e-3
    points: list[Point] = []
    while len(points) < count:
        g0, g1 = rng.gaussian_pair()
        g2, _ = rng.gaussian_pair()
        points.append((scale_x * g0, scale_y * g1, scale_z * g2))
    return points


def _near_integer_boundary(rng: SplitMix64, count: int) -> list[Point]:
    """Stress: coordinates within `2^-50` of small-integer grid nodes.

    `binary64` ulp at unit scale is ≈ 2^-52; this scenario stays one bit
    above the ulp boundary so the quantizer round-to-nearest path is
    exercised consistently.
    """
    boundary_jitter = 2.0**-50
    points: list[Point] = []
    while len(points) < count:
        # cycle through (-2, -1, 0, 1, 2) grid nodes via SplitMix
        idx = rng.next_u64() % 5
        base = float(int(idx) - 2)
        g0, g1 = rng.gaussian_pair()
        g2, _ = rng.gaussian_pair()
        points.append(
            (
                base + boundary_jitter * g0,
                base + boundary_jitter * g1,
                base + boundary_jitter * g2,
            )
        )
    return points


def _signed_zero_mix(rng: SplitMix64, count: int) -> list[Point]:
    """Stress: roughly half points carry `+0.0`, half carry `-0.0` on one axis.

    The C++ orderer normalises signed zero (Goldberg 1991, IEEE 754
    §6.3); this fixture ensures runtime injection of the same condition.
    """
    points: list[Point] = []
    while len(points) < count:
        u = rng.next_u64()
        zero_axis = u & 0x1  # +0 if even, -0 if odd
        sign = -0.0 if zero_axis else 0.0
        g0, g1 = rng.gaussian_pair()
        points.append((g0, g1, sign))
    return points


STRESS_SCENARIOS: dict[str, Callable[[SplitMix64, int], list[Point]]] = {
    "extreme_aspect": _extreme_aspect,
    "near_integer_boundary": _near_integer_boundary,
    "signed_zero_mix": _signed_zero_mix,
}


def stress_points(count: int, scenario: str, seed: int) -> list[Point]:
    """Return `count` deterministic quantization-stress points.

    Behaviour:
      * `count == 0` → empty list.
      * `count < 0` → `ValueError`.
      * Unknown `scenario` → `ValueError` (Boundary-Gate).
    Algorithm: dispatch a named deterministic stress distribution over
    extreme aspect ratio, \(2^{-50}\) grid-boundary jitter, or signed zero.
    """
    if count < 0:
        raise ValueError("count must be non-negative")
    builder = STRESS_SCENARIOS.get(scenario)
    if builder is None:
        raise ValueError(f"unknown quantization_stress scenario: {scenario}")
    rng = SplitMix64(seed ^ 0x243F_6A88_85A3_08D3)  # substream isolation
    return builder(rng, count)


def parse_args() -> argparse.Namespace:
    """Parse the standalone CLI used by Synthetic stress-fixture builders."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=sorted(STRESS_SCENARIOS), required=True)
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    """Emit a headerless XYZ CSV for a stress-fixture scenario."""
    args = parse_args()
    write_xyz_csv(args.output, stress_points(args.count, args.scenario, args.seed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
