# ============================================================================
# covmcd_reference.R - robustbase covMcd oracle helper.
#
# References:
#   - Rousseeuw and Van Driessen, A Fast Algorithm for the Minimum Covariance
#     Determinant Estimator, 1999, DOI: 10.1080/00401706.1999.10485670.
#   - Hubert, Rousseeuw and Verdonck, A Deterministic Algorithm for Robust
#     Location and Scatter, 2012, DOI: 10.1080/10618600.2012.672100.
#   - R Core Team and robustbase authors, covMcd / h.alpha.n R documentation,
#     2026.
#
# Oracle usage:
#   - covmcd_reference() is the R reference for rch::robust::det_mcd()
#     implemented in include/rch/robust/det_mcd.hpp.
#   - generate_oracles.R writes its center/scatter/h output to
#     tests/oracle/det_mcd_oracles.jsonl.
#   - tests/oracle/test_det_mcd_oracle.cpp reads that JSONL file and compares
#     C++ DetMCD output against these R-backed fixtures.
#   - tests/integration/test_reference_r_baselines.py sources this file directly
#     to verify h_alpha_n() and the deterministic synthetic cloud.
# ============================================================================

# Return robustbase's MCD subset size
# \(h=\lfloor 2n_2-n+2\alpha(n-n_2)\rfloor\),
# where \(n_2=\lfloor(n+p+1)/2\rfloor\).
h_alpha_n <- function(alpha, n, p) {
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

# Build a deterministic inlier/outlier cloud for reproducible oracle rows.
make_covmcd_synthetic_cloud <- function(n, alpha = 0.5, p = 3) {
  h <- h_alpha_n(alpha, n, p)
  if (p != 3L) {
    stop("make_covmcd_synthetic_cloud currently supports p = 3", call. = FALSE)
  }
  x <- matrix(0, nrow = n, ncol = p)

  # First \(h\) rows form the candidate clean subset.
  for (i in seq_len(h)) {
    zero <- i - 1
    a <- (zero %% 9) - 4
    b <- ((zero %/% 3) %% 7) - 3
    c <- ((zero * 5) %% 11) - 5
    x[i, ] <- c(0.08 * a, 0.05 * b + 0.01 * a, 0.04 * c - 0.02 * b)
  }

  # Remaining rows are separated outliers.
  if (h < n) {
    for (i in (h + 1):n) {
      k <- i - h
      x[i, ] <- c(20 + k, -15 - (2 * k), 10 + (3 * k))
    }
  }
  x
}

# Run deterministic raw MCD and return the un-reweighted location/scatter.
covmcd_reference <- function(x, alpha = 0.5, maxcsteps = 200) {
  if (!requireNamespace("robustbase", quietly = TRUE)) {
    stop("robustbase package is required to generate covMcd oracles", call. = FALSE)
  }
  fit <- robustbase::covMcd(
    x,
    alpha = alpha,
    nsamp = "deterministic",
    raw.only = TRUE,
    use.correction = TRUE,
    maxcsteps = maxcsteps
  )
  center <- if (!is.null(fit$raw.center)) fit$raw.center else fit$center
  scatter <- if (!is.null(fit$raw.cov)) fit$raw.cov else fit$cov
  list(center = as.numeric(center), scatter = scatter)
}
