#!/usr/bin/env python3
# ----------------------------------------------------------------------------
# contamination.py — D-axis contamination generators for synthetic datasets
#
# References:
#   - Peter J. Rousseeuw, Katrien Van Driessen, A Fast Algorithm for the
#     Minimum Covariance Determinant Estimator, 1999, DOI: 10.1080/00401706.1999.10485670.
#   - David Goldberg, What Every Computer Scientist Should Know About
#     Floating-Point Arithmetic, 1991, DOI: 10.1145/103162.103163.
# ----------------------------------------------------------------------------
"""Synthetic dataset D-axis contamination generators.

Public API: `outlier_count`, `inject_uniform_bbox`, `inject_clustered`,
`contaminate(points, mode, fraction, seed)`. The CLI driver writes a
contaminated XYZ CSV from an input file via `--mode` and `--fraction`.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

from data.synthetic.generators.common import (
    Point,
    SplitMix64,
    read_xyz_csv,
    write_xyz_csv,
)


def bounds(points: list[Point]) -> tuple[Point, Point]:
    """Return axis-aligned bounds for uniform-bbox outlier placement."""
    if not points:
        return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
    lo = [min(point[axis] for point in points) for axis in range(3)]
    hi = [max(point[axis] for point in points) for axis in range(3)]
    return (lo[0], lo[1], lo[2]), (hi[0], hi[1], hi[2])


def placement_spans(lo: Point, hi: Point) -> list[float]:
    """Return the per-axis length scale used to place outliers.

    The scale must be *relative to the cloud*, otherwise the D-axis stops being
    a contamination-severity knob and becomes a function of the dataset's unit
    of measure. The previous `max(hi - lo, 1.0)` floor was absolute: for the
    Stanford Bunny (extent ~0.155 units) it placed outliers 6-13 object
    diameters away, inflating the covering box by a factor of ~37000 in volume,
    while for the Armadillo (extent ~127-151 units) it never triggered at all.

    Degenerate axes still need a fallback: `coplanar` has zero z-extent and
    `collinear` has zero y- and z-extent (see degeneracy_cases.py), and a zero
    span would place "outliers" inside the cloud. Those axes borrow the largest
    non-degenerate extent, which keeps the placement scale-relative. Only a
    cloud with no extent at all falls back to 1.0.
    """
    extents = [hi[axis] - lo[axis] for axis in range(3)]
    scale = max(extents)
    if not math.isfinite(scale) or scale <= 0.0:
        return [1.0, 1.0, 1.0]
    return [extent if extent > 0.0 else scale for extent in extents]


def outlier_count(clean_count: int, fraction: float) -> int:
    """Convert a D-axis fraction into an added-outlier count."""
    if clean_count < 0:
        raise ValueError("clean_count must be non-negative")
    if not math.isfinite(fraction) or fraction < 0.0:
        raise ValueError("fraction must be finite and non-negative")
    return int(round(float(clean_count) * fraction))


def inject_uniform_bbox(points: list[Point], fraction: float, seed: int) -> list[Point]:
    """Append deterministic outliers strictly outside the clean axis-aligned bbox.

    Geometry:
      * For each new outlier, a "primary axis" is chosen via SplitMix64.
      * On the primary axis the outlier is placed `[span, 2·span]` away
        from the bbox boundary (sign chosen by an additional SplitMix bit),
        guaranteeing it falls outside the original cloud.
      * The two secondary axes wander in `[lo - 2·span, hi + 2·span]`.
    Substream isolation: seed XOR mask `0xD1B54A32D192ED03` keeps this
    generator's draws disjoint from `inject_clustered`.
    """
    count = outlier_count(len(points), fraction)
    if count == 0:
        return list(points)
    lo, hi = bounds(points)
    spans = placement_spans(lo, hi)
    rng = SplitMix64(seed ^ 0xD1B54A32D192ED03)
    contaminated = list(points)
    for _ in range(count):
        axis = rng.next_u64() % 3
        values = []
        for dim in range(3):
            margin = 2.0 * spans[dim]
            if dim == axis:
                side = -1.0 if (rng.next_u64() & 1) == 0 else 1.0
                anchor = lo[dim] if side < 0.0 else hi[dim]
                values.append(anchor + side * rng.uniform(spans[dim], margin))
            else:
                values.append(rng.uniform(lo[dim] - margin, hi[dim] + margin))
        contaminated.append((values[0], values[1], values[2]))
    return contaminated


def inject_clustered(points: list[Point], fraction: float, seed: int) -> list[Point]:
    """Append deterministic clustered outliers near one remote center.

    Geometry:
      * Cluster center = `(hi + 3·span)` per axis ⇒ definitively outside the
        clean bbox (used for D4 in synthetic datasets).
      * Each outlier jitters by `±5% span` around this center.
    Substream isolation: seed XOR mask `0xABC98388FB8FAC03` keeps draws
    disjoint from `inject_uniform_bbox`.
    """
    count = outlier_count(len(points), fraction)
    if count == 0:
        return list(points)
    lo, hi = bounds(points)
    spans = placement_spans(lo, hi)
    center = tuple(hi[axis] + 3.0 * spans[axis] for axis in range(3))
    rng = SplitMix64(seed ^ 0xABC98388FB8FAC03)
    contaminated = list(points)
    for _ in range(count):
        jitter = tuple(
            rng.uniform(-0.05 * spans[axis], 0.05 * spans[axis]) for axis in range(3)
        )
        contaminated.append(tuple(center[axis] + jitter[axis] for axis in range(3)))  # type: ignore[arg-type]
    return contaminated


def contaminate(
    points: list[Point], mode: str, fraction: float, seed: int
) -> list[Point]:
    """Dispatch D-axis contamination modes from runlist YAML."""
    if mode == "clean":
        return list(points)
    if mode == "uniform_bbox":
        return inject_uniform_bbox(points, fraction, seed)
    if mode == "clustered":
        return inject_clustered(points, fraction, seed)
    raise ValueError(f"unknown contamination mode: {mode}")


def parse_args() -> argparse.Namespace:
    """Parse the standalone contamination CLI."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--mode", choices=("clean", "uniform_bbox", "clustered"), required=True
    )
    parser.add_argument("--fraction", type=float, required=True)
    parser.add_argument("--seed", type=int, required=True)
    return parser.parse_args()


def main() -> int:
    """Read clean points, append outliers, and write headerless XYZ CSV."""
    args = parse_args()
    write_xyz_csv(
        args.output,
        contaminate(read_xyz_csv(args.input), args.mode, args.fraction, args.seed),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
