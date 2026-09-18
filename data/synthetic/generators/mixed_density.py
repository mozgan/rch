#!/usr/bin/env python3
# ----------------------------------------------------------------------------
# mixed_density.py — E-axis mixed-density Gaussian-mixture generator
#
# References:
#   - Geoffrey J. McLachlan, David Peel, Finite Mixture Models, 2000,
#     DOI: 10.1002/0471721182.
#   - George E. P. Box, Mervin E. Muller, A Note on the Generation of Random
#     Normal Deviates, 1958, DOI: 10.1214/aoms/1177706645.
# ----------------------------------------------------------------------------
"""Synthetic mixed-density Gaussian-mixture generator.

`mixture_points(count, family, seed)` returns a deterministic 3D point cloud
sampled from a three-component Gaussian mixture with anisotropic component
weights and scales; used by the occupancy bit allocator stress experiments.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Sequence

from data.synthetic.generators.common import Point, SplitMix64, write_xyz_csv

# Each component: (center_xyz, sigma_scalar, weight)
ComponentSpec = tuple[tuple[float, float, float], float, float]

MIXTURE_FAMILIES: dict[str, tuple[ComponentSpec, ComponentSpec, ComponentSpec]] = {
    # default: dense core + two satellites with asymmetric weights.
    "three_blobs": (
        ((0.0, 0.0, 0.0), 0.5, 0.5),
        ((2.5, 0.0, 0.0), 1.0, 0.3),
        ((0.0, 2.0, 1.5), 0.3, 0.2),
    ),
    # high-contrast: one tight core with two diffuse outer modes.
    "core_and_halo": (
        ((0.0, 0.0, 0.0), 0.2, 0.6),
        ((3.0, 3.0, 0.0), 1.5, 0.2),
        ((-3.0, -2.0, 0.0), 1.5, 0.2),
    ),
}


def select_component(rng: SplitMix64, weights: Sequence[float]) -> int:
    """Return the index of the chosen mixture component via categorical CDF.

    Boundary-Gate:
      * `sum(weights) <= 0` → `ValueError`.
      * Any non-finite or negative `w` → `ValueError`.
    Float-comparison contract: cumulative-sum is computed in double precision
    in component-order; a single `uniform01() · total` is compared in the
    same precision so the dispatch is invariant on any IEEE-754 toolchain.
    """
    total = 0.0
    for weight in weights:
        if not math.isfinite(weight) or weight < 0.0:
            raise ValueError("mixture weights must be finite and non-negative")
        total += weight
    if not math.isfinite(total) or total <= 0.0:
        raise ValueError("mixture weights must sum to a positive value")
    target = rng.uniform01() * total
    cumulative = 0.0
    for index, weight in enumerate(weights):
        cumulative += weight
        if target < cumulative:
            return index
    return len(weights) - 1  # safety: numerical edge


def mixture_points(count: int, family: str, seed: int) -> list[Point]:
    """Return `count` deterministic Gaussian-mixture points.

    Behaviour:
      * `count == 0` → empty list.
      * `count < 0` → `ValueError`.
      * Unknown `family` → `ValueError` (Boundary-Gate).
      * Component centers, scales, and weights must be finite; \(\sigma > 0\).
    Algorithm: choose component \(k\) from categorical CDF over weights,
    then emit \(x = \mu_k + \sigma_k z\), \(z \sim \mathcal{N}(0, I_3)\).
    Per-point cost: 1 categorical select (1 SplitMix64 advance) + 2
    `gaussian_pair()` calls (4 SplitMix64 advances) = 5 advances per point —
    constant step count for cross-version reproducibility.
    """
    if count < 0:
        raise ValueError("count must be non-negative")
    if family not in MIXTURE_FAMILIES:
        raise ValueError(f"unknown mixed_density family: {family}")
    components = MIXTURE_FAMILIES[family]
    for center, sigma, weight in components:
        if (
            len(center) != 3
            or any(not math.isfinite(value) for value in center)
            or (not math.isfinite(sigma))
            or sigma <= 0.0
            or (not math.isfinite(weight))
            or weight < 0.0
        ):
            raise ValueError("mixture components must be finite with sigma > 0")
    weights = [component[2] for component in components]
    rng = SplitMix64(seed ^ 0x517C_C1B7_2722_0A95)  # substream isolation prime
    points: list[Point] = []
    while len(points) < count:
        idx = select_component(rng, weights)
        center, sigma, _ = components[idx]
        g0, g1 = rng.gaussian_pair()
        g2, _ = rng.gaussian_pair()
        points.append(
            (
                center[0] + sigma * g0,
                center[1] + sigma * g1,
                center[2] + sigma * g2,
            )
        )
    return points


def parse_args() -> argparse.Namespace:
    """Parse the standalone CLI used by synthetic dataset fixture builders."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family", choices=sorted(MIXTURE_FAMILIES), required=True)
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    """Emit a headerless XYZ CSV of `count` mixture-model points."""
    args = parse_args()
    write_xyz_csv(args.output, mixture_points(args.count, args.family, args.seed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
