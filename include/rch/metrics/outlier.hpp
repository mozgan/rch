#pragma once

// ----------------------------------------------------------------------------
// metrics/outlier.hpp - outlier-stability metric implementations.
//
// Algorithm:
//   - For order stability, remove contaminated-only ids, then compare the
//     remaining pair order against the clean ranking.
//   - Count concordant and discordant pairs and compute
//     \(\tau=(C-D)/(C+D)\).
//   - For frame stability, compare corresponding axes up to sign with
//     \(\theta_j=\arccos(|u_j^T v_j|/(\|u_j\|_2\|v_j\|_2))\).
//   - Return the largest axis angle as the frame perturbation metric.
//
// References:
//   - M. G. Kendall, A New Measure of Rank Correlation, 1938,
//     DOI: 10.1093/biomet/30.1-2.81.
//   - Peter J. Huber and Elvezio M. Ronchetti, Robust Statistics,
//     2nd ed., 2009, DOI: 10.1002/9780470434697.
//   - ISO/IEC, ISO/IEC 14882:2020 Programming languages - C++, `std::hypot`.
// ----------------------------------------------------------------------------

#include <algorithm>
#include <cmath>
#include <concepts>
#include <cstddef>
#include <optional>
#include <span>
#include <vector>

#include "rch/core/matrix3.hpp"
#include "rch/metrics/locality.hpp"

namespace rch::metrics {

namespace detail {

// Checks whether the provided ids form one full clean-order permutation.
template <RankIndex Index>
[[nodiscard]] inline auto clean_index_permutation(std::span<const Index> order, std::size_t n)
    -> bool {
    if (order.size() != n) {
        return false;
    }
    std::vector<bool> seen(n, false);
    for (const Index raw : order) {
        const auto index = static_cast<std::size_t>(raw);
        if (index >= n || seen[index]) {
            return false;
        }
        seen[index] = true;
    }
    return true;
}

} // namespace detail

// Computes Kendall's tau after filtering out contaminated-only indices.
template <RankIndex Index = std::size_t>
[[nodiscard]] inline auto kendall_tau_against_clean(
    std::span<const Index> clean_order,
    std::span<const Index> contaminated_order,
    std::size_t clean_count
) -> double {
    if (!detail::clean_index_permutation(clean_order, clean_count)) [[unlikely]] {
        return 0.0;
    }
    std::vector<std::size_t> filtered;
    filtered.reserve(contaminated_order.size());
    for (const auto raw : contaminated_order) {
        const auto raw_index = static_cast<std::size_t>(raw);
        if (raw_index < clean_count) {
            filtered.push_back(raw_index);
        }
    }
    if (!detail::clean_index_permutation(std::span<const std::size_t>{filtered}, clean_count)) {
        return 0.0;
    }
    if (filtered.size() < 2U) [[unlikely]] {
        return 1.0;
    }
    std::vector<std::size_t> clean_rank(clean_count, clean_count);
    for (std::size_t pos = 0U; pos < clean_order.size(); ++pos) {
        const auto raw = static_cast<std::size_t>(clean_order[pos]);
        if (raw < clean_count) {
            clean_rank[raw] = pos;
        }
    }
    std::size_t concordant = 0U;
    std::size_t discordant = 0U;
    for (std::size_t left = 0U; left < filtered.size(); ++left) {
        const auto lr = clean_rank[filtered[left]];
        for (std::size_t right = left + 1U; right < filtered.size(); ++right) {
            const auto rr = clean_rank[filtered[right]];
            if (lr < rr) {
                ++concordant;
            } else {
                ++discordant;
            }
        }
    }
    const std::size_t denom = concordant + discordant;
    if (denom == 0U) [[unlikely]] {
        return 1.0;
    }
    const double diff = static_cast<double>(concordant) - static_cast<double>(discordant);
    return diff / static_cast<double>(denom);
}

// Returns the largest unsigned angle between matching frame axes.
[[nodiscard]] inline auto frame_angle_rad(
    const rch::core::Matrix3<double>& clean_axes, const rch::core::Matrix3<double>& perturbed_axes
) -> std::optional<double> {
    double worst = 0.0;
    for (std::size_t axis = 0U; axis < 3U; ++axis) {
        const double clean_norm =
            std::hypot(clean_axes(0U, axis), clean_axes(1U, axis), clean_axes(2U, axis));
        const double perturbed_norm = std::hypot(
            perturbed_axes(0U, axis), perturbed_axes(1U, axis), perturbed_axes(2U, axis)
        );
        if (!std::isfinite(clean_norm) || !std::isfinite(perturbed_norm)) {
            return std::nullopt;
        }
        if (clean_norm <= 0.0 || perturbed_norm <= 0.0) {
            return std::nullopt;
        }

        double cosine = 0.0;
        for (std::size_t row = 0U; row < 3U; ++row) {
            cosine +=
                (clean_axes(row, axis) / clean_norm) * (perturbed_axes(row, axis) / perturbed_norm);
        }
        if (!std::isfinite(cosine)) {
            return std::nullopt;
        }
        cosine = std::clamp(std::abs(cosine), 0.0, 1.0);
        worst = std::max(worst, std::acos(cosine));
    }
    return worst;
}

} // namespace rch::metrics
