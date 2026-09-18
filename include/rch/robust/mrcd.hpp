#pragma once

// ----------------------------------------------------------------------------
// mrcd.hpp - Minimum Regularized Covariance Determinant frame estimator.
//
// References:
//   - Kris Boudt, Peter J. Rousseeuw, Steven Vanduffel, Tim Verdonck,
//     "The Minimum Regularized Covariance Determinant Estimator", 2020,
//     doi:10.1007/s11222-019-09869-x.
//   - Peter J. Rousseeuw, Katrien Van Driessen, "A Fast Algorithm for the
//     Minimum Covariance Determinant Estimator", 1999, doi:10.1080/00401706.1999.10485670.
//
// Algorithm:
//   1. Standardize data to \(U\) with coordinatewise median/MAD and target \(T=I\).
//   2. Build deterministic MCD starts and initial \(h\)-subsets.
//   3. Choose \(\rho\) so \(K(H)=\rho I+(1-\rho)c_\alpha S_U(H)\) is well conditioned.
//   4. Run generalized C-steps minimizing \(\det(K(H))\).
//   5. Back-transform center and scatter to raw coordinates.
// ----------------------------------------------------------------------------

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <limits>
#include <span>
#include <vector>

#include "rch/core/matrix3.hpp"
#include "rch/frames/eigen3x3.hpp"
#include "rch/robust/det_mcd.hpp"
#include "rch/robust/fallback_policy.hpp"
#include "rch/robust/initial_estimators.hpp"
#include "rch/robust/mcd_correction.hpp"
#include "rch/robust/median_mad.hpp"

namespace rch::robust {

inline constexpr std::size_t kMrcdDimension = 3U;

struct MrcdOptions {
    // MCD trimming parameter used for \(h\) and \(c_\alpha\).
    double alpha{0.5};
    std::size_t maxcsteps{200U};
    std::size_t min_n{kDetMcdRecommendedSmallN};
    double scale_floor{1.0e-12};
    double condition_number_cap{50.0};
    double rho_guardrail{0.1};
    double determinant_tolerance{1.0e-12};
    // Apply the Eq. (7) consistency factor \(c_\alpha\) to the subset covariance.
    bool apply_consistency_correction{true};
};

// Final MRCD estimate and diagnostics.
struct MrcdResult {
    FallbackPolicy policy{FallbackPolicy::none};
    rch::core::Vec3<double> center{};
    rch::core::Matrix3<double> scatter{};
    std::vector<std::size_t> subset_indices{};
    double determinant{};
    double rho{};
    // \(c_\alpha\) actually used in Eq. (7); 1.0 when disabled.
    double consistency{1.0};
    std::size_t h{};
    std::size_t start_index{};
    std::size_t cstep_iterations{};
    bool converged{};
    bool used_regularization{};
};

namespace detail {

struct MrcdStandardization {
    // Coordinatewise robust standardization parameters.
    rch::core::Vec3<double> center{};
    rch::core::Vec3<double> scale{};
    bool ok{};
};

struct MrcdInitialSubset {
    // Initial subset plus its condition-number-driven ridge weight.
    std::vector<std::size_t> indices{};
    double rho{};
    std::size_t start_index{};
};

struct MrcdState {
    // Internal state for one generalized C-step chain on standardized data.
    rch::core::Vec3<double> center{};
    rch::core::Matrix3<double> scatter{};
    std::vector<std::size_t> subset_indices{};
    double objective{};
    std::size_t iterations{};
    bool converged{};
};

[[nodiscard]] inline auto mrcd_sanitized_options(const MrcdOptions& options) noexcept
    -> MrcdOptions {
    // Replace each out-of-domain numeric option by its default; NaN comparisons are
    // always false, so an unchecked NaN would disable guardrails rather than trip them.
    const MrcdOptions defaults{};
    MrcdOptions sanitized = options;
    if (!(std::isfinite(options.scale_floor) && options.scale_floor >= 0.0)) {
        sanitized.scale_floor = defaults.scale_floor;
    }
    if (!(std::isfinite(options.condition_number_cap) && options.condition_number_cap > 1.0)) {
        sanitized.condition_number_cap = defaults.condition_number_cap;
    }
    if (!(std::isfinite(options.rho_guardrail) && options.rho_guardrail >= 0.0 &&
          options.rho_guardrail <= 1.0)) {
        sanitized.rho_guardrail = defaults.rho_guardrail;
    }
    if (!(std::isfinite(options.determinant_tolerance) && options.determinant_tolerance >= 0.0)) {
        sanitized.determinant_tolerance = defaults.determinant_tolerance;
    }
    return sanitized;
}

[[nodiscard]] inline auto
mrcd_finite_points(const std::span<const rch::core::Vec3<double>> points) noexcept -> bool {
    // MRCD needs finite coordinates before median, MAD, and eigen operations.
    return std::ranges::all_of(points, [](const auto& point) noexcept {
        return rch::core::is_finite(point);
    });
}

[[nodiscard]] inline auto
mrcd_axis_values(const std::span<const rch::core::Vec3<double>> points, const std::size_t axis)
    -> std::vector<double> {
    // Extract one coordinate axis for robust marginal summaries.
    std::vector<double> values;
    values.reserve(points.size());
    for (const auto& point : points) {
        values.push_back(point[axis]);
    }
    return values;
}

[[nodiscard]] inline auto mrcd_standardization(
    const std::span<const rch::core::Vec3<double>> points, const double scale_floor
) -> MrcdStandardization {
    // Median/MAD standardization; zero robust scale disables MRCD.
    MrcdStandardization standardization{};
    standardization.ok = true;
    for (std::size_t axis = 0U; axis < kMrcdDimension; ++axis) {
        auto values = mrcd_axis_values(points, axis);
        standardization.center[axis] = median(values).value_or(0.0);
        const double scale = mad(std::span<const double>{values}, standardization.center[axis]);
        if (!std::isfinite(scale) || scale <= scale_floor) {
            standardization.ok = false;
            standardization.scale[axis] = 0.0;
        } else {
            standardization.scale[axis] = scale;
        }
    }
    return standardization;
}

[[nodiscard]] inline auto mrcd_standardize_points(
    const std::span<const rch::core::Vec3<double>> points,
    const MrcdStandardization& standardization
) -> std::vector<rch::core::Vec3<double>> {
    // \(u_{ij}=(x_{ij}-m_j)/s_j\).
    std::vector<rch::core::Vec3<double>> standardized;
    standardized.reserve(points.size());
    for (const auto& point : points) {
        standardized.push_back({
            (point[0] - standardization.center[0]) / standardization.scale[0],
            (point[1] - standardization.center[1]) / standardization.scale[1],
            (point[2] - standardization.center[2]) / standardization.scale[2],
        });
    }
    return standardized;
}

// Boudt, Rousseeuw, Vanduffel & Verdonck (2020), Eq. (7):
//     K(H) = rho * T + (1 - rho) * c_alpha * S_U(H)
// with T = I_p on the standardized data U (paper §2.4) and c_alpha "the same
// consistency factor as in (5)". c_alpha does not cancel here: it scales only
// the sample-covariance term, not the target, so it changes both the objective
// det(K(H)) and the rho chosen by the condition-number heuristic.
[[nodiscard]] constexpr auto mrcd_regularized_covariance(
    const rch::core::Matrix3<double>& scatter, const double rho, const double consistency = 1.0
) noexcept -> rch::core::Matrix3<double> {
    auto regularized = scatter * ((1.0 - rho) * consistency);
    for (std::size_t axis = 0U; axis < kMrcdDimension; ++axis) {
        regularized(axis, axis) += rho;
    }
    return regularized;
}

[[nodiscard]] inline auto mrcd_subset_points(
    const std::span<const rch::core::Vec3<double>> points,
    const std::span<const std::size_t> indices
) -> std::vector<rch::core::Vec3<double>> {
    // Materialize an \(H\)-subset for covariance calculation.
    std::vector<rch::core::Vec3<double>> subset;
    subset.reserve(indices.size());
    for (const std::size_t index : indices) {
        subset.push_back(points[index]);
    }
    return subset;
}

[[nodiscard]] inline auto mrcd_state_from_subset(
    const std::span<const rch::core::Vec3<double>> points,
    std::vector<std::size_t> subset_indices,
    const double rho,
    const double consistency = 1.0
) -> MrcdState {
    // Compute \(\mu_H\), \(S_U(H)\), and objective \(\det(K(H))\).
    const auto subset = mrcd_subset_points(points, subset_indices);
    const auto center = rch::core::mean3(std::span<const rch::core::Vec3<double>>{subset});
    const auto scatter =
        rch::core::covariance3(std::span<const rch::core::Vec3<double>>{subset}, center);
    const auto regularized = mrcd_regularized_covariance(scatter, rho, consistency);
    return MrcdState{
        center,
        scatter,
        std::move(subset_indices),
        rch::core::determinant(regularized),
        0U,
        false,
    };
}

[[nodiscard]] inline auto mrcd_mahalanobis_squared(
    const rch::core::Vec3<double>& point,
    const rch::core::Vec3<double>& center,
    const rch::core::Matrix3<double>& inverse_scatter
) noexcept -> double {
    // Squared Mahalanobis distance under the current regularized scatter.
    const rch::core::Vec3<double> delta{
        point[0] - center[0],
        point[1] - center[1],
        point[2] - center[2],
    };
    return rch::core::dot(delta, rch::core::multiply(inverse_scatter, delta));
}

[[nodiscard]] inline auto mrcd_select_h_smallest_distances(
    const std::span<const rch::core::Vec3<double>> points,
    const rch::core::Vec3<double>& center,
    const rch::core::Matrix3<double>& inverse_scatter,
    const std::size_t h
) -> std::vector<std::size_t> {
    // Select the \(h\) smallest distances with deterministic tie-breaking.
    std::vector<std::pair<double, std::size_t>> distances;
    distances.reserve(points.size());
    for (std::size_t i = 0U; i < points.size(); ++i) {
        double distance = mrcd_mahalanobis_squared(points[i], center, inverse_scatter);
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

[[nodiscard]] inline auto mrcd_rho_for_condition_cap(
    const rch::core::Matrix3<double>& scatter, const double condition_number_cap
) noexcept -> double {
    // Smallest \(\rho\in[0,1]\) that enforces the requested condition cap.
    if (!rch::core::is_finite(scatter) || !std::isfinite(condition_number_cap) ||
        condition_number_cap <= 1.0) {
        return 1.0;
    }
    const auto eigen = rch::frames::cyclic_jacobi_eigen_symmetric3(scatter);
    if (!eigen.converged) {
        return 1.0;
    }
    const double min_lambda = eigen.eigenvalues[0];
    const double max_lambda = eigen.eigenvalues[2];
    if (!std::isfinite(min_lambda) || !std::isfinite(max_lambda) || max_lambda <= 0.0) {
        return 1.0;
    }
    if (min_lambda > 0.0 && (max_lambda / min_lambda) <= condition_number_cap) {
        return 0.0;
    }

    const double numerator = max_lambda - (condition_number_cap * min_lambda);
    const double denominator = (condition_number_cap - 1.0) + numerator;
    if (numerator <= 0.0) {
        return 0.0;
    }
    if (denominator <= 0.0) {
        return 1.0;
    }
    return std::clamp(numerator / denominator, 0.0, 1.0);
}

[[nodiscard]] inline auto mrcd_initial_subsets(
    const std::span<const rch::core::Vec3<double>> standardized,
    const std::size_t h,
    const double condition_number_cap,
    const double consistency
) -> std::vector<MrcdInitialSubset> {
    // Derive candidate \(H\)-subsets from deterministic starts.
    const auto starts = make_initial_estimates(standardized, h);
    std::vector<MrcdInitialSubset> subsets;
    subsets.reserve(starts.size());

    for (std::size_t start_index = 0U; start_index < starts.size(); ++start_index) {
        const auto& start = starts[start_index];
        const auto inverse =
            rch::core::inverse(start.scatter, std::numeric_limits<double>::epsilon());
        if (!inverse.has_value()) {
            continue;
        }
        auto indices = mrcd_select_h_smallest_distances(standardized, start.center, *inverse, h);
        const auto state = mrcd_state_from_subset(standardized, indices, 0.0, consistency);
        subsets.push_back(
            MrcdInitialSubset{
                std::move(indices),
                // The condition-number heuristic (paper §2.4) bounds cond(K(H)),
                // and K(H) blends rho*I with (1-rho)*c_alpha*S -- so the
                // eigenvalues that matter are those of c_alpha*S, not S.
                mrcd_rho_for_condition_cap(state.scatter * consistency, condition_number_cap),
                start_index,
            }
        );
    }
    return subsets;
}

[[nodiscard]] inline auto mrcd_median(std::vector<double> values) -> double {
    // Median helper with empty input mapped to zero.
    return median(std::move(values)).value_or(0.0);
}

[[nodiscard]] inline auto mrcd_choose_rho(
    const std::span<const MrcdInitialSubset> initial_subsets, const double rho_guardrail
) -> double {
    // MRCD heuristic: use max rho unless it exceeds the guardrail.
    std::vector<double> rhos;
    rhos.reserve(initial_subsets.size());
    for (const auto& subset : initial_subsets) {
        rhos.push_back(subset.rho);
    }
    if (rhos.empty()) [[unlikely]] {
        return rho_guardrail;
    }
    const double max_rho = *std::ranges::max_element(rhos);
    if (max_rho <= rho_guardrail) {
        return max_rho;
    }
    return std::max(rho_guardrail, mrcd_median(std::move(rhos)));
}

[[nodiscard]] inline auto mrcd_generalized_csteps(
    const std::span<const rch::core::Vec3<double>> standardized,
    std::vector<std::size_t> initial_subset,
    const std::size_t h,
    const double rho,
    const double consistency,
    const MrcdOptions& options
) -> MrcdState {
    // Generalized C-steps for the MRCD objective \(\det(K(H))\).
    auto state = mrcd_state_from_subset(standardized, std::move(initial_subset), rho, consistency);
    for (std::size_t iteration = 0U; iteration < options.maxcsteps; ++iteration) {
        const auto regularized = mrcd_regularized_covariance(state.scatter, rho, consistency);
        const auto inverse =
            rch::core::inverse(regularized, std::numeric_limits<double>::epsilon());
        if (!inverse.has_value()) {
            break;
        }

        auto selected = mrcd_select_h_smallest_distances(standardized, state.center, *inverse, h);
        if (selected == state.subset_indices) {
            state.converged = true;
            state.iterations = iteration;
            break;
        }

        auto next = mrcd_state_from_subset(standardized, std::move(selected), rho, consistency);
        next.iterations = iteration + 1U;
        const double tolerance =
            options.determinant_tolerance * std::max(1.0, std::abs(state.objective));
        if (next.objective > state.objective + tolerance) {
            state.iterations = iteration;
            break;
        }
        state = std::move(next);
    }
    return state;
}

[[nodiscard]] inline auto
mrcd_back_transform_center(const rch::core::Vec3<double>& center, const MrcdStandardization& s)
    -> rch::core::Vec3<double> {
    // Return from standardized coordinates to raw coordinates.
    return {
        s.center[0] + (s.scale[0] * center[0]),
        s.center[1] + (s.scale[1] * center[1]),
        s.center[2] + (s.scale[2] * center[2]),
    };
}

[[nodiscard]] inline auto
mrcd_back_transform_scatter(const rch::core::Matrix3<double>& scatter, const MrcdStandardization& s)
    -> rch::core::Matrix3<double> {
    // Back-transform scatter as \(D K D\).
    rch::core::Matrix3<double> out{};
    for (std::size_t row = 0U; row < kMrcdDimension; ++row) {
        for (std::size_t col = 0U; col < kMrcdDimension; ++col) {
            out(row, col) = s.scale[row] * scatter(row, col) * s.scale[col];
        }
    }
    return out;
}

} // namespace detail

[[nodiscard]] inline auto
mrcd(const std::span<const rch::core::Vec3<double>> points, const MrcdOptions& raw_options = {})
    -> MrcdResult {
    // Full MRCD estimator on fixed dimension \(p=3\).
    // Non-finite or out-of-domain numeric options fall back to their defaults per field:
    // otherwise a NaN threshold silently propagates into rho, the objective, and the
    // final scatter instead of degrading to the documented default behaviour.
    const auto options = detail::mrcd_sanitized_options(raw_options);
    MrcdResult result{};
    result.h = mcd_h_size(points.size(), kMrcdDimension, options.alpha);

    if (points.size() < options.min_n || result.h <= kMrcdDimension) {
        result.policy = FallbackPolicy::disabled_small_n;
        return result;
    }
    if (!detail::mrcd_finite_points(points)) {
        result.policy = FallbackPolicy::disabled_rank_deficient;
        return result;
    }

    const auto standardization = detail::mrcd_standardization(points, options.scale_floor);
    if (!standardization.ok) {
        result.policy = FallbackPolicy::disabled_rank_deficient;
        return result;
    }
    // c_alpha of Eq. (5)/(7); falls back to 1.0 only if it cannot be evaluated.
    const double consistency =
        options.apply_consistency_correction
            ? mcd_consistency_factor(points.size(), kMrcdDimension, result.h).value_or(1.0)
            : 1.0;
    result.consistency = consistency;

    const auto standardized = detail::mrcd_standardize_points(points, standardization);
    const auto initial_subsets = detail::mrcd_initial_subsets(
        std::span<const rch::core::Vec3<double>>{standardized},
        result.h,
        options.condition_number_cap,
        consistency
    );
    if (initial_subsets.empty()) {
        result.policy = FallbackPolicy::disabled_rank_deficient;
        return result;
    }

    result.rho = detail::mrcd_choose_rho(
        std::span<const detail::MrcdInitialSubset>{initial_subsets}, options.rho_guardrail
    );

    bool have_candidate = false;
    detail::MrcdState best{};
    for (const auto& initial : initial_subsets) {
        if (initial.rho > result.rho + options.determinant_tolerance) {
            continue;
        }
        auto candidate = detail::mrcd_generalized_csteps(
            std::span<const rch::core::Vec3<double>>{standardized},
            initial.indices,
            result.h,
            result.rho,
            consistency,
            options
        );
        if (!have_candidate || candidate.objective < best.objective ||
            (rch::core::exactly_equal_for_tie_break(candidate.objective, best.objective) &&
             initial.start_index < result.start_index)) {
            best = std::move(candidate);
            result.start_index = initial.start_index;
            have_candidate = true;
        }
    }
    if (!have_candidate || best.subset_indices.empty()) {
        result.policy = FallbackPolicy::disabled_rank_deficient;
        return result;
    }

    const auto scatter_u =
        detail::mrcd_regularized_covariance(best.scatter, result.rho, consistency);
    result.center = detail::mrcd_back_transform_center(best.center, standardization);
    result.scatter = detail::mrcd_back_transform_scatter(scatter_u, standardization);
    result.subset_indices = std::move(best.subset_indices);
    result.determinant = rch::core::determinant(result.scatter);
    result.cstep_iterations = best.iterations;
    result.converged = best.converged;
    result.used_regularization = result.rho > 0.0;
    result.policy =
        result.used_regularization ? FallbackPolicy::chi2_regularized : FallbackPolicy::none;
    if (!rch::core::is_finite(result.center) || !rch::core::is_finite(result.scatter) ||
        !(result.determinant > 0.0)) {
        result.policy = FallbackPolicy::disabled_rank_deficient;
    }
    return result;
}

} // namespace rch::robust
