# ============================================================================
# generate_oracles.R - create DetMCD, MRCD, and OGK JSONL oracle files.
#
# References:
#   - R Core Team, R: A Language and Environment for Statistical Computing,
#     2026.
#   - Rousseeuw and Van Driessen, A Fast Algorithm for the Minimum Covariance
#     Determinant Estimator, 1999, DOI: 10.1080/00401706.1999.10485670.
#   - Maronna and Zamar, Robust Estimates of Location and Dispersion of
#     High-Dimensional Datasets, 2002, DOI: 10.1198/004017002188618509.
#   - Boudt, Rousseeuw, Vanduffel and Verdonck, The Minimum Regularized
#     Covariance Determinant Estimator, 2019, DOI: 10.1007/s11222-019-09869-x.
#
# Oracle usage:
#   - This script generates JSONL fixtures consumed by the C++ oracle tests.
#   - Argument 1 writes DetMCD rows for tests/oracle/test_det_mcd_oracle.cpp.
#     Default path: tests/oracle/det_mcd_oracles.jsonl.
#   - Argument 2 writes MRCD rows for tests/oracle/test_mrcd_oracle.cpp.
#     Typical path: tests/oracle/mrcd_oracles.jsonl.
#   - Argument 3 writes OGK rows for tests/oracle/test_ogk_oracle.cpp.
#     Typical path: tests/oracle/ogk_oracles.jsonl.
#   - tests/integration/test_reference_r_baselines.py also runs this script in a
#     temporary directory to smoke-test JSON validity without updating fixtures.
# ============================================================================

reference_r_dir <- function() {
  frames <- sys.frames()
  for (frame in rev(frames)) {
    if (!is.null(frame$ofile)) {
      return(dirname(normalizePath(frame$ofile, mustWork = TRUE)))
    }
  }

  file_args <- grep("^--file=", commandArgs(trailingOnly = FALSE), value = TRUE)
  if (length(file_args) > 0L) {
    return(dirname(normalizePath(sub("^--file=", "", file_args[[1L]]), mustWork = TRUE)))
  }

  getwd()
}

source(file.path(reference_r_dir(), "covmcd_reference.R"))

# Format numeric scalars/vectors for strict JSON; R's NA maps to JSON null.
format_number <- function(x) {
  if (!is.numeric(x)) {
    stop("format_number expects numeric input", call. = FALSE)
  }
  if (any(is.infinite(x))) {
    stop("cannot encode infinite numeric value as strict JSON", call. = FALSE)
  }
  out <- formatC(x, digits = 17, format = "fg", flag = "#")
  out[is.na(x)] <- "null"
  out
}

json_array <- function(x) {
  paste0("[", paste(format_number(x), collapse = ","), "]")
}

# Emit a JSON matrix as an array of numeric rows.
json_matrix <- function(x) {
  if (!is.matrix(x)) {
    stop("json_matrix expects a matrix", call. = FALSE)
  }
  if (nrow(x) == 0L) {
    return("[]")
  }
  rows <- apply(x, 1, json_array)
  paste0("[", paste(rows, collapse = ","), "]")
}

# Escape the minimal JSON string characters used by generated case names.
json_string <- function(x) {
  if (!is.character(x) || length(x) != 1L || is.na(x)) {
    stop("json_string expects one non-missing string", call. = FALSE)
  }

  chars <- strsplit(x, "", fixed = TRUE)[[1L]]
  escaped <- vapply(chars, function(ch) {
    if (identical(ch, "\\")) {
      return("\\\\")
    }
    if (identical(ch, "\"")) {
      return("\\\"")
    }
    if (identical(ch, "\b")) {
      return("\\b")
    }
    if (identical(ch, "\f")) {
      return("\\f")
    }
    if (identical(ch, "\n")) {
      return("\\n")
    }
    if (identical(ch, "\r")) {
      return("\\r")
    }
    if (identical(ch, "\t")) {
      return("\\t")
    }

    code <- utf8ToInt(ch)
    if (length(code) == 1L && code < 0x20L) {
      return(sprintf("\\u%04x", code))
    }
    ch
  }, character(1), USE.NAMES = FALSE)

  paste0('"', paste(escaped, collapse = ""), '"')
}

# Convert one synthetic cloud and one reference estimator output to JSONL.
case_to_json_for <- function(reference_fn, case_name, n) {
  points <- make_covmcd_synthetic_cloud(n)
  reference <- reference_fn(points)
  h <- h_alpha_n(0.5, n, 3)
  fields <- c(
    paste0('"case":', json_string(case_name)),
    paste0('"n":', n),
    paste0('"h":', h),
    paste0('"points":', json_matrix(points)),
    paste0('"center":', json_array(reference$center)),
    paste0('"scatter":', json_matrix(reference$scatter))
  )
  if (!is.null(reference$rho)) {
    fields <- c(fields, paste0('"rho":', format_number(reference$rho)))
  }
  paste0("{", paste(fields, collapse = ","), "}")
}

# Canonical oracle sizes used by the C++ oracle tests.
cases <- list(
  synthetic_n50 = 50,
  synthetic_n100 = 100,
  synthetic_n200 = 200
)

# Write one JSONL file for a package-backed reference estimator.
write_oracle <- function(reference_fn, path) {
  if (is.na(path) || nchar(path) == 0L) {
    return(invisible(NULL))
  }
  lines <- Map(function(name, n) case_to_json_for(reference_fn, name, n), names(cases), cases)
  writeLines(unlist(lines, use.names = FALSE), path)
}

# True when this file is loaded for helper functions instead of executed.
.generate_oracles_loaded_by_source <- any(vapply(
  sys.calls(),
  function(call) identical(call[[1L]], quote(source)),
  logical(1)
))

is_sourced <- function() {
  .generate_oracles_loaded_by_source
}

if (!is_sourced()) {
  script_args <- commandArgs(trailingOnly = TRUE)
  det_mcd_path <- if (length(script_args) >= 1) script_args[[1]] else "tests/oracle/det_mcd_oracles.jsonl"
  mrcd_path <- if (length(script_args) >= 2) script_args[[2]] else NA_character_
  ogk_path <- if (length(script_args) >= 3) script_args[[3]] else NA_character_

  write_oracle(function(points) covmcd_reference(points), det_mcd_path)

  if (!is.na(mrcd_path)) {
    source(file.path(reference_r_dir(), "mrcd_reference.R"))
    write_oracle(function(points) mrcd_reference(points), mrcd_path)
  }

  if (!is.na(ogk_path)) {
    source(file.path(reference_r_dir(), "ogk_reference.R"))
    write_oracle(function(points) ogk_reference(points), ogk_path)
  }
}
