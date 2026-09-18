#!/usr/bin/env python3
# ----------------------------------------------------------------------------
# torus.py — E-axis torus-surface generator.
#
# References:
#   - John H. Halton, On the efficiency of certain quasi-random sequences of
#     points in evaluating multi-dimensional integrals, 1960.
#   - David Goldberg, What Every Computer Scientist Should Know About
#     Floating-Point Arithmetic, 1991, DOI: 10.1145/103162.103163.
# ----------------------------------------------------------------------------
"""Torus-surface generator (parametric R + r torus).

`torus_points(count, family, seed)` returns a deterministic 3D point cloud
sampled from a parametric torus surface using a 2D Halton sequence; suitable
for genus-1 thin-manifold locality experiments.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

from data.synthetic.generators.common import Point, write_xyz_csv

TORUS_RADII: dict[str, tuple[float, float]] = {
    # (R_major, r_minor) — must satisfy 0 < r < R for an embedded torus.
    "standard": (1.0, 0.3),
    "thin": (1.0, 0.1),
    "fat": (1.0, 0.45),
}

# Halton bases 2 and 3 — same construction as surface_patch.py.
_HALTON_BASE_U = 2
_HALTON_BASE_V = 3
# Coprime offset prime so two distinct seeds index disjoint Halton sub-stripes.
_SEED_OFFSET_PRIME = 1_000_003


def _radical_inverse(value: int, base: int) -> float:
    result = 0.0
    scale = 1.0 / float(base)
    while value > 0:
        result += scale * float(value % base)
        value //= base
        scale /= float(base)
    return result


def torus_xyz(u: float, v: float, R: float, r: float) -> Point:
    """Map (u, v) ∈ [0, 2π)² → 3D point on the torus.

    Standard parametrization; pure function, no rounding-aware
    fast paths so output is invariant across Python versions on the same
    `binary64` toolchain.
    """
    cos_v = math.cos(v)
    sin_v = math.sin(v)
    cos_u = math.cos(u)
    sin_u = math.sin(u)
    radius = R + r * cos_v
    return (radius * cos_u, radius * sin_u, r * sin_v)


def torus_points(count: int, family: str, seed: int) -> list[Point]:
    """Return `count` deterministic torus surface points.

    Behaviour:
      * `count == 0` → empty list.
      * `count < 0` → `ValueError`.
      * Unknown `family` → `ValueError`.
      * Non-finite radii or \(0 < r < R\) violation → `ValueError`.
    Algorithm: with \(u=2\pi h_2(i)\), \(v=2\pi h_3(i)\),
    emit \(((R+r\cos v)\cos u, (R+r\cos v)\sin u, r\sin v)\).
    Cost per point: 2 radical-inverse evaluations + 4 trig calls; without PRNG
    """
    if count < 0:
        raise ValueError("count must be non-negative")
    if family not in TORUS_RADII:
        raise ValueError(f"unknown torus family: {family}")
    R, r = TORUS_RADII[family]
    if (
        (not math.isfinite(R))
        or (not math.isfinite(r))
        or R <= 0.0
        or r <= 0.0
        or r >= R
    ):
        raise ValueError(
            f"torus radii must be finite and satisfy 0 < r < R; got R={R}, r={r}"
        )
    offset = (seed % _SEED_OFFSET_PRIME) + 1  # avoid index 0 (Halton singularity)
    two_pi = 2.0 * math.pi
    points: list[Point] = []
    for i in range(count):
        idx = offset + i
        u = two_pi * _radical_inverse(idx, _HALTON_BASE_U)
        v = two_pi * _radical_inverse(idx, _HALTON_BASE_V)
        points.append(torus_xyz(u, v, R, r))
    return points


def parse_args() -> argparse.Namespace:
    """Parse the standalone torus-generator CLI."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family", choices=sorted(TORUS_RADII), required=True)
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    """Emit a headerless XYZ CSV of `count` torus-surface points."""
    args = parse_args()
    write_xyz_csv(args.output, torus_points(args.count, args.family, args.seed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
