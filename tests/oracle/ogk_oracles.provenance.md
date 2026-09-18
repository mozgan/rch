# Provenance: `ogk_oracles.jsonl`

## Reference implementation

Expected `center` and `scatter` were produced with **robustbase 0.99.7** under
**R 4.1.2**, using the configuration that computes the *same estimator* as
`include/rch/robust/ogk.hpp`:

```r
library(robustbase)

# GK pairwise covariance driven by MAD rather than covGK's scaleTau2 default
madcov <- function(x, y, ...) (s_mad(x + y)^2 - s_mad(x - y)^2) / 4

g <- covOGK(X, sigmamu = s_mad, rcov = madcov, n.iter = 1)
g$center   # -> "center"
g$cov      # -> "scatter"  (raw OGK; NOT g$wcov, which is reweighted)
```

`X` is the `points` array of each record, unchanged.

## All three arguments are load-bearing

Getting any one of them wrong silently compares against a different estimator:

- **`rcov = madcov`.** `covOGK`'s signature is
  `covOGK(X, n.iter, sigmamu, rcov = covGK, ...)`, and `covGK(x, y, scalefn = scaleTau2)`
  takes its scale from `scalefn`, not from `sigmamu`. Because `sigmamu` binds to a *named*
  parameter it never reaches `covGK`. So plain `covOGK(X, sigmamu = s_mad)` is a **mixed**
  estimator — MAD marginal scales, but scaleTau2 pairwise covariances.
- **`n.iter = 1`.** robustbase defaults to `2`. `ogk.hpp` orthogonalizes once, i.e. it is
  Maronna & Zamar's OGK(1). (MZ define the estimator with *l* iterations and report no
  improvement beyond the second; that variant choice is a separate design question, not
  something this fixture decides.)
- **`g$cov`, not `g$wcov`.** `ogk.hpp` returns the raw estimate and performs no
  hard-rejection reweighting step.

## Why the earlier fixture needed a 0.6 tolerance

The previous values were generated with `covOGK(X, sigmamu = s_mad, n.iter = 2)` — verified
by re-running that exact configuration, which reproduces the old numbers to 1e-7/1e-8. That
hits both traps above, so the fixture described a different estimator from the one under
test, and `tol_scatter_rel` had to be widened to 0.6 to absorb the mismatch. At that width
the test could not detect a real regression.

## Residual disagreement, and why it is not zero

With the matched configuration the remaining differences are:

| quantity | agreement |
|---|---|
| `center` | ~5e-16 (machine precision) |
| `scatter` | ~3.0e-6 relative |

The scatter offset is fully accounted for: R's `mad()` uses the **rounded** constant
`1.4826`, whereas `median_mad.hpp` uses the exact `1/Phi^{-1}(0.75) = 1.4826022185056020`.
The OGK covariance scales as the square of that constant, so the predicted relative offset
is `(1.482602218505602 / 1.4826)^2 - 1 = 2.9927e-06`, matching the observed 2.993e-06.
Location is invariant to the constant (it cancels between the marginal scales `d` and the
projected medians), which is why the center agrees to machine precision.

`tol_scatter_rel` is therefore set to `1e-5` — comfortably above that known 3e-6 floor and
five orders of magnitude tighter than before.

## References

- Maronna, R. A. & Zamar, R. H. (2002), "Robust Estimates of Location and Dispersion for
  High-Dimensional Datasets", *Technometrics* 44(4), doi:10.1198/004017002188618509.
- Gnanadesikan, R. & Kettenring, J. R. (1972), "Robust Estimates, Residuals, and Outlier
  Detection with Multiresponse Data", *Biometrics* 28(1).
- Rousseeuw, P. J. & Croux, C. (1993), "Alternatives to the Median Absolute Deviation",
  *JASA* 88(424), doi:10.1080/01621459.1993.10476408.
- robustbase 0.99.7, `covOGK` / `covGK` / `s_mad` source.
