#!/usr/bin/env python3
# ----------------------------------------------------------------------------
# degeneracy_cases.py — Synthetic Dataset rank-deficient synthetic fixtures
#
# References:
#   - Peter J. Rousseeuw, Katrien Van Driessen, A Fast Algorithm for the
#     Minimum Covariance Determinant Estimator, 1999, DOI: 10.1080/00401706.1999.10485670.
# ----------------------------------------------------------------------------
"""Degenerate synthetic cases: coplanar and collinear point clouds.

Public API: `coplanar_points`, `collinear_points`, `make_case` dispatcher.
The CLI driver writes the requested degenerate cloud to a headerless XYZ CSV.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

from data.synthetic.generators.common import Point, write_xyz_csv


def coplanar_points(count: int, seed: int) -> list[Point]:
    """Return deterministic \(z=0\) points on a golden-angle spiral grid."""
    if count < 0:
        raise ValueError("count must be non-negative")
    golden = (1.0 + math.sqrt(5.0)) / 2.0
    return [
        (
            math.cos((seed + i) / golden) * (1.0 + 0.001 * i),
            math.sin((seed + i) / golden) * (1.0 + 0.001 * i),
            0.0,
        )
        for i in range(count)
    ]


def collinear_points(count: int, seed: int) -> list[Point]:
    """Return deterministic \(y=z=0\) points for rank-one fallback tests."""
    if count < 0:
        raise ValueError("count must be non-negative")
    offset = (seed % 17) * 0.01
    return [
        (-1.0 + offset + (2.0 * i / max(1, count - 1)), 0.0, 0.0) for i in range(count)
    ]


def make_case(case: str, count: int, seed: int) -> list[Point]:
    """Dispatch the named degeneracy case."""
    if case == "coplanar":
        return coplanar_points(count, seed)
    if case == "collinear":
        return collinear_points(count, seed)
    raise ValueError(f"unknown degeneracy case: {case}")


def parse_args() -> argparse.Namespace:
    """Parse the standalone degeneracy generator CLI."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=("coplanar", "collinear"), required=True)
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    """Generate the requested degenerate point cloud."""
    args = parse_args()
    write_xyz_csv(args.output, make_case(args.case, args.count, args.seed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
