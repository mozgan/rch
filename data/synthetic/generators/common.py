#!/usr/bin/env python3
# ----------------------------------------------------------------------------
# common.py — synthetic dataset generator helper
#
# References:
#   - Guy L. Steele Jr., Doug Lea, Christine H. Flood, Fast splittable
#     pseudorandom number generators, 2014, DOI: 10.1145/2660193.2660195.
#   - George E. P. Box, Mervin E. Muller, A Note on the Generation of Random
#     Normal Deviates, 1958, DOI: 10.1214/aoms/1177706645.
#   - David Goldberg, What Every Computer Scientist Should Know About
#     Floating-Point Arithmetic, 1991, DOI: 10.1145/103162.103163.
# ----------------------------------------------------------------------------
"""Deterministic helpers for synthetic point-cloud generators

This module supplies the SplitMix64 PRNG, IEEE-754 unit-interval mapping,
Box-Muller standard-normal pair generator, and the headerless XYZ I/O used by
the synthetic data generator scripts. All public functions are pure: same arguments
produce the same outputs across invocations and across (binary64) toolchains.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Iterable, Sequence

Point = tuple[float, float, float]


class SplitMix64:
    """Small deterministic 64-bit PRNG used by synthetic generator scripts.

    Invariants:
      * `next_u64()` in [0, 2^64) for any input state.
      * Same seed produces identical streams across invocations and Python
        versions (uses fixed unsigned 64-bit arithmetic via `& 2^64-1`).
    """

    def __init__(self, seed: int) -> None:
        """Store the 64-bit seed; signed-int and overflow inputs masked."""
        self._state = seed & 0xFFFFFFFFFFFFFFFF

    def next_u64(self) -> int:
        """Advance state and return the SplitMix64 finalizer output.

        Bitwise contract (Vigna 2014):
            state ← state + γ           with γ = 0x9E3779B97F4A7C15
            z ← (z xor z>>30) · M1      with M1 = 0xBF58476D1CE4E5B9
            z ← (z xor z>>27) · M2      with M2 = 0x94D049BB133111EB
            return z xor z>>31
        Each step is masked to 64-bit unsigned to mirror the C reference.
        """
        self._state = (self._state + 0x9E3779B97F4A7C15) & 0xFFFFFFFFFFFFFFFF
        z = self._state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & 0xFFFFFFFFFFFFFFFF
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & 0xFFFFFFFFFFFFFFFF
        return z ^ (z >> 31)

    def uniform01(self) -> float:
        """Map the top 53 bits to a binary64 value in [0, 1).

        Rationale: IEEE-754 binary64 mantissa carries 53 explicit bits. The
        right-shift by 11 keeps only the high 53 bits before scaling by
        2^-53; this is the standard `double_from_bits` recipe used by Vigna's
        reference and matches the convention in `<random>::uniform_real`.
        Output range is closed-open: never returns 1.0 exactly.
        """
        return float(self.next_u64() >> 11) * (1.0 / float(1 << 53))

    def uniform(self, lo: float, hi: float) -> float:
        """Return a deterministic uniform sample in [lo, hi).

        Degenerate or reversed ranges are treated as empty and return `lo`;
        generators in this package normally supply `lo <= hi`.
        """
        if hi <= lo:
            return lo
        return lo + (hi - lo) * self.uniform01()

    def gaussian_pair(self) -> tuple[float, float]:
        """Return two i.i.d. standard-normal samples via Box-Muller"""
        u1 = max(self.uniform01(), 2.0**-53)
        u2 = self.uniform01()
        radius = math.sqrt(-2.0 * math.log(u1))
        angle = 2.0 * math.pi * u2
        return radius * math.cos(angle), radius * math.sin(angle)


def finite_point(point: Sequence[float]) -> bool:
    """Mirror the C++ finite-input gate enforced by `src/cli/rch_order.cpp`.

    Returns True iff `point` has exactly three coordinates and each is finite
    (no NaN, no ±Inf). This is a sanity-check on inputs we *write*; the C++
    side independently re-validates and fails closed via `invalid_input`
    telemetry — duplication is by design.
    """
    if len(point) != 3:
        return False
    try:
        return all(math.isfinite(float(value)) for value in point)
    except (TypeError, ValueError, OverflowError):
        return False


def write_xyz_csv(path: Path, points: Iterable[Point]) -> None:
    """Write headerless XYZ CSV accepted by `src/cli/rch_order.cpp`.

    Format contract:
      * One point per line, three comma-separated coordinates, LF newline.
      * `%.17g` width preserves binary64 round-trip exactly (IEEE-754
        §5.12.2 / Steele-White Dragon4 / Burger-Dybvig 1996); 17 significant
        digits are sufficient to round-trip a `double`. Generators and
        runners share this convention so re-reading produces bit-identical
        coordinates on the same toolchain.
      * Parent directory is created if missing (mkdir -p semantics).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for x, y, z in points:
            if not finite_point((x, y, z)):
                raise ValueError(f"non-finite point cannot be written to {path}")
            handle.write(f"{x:.17g},{y:.17g},{z:.17g}\n")


def read_xyz_csv(path: Path) -> list[Point]:
    """Read the headerless XYZ CSV emitted by the synthetic data generators.

    Fail-closed gates:
      * Empty / whitespace-only lines silently skipped.
      * `;` separator is normalised to `,` to accept CSV exports that use
        EU-locale delimiters; mixed delimiters tolerated within a single line.
      * A row with column count ≠ 3 raises `ValueError` (matches the
        `rch_order.cpp` ASCII parser contract).
      * A row with any non-finite value (NaN/Inf) raises `ValueError`
        (rejects pre-quantisation inputs the orderer would refuse).
    """
    points: list[Point] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            parts = [float(part) for part in stripped.replace(";", ",").split(",")]
            if len(parts) != 3:
                raise ValueError(f"expected 3 coordinates in {path}: {line!r}")
            point = (parts[0], parts[1], parts[2])
            if not finite_point(point):
                raise ValueError(f"non-finite point in {path}: {line!r}")
            points.append(point)
    return points
