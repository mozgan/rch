#pragma once

// ----------------------------------------------------------------------------
// fallback_policy.hpp
//
// References:
//   - Peter J. Rousseeuw, Katrien Van Driessen, "A Fast Algorithm for the
//     Minimum Covariance Determinant Estimator", 1999, doi:10.1080/00401706.1999.10485670.
//   - Johanna Hardin, David M. Rocke, "The Distribution of Robust Distances",
//     2005, doi:10.1198/106186005X77685.
//
// Purpose:
//   Compact status labels for robust estimators that may reject small,
//   rank-deficient, or regularized inputs.
// ----------------------------------------------------------------------------

#include <string_view>

namespace rch::robust {

enum class FallbackPolicy {
    none,
    // Too few observations for a stable robust scatter estimate.
    disabled_small_n,
    // Non-finite or rank-deficient data prevented a robust estimate.
    disabled_rank_deficient,
    // A ridge was required before using chi-square-style distances.
    chi2_regularized,
    // Hardin-Rocke finite-sample adjusted F cutoff was used.
    hr_adjusted_f,
};

// Stable text representation for logs, fixtures, and CLI output.
[[nodiscard]] constexpr auto to_string(const FallbackPolicy policy) noexcept -> std::string_view {
    switch (policy) {
    case FallbackPolicy::none:
        return "none";
    case FallbackPolicy::disabled_small_n:
        return "disabled_small_n";
    case FallbackPolicy::disabled_rank_deficient:
        return "disabled_rank_deficient";
    case FallbackPolicy::chi2_regularized:
        return "chi2_regularized";
    case FallbackPolicy::hr_adjusted_f:
        return "hr_adjusted_f";
    default:
        return "unknown";
    }
}

} // namespace rch::robust
