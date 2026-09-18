#pragma once

// ----------------------------------------------------------------------------
// c_step.hpp - robust C-step runner for FAST-MCD.
//
// References:
//   - Peter J. Rousseeuw, Katrien Van Driessen, "A Fast Algorithm for the
//     Minimum Covariance Determinant Estimator", 1999, doi:10.1080/00401706.1999.10485670.
//   - Mia Hubert, Peter J. Rousseeuw, Tim Verdonck, "A Deterministic Algorithm
//     for Robust Location and Scatter", 2012, doi:10.1080/10618600.2012.672100.
//
// Algorithm:
//   1. Regularize the current scatter matrix if it is not positive definite.
//   2. Compute robust distances \(d_i^2=(x_i-\mu)^T S^{-1}(x_i-\mu)\).
//   3. Select the \(h\) observations with smallest \(d_i^2\).
//   4. Replace \((\mu,S)\) by the mean and covariance of that subset.
//   5. Stop when the subset is unchanged or \(\det(S)\) no longer decreases.
// ----------------------------------------------------------------------------

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <limits>
#include <span>
#include <vector>

#include "rch/core/matrix3.hpp"
#include "rch/robust/regularization.hpp"

namespace rch::robust {

struct CStepOptions {
    // Target subset size \(h\), with \(p < h \le n\) supplied by the caller.
    std::size_t h{};
    // Maximum number of concentration steps.
    std::size_t maxcsteps{200U};
    // Relative tolerance for monotone determinant comparisons.
    double determinant_tolerance{1.0e-12};
};

// Final state of one C-step chain.
struct CStepState {
    rch::core::Vec3<double> center{};
    rch::core::Matrix3<double> scatter{};
    std::vector<std::size_t> subset_indices{};
    double determinant{};
    std::size_t iterations{};
    bool converged{};
    bool used_regularization{};
};

namespace detail {

[[nodiscard]] inline auto sanitized_determinant_tolerance(const double tolerance) noexcept
    -> double {
    return (std::isfinite(tolerance) && tolerance >= 0.0) ? tolerance
                                                          : CStepOptions{}.determinant_tolerance;
}

[[nodiscard]] inline auto points_from_indices(
    const std::span<const rch::core::Vec3<double>> points,
    const std::span<const std::size_t> indices
) -> std::vector<rch::core::Vec3<double>> {
    // Materialize the \(H\)-subset so mean/covariance code can consume a span.
    std::vector<rch::core::Vec3<double>> subset;
    subset.reserve(indices.size());
    for (const std::size_t index : indices) {
        subset.push_back(points[index]);
    }
    return subset;
}

[[nodiscard]] inline auto mahalanobis_squared(
    const rch::core::Vec3<double>& point,
    const rch::core::Vec3<double>& center,
    const rch::core::Matrix3<double>& inverse_scatter
) noexcept -> double {
    // Squared Mahalanobis distance \(d^2=(x-\mu)^T S^{-1}(x-\mu)\).
    const rch::core::Vec3<double> delta{
        point[0] - center[0],
        point[1] - center[1],
        point[2] - center[2],
    };
    return rch::core::dot(delta, rch::core::multiply(inverse_scatter, delta));
}

[[nodiscard]] inline auto select_h_smallest_distances(
    const std::span<const rch::core::Vec3<double>> points,
    const rch::core::Vec3<double>& center,
    const rch::core::Matrix3<double>& inverse_scatter,
    const std::size_t h
) -> std::vector<std::size_t> {
    // Stable selection of the \(h\) smallest distances; ties are deterministic.
    std::vector<std::pair<double, std::size_t>> distances;
    distances.reserve(points.size());
    for (std::size_t i = 0U; i < points.size(); ++i) {
        double distance = mahalanobis_squared(points[i], center, inverse_scatter);
        if (!std::isfinite(distance)) {
            distance = std::numeric_limits<double>::infinity();
        }
        distances.emplace_back(distance, i);
    }
    std::ranges::sort(distances, [points](const auto& lhs, const auto& rhs) noexcept {
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

    std::vector<std::size_t> selected;
    selected.reserve(h);
    for (std::size_t i = 0U; i < h && i < distances.size(); ++i) {
        selected.push_back(distances[i].second);
    }
    std::ranges::sort(selected);
    return selected;
}

[[nodiscard]] inline auto state_from_subset(
    const std::span<const rch::core::Vec3<double>> points, std::vector<std::size_t> subset_indices
) -> CStepState {
    // Recompute \(\mu_H\), \(S_H\), and \(\det(S_H)\) from the selected subset.
    const auto subset = points_from_indices(points, subset_indices);
    const auto center = rch::core::mean3(std::span<const rch::core::Vec3<double>>{subset});
    const auto scatter =
        rch::core::covariance3(std::span<const rch::core::Vec3<double>>{subset}, center);
    const auto regularized = regularize_spd(scatter);
    return CStepState{
        center,
        regularized.scatter,
        std::move(subset_indices),
        rch::core::determinant(regularized.scatter),
        0U,
        false,
        regularized.applied,
    };
}

} // namespace detail

class CStepRunner {
public:
    // Run FAST-MCD concentration steps from one initial \((\mu,S)\).
    [[nodiscard]] auto
    run(const std::span<const rch::core::Vec3<double>> points,
        const rch::core::Vec3<double>& initial_center,
        const rch::core::Matrix3<double>& initial_scatter,
        const CStepOptions& options) const -> CStepState {
        const auto initial_regularized = regularize_spd(initial_scatter);

        CStepState state{
            initial_center,
            initial_regularized.scatter,
            {},
            rch::core::determinant(initial_regularized.scatter),
            0U,
            false,
            initial_regularized.applied,
        };
        if (options.h == 0U || options.h > points.size()) {
            return state;
        }

        for (std::size_t iteration = 0U; iteration < options.maxcsteps; ++iteration) {
            const auto inverse =
                rch::core::inverse(state.scatter, std::numeric_limits<double>::epsilon());
            if (!inverse.has_value()) {
                state.used_regularization = true;
                break;
            }

            auto selected =
                detail::select_h_smallest_distances(points, state.center, *inverse, options.h);
            if (selected == state.subset_indices) {
                state.converged = true;
                state.iterations = iteration;
                break;
            }

            auto next = detail::state_from_subset(points, std::move(selected));
            next.iterations = iteration + 1U;
            next.used_regularization = next.used_regularization || state.used_regularization;

            const double tolerance =
                detail::sanitized_determinant_tolerance(options.determinant_tolerance) *
                std::max(1.0, std::abs(state.determinant));
            if (!state.subset_indices.empty() && next.determinant > state.determinant + tolerance) {
                state.iterations = iteration;
                break;
            }
            state = std::move(next);
        }
        return state;
    }
};

} // namespace rch::robust
