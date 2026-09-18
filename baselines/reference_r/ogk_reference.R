# ============================================================================
# ogk_reference.R - robustbase covOGK oracle helper.
#
# References:
#   - Gnanadesikan and Kettenring, Robust Estimates, Residuals, and Outlier
#     Detection with Multiresponse Data, 1972.
#   - Maronna and Zamar, Robust Estimates of Location and Dispersion of
#     High-Dimensional Datasets, 2002, DOI: 10.1198/004017002188618509.
#   - R Core Team and robustbase authors, covOGK R documentation, 2026.
#
# Oracle usage:
#   - ogk_reference() is the R reference for rch::robust::ogk()
#     implemented in include/rch/robust/ogk.hpp.
#   - generate_oracles.R writes its center/scatter output to
#     tests/oracle/ogk_oracles.jsonl when a third output path is supplied.
#   - tests/oracle/test_ogk_oracle.cpp reads that JSONL file and compares C++
#     OGK output against these R-backed fixtures.
# ============================================================================

# GK pairwise covariance driven by MAD.
#
# This must be passed to covOGK() explicitly. covOGK()'s signature is
#   covOGK(X, n.iter, sigmamu, rcov = covGK, ...)
# and covGK(x, y, scalefn = scaleTau2) takes its scale from `scalefn`, not from
# `sigmamu`. Because `sigmamu` binds to a *named* parameter of covOGK it never
# reaches covGK, so covOGK(X, sigmamu = s_mad) silently yields a MIXED estimator:
# MAD marginal scales but scaleTau2 pairwise covariances.
ogk_mad_covariance <- function(x, y, ...) {
  (robustbase::s_mad(x + y)^2 - robustbase::s_mad(x - y)^2) / 4
}

# Reference for rch::robust::ogk(): MAD-based OGK(1), raw (no reweighting).
#
# The three arguments below all have to match include/rch/robust/ogk.hpp, and
# getting any one of them wrong compares against a different estimator:
#
#   * rcov    - see ogk_mad_covariance() above.
#   * n.iter  - covOGK() defaults to 2. ogk.hpp orthogonalizes once. Maronna &
#               Zamar (2002, Sec. 2) define the base estimate by steps 1-4 and
#               write "OGK(l) henceforth denotes the OGK estimate with l
#               iterations, so that OGK(1) corresponds to the initial estimate
#               (4)", so OGK(1) is a named member of the family, not a shortcut.
#   * $cov    - the raw estimate. ogk.hpp applies no hard-rejection reweighting
#               step, so $wcov would be the wrong slot.
#
# Note that rrcov::CovOgk()@raw.cov is NOT directly comparable: rrcov rescales
# the raw covariance by \(c_\delta=\operatorname{median}(d^2)/\chi^2_p(0.5)\)
# to make it consistent at the normal model, which covOGK() and ogk.hpp do not.
# The shapes agree to ~1e-15; only that scalar normalization differs.
ogk_reference <- function(x) {
  if (!requireNamespace("robustbase", quietly = TRUE)) {
    stop(
      "robustbase package is required to generate covOGK oracles",
      call. = FALSE
    )
  }
  fit <- robustbase::covOGK(
    x,
    n.iter = 1L,
    sigmamu = robustbase::s_mad,
    rcov = ogk_mad_covariance
  )
  center <- as.numeric(fit$center)
  scatter <- fit$cov
  list(center = center, scatter = scatter)
}
