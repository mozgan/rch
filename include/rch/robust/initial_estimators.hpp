#pragma once

// ----------------------------------------------------------------------------
// initial_estimators.hpp
//
// References:
//   - Mia Hubert, Peter J. Rousseeuw, Tim Verdonck, "A Deterministic Algorithm
//     for Robust Location and Scatter", 2012, doi:10.1080/10618600.2012.672100.
//   - Ricardo A. Maronna, Ruben H. Zamar, "Robust Estimates of Location and
//     Dispersion for High-Dimensional Datasets", 2002, doi:10.1198/004017002188618509.
//   - Peter J. Rousseeuw, Christophe Croux, "Alternatives to the Median Absolute
//     Deviation", 1993, doi:10.1080/01621459.1993.10476408.
//   - Rob J. Hyndman, Yanan Fan, "Sample Quantiles in Statistical Packages",
//     1996, doi:10.1080/00031305.1996.10473566.
//   - robustbase covMcd: <https://rdrr.io/cran/robustbase/man/covMcd.html>
//   - ISO C++ `std::hypot`: Euclidean norms without undue intermediate
//     overflow/underflow.
//
// Algorithm:
//   1. Standardize data with coordinatewise median and MAD.
//   2. Build deterministic starts using tanh, Spearman ranks, normal scores,
//      spatial signs, BACON-style central subset, and OGK.
//   3. Map standardized scatter \(R\) back by \(S=D R D\).
//   4. Regularize each start before it is sent to C-steps.
// ----------------------------------------------------------------------------

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <limits>
#include <span>
#include <string_view>
#include <vector>

#include "rch/core/matrix3.hpp"
#include "rch/robust/median_mad.hpp"
#include "rch/robust/regularization.hpp"

namespace rch::robust {

enum class InitialEstimatorKind {
    tanh,
    spearman,
    normal_score,
    spatial_sign,
    bacon,
    ogk,
};

// One deterministic start \((\mu_0,S_0)\) for a later MCD C-step chain.
struct InitialEstimate {
    InitialEstimatorKind kind{};
    std::string_view name{};
    rch::core::Vec3<double> center{};
    rch::core::Matrix3<double> scatter{};
    bool regularized{};
};

namespace detail {

struct RankItem {
    // Value/index pair used to assign deterministic average ranks.
    double value{};
    std::size_t index{};
};

[[nodiscard]] inline auto euclidean_norm(const rch::core::Vec3<double>& point) noexcept -> double {
    return std::hypot(point[0], point[1], point[2]);
}

[[nodiscard]] inline auto estimator_name(const InitialEstimatorKind kind) noexcept
    -> std::string_view {
    // Stable estimator names for fixtures and diagnostics.
    switch (kind) {
    case InitialEstimatorKind::tanh:
        return "tanh";
    case InitialEstimatorKind::spearman:
        return "spearman";
    case InitialEstimatorKind::normal_score:
        return "normal_score";
    case InitialEstimatorKind::spatial_sign:
        return "spatial_sign";
    case InitialEstimatorKind::bacon:
        return "bacon";
    case InitialEstimatorKind::ogk:
        return "ogk";
    default:
        return "unknown";
    }
}

[[nodiscard]] inline auto
ranks_for_axis(const std::span<const rch::core::Vec3<double>> points, const std::size_t axis)
    -> std::vector<double> {
    // Average ranks with deterministic ordering inside exact ties.
    std::vector<RankItem> sorted;
    sorted.reserve(points.size());
    for (std::size_t i = 0U; i < points.size(); ++i) {
        sorted.push_back(RankItem{points[i][axis], i});
    }
    std::ranges::sort(sorted, [](const RankItem& lhs, const RankItem& rhs) noexcept {
        if (rch::core::exactly_equal_for_tie_break(lhs.value, rhs.value)) {
            return lhs.index < rhs.index;
        }
        return lhs.value < rhs.value;
    });

    std::vector<double> ranks(points.size(), 0.0);
    std::size_t first = 0U;
    while (first < sorted.size()) {
        std::size_t last = first + 1U;
        while (last < sorted.size() &&
               rch::core::exactly_equal_for_tie_break(sorted[last].value, sorted[first].value)) {
            ++last;
        }
        const double rank = 0.5 * (static_cast<double>(first + 1U) + static_cast<double>(last));
        for (std::size_t pos = first; pos < last; ++pos) {
            ranks[sorted[pos].index] = rank;
        }
        first = last;
    }
    return ranks;
}

[[nodiscard]] inline auto inverse_standard_normal(const double probability) noexcept -> double {
    // Acklam-style rational approximation for \(\Phi^{-1}(p)\).
    constexpr std::array<double, 6> a{
        -3.969683028665376e+01,
        2.209460984245205e+02,
        -2.759285104469687e+02,
        1.383577518672690e+02,
        -3.066479806614716e+01,
        2.506628277459239e+00,
    };
    constexpr std::array<double, 5> b{
        -5.447609879822406e+01,
        1.615858368580409e+02,
        -1.556989798598866e+02,
        6.680131188771972e+01,
        -1.328068155288572e+01,
    };
    constexpr std::array<double, 6> c{
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e+00,
        -2.549732539343734e+00,
        4.374664141464968e+00,
        2.938163982698783e+00,
    };
    constexpr std::array<double, 4> d{
        7.784695709041462e-03,
        3.224671290700398e-01,
        2.445134137142996e+00,
        3.754408661907416e+00,
    };
    constexpr double plow = 0.02425;
    constexpr double phigh = 1.0 - plow;
    const double p = std::clamp(probability, std::numeric_limits<double>::min(), 1.0 - 1.0e-16);

    if (p < plow) {
        const double q = std::sqrt(-2.0 * std::log(p));
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) /
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0);
    }
    if (p > phigh) {
        const double q = std::sqrt(-2.0 * std::log1p(-p));
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) /
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0);
    }

    const double q = p - 0.5;
    const double r = q * q;
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q /
           (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0);
}

[[nodiscard]] inline auto standardized_points(const std::span<const rch::core::Vec3<double>> points)
    -> std::vector<rch::core::Vec3<double>> {
    // \(z_{ij}=(x_{ij}-med_j)/MAD_j\), using scale floors from MAD helpers.
    const auto center = componentwise_median(points);
    const auto scale = componentwise_mad_scale(points, center);
    std::vector<rch::core::Vec3<double>> standardized;
    standardized.reserve(points.size());
    for (const auto& point : points) {
        standardized.push_back({
            (point[0] - center[0]) / scale[0],
            (point[1] - center[1]) / scale[1],
            (point[2] - center[2]) / scale[2],
        });
    }
    return standardized;
}

[[nodiscard]] inline auto correlation_from_covariance(const rch::core::Matrix3<double>& covariance)
    -> rch::core::Matrix3<double> {
    // Convert covariance to a clamped correlation matrix for robust starts.
    rch::core::Matrix3<double> correlation{};
    for (std::size_t axis = 0U; axis < 3U; ++axis) {
        correlation(axis, axis) = 1.0;
    }
    for (std::size_t row = 0U; row < 3U; ++row) {
        for (std::size_t col = row + 1U; col < 3U; ++col) {
            const double row_variance = std::max(covariance(row, row), 0.0);
            const double col_variance = std::max(covariance(col, col), 0.0);
            const double denom = std::sqrt(row_variance) * std::sqrt(col_variance);
            const double value = denom > 0.0 ? covariance(row, col) / denom : 0.0;
            correlation(row, col) = std::clamp(value, -0.999, 0.999);
            correlation(col, row) = correlation(row, col);
        }
    }
    return correlation;
}

// HRV (2012) §3.1 builds every pair (mu_k(Z), Sigma_k(Z)) in the *standardized*
// space Z = (X - med(X)) / scale(X), and computes the statistical distances
// d_ik = D(z_i, mu_k(Z), Sigma_k(Z)) on Z as well. The C-step runner in this
// project works on the raw points, so a standardized-space correlation matrix R
// has to be mapped back to raw coordinates as
//     Sigma = D R D,     D = diag(per-axis MAD scale),
// which reproduces exactly the same ordering of Mahalanobis distances as the
// paper's standardized-space formulation. Handing the C-step a unit-diagonal R
// together with a raw-coordinate center is a unit mismatch, and it destroys the
// scale equivariance that HRV state the standardization exists to provide
// ("This standardization makes the algorithm location and scale equivariant,
// that is, (1) and (2) hold for any nonsingular diagonal matrix A").
[[nodiscard]] inline auto rescale_to_raw_coordinates(
    const rch::core::Matrix3<double>& correlation, const rch::core::Vec3<double>& scale
) noexcept -> rch::core::Matrix3<double> {
    rch::core::Matrix3<double> scatter{};
    for (std::size_t row = 0U; row < 3U; ++row) {
        for (std::size_t col = 0U; col < 3U; ++col) {
            scatter(row, col) = scale[row] * correlation(row, col) * scale[col];
        }
    }
    return scatter;
}

[[nodiscard]] inline auto
covariance_of_transformed(const std::span<const rch::core::Vec3<double>> transformed)
    -> rch::core::Matrix3<double> {
    // Classical covariance of already robustly transformed observations.
    const auto center = rch::core::mean3(transformed);
    return rch::core::covariance3(transformed, center);
}

[[nodiscard]] inline auto finalize_start(
    const InitialEstimatorKind kind,
    const rch::core::Vec3<double>& center,
    const rch::core::Matrix3<double>& scatter
) -> InitialEstimate {
    // Apply SPD regularization and attach the estimator label.
    const auto regularized = regularize_spd(scatter);
    return InitialEstimate{
        kind, estimator_name(kind), center, regularized.scatter, regularized.applied
    };
}

[[nodiscard]] inline auto tanh_start(const std::span<const rch::core::Vec3<double>> points)
    -> InitialEstimate {
    // HRV tanh start: shrink standardized coordinates by \(\tanh(z)\).
    const auto center = componentwise_median(points);
    const auto scale = componentwise_mad_scale(points, center);
    auto standardized = standardized_points(points);
    for (auto& point : standardized) {
        for (double& value : point) {
            value = std::tanh(value);
        }
    }
    return finalize_start(
        InitialEstimatorKind::tanh,
        center,
        rescale_to_raw_coordinates(
            correlation_from_covariance(covariance_of_transformed(standardized)), scale
        )
    );
}

[[nodiscard]] inline auto spearman_start(const std::span<const rch::core::Vec3<double>> points)
    -> InitialEstimate {
    // Rank-correlation start based on standardized Spearman scores.
    std::vector<rch::core::Vec3<double>> transformed(points.size());
    const double n = static_cast<double>(points.size());
    const double center = 0.5 * (n + 1.0);
    const double scale = std::sqrt(((n * n) - 1.0) / 12.0);
    for (std::size_t axis = 0U; axis < 3U; ++axis) {
        const auto ranks = ranks_for_axis(points, axis);
        for (std::size_t i = 0U; i < points.size(); ++i) {
            transformed[i][axis] = (ranks[i] - center) / scale;
        }
    }
    const auto raw_center = componentwise_median(points);
    return finalize_start(
        InitialEstimatorKind::spearman,
        raw_center,
        rescale_to_raw_coordinates(
            correlation_from_covariance(covariance_of_transformed(transformed)),
            componentwise_mad_scale(points, raw_center)
        )
    );
}

[[nodiscard]] inline auto normal_score_start(const std::span<const rch::core::Vec3<double>> points)
    -> InitialEstimate {
    // Normal-score start with Blom plotting positions \((r-3/8)/(n+1/4)\).
    std::vector<rch::core::Vec3<double>> transformed(points.size());
    const double n = static_cast<double>(points.size());
    for (std::size_t axis = 0U; axis < 3U; ++axis) {
        const auto ranks = ranks_for_axis(points, axis);
        for (std::size_t i = 0U; i < points.size(); ++i) {
            const double p = (ranks[i] - 0.375) / (n + 0.25);
            transformed[i][axis] = inverse_standard_normal(p);
        }
    }
    const auto raw_center = componentwise_median(points);
    return finalize_start(
        InitialEstimatorKind::normal_score,
        raw_center,
        rescale_to_raw_coordinates(
            correlation_from_covariance(covariance_of_transformed(transformed)),
            componentwise_mad_scale(points, raw_center)
        )
    );
}

[[nodiscard]] inline auto spatial_sign_start(const std::span<const rch::core::Vec3<double>> points)
    -> InitialEstimate {
    // Spatial-sign start using \(z_i/\|z_i\|\) for nonzero standardized points.
    auto transformed = standardized_points(points);
    for (auto& point : transformed) {
        const double norm = euclidean_norm(point);
        if (norm > 0.0) {
            point = {point[0] / norm, point[1] / norm, point[2] / norm};
        }
    }
    const auto raw_center = componentwise_median(points);
    return finalize_start(
        InitialEstimatorKind::spatial_sign,
        raw_center,
        rescale_to_raw_coordinates(
            correlation_from_covariance(covariance_of_transformed(transformed)),
            componentwise_mad_scale(points, raw_center)
        )
    );
}

[[nodiscard]] inline auto subset_from_indices(
    const std::span<const rch::core::Vec3<double>> points,
    const std::span<const std::size_t> indices
) -> std::vector<rch::core::Vec3<double>> {
    // Materialize a subset for covariance calculation.
    std::vector<rch::core::Vec3<double>> subset;
    subset.reserve(indices.size());
    for (const std::size_t index : indices) {
        subset.push_back(points[index]);
    }
    return subset;
}

[[nodiscard]] inline auto
bacon_start(const std::span<const rch::core::Vec3<double>> points, const std::size_t h)
    -> InitialEstimate {
    // BACON-style start: use the \(h\) smallest robust standardized radii.
    const auto center = componentwise_median(points);
    const auto scale = componentwise_mad_scale(points, center);
    std::vector<std::pair<double, std::size_t>> scores;
    scores.reserve(points.size());
    for (std::size_t i = 0U; i < points.size(); ++i) {
        const rch::core::Vec3<double> standardized{
            (points[i][0] - center[0]) / scale[0],
            (points[i][1] - center[1]) / scale[1],
            (points[i][2] - center[2]) / scale[2],
        };
        scores.emplace_back(euclidean_norm(standardized), i);
    }
    std::ranges::sort(scores, [points](const auto& lhs, const auto& rhs) noexcept {
        if (rch::core::exactly_equal_for_tie_break(lhs.first, rhs.first)) {
            const auto& lhs_point = points[lhs.second];
            const auto& rhs_point = points[rhs.second];
            if (rch::core::lexicographic_point_less_for_tie_break(lhs_point, rhs_point)) {
                return true;
            }
            if (rch::core::lexicographic_point_less_for_tie_break(rhs_point, lhs_point)) {
                return false;
            }
            return lhs.second < rhs.second;
        }
        return lhs.first < rhs.first;
    });

    std::vector<std::size_t> indices;
    indices.reserve(h);
    const std::size_t subset_size = std::min(h, scores.size());
    for (std::size_t i = 0U; i < subset_size; ++i) {
        indices.push_back(scores[i].second);
    }
    std::ranges::sort(indices);
    const auto subset = subset_from_indices(points, indices);
    const auto subset_center = rch::core::mean3(std::span<const rch::core::Vec3<double>>{subset});
    return finalize_start(
        InitialEstimatorKind::bacon,
        subset_center,
        rch::core::covariance3(std::span<const rch::core::Vec3<double>>{subset}, subset_center)
    );
}

[[nodiscard]] inline auto robust_variance(std::vector<double> values) -> double {
    // Univariate robust variance \(MAD^2\).
    const auto center = median(values).value_or(0.0);
    const double scale = mad(std::span<const double>{values}, center);
    return scale * scale;
}

[[nodiscard]] inline auto ogk_start(const std::span<const rch::core::Vec3<double>> points)
    -> InitialEstimate {
    // OGK start using \(cov(x,y)=(s^2(x+y)-s^2(x-y))/4\).
    const auto standardized = standardized_points(points);
    rch::core::Matrix3<double> covariance{};
    for (std::size_t axis = 0U; axis < 3U; ++axis) {
        std::vector<double> values;
        values.reserve(standardized.size());
        for (const auto& point : standardized) {
            values.push_back(point[axis]);
        }
        covariance(axis, axis) = robust_variance(std::move(values));
    }
    for (std::size_t row = 0U; row < 3U; ++row) {
        for (std::size_t col = row + 1U; col < 3U; ++col) {
            std::vector<double> sum_values;
            std::vector<double> diff_values;
            sum_values.reserve(standardized.size());
            diff_values.reserve(standardized.size());
            for (const auto& point : standardized) {
                sum_values.push_back(point[row] + point[col]);
                diff_values.push_back(point[row] - point[col]);
            }
            covariance(row, col) = 0.25 * (robust_variance(std::move(sum_values)) -
                                           robust_variance(std::move(diff_values)));
            covariance(col, row) = covariance(row, col);
        }
    }
    const auto raw_center = componentwise_median(points);
    return finalize_start(
        InitialEstimatorKind::ogk,
        raw_center,
        rescale_to_raw_coordinates(
            correlation_from_covariance(covariance), componentwise_mad_scale(points, raw_center)
        )
    );
}

} // namespace detail

using InitialEstimatorBuilder =
    InitialEstimate (*)(std::span<const rch::core::Vec3<double>>, std::size_t);

struct InitialEstimatorStrategy {
    InitialEstimatorKind kind{};
    std::string_view name{};
    InitialEstimatorBuilder build{};
};

// Build all deterministic starts expected by DetMCD.
[[nodiscard]] inline auto
make_initial_estimates(const std::span<const rch::core::Vec3<double>> points, const std::size_t h)
    -> std::array<InitialEstimate, 6> {
    return {
        detail::tanh_start(points),
        detail::spearman_start(points),
        detail::normal_score_start(points),
        detail::spatial_sign_start(points),
        detail::bacon_start(points, h),
        detail::ogk_start(points),
    };
}

} // namespace rch::robust
