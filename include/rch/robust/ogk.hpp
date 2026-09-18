#pragma once

// ----------------------------------------------------------------------------
// ogk.hpp - Orthogonalized Gnanadesikan-Kettenring scatter estimator.
//
// References:
//   - Ricardo A. Maronna, Ruben H. Zamar, "Robust Estimates of Location and
//     Dispersion for High-Dimensional Datasets", 2002, doi:10.1198/004017002188618509.
//   - Ram Gnanadesikan, John R. Kettenring, "Robust Estimates, Residuals, and
//     Outlier Detection with Multiresponse Data", 1972.
//   - Peter J. Rousseeuw, Christophe Croux, "Alternatives to the Median Absolute
//     Deviation", 1993, doi:10.1080/01621459.1993.10476408.
//
// Algorithm:
//   1. Estimate marginal scales \(s_j\) by MAD and scale coordinates.
//   2. Estimate pairwise GK covariance by
//      \(\operatorname{cov}(x,y)=(s^2(x+y)-s^2(x-y))/4\).
//   3. Orthogonalize with an eigen decomposition of the pairwise matrix.
//   4. Re-estimate robust variances in eigen-coordinates and back-transform.
//
// Variant: this is MAD-based **OGK(1)** and the estimate is **raw**. Maronna & Zamar
// define the estimator with \(l\) orthogonalization iterations and report no gain past
// the second; robustbase's `covOGK` defaults to `n.iter = 2`. Steps 1-4 above run once.
// No hard-rejection reweighting step is applied either, so this corresponds to
// robustbase's `$cov`, not `$wcov`.
//
// Cross-checking against robustbase requires three arguments, and getting any one of
// them wrong silently compares against a different estimator:
//
//     madcov <- function(x, y, ...) (s_mad(x + y)^2 - s_mad(x - y)^2) / 4
//     covOGK(X, sigmamu = s_mad, rcov = madcov, n.iter = 1)$cov
//
// `rcov` is the subtle one: `covGK(x, y, scalefn = scaleTau2)` takes its scale from
// `scalefn`, and `sigmamu` binds to a named parameter of `covOGK`, so it never reaches
// `covGK`. Plain `covOGK(X, sigmamu = s_mad)` is therefore a mixed estimator with MAD
// marginals but scaleTau2 pairwise covariances. With all three set, agreement is ~5e-16
// on the center and ~3e-6 on the scatter, the latter being entirely R's rounded
// `mad()` constant 1.4826 versus the exact 1/Phi^{-1}(0.75) used here.
// See `tests/oracle/ogk_oracles.provenance.md`.
// ----------------------------------------------------------------------------

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <span>
#include <vector>

#include "rch/core/matrix3.hpp"
#include "rch/frames/eigen3x3.hpp"
#include "rch/robust/fallback_policy.hpp"
#include "rch/robust/median_mad.hpp"
#include "rch/robust/regularization.hpp"

namespace rch::robust {

inline constexpr std::size_t kOgkDimension = 3U;

struct OgkOptions {
    // Minimum accepted marginal robust scale.
    double scale_floor{1.0e-12};
    // Relative ridge used if the reconstructed scatter is not SPD.
    double regularization_relative_floor{1.0e-12};
};

// Final OGK location/scatter estimate and fallback status.
struct OgkResult {
    FallbackPolicy policy{FallbackPolicy::none};
    rch::core::Vec3<double> center{};
    rch::core::Matrix3<double> scatter{};
    bool used_regularization{};
};

namespace detail {

[[nodiscard]] inline auto
finite_points(const std::span<const rch::core::Vec3<double>> points) noexcept -> bool {
    // Reject NaN/Inf before robust scale and eigen computations.
    return std::ranges::all_of(points, [](const auto& point) noexcept {
        return rch::core::is_finite(point);
    });
}

[[nodiscard]] inline auto
axis_values(const std::span<const rch::core::Vec3<double>> points, const std::size_t axis)
    -> std::vector<double> {
    // Extract one coordinate axis.
    std::vector<double> values;
    values.reserve(points.size());
    for (const auto& point : points) {
        values.push_back(point[axis]);
    }
    return values;
}

[[nodiscard]] inline auto robust_location(std::vector<double> values) -> double {
    // Median location; empty input maps to zero.
    return median(std::move(values)).value_or(0.0);
}

[[nodiscard]] inline auto robust_scale(std::vector<double> values, const double scale_floor)
    -> double {
    // MAD scale with explicit zero result below the usable floor.
    const double center = robust_location(values);
    const double scale = mad(std::span<const double>{values}, center);
    if (!std::isfinite(scale) || scale <= scale_floor) {
        return 0.0;
    }
    return scale;
}

[[nodiscard]] inline auto transform_to_scaled_coordinates(
    const std::span<const rch::core::Vec3<double>> points, const rch::core::Vec3<double>& scales
) -> std::vector<rch::core::Vec3<double>> {
    // \(y_{ij}=x_{ij}/s_j\).
    std::vector<rch::core::Vec3<double>> scaled;
    scaled.reserve(points.size());
    for (const auto& point : points) {
        rch::core::Vec3<double> y{};
        for (std::size_t axis = 0U; axis < kOgkDimension; ++axis) {
            y[axis] = scales[axis] > 0.0 ? point[axis] / scales[axis] : 0.0;
        }
        scaled.push_back(y);
    }
    return scaled;
}

[[nodiscard]] inline auto pairwise_correlation_matrix(
    const std::span<const rch::core::Vec3<double>> scaled_points, const double scale_floor
) -> rch::core::Matrix3<double> {
    // GK pairwise covariance matrix with diagonal fixed to one.
    rch::core::Matrix3<double> matrix{};
    for (std::size_t axis = 0U; axis < kOgkDimension; ++axis) {
        matrix(axis, axis) = 1.0;
    }

    for (std::size_t row = 0U; row < kOgkDimension; ++row) {
        for (std::size_t col = row + 1U; col < kOgkDimension; ++col) {
            std::vector<double> sums;
            std::vector<double> diffs;
            sums.reserve(scaled_points.size());
            diffs.reserve(scaled_points.size());
            for (const auto& point : scaled_points) {
                sums.push_back(point[row] + point[col]);
                diffs.push_back(point[row] - point[col]);
            }
            const double sum_scale = robust_scale(std::move(sums), scale_floor);
            const double diff_scale = robust_scale(std::move(diffs), scale_floor);
            const double value = 0.25 * ((sum_scale * sum_scale) - (diff_scale * diff_scale));
            // Local guard with no counterpart in Maronna-Zamar or robustbase: on
            // MAD-scaled coordinates this entry is correlation-like, so |value| > 1
            // would make the pairwise matrix indefinite. Measured across the
            // regression corpus the clamp never binds; it exists to keep the
            // eigendecomposition in step 3 well posed on adversarial input.
            matrix(row, col) = std::clamp(value, -0.999, 0.999);
            matrix(col, row) = matrix(row, col);
        }
    }
    return matrix;
}

[[nodiscard]] inline auto project_to_eigenvectors(
    const std::span<const rch::core::Vec3<double>> scaled_points,
    const rch::core::Matrix3<double>& eigenvectors
) -> std::vector<rch::core::Vec3<double>> {
    // Project scaled observations into eigenvector coordinates.
    std::vector<rch::core::Vec3<double>> projected;
    projected.reserve(scaled_points.size());
    for (const auto& point : scaled_points) {
        rch::core::Vec3<double> v{};
        for (std::size_t axis = 0U; axis < kOgkDimension; ++axis) {
            v[axis] = (point[0] * eigenvectors(0U, axis)) + (point[1] * eigenvectors(1U, axis)) +
                      (point[2] * eigenvectors(2U, axis));
        }
        projected.push_back(v);
    }
    return projected;
}

[[nodiscard]] constexpr auto diagonal_matrix(const rch::core::Vec3<double>& diagonal) noexcept
    -> rch::core::Matrix3<double> {
    // Construct \(\operatorname{diag}(d_1,d_2,d_3)\).
    rch::core::Matrix3<double> matrix{};
    matrix(0U, 0U) = diagonal[0];
    matrix(1U, 1U) = diagonal[1];
    matrix(2U, 2U) = diagonal[2];
    return matrix;
}

[[nodiscard]] constexpr auto matrix_product(
    const rch::core::Matrix3<double>& lhs, const rch::core::Matrix3<double>& rhs
) noexcept -> rch::core::Matrix3<double> {
    // Fixed-size \(3\times3\) matrix product.
    rch::core::Matrix3<double> out{};
    for (std::size_t row = 0U; row < kOgkDimension; ++row) {
        for (std::size_t col = 0U; col < kOgkDimension; ++col) {
            for (std::size_t mid = 0U; mid < kOgkDimension; ++mid) {
                out(row, col) += lhs(row, mid) * rhs(mid, col);
            }
        }
    }
    return out;
}

[[nodiscard]] inline auto back_transform_center(
    const rch::core::Vec3<double>& projected_center,
    const rch::core::Matrix3<double>& eigenvectors,
    const rch::core::Vec3<double>& scales
) noexcept -> rch::core::Vec3<double> {
    // Back-transform location from eigen/scaled coordinates.
    const auto center_y = rch::core::multiply(eigenvectors, projected_center);
    return {scales[0] * center_y[0], scales[1] * center_y[1], scales[2] * center_y[2]};
}

[[nodiscard]] inline auto back_transform_scatter(
    const rch::core::Vec3<double>& variances,
    const rch::core::Matrix3<double>& eigenvectors,
    const rch::core::Vec3<double>& scales
) noexcept -> rch::core::Matrix3<double> {
    // Back-transform scatter as \(D E \Lambda E^T D\).
    const auto lambda = diagonal_matrix(variances);
    const auto scatter_y =
        matrix_product(matrix_product(eigenvectors, lambda), rch::core::transpose(eigenvectors));
    const auto scale_matrix = diagonal_matrix(scales);
    return matrix_product(matrix_product(scale_matrix, scatter_y), scale_matrix);
}

} // namespace detail

[[nodiscard]] inline auto
ogk(const std::span<const rch::core::Vec3<double>> points, const OgkOptions& options = {})
    -> OgkResult {
    // Full OGK estimator for fixed dimension \(p=3\).
    OgkResult result{};
    if (points.size() < 2U) {
        result.policy = FallbackPolicy::disabled_small_n;
        return result;
    }
    if (!detail::finite_points(points)) {
        result.policy = FallbackPolicy::disabled_rank_deficient;
        return result;
    }

    rch::core::Vec3<double> scales{};
    for (std::size_t axis = 0U; axis < kOgkDimension; ++axis) {
        scales[axis] = detail::robust_scale(detail::axis_values(points, axis), options.scale_floor);
    }
    if (std::ranges::any_of(scales, [](const double scale) noexcept { return scale <= 0.0; })) {
        result.policy = FallbackPolicy::disabled_rank_deficient;
        return result;
    }

    const auto scaled = detail::transform_to_scaled_coordinates(points, scales);
    const auto pairwise = detail::pairwise_correlation_matrix(
        std::span<const rch::core::Vec3<double>>{scaled}, options.scale_floor
    );
    const auto eigen = rch::frames::cyclic_jacobi_eigen_symmetric3(pairwise);
    if (!eigen.converged || !rch::core::is_finite(eigen.eigenvectors)) {
        result.policy = FallbackPolicy::disabled_rank_deficient;
        return result;
    }

    const auto projected = detail::project_to_eigenvectors(
        std::span<const rch::core::Vec3<double>>{scaled}, eigen.eigenvectors
    );
    rch::core::Vec3<double> projected_center{};
    rch::core::Vec3<double> projected_variances{};
    for (std::size_t axis = 0U; axis < kOgkDimension; ++axis) {
        auto values =
            detail::axis_values(std::span<const rch::core::Vec3<double>>{projected}, axis);
        projected_center[axis] = detail::robust_location(values);
        const double scale = detail::robust_scale(std::move(values), options.scale_floor);
        projected_variances[axis] = scale * scale;
    }

    result.center = detail::back_transform_center(projected_center, eigen.eigenvectors, scales);
    const auto raw_scatter =
        detail::back_transform_scatter(projected_variances, eigen.eigenvectors, scales);
    const auto regularized = regularize_spd(raw_scatter, options.regularization_relative_floor);
    result.scatter = regularized.scatter;
    result.used_regularization = regularized.applied;
    result.policy =
        result.used_regularization ? FallbackPolicy::chi2_regularized : FallbackPolicy::none;
    if (!rch::core::is_finite(result.center) || !rch::core::is_finite(result.scatter)) {
        result.policy = FallbackPolicy::disabled_rank_deficient;
    }
    return result;
}

} // namespace rch::robust
