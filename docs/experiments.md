# Experiments And Interpretation

The repository evaluates RCH as a point-ordering component. It does not claim
that an ordering alone improves a complete scientific application. This page
separates the recorded observations from broader conclusions that the data do
not support.

## Questions In The Recorded Study

The experiment matrix asks:

1. Does RCH shorten adjacent-point steps on the tested clean anisotropic
   synthetic clouds?
2. Does the robust-frame branch preserve the relative order of clean inliers
   when specified contamination is added?
3. How do alternative frames, bit rules, and optional local refinement affect
   the result?
4. What runtime, process peak RSS, recall, block-read, and cache-counter costs
   are observed under the recorded measurement boundaries?
5. Do the two larger Stanford reconstruction vertex sets repeat the synthetic
   MIAD result?

## Methods

The internal methods are identified as A0 through A6 in
`experiments/configs/algorithms/`:

| ID | Method |
| --- | --- |
| A0 | input order |
| A1 | lexicographic |
| A2 | Morton |
| A3 | isotropic Hilbert |
| A4 | compact Hilbert on the raw AABB |
| A5 | sample-covariance-frame compact Hilbert |
| A5b | robust-frame Morton |
| A6 | RCH |

A7 is the optional external CGAL `spatial_sort` adapter. MRCD and OGK are
recorded as robust-estimator variants of A6.

The primary bit rules are C0 through C4. C3, robust-core occupancy, is the
default RCH rule. Refinement is off in the primary comparisons; the `all` arm
applies the same local search to non-input internal methods.

## Metrics

Mean inter-adjacent distance (MIAD) is

$$
\operatorname{MIAD}(\pi)
=\frac{1}{N-1}\sum_{r=1}^{N-1}
\lVert p_{\pi(r)}-p_{\pi(r-1)}\rVert_2.
$$

Lower MIAD means shorter consecutive steps. It is not a query-time, compression,
or cache theorem.

Kendall correlation is computed on the clean inliers' relative order before and
after contamination. Larger values mean greater stability for that experiment;
they do not prove contamination invariance.

The locality ratios, exact-neighbor recall, block-read statistics, ordering
time, process peak RSS, and optional hardware counters answer different
questions. A method can lead one metric and lose another.

## Recorded Outcomes

The primary refinement-off summaries generated from the stored matrix are:

| Comparison | Pairs | RCH median | Baseline median | Median paired difference |
| --- | ---: | ---: | ---: | ---: |
| MIAD vs isotropic Hilbert | 30 | 1.283 | 1.582 | -0.244 |
| MIAD vs Morton | 30 | 1.283 | 1.395 | -0.129 |
| MIAD vs CGAL | 30 | 1.283 | 2.122 | -0.695 |
| Kendall stability vs A5 | 420 | 0.556 | 0.388 | +0.145 |

These configurations reuse base clouds, rules, contamination levels, and in
some generators sampling locations. They are not independent replicates. The
five-seed blocked sign-flip sensitivity analysis reports nominal one-sided
`0.03125` and Holm-adjusted `0.09375` for the three clean MIAD comparisons; it
does not establish significance at 0.05 after adjustment.

On Bunny and Armadillo, isotropic Hilbert has lower MIAD in all ten
dataset-by-RCH-rule comparisons. In the reported four-method synthetic cost
summary, RCH has the highest mean ordering time and process peak RSS. These
negative and cost results are part of the evidence, not exceptions to hide.

## Measurement Boundaries

- Internal ordering time is the median of repeated ordering calls after input
  parsing; metric computation is excluded.
- CGAL time includes child-process startup and I/O, so it is not directly
  commensurate with the internal call boundary.
- Peak RSS is the process high-water mark, not incremental library allocation.
- Cache counters come from a separate deterministic block-read probe and are
  valid only when `perf_status` is `ok`.
- The three recorded runtime sizes describe finite observations and do not
  establish an asymptotic law.
- Bunny and Armadillo are reconstruction geometry checks, not a representative
  scientific-workflow sample.

## Where The Evidence Lives

- runlists: `experiments/runlists/`;
- algorithm and sweep configuration: `experiments/configs/`;
- row-level recorded results: `experiments/outputs/`;
- generated tables, statistics, and figures: `analysis/generated/`;
- generation code: `analysis/scripts/`;
- claim checks: `paper/review/verify_claims.py` and later review-round checks.

Generated tables include JSON and CSV forms so values can be inspected without
parsing LaTeX.

## Safe Conclusions

The evidence supports saying that RCH improved the specified synthetic MIAD and
contamination-stability comparisons in much of the recorded matrix, at a
measured cost. It also supports saying that this advantage did not transfer to
the two reconstruction MIAD checks.

The evidence does not support saying that RCH is universally more local, more
robust, faster, more memory-efficient, cache-optimal, or better for an
unmeasured application. A new use case should define its operational metric,
run paired comparisons on representative data, preserve dependence in the
analysis, and report unfavorable outcomes.
