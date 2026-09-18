# ============================================================================
# mrcd_reference.R - rrcov CovMrcd oracle helper.
#
# References:
#   - Boudt, Rousseeuw, Vanduffel and Verdonck, The Minimum Regularized
#     Covariance Determinant Estimator, 2019, DOI: 10.1007/s11222-019-09869-x.
#   - Todorov and Filzmoser, An Object-Oriented Framework for Robust
#     Multivariate Analysis, 2009, DOI: 10.18637/jss.v032.i03.
#   - R Core Team and rrcov authors, CovMrcd R documentation, 2026.
#
# Oracle usage:
#   - mrcd_reference() is the R reference for rch::robust::mrcd()
#     implemented in include/rch/robust/mrcd.hpp.
#   - generate_oracles.R writes its center/scatter/rho output to
#     tests/oracle/mrcd_oracles.jsonl when a second output path is supplied.
#   - tests/oracle/test_mrcd_oracle.cpp reads that JSONL file and compares C++
#     MRCD output against these R-backed fixtures.
# ============================================================================

# Mirror robustbase's \(h(\alpha,n,p)\) formula for MRCD oracle metadata.
h_alpha_n_mrcd <- function(alpha, n, p) {
  if (!is.numeric(alpha) || length(alpha) != 1L || !is.finite(alpha) ||
      alpha < 0.5 || alpha > 1.0) {
    stop("alpha must be a finite scalar in [0.5, 1]", call. = FALSE)
  }
  if (!is.numeric(n) || length(n) != 1L || !is.finite(n) || n < 1L ||
      n != floor(n)) {
    stop("n must be a positive integer scalar", call. = FALSE)
  }
  if (!is.numeric(p) || length(p) != 1L || !is.finite(p) || p < 1L ||
      p != floor(p) || p > n) {
    stop("p must be a positive integer scalar not exceeding n", call. = FALSE)
  }
  n2 <- floor((n + p + 1) / 2)
  floor(2 * n2 - n + 2 * alpha * (n - n2))
}

# Run MRCD and return robust center, regularized scatter, and \(\rho\).
mrcd_reference <- function(x, alpha = 0.5) {
  if (!requireNamespace("rrcov", quietly = TRUE)) {
    stop("rrcov package is required to generate CovMrcd oracles", call. = FALSE)
  }
  fit <- rrcov::CovMrcd(x, alpha = alpha)
  center <- as.numeric(rrcov::getCenter(fit))
  scatter <- rrcov::getCov(fit)
  rho <- if (.hasSlot(fit, "rho")) as.numeric(fit@rho) else NA_real_
  list(center = center, scatter = scatter, rho = rho)
}
