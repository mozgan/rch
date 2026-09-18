#pragma once

// ----------------------------------------------------------------------------
// bit_allocation_occupancy.hpp - occupancy-driven per-axis bit allocation for
// compact 3D curve keys.
//
// Algorithm:
//   - Interpret half extents as \(a=(a_0,a_1,a_2)\). The core box volume is
//     \(V=8a_0a_1a_2\).
//   - Clamp the support count to \(N=\max(1,n)\) and estimate a target cell
//     edge length \(\delta=(V/N)^{1/3}\).
//   - Candidate intrinsic-surface helpers may instead use
//     \(\delta_2=V^{1/3}/\sqrt{N}\), keeping the same core-volume length scale
//     while applying a 2D sample-count exponent.
//   - For each axis, estimate raw precision
//     \(m_j=\max(m_{\min},\lceil \log_2(2a_j/\delta) \rceil)\), with invalid
//     or degenerate domains falling back to \(m_{\min}\).
//   - Project raw bits onto the feasible key budget
//     \(\sum_j m_j \le M_{\max}\). For finite domains, the projection minimizes
//     the maximum covering-domain cell edge \(2a_j/2^{m_j}\); for invalid
//     domains, it falls back to deterministic clamping.
//   - Hybrid allocation computes \(\delta\) from a robust core domain but
//     applies the resulting resolution to a larger covering domain.
//
// References:
//   - Chris H. Hamilton and Andrew Rau-Chaplin, Compact Hilbert indices:
//     Space-filling curves for domains with unequal side lengths, 2008,
//     DOI: 10.1016/j.ipl.2007.08.034.
//   - John Skilling, Programming the Hilbert curve, 2004,
//     DOI: 10.1063/1.1751381.
//   - David Goldberg, What Every Computer Scientist Should Know About
//     Floating-Point Arithmetic, 1991, DOI: 10.1145/103162.103163.
// ----------------------------------------------------------------------------

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <span>

#include "rch/core/matrix3.hpp"
#include "rch/curves/bit_budget.hpp"

namespace rch::curves {

// User limits for occupancy-based bit allocation.
struct OccupancyBitAllocationOptions {
    std::uint8_t min_axis_bits{1U};
    std::uint8_t max_total_bits{kMaxCurveTotalBits};
    std::uint8_t max_axis_bits{kMaxCurveAxisBits};
};

// Diagnostic output for the occupancy allocation heuristic.
struct OccupancyBitAllocation {
    rch::core::Vec3<double> half_extents{};
    double volume_core{};
    double delta_target{};
    std::size_t n_core{1U};
    std::array<std::uint8_t, kCurveDimensions3> raw_bits{};
    BitBudgetResult budget{};
    bool finite_positive_domain{};
};

namespace detail {

// Clamps an axis cap to the implementation limit.
[[nodiscard]] constexpr auto effective_axis_cap(const std::uint8_t max_axis_bits) noexcept
    -> std::uint8_t {
    return max_axis_bits > kMaxCurveAxisBits ? kMaxCurveAxisBits : max_axis_bits;
}

// Estimates one axis bit count from target cell size and half extent.
[[nodiscard]] inline auto occupancy_axis_bits(
    const double half_extent,
    const double delta_target,
    const std::uint8_t min_axis_bits,
    const std::uint8_t max_axis_bits
) noexcept -> std::uint8_t {
    const std::uint8_t axis_cap = effective_axis_cap(max_axis_bits);
    const std::uint8_t effective_min = min_axis_bits > axis_cap ? axis_cap : min_axis_bits;

    if (!std::isfinite(half_extent) || !std::isfinite(delta_target) || half_extent <= 0.0 ||
        delta_target <= 0.0) {
        return effective_min;
    }

    const double log_ratio = std::log(2.0) + std::log(half_extent) - std::log(delta_target);
    if (!std::isfinite(log_ratio) || log_ratio <= 0.0) {
        return effective_min;
    }

    const double required_bits = std::ceil(log_ratio / std::log(2.0));
    if (!std::isfinite(required_bits) || required_bits <= static_cast<double>(effective_min)) {
        return effective_min;
    }

    const double capped_bits = std::min(required_bits, static_cast<double>(axis_cap));
    return static_cast<std::uint8_t>(capped_bits);
}

// Checks that all half extents define a finite positive 3D box.
[[nodiscard]] inline auto
has_finite_positive_domain(const rch::core::Vec3<double>& half_extents) noexcept -> bool {
    for (const double half_extent : half_extents) {
        if (!std::isfinite(half_extent) || half_extent <= 0.0) {
            return false;
        }
    }
    return true;
}

[[nodiscard]] constexpr auto effective_occupancy_min(
    std::uint8_t min_axis_bits, const std::uint8_t axis_cap, const std::uint8_t total_cap
) noexcept -> std::uint8_t {
    if (min_axis_bits > axis_cap) {
        min_axis_bits = axis_cap;
    }
    if (static_cast<std::uint16_t>(min_axis_bits) * kCurveDimensions3 >
        static_cast<std::uint16_t>(total_cap)) {
        min_axis_bits = static_cast<std::uint8_t>(total_cap / kCurveDimensions3);
    }
    return min_axis_bits;
}

[[nodiscard]] inline auto max_log2_cell_edge(
    const rch::core::Vec3<double>& half_extents,
    const std::array<std::uint8_t, kCurveDimensions3>& bits
) noexcept -> double {
    double worst = -std::numeric_limits<double>::infinity();
    for (std::size_t axis = 0U; axis < kCurveDimensions3; ++axis) {
        if (!std::isfinite(half_extents[axis]) || half_extents[axis] <= 0.0) {
            return std::numeric_limits<double>::infinity();
        }
        const double log_edge =
            1.0 + std::log2(half_extents[axis]) - static_cast<double>(bits[axis]);
        if (!std::isfinite(log_edge)) {
            return std::numeric_limits<double>::infinity();
        }
        worst = std::max(worst, log_edge);
    }
    return worst;
}

[[nodiscard]] constexpr auto lexicographically_more_precise(
    const std::array<std::uint8_t, kCurveDimensions3>& lhs,
    const std::array<std::uint8_t, kCurveDimensions3>& rhs
) noexcept -> bool {
    for (std::size_t axis = 0U; axis < kCurveDimensions3; ++axis) {
        if (lhs[axis] != rhs[axis]) {
            return lhs[axis] > rhs[axis];
        }
    }
    return false;
}

[[nodiscard]] inline auto minimize_worst_cell_edge_budget(
    const rch::core::Vec3<double>& half_extents,
    const std::span<const std::uint8_t, kCurveDimensions3> requested,
    const std::uint8_t max_total_bits,
    const std::uint8_t min_axis_bits,
    const std::uint8_t max_axis_bits
) noexcept -> BitBudgetResult {
    const BitBudgetResult fallback =
        enforce_bit_budget(requested, max_total_bits, min_axis_bits, max_axis_bits);
    if (!has_finite_positive_domain(half_extents)) {
        return fallback;
    }

    const std::uint8_t total_cap =
        max_total_bits > kMaxCurveTotalBits ? kMaxCurveTotalBits : max_total_bits;
    const std::uint8_t axis_cap = effective_axis_cap(max_axis_bits);
    const std::uint8_t effective_min = effective_occupancy_min(min_axis_bits, axis_cap, total_cap);

    std::array<std::uint8_t, kCurveDimensions3> clamped{};
    for (std::size_t axis = 0U; axis < kCurveDimensions3; ++axis) {
        clamped[axis] = std::clamp(requested[axis], effective_min, axis_cap);
    }

    const std::uint16_t requested_total =
        total_bits(std::span<const std::uint8_t, kCurveDimensions3>{clamped});
    const std::uint16_t target_total =
        std::min<std::uint16_t>(requested_total, static_cast<std::uint16_t>(total_cap));

    BitBudgetResult best = fallback;
    double best_score = max_log2_cell_edge(half_extents, best.bits);
    if (!std::isfinite(best_score)) {
        return fallback;
    }

    for (std::uint16_t b0 = effective_min; b0 <= clamped[0]; ++b0) {
        for (std::uint16_t b1 = effective_min; b1 <= clamped[1]; ++b1) {
            for (std::uint16_t b2 = effective_min; b2 <= clamped[2]; ++b2) {
                if (b0 + b1 + b2 != target_total) {
                    continue;
                }

                const std::array<std::uint8_t, kCurveDimensions3> candidate{
                    static_cast<std::uint8_t>(b0),
                    static_cast<std::uint8_t>(b1),
                    static_cast<std::uint8_t>(b2),
                };
                const double score = max_log2_cell_edge(half_extents, candidate);
                constexpr double tolerance = 8.0 * std::numeric_limits<double>::epsilon();
                if (score + tolerance < best_score ||
                    (std::abs(score - best_score) <= tolerance &&
                     lexicographically_more_precise(candidate, best.bits))) {
                    best.bits = candidate;
                    best_score = score;
                }
            }
        }
    }

    best.total_bits = total_bits(std::span<const std::uint8_t, kCurveDimensions3>{best.bits});
    best.axis_clamped = fallback.axis_clamped;
    best.downscaled = fallback.downscaled;
    return best;
}

} // namespace detail

// Allocates bits from a core volume and inlier count; this is a heuristic.
[[nodiscard]] inline auto allocate_occupancy_bits(
    const rch::core::Vec3<double>& half_extents,
    const std::size_t n_core,
    const OccupancyBitAllocationOptions& options = {}
) noexcept -> OccupancyBitAllocation {
    OccupancyBitAllocation allocation{};
    allocation.half_extents = half_extents;
    allocation.n_core = n_core > 0U ? n_core : 1U;
    allocation.finite_positive_domain = detail::has_finite_positive_domain(half_extents);

    if (allocation.finite_positive_domain) {
        allocation.volume_core = 8.0 * half_extents[0] * half_extents[1] * half_extents[2];
        allocation.finite_positive_domain =
            std::isfinite(allocation.volume_core) && allocation.volume_core > 0.0;
    }

    if (allocation.finite_positive_domain) {
        allocation.delta_target =
            std::cbrt(allocation.volume_core / static_cast<double>(allocation.n_core));
    }

    for (std::size_t axis = 0U; axis < kCurveDimensions3; ++axis) {
        allocation.raw_bits[axis] = detail::occupancy_axis_bits(
            half_extents[axis],
            allocation.delta_target,
            options.min_axis_bits,
            options.max_axis_bits
        );
    }

    allocation.budget = detail::minimize_worst_cell_edge_budget(
        half_extents,
        std::span<const std::uint8_t, kCurveDimensions3>{allocation.raw_bits},
        options.max_total_bits,
        options.min_axis_bits,
        options.max_axis_bits
    );
    return allocation;
}

// Reuses core density for resolution while sizing bits for a covering domain.
[[nodiscard]] inline auto allocate_hybrid_occupancy_bits(
    const rch::core::Vec3<double>& core_half_extents,
    const rch::core::Vec3<double>& covering_half_extents,
    const std::size_t n_core,
    const OccupancyBitAllocationOptions& options = {}
) noexcept -> OccupancyBitAllocation {
    const OccupancyBitAllocation core = allocate_occupancy_bits(core_half_extents, n_core, options);

    OccupancyBitAllocation allocation{};
    allocation.half_extents = covering_half_extents;
    allocation.n_core = core.n_core;
    allocation.volume_core = core.volume_core;
    allocation.delta_target = core.delta_target;
    allocation.finite_positive_domain =
        core.finite_positive_domain && detail::has_finite_positive_domain(covering_half_extents);

    for (std::size_t axis = 0U; axis < kCurveDimensions3; ++axis) {
        allocation.raw_bits[axis] = detail::occupancy_axis_bits(
            covering_half_extents[axis],
            allocation.delta_target,
            options.min_axis_bits,
            options.max_axis_bits
        );
    }

    allocation.budget = detail::minimize_worst_cell_edge_budget(
        covering_half_extents,
        std::span<const std::uint8_t, kCurveDimensions3>{allocation.raw_bits},
        options.max_total_bits,
        options.min_axis_bits,
        options.max_axis_bits
    );
    return allocation;
}

} // namespace rch::curves
