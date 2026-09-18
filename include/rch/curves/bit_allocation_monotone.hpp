#pragma once

// ----------------------------------------------------------------------------
// bit_allocation_monotone.hpp - monotone-half per-axis bit allocation baseline
// for compact 3D curve keys.
//
// Algorithm:
//   - Rank axes by descending finite positive half extent \(a_j\); ties use
//     axis id so the order is deterministic.
//   - Clamp the requested maximum precision to an effective axis cap
//     \(m_{\mathrm{cap}}\).
//   - Clamp the minimum precision \(m_{\min}\) so it fits both the axis cap and
//     total budget.
//   - Set a half-budget target
//     \(M_t=\min(\max(3m_{\min},\lfloor 3m_{\mathrm{cap}}/2 \rfloor),
//     M_{\max})\).
//   - Start all axes at \(m_{\min}\), then greedily add remaining bits to the
//     ranked axes up to \(m_{\mathrm{cap}}\); enforce the final budget.
//
// References:
//   - Chris H. Hamilton and Andrew Rau-Chaplin, Compact Hilbert indices:
//     Space-filling curves for domains with unequal side lengths, 2008,
//     DOI: 10.1016/j.ipl.2007.08.034.
//   - Chris Hamilton, Compact Hilbert Indices, Technical Report CS-2006-07,
//     2006.
// ----------------------------------------------------------------------------

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <span>

#include "rch/core/matrix3.hpp"
#include "rch/curves/bit_budget.hpp"

namespace rch::curves {

// User limits for monotone-half allocation.
struct MonotoneHalfBitAllocationOptions {
    std::uint8_t min_axis_bits{1U};
    std::uint8_t max_total_bits{kMaxCurveTotalBits};
    std::uint8_t max_axis_bits{kMaxCurveAxisBits};
};

// Diagnostic output for monotone-half allocation.
struct MonotoneHalfBitAllocation {
    rch::core::Vec3<double> half_extents{};
    std::uint8_t requested_max_precision{};
    std::uint16_t target_total_bits{};
    std::array<std::uint8_t, kCurveDimensions3> ranked_axes{};
    std::array<std::uint8_t, kCurveDimensions3> raw_bits{};
    BitBudgetResult budget{};
};

namespace detail {

// Combines requested precision with implementation and caller axis caps.
[[nodiscard]] constexpr auto effective_monotone_axis_cap(
    const std::uint8_t requested_max_precision, const std::uint8_t max_axis_bits
) noexcept -> std::uint8_t {
    const std::uint8_t cap = max_axis_bits > kMaxCurveAxisBits ? kMaxCurveAxisBits : max_axis_bits;
    return requested_max_precision > cap ? cap : requested_max_precision;
}

// Clamps minimum axis precision to axis and total-budget limits.
[[nodiscard]] constexpr auto effective_monotone_min(
    std::uint8_t min_axis_bits, const std::uint8_t axis_cap, const std::uint8_t max_total_bits
) noexcept -> std::uint8_t {
    if (min_axis_bits > axis_cap) {
        min_axis_bits = axis_cap;
    }
    const std::uint8_t total_cap =
        max_total_bits > kMaxCurveTotalBits ? kMaxCurveTotalBits : max_total_bits;
    if (static_cast<std::uint16_t>(min_axis_bits) * kCurveDimensions3 >
        static_cast<std::uint16_t>(total_cap)) {
        min_axis_bits = static_cast<std::uint8_t>(total_cap / kCurveDimensions3);
    }
    return min_axis_bits;
}

// Converts invalid or non-positive extents to zero ranking weight.
[[nodiscard]] inline auto axis_weight(const double half_extent) noexcept -> double {
    return std::isfinite(half_extent) && half_extent > 0.0 ? half_extent : 0.0;
}

// Ranks axes by descending extent, using axis id as deterministic tie-breaker.
[[nodiscard]] inline auto rank_axes_by_extent(const rch::core::Vec3<double>& half_extents) noexcept
    -> std::array<std::uint8_t, kCurveDimensions3> {
    std::array<std::uint8_t, kCurveDimensions3> axes{0U, 1U, 2U};
    std::ranges::sort(
        axes, [&half_extents](const std::uint8_t lhs, const std::uint8_t rhs) noexcept {
            const double lhs_weight = axis_weight(half_extents[lhs]);
            const double rhs_weight = axis_weight(half_extents[rhs]);
            if (!(lhs_weight < rhs_weight) && !(rhs_weight < lhs_weight)) {
                return lhs < rhs;
            }
            return lhs_weight > rhs_weight;
        }
    );
    return axes;
}

} // namespace detail

// Allocates about half of full compact precision, favoring longer axes first.
[[nodiscard]] inline auto allocate_monotone_half_bits(
    const rch::core::Vec3<double>& half_extents,
    const std::uint8_t requested_max_precision,
    const MonotoneHalfBitAllocationOptions& options = {}
) noexcept -> MonotoneHalfBitAllocation {
    MonotoneHalfBitAllocation allocation{};
    allocation.half_extents = half_extents;
    allocation.requested_max_precision = requested_max_precision;
    allocation.ranked_axes = detail::rank_axes_by_extent(half_extents);

    const std::uint8_t axis_cap =
        detail::effective_monotone_axis_cap(requested_max_precision, options.max_axis_bits);
    const std::uint8_t total_cap =
        options.max_total_bits > kMaxCurveTotalBits ? kMaxCurveTotalBits : options.max_total_bits;
    const std::uint8_t effective_min =
        detail::effective_monotone_min(options.min_axis_bits, axis_cap, total_cap);

    const std::uint16_t min_total = static_cast<std::uint16_t>(effective_min) * kCurveDimensions3;
    const std::uint16_t half_total =
        static_cast<std::uint16_t>((static_cast<std::uint16_t>(axis_cap) * kCurveDimensions3) / 2U);
    allocation.target_total_bits =
        std::min<std::uint16_t>(std::max(min_total, half_total), total_cap);

    allocation.raw_bits = {effective_min, effective_min, effective_min};
    std::uint16_t remaining = static_cast<std::uint16_t>(allocation.target_total_bits - min_total);
    for (const std::uint8_t axis : allocation.ranked_axes) {
        const std::uint8_t available =
            static_cast<std::uint8_t>(axis_cap - allocation.raw_bits[axis]);
        const std::uint8_t add =
            remaining > available ? available : static_cast<std::uint8_t>(remaining);
        allocation.raw_bits[axis] = static_cast<std::uint8_t>(allocation.raw_bits[axis] + add);
        remaining = static_cast<std::uint16_t>(remaining - add);
        if (remaining == 0U) {
            break;
        }
    }

    allocation.budget = enforce_bit_budget(
        std::span<const std::uint8_t, kCurveDimensions3>{allocation.raw_bits},
        total_cap,
        effective_min,
        axis_cap
    );
    return allocation;
}

} // namespace rch::curves
