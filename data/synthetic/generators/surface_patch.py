#!/usr/bin/env python3
# ----------------------------------------------------------------------------
# surface_patch.py — E-axis quadric surface-patch generator
#
# References:
#   - John H. Halton, On the efficiency of certain quasi-random sequences of
#     points in evaluating multi-dimensional integrals, 1960.
#   - George E. P. Box, Mervin E. Muller, A Note on the Generation of Random
#     Normal Deviates, 1958, DOI: 10.1214/aoms/1177706645.
# ----------------------------------------------------------------------------
"""quadric surface-patch generator for the E-axis thin-manifolds

`patch_points(count, family, seed)` returns a deterministic point cloud sampled
from `z = a·x² + b·y²` on `[-1, 1]²` plus a thin Gaussian z-jitter; suitable
for testing the C2 occupancy bit allocator against thin manifolds.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

from data.synthetic.generators.common import Point, SplitMix64, write_xyz_csv

QUADRIC_COEFFS: dict[str, tuple[float, float, float]] = {
    # (a, b, sigma_z) — z = a·x² + b·y² + N(0, sigma_z²)
    "paraboloid_low": (0.4, 0.2, 0.01),
    "paraboloid_high": (1.0, 0.5, 0.02),
}


def halton_pair(index: int) -> tuple[float, float]:
    """Return (h₂(i), h₃(i)) Halton low-discrepancy sample.

    Halton (1960): radical-inverse in bases (2, 3) gives the standard 2D
    low-discrepancy sequence. Index 0 returns (0, 0); generators use i = 1..N
    to avoid the origin singularity. Pure function — no PRNG state.
    """

    def radical_inverse(value: int, base: int) -> float:
        result = 0.0
        scale = 1.0 / float(base)
        while value > 0:
            result += scale * float(value % base)
            value //= base
            scale /= float(base)
        return result

    return radical_inverse(index, 2), radical_inverse(index, 3)


def patch_points(count: int, family: str, seed: int) -> list[Point]:
    """Return `count` deterministic quadric-surface-patch points.

    Algorithm: sample \((u,v)=(h_2(i),h_3(i))\), map to
    \(x=2u-1\), \(y=2v-1\), then emit
    \(z = ax^2 + by^2 + \sigma_z n\), \(n \sim \mathcal{N}(0,1)\).
    """
    if count < 0:
        raise ValueError("count must be non-negative")
    if family not in QUADRIC_COEFFS:
        raise ValueError(f"unknown surface_patch family: {family}")
    a, b, sigma_z = QUADRIC_COEFFS[family]
    if (
        (not math.isfinite(a))
        or (not math.isfinite(b))
        or (not math.isfinite(sigma_z))
        or sigma_z < 0.0
    ):
        raise ValueError("quadric coefficients must be finite with sigma_z >= 0")
    rng = SplitMix64(seed ^ 0x7F4A_7C15_9E37_79B9)  # substream isolation
    points: list[Point] = []
    for i in range(1, count + 1):
        u, v = halton_pair(i)
        x = -1.0 + 2.0 * u  # map [0,1) → [-1, 1)
        y = -1.0 + 2.0 * v
        z_base = (a * x * x) + (b * y * y)
        n0, _ = rng.gaussian_pair()
        z = z_base + (sigma_z * n0)
        points.append((x, y, z))
    return points


def parse_args() -> argparse.Namespace:
    """Parse the standalone CLI used by Synthetic fixture builders."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family", choices=sorted(QUADRIC_COEFFS), required=True)
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    """Emit a headerless XYZ CSV consumable by src/cli/rch_order.cpp."""
    args = parse_args()
    write_xyz_csv(args.output, patch_points(args.count, args.family, args.seed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
