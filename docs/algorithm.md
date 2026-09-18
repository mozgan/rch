# RCH Algorithm

RCH maps an indexed point sequence to a deterministic one-dimensional order.
This page describes the default `OrderingMethod::RCH` path. Alternative
methods reuse parts of the same implementation; they are summarized at the end.

Let

$$
P=(p_i)_{i=0}^{N-1}, \qquad p_i \in \mathbb{R}^3,
$$

where the index is part of the record identity. Duplicate coordinates are
therefore distinct inputs. The output permutation `pi` means that rank `r`
visits original point `p[pi[r]]`.

## Stage 1: Validate The Input

The input is a flat row-major span of `double` values. Its length must be
divisible by three and every coordinate must be finite. RCH normalizes both
IEEE-754 signed-zero encodings to positive zero for comparison and hashing.

Invalid shape and non-finite input return a structured error. Rows are never
silently dropped. Empty and singleton inputs are valid and produce the
corresponding empty or singleton permutation.

This validation does not prove that every intermediate floating-point operation
will remain finite. Extreme coordinate magnitudes may still overflow scatter
calculations or trigger fallback.

## Stage 2: Estimate Location And Scatter

The default robust branch is a deterministic MCD-style finite search. It is
inspired by DetMCD, but its starts, pilot, corrections, and numerical guards
are implementation-specific. It must not be described as an exact solution of
the combinatorial minimum-covariance-determinant problem.

For each axis, RCH obtains a lower median `c_j` and a MAD scale. A guarded
median of the three scales normalizes radial distances. The pilot counts points
whose normalized radius exceeds 5.2 and chooses

$$
\widehat{\epsilon}
= \frac{1}{N}\sum_i
\mathbf{1}\!\left[
\frac{\lVert p_i-c\rVert_2}{s_*}>5.2
\right],
\qquad
\alpha=\operatorname{clamp}(1-1.5\widehat{\epsilon},0.50,0.90).
$$

The score is a heuristic, not a calibrated contamination estimator. For the
three-dimensional robust branch, which requires `N >= 15`, the subset size is
computed from

$$
n_2=\left\lfloor\frac{N+4}{2}\right\rfloor,
\qquad
h=\left\lfloor 2n_2-N+2\alpha(N-n_2)\right\rfloor.
$$

Six deterministic initial-estimator families are followed by concentration
steps. Each step selects the `h` smallest squared Mahalanobis distances,
recomputes the subset mean and sample covariance, and stops on an unchanged
subset, numerical failure, determinant increase beyond tolerance, or the
200-step bound. Deterministic raw-coordinate and original-index tie-breaks are
used when distances are equal.

The eligible candidate with the smallest determinant wins. The selected
scatter receives the configured consistency and finite-sample corrections.
Ridge repairs are recorded. If the sample is too small, rank deficient, or
otherwise unusable by the robust branch, RCH falls back to sample mean and
sample covariance and sets `robust_fallback_used`.

MRCD and OGK are available as explicit estimator variants. Selecting them is
an ablation/configuration choice; it does not change the name of the ordering
method reported by `OrderingResult::method`.

## Stage 3: Construct The Principal Frame

For center `mu` and symmetric scatter `S`, a fixed cyclic Jacobi solver
computes descending eigenpairs:

$$
S \approx Q\,\operatorname{diag}(\lambda_1,\lambda_2,\lambda_3)Q^T.
$$

Eigenvector signs are canonicalized. If the eigensolver fails, values are not
finite, or a relative eigengap is too small to define stable axes, RCH uses
the canonical coordinate axes. This axis fallback is distinct from the robust
estimator fallback flag.

Each point is projected without whitening:

$$
y_i = Q^T(p_i-\mu).
$$

The orthogonal projection preserves Euclidean distances in exact arithmetic.
RCH then forms two symmetric boxes:

- the statistical core has half-extents `a_j = 2 sqrt(lambda_j)`, with guarded
  diagonal-scatter values when canonical axes are used;
- the covering box extends each half-extent to include every projected point.

The core support is the number of points inside all three core intervals.

## Stage 4: Allocate Axis Bits

For positive half-extents `b=(b_x,b_y,b_z)` and support count `n`, occupancy
allocation computes

$$
V=8b_xb_yb_z,
\qquad
\delta=\left(\frac{V}{\max(n,1)}\right)^{1/3},
$$

and requests

$$
m_j^{\mathrm{raw}}
=\max\!\left(
1,
\left\lceil
\log_2\max\!\left(\frac{2b_j}{\delta},1\right)
\right\rceil
\right).
$$

The requested depths are projected into the encoder budget: at most 32 bits
per axis and 63 bits in total. For a valid domain, the bounded search minimizes
the worst log cell edge among feasible depth vectors; deterministic
lexicographic precision breaks numerical ties.

The public allocators differ in how they choose resolution and domain:

| Allocator | Resolution source | Quantization domain |
| --- | --- | --- |
| `Uniform` | configured equal depth | covering box |
| `SampleCountUniform` | equal depth from `N` | covering box |
| `MonotoneHalf` | extent-ranked half budget | covering box |
| `OccupancyFloor1` | all-point occupancy, 1-bit floor | covering box |
| `OccupancyFloor10` | all-point occupancy, 10-bit floor | covering box |
| `FrameCoreOccupancy` | robust-core occupancy | core box |
| `HybridOccupancy` | core target cell size | covering box |

`FrameCoreOccupancy` is the default. Because it quantizes in the core box,
out-of-core points are clamped to boundary cells. This may improve stability in
some contaminated settings, but it can also increase key collisions. The
hybrid rule keeps the core-derived target resolution while covering all
projected points.

## Stage 5: Quantize, Encode, And Sort

For half-extent `b_j` and depth `m_j`, a projected coordinate is conceptually
mapped by

$$
t_j=\frac{y_j+b_j}{2b_j},
\qquad
q_j=
\begin{cases}
0, & t_j\le 0,\\
\lfloor t_j2^{m_j}\rfloor, & 0<t_j<1,\\
2^{m_j}-1, & t_j\ge 1.
\end{cases}
$$

The implementation checks the interval and conversion bounds and uses
`long double` for the interior arithmetic. Invalid intervals and zero-depth
axes map to zero.

The compact Hilbert encoder accepts unequal per-axis depths and produces at
most 63 key bits. Quantization collisions do not discard records. Before any
optional refinement, RCH sorts the total key

$$
(H_i,T(p_{ix}),T(p_{iy}),T(p_{iz}),i),
$$

where `H_i` is the curve key and `T` is a bit-derived total-order transform for
accepted binary64 coordinates. Raw coordinates and then the original index
make the order total even for colliding keys and duplicate points.

## Stage 6: Refine And Hash

Refinement is off by default. `RefinementMode::All` applies the same bounded
MIAD-decreasing local search to every non-input internal method:

- single-point relocation within the next 16 positions;
- 2-opt reversal with segment length at most 16;
- adjacent swaps after the joint passes.

A move is accepted only when its computed local edge delta is negative.
Refinement changes the permutation but not the stored curve keys or bit depths;
the final sequence therefore need not remain key-sorted.

The SHA-256 output digest covers the method tag, three depths, robust-fallback
flag, permutation length and entries, and primary-key length and entries.
Floating-point centers, axes, extents, timing, and memory are intentionally
excluded. The digest is an integer-output regression identifier, not a
cryptographic attestation of the input file or environment.

## Alternatives In The Same API

`order_point_cloud` also implements input order, lexicographic order, raw-AABB
Morton, equal-depth Hilbert, raw-AABB compact Hilbert, PCA-frame compact
Hilbert, and robust-frame Morton. This common facade makes configurations
comparable, but differences in domain, frame, curve, and refinement must still
be considered when interpreting measurements.

## Complexity

With dimension, start count, iteration limits, bit budget, and refinement
windows fixed as in this implementation, the curve sort and repeated
distance/subset sorts give an overall upper-order cost of `O(N log N)` and
`O(N)` auxiliary storage. This statement treats the fixed robust-search bounds
as constants; it does not imply small constants. The recorded timings show that
the robust fit is materially more expensive than simpler baselines at the
tested sizes.

## What Is And Is Not Claimed

RCH combines established robust-scatter, principal-frame, compact-Hilbert, and
local-search ideas into a specified and tested pipeline. The implementation
does not claim a new MCD estimator, a new Hilbert curve, globally optimal bit
allocation for locality, an optimal path, full affine equivariance, or
bit-identical floating-point diagnostics on every platform.
