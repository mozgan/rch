# Experiments And Interpretation

The repository evaluates RCH as a point-ordering component. It does not claim
that an ordering alone improves a complete scientific application. This page
separates the recorded observations from broader conclusions that the data do
not support.

## Evaluation goals

The experiment matrix asks:

1. Does RCH shorten adjacent-point steps on the tested clean anisotropic
   synthetic clouds?
2. Does the robust-frame branch preserve the relative order of clean inliers
   when specified contamination is added?
3. How do alternative frames, bit rules, and optional local refinement affect
   the result?
4. What runtime, process peak RSS, recall, block-read, and cache-counter costs
   are observed under the recorded measurement boundaries?
5. Do seven fixed real inputs, including four LiDAR inputs, repeat the synthetic
   MIAD result, and do query and total workflow times improve?

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

C0 uses uniform depth, C1 uses monotone-half allocation, C2 uses covering
occupancy, and C3 uses core occupancy. C4 uses core-derived resolution in a
covering domain. C3 is the default RCH rule. See
[bit allocation](algorithm.md#stage-4-allocate-axis-bits) for the definitions.
Refinement is off in the main comparisons; the `all` arm applies the same
local search to non-input internal methods.

## Metrics

Mean inter-adjacent distance (MIAD) is

$$
\operatorname{MIAD}(\pi)
=\frac{1}{N-1}\sum_{r=1}^{N-1}
\lVert p_{\pi(r)}-p_{\pi(r-1)}\rVert_2.
$$

The formula above uses zero-based point indices and `N >= 2`; the implementation
returns MIAD zero for empty and singleton inputs. Lower MIAD means shorter
consecutive steps. It does not by itself establish faster queries, smaller
compressed files, or fewer cache misses.

Kendall correlation is computed on the clean inliers' relative order before and
after contamination. Larger values mean greater stability for that experiment;
they do not prove contamination invariance.

The locality ratios, exact-neighbor recall, block-read statistics, ordering
time, process peak RSS, and optional hardware counters answer different
questions. A method can lead one metric and lose another.

## Results

The locality comparison uses 80 independent clouds from four anisotropic
Gaussian groups. Stability uses 220 independent clouds from eleven geometry
groups. Each group has 20 clouds. Locality averages rule-specific
paired differences within each cloud. Stability averages rules and contamination
conditions within each cloud. Bootstrap sampling keeps each cloud together
within its geometry group.

| Comparison | Independent clouds | Median RCH-minus-reference difference |
| --- | ---: | ---: |
| MIAD vs isotropic Hilbert | 80 | -0.220 |
| MIAD vs Morton | 80 | -0.125 |
| MIAD vs CGAL | 80 | -0.658 |
| Kendall stability vs A5 | 220 | +0.150 |

Use `make analyze-independent` to regenerate the independent-cloud summaries
from matching measurements. See [Reproducibility](reproducibility.md) for
output generation and validation.
These results apply to the tested geometry groups, not to every point cloud.

The real-data evaluation uses seven fixed inputs: Bunny, Armadillo, Dragon,
Cameron Peak, Santiam River, Long Island, and Southwest Florida. The first
three are reconstruction vertex sets; the other four are LiDAR inputs.
Default RCH/C3 has higher MIAD than isotropic Hilbert in six cases. RCH/C4
has lower MIAD than isotropic Hilbert on the four LiDAR inputs but higher
MIAD on the reconstructions.
These per-input results do not establish a general ranking of the bit rules.

Query results depend on the input and access path. In the continuous
storage/query workflow, the median paired RCH/C3-minus-isotropic-Hilbert
total-time difference is positive in all 21 tested settings. The measured
query savings do not offset preparation cost in those workloads. See the
[workflow guide](application-workflow.md) for the timing boundaries.

## Controls and failure regimes

- Matched-grid controls vary depth and origin while holding physical widths
  fixed. They test center and axes together, using the complete contamination
  design; they are not a deployable grid policy.
- A clean shared-domain control does not show a clear median MIAD benefit
  from robust frame fitting alone.
- Clamp-on/off controls show an all-point path-length cost, conditional on
  their extended encoder. They do not measure total native C3 clipping loss.
- The geometry map and fixed-budget C1 controls show that shape and bit
  distribution matter. They do not provide a validated selector for unseen inputs.
- Refinement uses the same search on both internal methods. It changes some
  rankings and adds cost; a refined order need not remain key-sorted.

See [Build workflows](build-workflows.md) for the corresponding targets.

## Measurement Boundaries

- Internal ordering time is the median of repeated ordering calls after input
  parsing; metric computation is excluded.
- CGAL time includes child-process startup and I/O, so it is not directly
  commensurate with the internal call boundary.
- Peak RSS is the process high-water mark, not incremental library allocation.
- Cache counters come from a separate deterministic block-read probe and are
  valid only when `perf_status` is `ok`.
- Cost decomposition uses 1,024, 4,096 and 16,384 points. Full-input timings
  cover the seven real inputs. These are finite measurements, not an
  asymptotic scaling law.
- Repeated queries and timing runs on the seven fixed real inputs do not
  create independent scenes or a representative population of applications.

## Where The Evidence Lives

- runlists: `experiments/runlists/`;
- algorithm and sweep configuration: `experiments/configs/`;
- generated row-level measurements: `experiments/outputs/` (ignored by Git);
- generated tables, statistics, and figures: `analysis/generated/`;
- generation code: `analysis/scripts/`;
- stored-result checks: `make validate-extended-benchmarks` and `make test-integration`; `make measurement-diagnostics` provides descriptive refinement and key-sharing reports.

These are output locations, not files guaranteed to be present in a fresh clone.
Many generated tables have JSON or CSV forms; application studies also provide
source-linked CSV summaries so values can be inspected without parsing LaTeX.

## Safe Conclusions

The results support conditional locality and contamination-stability benefits
on the selected synthetic groups, with substantial preparation cost. The
seven-input evaluation shows that these benefits do not establish lower MIAD
on every real input or faster complete storage/query workflows.

The evidence does not support saying that RCH is universally more local, more
robust, faster, more memory-efficient, cache-optimal, or better for an
unmeasured application. A new use case should define its operational metric,
run paired comparisons on representative data, preserve dependence in the
analysis, and report unfavorable outcomes.
