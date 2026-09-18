#!/usr/bin/env python3
# ----------------------------------------------------------------------------
# gaussian_ellipsoid.py — Synthetic dataset Gaussian ellipsoid generator.
#
# References:
#   - George E. P. Box, Mervin E. Muller, A Note on the Generation of Random
#     Normal Deviates, 1958, DOI: 10.1214/aoms/1177706645.
#   - David Goldberg, What Every Computer Scientist Should Know About
#     Floating-Point Arithmetic, 1991, DOI: 10.1145/103162.103163.
# ----------------------------------------------------------------------------
"""Gaussian ellipsoid generators for E0/E1/E2 synthetic geometry.

`ellipsoid_points(count, axes, seed)` builds a deterministic anisotropic
Gaussian cloud, applies a per-seed reporting rotation, and returns a list of
finite point triples ready for `write_xyz_csv`.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

from data.synthetic.generators.common import Point, SplitMix64, write_xyz_csv

GEOMETRY_AXES: dict[str, tuple[float, float, float]] = {
    "sphere": (1.0, 1.0, 1.0),
    "plate_5to1": (5.0, 1.0, 1.0),
    "rod_10to1": (10.0, 1.0, 1.0),
}


def rotation_matrix(
    seed: int,
) -> tuple[
    tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]
]:
    """Return deterministic ZYX Tait-Bryan rotation matrix.

    Algorithm: draw yaw, pitch, roll in \([0, 2\pi)\); then form
    \(R = R_z(\psi) R_y(\theta) R_x(\phi)\).
    """
    rng = SplitMix64(seed ^ 0x6A09E667F3BCC909)
    yaw = 2.0 * 3.141592653589793 * rng.uniform01()
    pitch = 2.0 * 3.141592653589793 * rng.uniform01()
    roll = 2.0 * 3.141592653589793 * rng.uniform01()
    cy, sy = math.cos(yaw), math.sin(yaw)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cr, sr = math.cos(roll), math.sin(roll)
    return (
        (cy * cp, (cy * sp * sr) - (sy * cr), (cy * sp * cr) + (sy * sr)),
        (sy * cp, (sy * sp * sr) + (cy * cr), (sy * sp * cr) - (cy * sr)),
        (-sp, cp * sr, cp * cr),
    )


def apply_rotation(
    point: Point, matrix: tuple[tuple[float, float, float], ...]
) -> Point:
    """Rotate a point by the deterministic reporting-rotation matrix."""
    return (
        (matrix[0][0] * point[0])
        + (matrix[0][1] * point[1])
        + (matrix[0][2] * point[2]),
        (matrix[1][0] * point[0])
        + (matrix[1][1] * point[1])
        + (matrix[1][2] * point[2]),
        (matrix[2][0] * point[0])
        + (matrix[2][1] * point[1])
        + (matrix[2][2] * point[2]),
    )


def ellipsoid_points(
    count: int, axes: tuple[float, float, float], seed: int
) -> list[Point]:
    """Return `count` deterministic Gaussian ellipsoid points.

    Behaviour:
      * `count == 0` → empty list.
      * `count < 0` → `ValueError`.
      * `axes` must be three finite positive values; non-positive components are
        rejected because `axis = 0` would collapse the ellipsoid to a
        plane, making the E-axis label meaningless).
      * Samples are \(x = R \operatorname{diag}(a,b,c) z\), where
        \(z \sim \mathcal{N}(0, I_3)\).
    Per-point cost: exactly 4 SplitMix64 advancements via two
    `gaussian_pair()` calls — by construction so the seed → output map is
    invariant to compiler / Python-version changes.
    """
    if count < 0:
        raise ValueError("count must be non-negative")
    if len(axes) != 3 or any(
        (not math.isfinite(axis)) or axis <= 0.0 for axis in axes
    ):
        raise ValueError("axes must contain three finite positive values")

    rng = SplitMix64(seed)
    rotation = rotation_matrix(seed)
    points: list[Point] = []
    while len(points) < count:
        g0, g1 = rng.gaussian_pair()
        g2, _ = rng.gaussian_pair()
        points.append(
            apply_rotation((axes[0] * g0, axes[1] * g1, axes[2] * g2), rotation)
        )
    return points


def parse_args() -> argparse.Namespace:
    """Parse the standalone generator CLI used by synthetic dataset runner tests."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--geometry", choices=sorted(GEOMETRY_AXES), required=True)
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    """Generate a headerless XYZ CSV file for src/cli/rch_order.cpp."""
    args = parse_args()
    write_xyz_csv(
        args.output,
        ellipsoid_points(args.count, GEOMETRY_AXES[args.geometry], args.seed),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
