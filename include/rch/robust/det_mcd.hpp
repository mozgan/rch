#pragma once

// ----------------------------------------------------------------------------
// det_mcd.hpp - DetMCD-style deterministic covariance estimator.
//
// References:
//   - Mia Hubert, Peter J. Rousseeuw, Tim Verdonck, "A Deterministic Algorithm
//     for Robust Location and Scatter", 2012, doi:10.1080/10618600.2012.672100.
//   - Peter J. Rousseeuw, Katrien Van Driessen, "A Fast Algorithm for the
//     Minimum Covariance Determinant Estimator", 1999, doi:10.1080/00401706.1999.10485670.
//   - Johanna Hardin, David M. Rocke, "The Distribution of Robust Distances",
//     2005, doi:10.1198/106186005X77685.
//
// Algorithm:
//   1. Choose \(h\) from \(n,p,\alpha\), with \(h \ge \lfloor(n+p+1)/2\rfloor\).
//   2. Reject non-finite or rank-deficient samples before inversion.
//   3. Build deterministic starts from robust marginal transforms and OGK.
//   4. Run C-steps and keep the candidate with minimal \(\det(S_H)\).
//   5. Apply MCD consistency/small-sample factors and optional HR cutoff.
// ----------------------------------------------------------------------------

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <limits>
#include <optional>
#include <span>
#include <vector>

#include "rch/core/matrix3.hpp"
#include "rch/frames/eigen3x3.hpp"
#include "rch/robust/c_step.hpp"
#include "rch/robust/fallback_policy.hpp"
#include "rch/robust/hardin_rocke_cutoff.hpp"
#include "rch/robust/initial_estimators.hpp"
#include "rch/robust/mcd_correction.hpp"
#include "rch/robust/median_mad.hpp"

namespace rch::robust {

inline constexpr std::size_t kDetMcdDimension = 3U;
inline constexpr std::size_t kDetMcdRecommendedSmallN = 5U * kDetMcdDimension;
inline constexpr double kAdaptiveMcdAlphaMin = 0.50;
inline constexpr double kAdaptiveMcdAlphaMax = 0.90;
inline constexpr double kAdaptiveMcdAlphaEpsSlope = 1.5;
inline constexpr double kAdaptiveMcdOutlierZPilot = 5.2;
inline constexpr double kAdaptiveMcdScaleFloor = 1.0e-12;
inline constexpr double kDefaultDetMcdRankRelativeTolerance = 1.0e-12;

struct DetMcdOptions {
    // Trimming parameter; \(\alpha=0.5\) gives maximal-breakdown MCD.
    double alpha{0.5};
    std::size_t maxcsteps{200U};
    std::size_t min_n{kDetMcdRecommendedSmallN};
    double rank_relative_tolerance{1.0e-12};
    bool compute_hr_cutoff{true};
    // Rescale the h-subset covariance into the raw MCD scatter, matching
    // robustbase covMcd(): consistency factor x finite-sample correction.
    // Disable only to inspect the uncorrected h-subset covariance.
    bool apply_consistency_correction{true};
    bool apply_small_sample_correction{true};
};

struct DetMcdResult {
    // Explains whether a robust estimate was produced or why it was skipped.
    FallbackPolicy policy{FallbackPolicy::none};
    rch::core::Vec3<double> center{};
    rch::core::Matrix3<double> scatter{};
    std::vector<std::size_t> subset_indices{};
    double determinant{};
    double cutoff{};
    // Multiplier applied to the h-subset covariance to obtain `scatter`
    // (c_alpha x finite-sample factor); 1.0 when no correction was applied.
    double scatter_correction{1.0};
    std::size_t h{};
    std::size_t start_index{};
    std::size_t cstep_iterations{};
    bool converged{};
    bool used_regularization{};
};

struct AdaptiveMcdPilot {
    // Pilot contamination estimate used by callers that choose alpha adaptively.
    double eps_hat{};
    double alpha{kAdaptiveMcdAlphaMax};
    std::size_t h{};
};

[[nodiscard]] inline auto mcd_h_size(
    const std::size_t n, const std::size_t p = kDetMcdDimension, const double alpha = 0.5
) noexcept -> std::size_t {
    // robustbase-style \(h(\alpha)=\lfloor 2n_2-n+2\alpha(n-n_2)\rfloor\).
    const double sanitized_alpha = std::isfinite(alpha) ? std::clamp(alpha, 0.5, 1.0) : 0.5;
    const std::size_t n2 = (n + p + 1U) / 2U;
    const double n_d = static_cast<double>(n);
    const double n2_d = static_cast<double>(n2);
    const double raw = (2.0 * n2_d) - n_d + (2.0 * sanitized_alpha * (n_d - n2_d));
    const double clamped = std::clamp(std::floor(raw), 0.0, n_d);
    return static_cast<std::size_t>(clamped);
}

[[nodiscard]] inline auto
componentwise_lower_median_point(const std::span<const rch::core::Vec3<double>> points)
    -> rch::core::Vec3<double> {
    // HRV use lower medians for deterministic pilot ordering.
    rch::core::Vec3<double> center{};
    for (std::size_t axis = 0U; axis < kDetMcdDimension; ++axis) {
        auto values = component_values(points, axis);
        center[axis] = lower_median(std::move(values)).value_or(0.0);
    }
    return center;
}

[[nodiscard]] inline auto adaptive_mcd_pilot(const std::span<const rch::core::Vec3<double>> points)
    -> AdaptiveMcdPilot {
    // Estimate gross outlier fraction from robust radial distances.
    AdaptiveMcdPilot pilot{};
    if (points.empty()) {
        pilot.alpha = kAdaptiveMcdAlphaMin;
        return pilot;
    }

    const auto center = componentwise_lower_median_point(points);
    std::array<double, kDetMcdDimension> scales{};
    for (std::size_t axis = 0U; axis < kDetMcdDimension; ++axis) {
        auto values = component_values(points, axis);
        scales[axis] = mad(std::span<const double>{values}, center[axis]);
    }
    std::ranges::sort(scales);
    const double scale_eff = std::max(scales[1], kAdaptiveMcdScaleFloor);

    std::size_t outliers = 0U;
    for (const auto& point : points) {
        const double dx = point[0] - center[0];
        const double dy = point[1] - center[1];
        const double dz = point[2] - center[2];
        const double radius = std::hypot(dx, dy, dz) / scale_eff;
        if (radius > kAdaptiveMcdOutlierZPilot) {
            ++outliers;
        }
    }

    pilot.eps_hat = static_cast<double>(outliers) / static_cast<double>(points.size());
    pilot.alpha = std::clamp(
        1.0 - (kAdaptiveMcdAlphaEpsSlope * pilot.eps_hat),
        kAdaptiveMcdAlphaMin,
        kAdaptiveMcdAlphaMax
    );
    pilot.h = mcd_h_size(points.size(), kDetMcdDimension, pilot.alpha);
    return pilot;
}

[[nodiscard]] inline auto scatter_max_abs_entry(const rch::core::Matrix3<double>& scatter) noexcept
    -> double {
    double scale = 0.0;
    for (std::size_t row = 0U; row < kDetMcdDimension; ++row) {
        for (std::size_t col = 0U; col < kDetMcdDimension; ++col) {
            scale = std::max(scale, std::abs(scatter(row, col)));
        }
    }
    return scale;
}

[[nodiscard]] inline auto sample_rank_deficient(
    const std::span<const rch::core::Vec3<double>> points, const double relative_tolerance
) noexcept -> bool {
    // A near-zero full-sample determinant means C-step inversions are unreliable.
    const double tolerance = (std::isfinite(relative_tolerance) && relative_tolerance >= 0.0)
                                 ? relative_tolerance
                                 : kDefaultDetMcdRankRelativeTolerance;
    const auto center = rch::core::mean3(points);
    const auto scatter = rch::core::covariance3(points, center);
    const double scale = scatter_max_abs_entry(scatter);
    if (!(scale > 0.0)) {
        return true;
    }
    rch::core::Matrix3<double> normalized{};
    for (std::size_t row = 0U; row < kDetMcdDimension; ++row) {
        for (std::size_t col = 0U; col < kDetMcdDimension; ++col) {
            normalized(row, col) = scatter(row, col) / scale;
        }
    }
    const auto eigen = rch::frames::cyclic_jacobi_eigen_symmetric3(normalized);
    if (!eigen.converged || !rch::core::is_finite(eigen.eigenvalues)) {
        return true;
    }
    const double determinant = rch::core::determinant(normalized);
    const double min_eigenvalue = *std::ranges::min_element(eigen.eigenvalues);
    const double determinant_floor = tolerance * tolerance * tolerance;
    return !(min_eigenvalue > tolerance && determinant > determinant_floor);
}

[[nodiscard]] inline auto
det_mcd(const std::span<const rch::core::Vec3<double>> points, const DetMcdOptions& options = {})
    -> DetMcdResult {
    // Deterministic MCD pipeline: starts -> C-steps -> correction -> cutoff.
    DetMcdResult result{};
    result.h = mcd_h_size(points.size(), kDetMcdDimension, options.alpha);

    if (points.size() < options.min_n || result.h <= kDetMcdDimension) {
        result.policy = FallbackPolicy::disabled_small_n;
        return result;
    }
    if (std::ranges::any_of(
            points, [](const auto& point) noexcept { return !rch::core::is_finite(point); }
        ) ||
        sample_rank_deficient(points, options.rank_relative_tolerance)) {
        result.policy = FallbackPolicy::disabled_rank_deficient;
        return result;
    }

    const auto starts = make_initial_estimates(points, result.h);
    const CStepRunner runner{};
    const CStepOptions cstep_options{
        result.h,
        options.maxcsteps,
        (std::isfinite(options.rank_relative_tolerance) && options.rank_relative_tolerance >= 0.0)
            ? options.rank_relative_tolerance
            : kDefaultDetMcdRankRelativeTolerance,
    };

    bool have_candidate = false;
    for (std::size_t start_index = 0U; start_index < starts.size(); ++start_index) {
        const auto& start = starts[start_index];
        auto candidate = runner.run(points, start.center, start.scatter, cstep_options);
        candidate.used_regularization = candidate.used_regularization || start.regularized;
        if (!have_candidate || candidate.determinant < result.determinant ||
            (rch::core::exactly_equal_for_tie_break(candidate.determinant, result.determinant) &&
             start_index < result.start_index)) {
            result.center = candidate.center;
            result.scatter = candidate.scatter;
            result.subset_indices = std::move(candidate.subset_indices);
            result.determinant = candidate.determinant;
            result.start_index = start_index;
            result.cstep_iterations = candidate.iterations;
            result.converged = candidate.converged;
            result.used_regularization = candidate.used_regularization;
            have_candidate = true;
        }
    }

    if (!have_candidate || result.subset_indices.empty()) {
        result.policy = FallbackPolicy::disabled_rank_deficient;
        return result;
    }

    // The C-step minimizes det(S_H); scaling every candidate by the same
    // positive constant leaves the argmin subset untouched, so the correction
    // is applied once, after the winning subset is fixed. This mirrors
    // robustbase, where raw.cov = calpha * correct * cov(H_MCD).
    if (options.apply_consistency_correction) {
        const auto correction = mcd_scatter_correction(
            points.size(),
            kDetMcdDimension,
            result.h,
            options.alpha,
            options.apply_small_sample_correction
        );
        if (correction.has_value()) {
            result.scatter_correction = *correction;
            result.scatter = result.scatter * (*correction);
            result.determinant = rch::core::determinant(result.scatter);
        }
    }

    if (result.used_regularization) {
        result.policy = FallbackPolicy::chi2_regularized;
    } else if (options.compute_hr_cutoff) {
        const auto cutoff = hardin_rocke_f_cutoff(points.size(), kDetMcdDimension, result.h, 0.975);
        if (cutoff.has_value()) {
            // Hardin & Rocke (2005) Eq. (3.2) is stated for d^2_{S*}, where S* is
            // the *raw* MCD scatter: the paper defines c by "S and c^{-1} S* [...]
            // are consistent estimators for Sigma".
            // `result.scatter` is the corrected scatter k * S*, and
            // d^2_{k S*} = d^2_{S*} / k, so the threshold that pairs with the
            // scatter actually returned here is the HR cutoff divided by k.
            // `hardin_rocke_f_cutoff` itself is left untouched -- it remains the
            // raw-scatter quantity pinned against the MAINT.Data oracle.
            result.cutoff =
                (result.scatter_correction > 0.0) ? (*cutoff / result.scatter_correction) : *cutoff;
            result.policy = FallbackPolicy::hr_adjusted_f;
        }
    }
    return result;
}

} // namespace rch::robust
