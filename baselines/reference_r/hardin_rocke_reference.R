# ============================================================================
# hardin_rocke_reference.R - MAINT.Data qHardRoqF fixture.
#
# References:
#   - Hardin and Rocke, The Distribution of Robust Distances, 2005,
#     DOI: 10.1198/106186005X77685.
#   - Irpino and Verde, MAINT.Data qHardRoqF R documentation, 2026.
#
# Oracle usage:
#   - hardin_rocke_reference() is the R reference for
#     rch::robust::hardin_rocke_f_cutoff(), implemented in
#     include/rch/robust/hardin_rocke_cutoff.hpp.
#   - When run with one output path, this script writes
#     tests/oracle/hardin_rocke_cutoffs.jsonl-style cutoff fixtures.
#   - tests/oracle/test_det_mcd_oracle.cpp reads hardin_rocke_cutoffs.jsonl and
#     compares the C++ cutoff helper against these R-backed values.
# ============================================================================

# Return the scaled-\(F\) cutoff for raw-MCD squared robust distances.
hardin_rocke_reference <- function(p, nobs, nvar, h, adj = TRUE) {
  if (!requireNamespace("MAINT.Data", quietly = TRUE)) {
    stop("MAINT.Data package is required to generate qHardRoqF fixtures", call. = FALSE)
  }
  MAINT.Data::qHardRoqF(p = p, nobs = nobs, nvar = nvar, h = h, adj = adj)
}

# True when this file is loaded for helper functions instead of executed.
.hardin_rocke_reference_loaded_by_source <- any(vapply(
  sys.calls(),
  function(call) identical(call[[1L]], quote(source)),
  logical(1)
))

is_sourced <- function() {
  .hardin_rocke_reference_loaded_by_source
}

# When invoked as a script, emit fixed \(p=0.975\) cutoff fixtures as JSONL.
if (!is_sourced()) {
  args <- commandArgs(trailingOnly = TRUE)
  if (length(args) >= 1) {
    output_path <- args[[1]]
    rows <- list(
      list(case = "n50_p3_h27", p = 0.975, nobs = 50, nvar = 3, h = 27),
      list(case = "n100_p3_h52", p = 0.975, nobs = 100, nvar = 3, h = 52),
      list(case = "n200_p3_h102", p = 0.975, nobs = 200, nvar = 3, h = 102)
    )
    lines <- vapply(rows, function(row) {
      cutoff <- hardin_rocke_reference(row$p, row$nobs, row$nvar, row$h, TRUE)
      paste0(
        '{"case":"', row$case,
        '","p":', formatC(row$p, digits = 17, format = "fg", flag = "#"),
        ',"nobs":', row$nobs,
        ',"nvar":', row$nvar,
        ',"h":', row$h,
        ',"adj":true',
        ',"cutoff":', formatC(cutoff, digits = 17, format = "fg", flag = "#"),
        "}"
      )
    }, character(1))
    writeLines(lines, output_path)
  }
}
