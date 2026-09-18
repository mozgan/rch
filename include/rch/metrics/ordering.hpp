#pragma once

// ----------------------------------------------------------------------------
// metrics/ordering.hpp - kNN sort-window recall C++ implementation.
//
// Algorithm:
//   - For each point \(p_i\), compute exact squared distances to all other
//     points and select its \(k\) nearest neighbors.
//   - Build a rank window around \(r(i)\) in the serialized order.
//   - Compute per-point recall as
//     \(|N_k(i) \cap W(i)| / k\), where \(W(i)\) is the order window.
//   - Return the mean recall over all points.
//
// References:
//   - Craig Gotsman and Michael Lindenbaum, On the metric properties of
//     discrete space-filling curves, 1996, DOI: 10.1109/83.499920.
//   - Peter Bollmann, The normalized recall and related measures, 1983,
//     DOI: 10.1145/1013230.511811.
// ----------------------------------------------------------------------------

#include <algorithm>
#include <cstddef>
#include <iterator>
#include <ranges>
#include <span>
#include <utility>
#include <vector>

#include "rch/core/matrix3.hpp"
#include "rch/metrics/locality.hpp"

namespace rch::metrics {

// Measures how often true k-nearest neighbors appear in a local order window.
template <RankIndex Index = std::size_t>
[[nodiscard]] inline auto recall_at_k_window(
    std::span<const rch::core::Vec3<double>> points,
    std::span<const Index> order,
    std::size_t k = 8U,
    std::size_t window = 64U
) -> double {
    const std::size_t n = points.size();
    const bool invalid_input =
        !detail::is_permutation_of_size(order, n) || !detail::all_points_finite(points);
    if (invalid_input) [[unlikely]] {
        return 0.0;
    }
    if (n <= 1U) [[unlikely]] {
        return 1.0;
    }
    const auto rank = detail::inverse_permutation<Index>(order, n);
    const std::size_t half = std::max<std::size_t>(1U, window / 2U);
    const std::size_t k_eff = std::min(k, n - 1U);
    if (k_eff == 0U) [[unlikely]] {
        return 1.0;
    }

    using DistanceIndex = std::pair<double, std::size_t>;
    std::vector<DistanceIndex> distances;
    distances.reserve(n);

    double accumulator = 0.0;
    for (std::size_t i = 0U; i < n; ++i) {
        distances.clear();
        for (std::size_t j = 0U; j < n; ++j) {
            if (j == i) {
                continue;
            }
            distances.emplace_back(detail::squared_l2(points[i], points[j]), j);
        }
        std::ranges::partial_sort(
            distances, distances.begin() + static_cast<std::ptrdiff_t>(k_eff)
        );

        std::vector<std::size_t> exact;
        exact.reserve(k_eff);
        for (std::size_t e = 0U; e < k_eff; ++e) {
            exact.push_back(distances[e].second);
        }
        std::ranges::sort(exact);

        const std::size_t centre = rank[i];
        if (centre >= order.size()) [[unlikely]] {
            continue;
        }
        const std::size_t left = (centre >= half) ? (centre - half) : 0U;
        const std::size_t right = std::min(order.size(), centre + half + 1U);
        std::vector<std::size_t> window_set;
        window_set.reserve(right - left);
        for (std::size_t pos = left; pos < right; ++pos) {
            const auto raw = static_cast<std::size_t>(order[pos]);
            if (raw != i) {
                window_set.push_back(raw);
            }
        }
        std::ranges::sort(window_set);

        std::vector<std::size_t> intersection;
        std::ranges::set_intersection(exact, window_set, std::back_inserter(intersection));
        accumulator += static_cast<double>(intersection.size()) / static_cast<double>(k_eff);
    }
    return accumulator / static_cast<double>(n);
}

} // namespace rch::metrics
