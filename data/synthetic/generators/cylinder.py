#!/usr/bin/env python3
# ----------------------------------------------------------------------------
# cylinder.py — E-axis cylindrical-surface generator for synthetic datasets
#
# References:
#   - John H. Halton, On the efficiency of certain quasi-random sequences of
#     points in evaluating multi-dimensional integrals, 1960.
#   - David Goldberg, What Every Computer Scientist Should Know About
#     Floating-Point Arithmetic, 1991, DOI: 10.1145/103162.103163.
# ----------------------------------------------------------------------------
"""Synthetic dataset cylinder lateral-surface generator.

`cylinder_points(count, family, seed)` returns a deterministic point cloud
sampled from the lateral surface of a finite right circular cylinder using a
2D Halton sequence for low-discrepancy θ-h coverage.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

from data.synthetic.generators.common import Point, SplitMix64, write_xyz_csv

CYLINDER_DIMS: dict[str, tuple[float, float]] = {
    # (radius, height)
    "standard": (0.5, 4.0),  # H / (2r) = 4    → 4:1:1 bbox
    "tall": (0.3, 6.0),  # H / (2r) = 10   → 10:1:1 bbox
    "short": (1.0, 1.0),  # H / (2r) = 0.5  → near-isotropic-ish disk-like
}

_HALTON_BASE_U = 2
_HALTON_BASE_V = 3
# Before the modulo wrap, consecutive seeds use adjacent Halton offsets, so
# fixed-size windows overlap by count - 1 points.
_SEED_OFFSET_PRIME = 1_000_003


def _radical_inverse(value: int, base: int) -> float:
    """Halton radical inverse — duplicated rather than imported to keep this
    generator self-contained and to avoid a cross-module coupling between
    fixture builders. Pure, deterministic.
    """
    result = 0.0
    scale = 1.0 / float(base)
    while value > 0:
        result += scale * float(value % base)
        value //= base
        scale /= float(base)
    return result


def cylinder_xyz(theta: float, h: float, radius: float) -> Point:
    """Map (θ, h) → 3D point on the cylinder lateral surface."""
    return (radius * math.cos(theta), radius * math.sin(theta), h)


def cylinder_points(
    count: int, family: str, seed: int, sampling: str = "halton"
) -> list[Point]:
    """Return `count` deterministic cylinder-lateral surface points.

    Behaviour:
      * `count == 0` → empty list.
      * `count < 0` → `ValueError`.
      * Unknown `family` → `ValueError`.
      * `radius <= 0` or `height <= 0` or non-finite dims → `ValueError`.
    Algorithm: map \(u=h_2(i)\), \(v=h_3(i)\) to
    \((r\cos(2\pi u), r\sin(2\pi u), -H/2 + Hv)\).
    """
    if count < 0:
        raise ValueError("count must be non-negative")
    if family not in CYLINDER_DIMS:
        raise ValueError(f"unknown cylinder family: {family}")
    if sampling not in {"halton", "iid"}:
        raise ValueError("sampling must be 'halton' or 'iid'")
    radius, height = CYLINDER_DIMS[family]
    if (
        (not math.isfinite(radius))
        or (not math.isfinite(height))
        or radius <= 0.0
        or height <= 0.0
    ):
        raise ValueError(
            f"cylinder dims must be finite and positive; got r={radius}, H={height}"
        )
    offset = (seed % _SEED_OFFSET_PRIME) + 1
    rng = SplitMix64(seed ^ 0x7F4A_7C15_9E37_79B9)
    two_pi = 2.0 * math.pi
    half_h = 0.5 * height
    points: list[Point] = []
    for i in range(count):
        if sampling == "halton":
            idx = offset + i
            theta_u = _radical_inverse(idx, _HALTON_BASE_U)
            height_u = _radical_inverse(idx, _HALTON_BASE_V)
        else:
            theta_u = rng.uniform01()
            height_u = rng.uniform01()
        theta = two_pi * theta_u
        h = -half_h + height * height_u
        points.append(cylinder_xyz(theta, h, radius))
    return points


def parse_args() -> argparse.Namespace:
    """Parse the standalone cylinder-generator CLI."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family", choices=sorted(CYLINDER_DIMS), required=True)
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    """Emit a headerless XYZ CSV of `count` cylinder-surface points."""
    args = parse_args()
    write_xyz_csv(args.output, cylinder_points(args.count, args.family, args.seed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
