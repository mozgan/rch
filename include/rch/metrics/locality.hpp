#pragma once

// ----------------------------------------------------------------------------
// metrics/locality.hpp - locality metric C++ implementations.
//
// Algorithm:
//   - Build the inverse permutation \(r(i)\), mapping point id to rank.
//   - For pairwise locality, evaluate
//     \(L(i,j)=\|p_i-p_j\|_2^3 / |r(i)-r(j)|\) over valid point pairs.
//   - Return the maximum pair value for worst-case locality and the minimum pair
//     value for best-case locality.
//   - For adjacent locality, average \(\|p_{o_t}-p_{o_{t-1}}\|_2\) along the
//     ordering.
//   - For block locality, compute each ordered block diameter and report the
//     mean plus the empirical \(p_{95}\) diameter.
//
// References:
//   - Craig Gotsman and Michael Lindenbaum, On the metric properties of
//     discrete space-filling curves, 1996, DOI: 10.1109/83.499920.
// ----------------------------------------------------------------------------

#include <algorithm>
#include <cmath>
#include <concepts>
#include <cstddef>
#include <functional>
#include <numeric>
#include <ranges>
#include <span>
#include <utility>
#include <vector>

#include "rch/core/matrix3.hpp"

namespace rch::metrics {

// Restricts ordering indices to unsigned integer rank identifiers.
template <typename T>
concept RankIndex = std::unsigned_integral<T>;

namespace detail {

// Computes \(\|a-b\|_2^2\) without the final square root.
[[nodiscard]] inline constexpr auto
squared_l2(const rch::core::Vec3<double>& a, const rch::core::Vec3<double>& b) noexcept -> double {
    const double dx = a[0] - b[0];
    const double dy = a[1] - b[1];
    const double dz = a[2] - b[2];
    return (dx * dx) + (dy * dy) + (dz * dz);
}

// Converts an ordering \(o_t\) into rank lookup \(r(i)\).
template <RankIndex Index>
[[nodiscard]] inline auto inverse_permutation(std::span<const Index> order, std::size_t n)
    -> std::vector<std::size_t> {
    std::vector<std::size_t> rank(n, static_cast<std::size_t>(n));
    for (std::size_t pos = 0U; pos < order.size(); ++pos) {
        const auto raw = static_cast<std::size_t>(order[pos]);
        if (raw < n) {
            rank[raw] = pos;
        }
    }
    return rank;
}

// Verifies that \(o\) is a complete permutation of point ids \([0,n)\).
template <RankIndex Index>
[[nodiscard]] inline auto is_permutation_of_size(std::span<const Index> order, std::size_t n)
    -> bool {
    if (order.size() != n) {
        return false;
    }
    std::vector<bool> seen(n, false);
    for (const Index raw_index : order) {
        const auto index = static_cast<std::size_t>(raw_index);
        if (index >= n || seen[index]) {
            return false;
        }
        seen[index] = true;
    }
    return true;
}

// Verifies that all coordinates are finite before distance-based metrics run.
[[nodiscard]] inline auto all_points_finite(std::span<const rch::core::Vec3<double>> points)
    -> bool {
    return std::ranges::all_of(points, [](const rch::core::Vec3<double>& point) noexcept {
        return rch::core::is_finite(point);
    });
}

} // namespace detail

// Returns the worst pairwise locality ratio over the valid ordered points.
template <RankIndex Index = std::size_t>
[[nodiscard]] inline auto
l1_locality(std::span<const rch::core::Vec3<double>> points, std::span<const Index> order)
    -> double {
    if (order.size() < 2U) [[unlikely]] {
        return 0.0;
    }
    const bool invalid_input =
        !detail::is_permutation_of_size(order, points.size()) || !detail::all_points_finite(points);
    if (invalid_input) [[unlikely]] {
        return 0.0;
    }
    const auto rank = detail::inverse_permutation<Index>(order, points.size());
    double worst = 0.0;
    for (std::size_t i = 0U; i < points.size(); ++i) {
        for (std::size_t j = i + 1U; j < points.size(); ++j) {
            const auto ri = rank[i];
            const auto rj = rank[j];
            if (ri >= points.size() || rj >= points.size()) {
                continue;
            }
            const std::size_t gap = (ri > rj) ? (ri - rj) : (rj - ri);
            if (gap == 0U) [[unlikely]] {
                continue;
            }
            const double dist = std::sqrt(detail::squared_l2(points[i], points[j]));
            const double value = (dist * dist * dist) / static_cast<double>(gap);
            worst = std::max(worst, value);
        }
    }
    return worst;
}

// Returns the best pairwise locality ratio over the valid ordered points.
template <RankIndex Index = std::size_t>
[[nodiscard]] inline auto
l2_locality(std::span<const rch::core::Vec3<double>> points, std::span<const Index> order)
    -> double {
    if (order.size() < 2U) [[unlikely]] {
        return 0.0;
    }
    const bool invalid_input =
        !detail::is_permutation_of_size(order, points.size()) || !detail::all_points_finite(points);
    if (invalid_input) [[unlikely]] {
        return 0.0;
    }
    const auto rank = detail::inverse_permutation<Index>(order, points.size());
    bool seen = false;
    double best = 0.0;
    for (std::size_t i = 0U; i < points.size(); ++i) {
        for (std::size_t j = i + 1U; j < points.size(); ++j) {
            const auto ri = rank[i];
            const auto rj = rank[j];
            if (ri >= points.size() || rj >= points.size()) {
                continue;
            }
            const std::size_t gap = (ri > rj) ? (ri - rj) : (rj - ri);
            if (gap == 0U) [[unlikely]] {
                continue;
            }
            const double dist = std::sqrt(detail::squared_l2(points[i], points[j]));
            const double value = (dist * dist * dist) / static_cast<double>(gap);
            if (!seen || value < best) {
                best = value;
                seen = true;
            }
        }
    }
    return best;
}

// Averages Euclidean distances between consecutive ordered points.
template <RankIndex Index = std::size_t>
[[nodiscard]] inline auto mean_inter_adjacent_distance(
    std::span<const rch::core::Vec3<double>> points, std::span<const Index> order
) -> double {
    if (order.size() < 2U) [[unlikely]] {
        return 0.0;
    }
    const bool invalid_input =
        !detail::is_permutation_of_size(order, points.size()) || !detail::all_points_finite(points);
    if (invalid_input) [[unlikely]] {
        return 0.0;
    }
    double sum = 0.0;
    for (std::size_t pos = 1U; pos < order.size(); ++pos) {
        const auto a = static_cast<std::size_t>(order[pos - 1U]);
        const auto b = static_cast<std::size_t>(order[pos]);
        sum += std::sqrt(detail::squared_l2(points[a], points[b]));
    }
    return sum / static_cast<double>(order.size() - 1U);
}

// Reports mean and empirical p95 diameters of fixed-size ordered blocks.
template <RankIndex Index = std::size_t>
[[nodiscard]] inline auto block_read_locality(
    std::span<const rch::core::Vec3<double>> points,
    std::span<const Index> order,
    std::size_t block_size = 32U
) -> std::pair<double, double> {
    if (block_size < 2U) {
        return {0.0, 0.0};
    }
    if (order.size() < 2U) [[unlikely]] {
        return {0.0, 0.0};
    }
    const bool invalid_input =
        !detail::is_permutation_of_size(order, points.size()) || !detail::all_points_finite(points);
    if (invalid_input) [[unlikely]] {
        return {0.0, 0.0};
    }
    std::vector<double> diameters;
    diameters.reserve((order.size() + block_size - 1U) / block_size);
    for (std::size_t start = 0U; start < order.size(); start += block_size) {
        const std::size_t end = std::min(order.size(), start + block_size);
        if ((end - start) < 2U) {
            continue;
        }
        double worst2 = 0.0;
        for (std::size_t i = start; i < end; ++i) {
            const auto pi = static_cast<std::size_t>(order[i]);
            for (std::size_t j = i + 1U; j < end; ++j) {
                const auto pj = static_cast<std::size_t>(order[j]);
                worst2 = std::max(worst2, detail::squared_l2(points[pi], points[pj]));
            }
        }
        diameters.push_back(std::sqrt(worst2));
    }
    if (diameters.empty()) [[unlikely]] {
        return {0.0, 0.0};
    }
    const double mean = std::ranges::fold_left(diameters, 0.0, std::plus<>{}) /
                        static_cast<double>(diameters.size());
    std::ranges::sort(diameters);
    // p95 index follows the Python runner: ceil(0.95 * N) - 1, clamped.
    const std::size_t raw =
        static_cast<std::size_t>(std::ceil(0.95 * static_cast<double>(diameters.size())));
    const std::size_t p95 = std::min(diameters.size() - 1U, raw == 0U ? 0U : raw - 1U);
    return {mean, diameters[p95]};
}

} // namespace rch::metrics
