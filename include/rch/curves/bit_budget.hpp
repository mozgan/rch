#pragma once

// ----------------------------------------------------------------------------
// bit_budget.hpp - deterministic clamping of per-axis curve precision to a
// `uint64_t` key budget.
//
// Algorithm:
//   - Treat requested precision as \(m=(m_0,m_1,m_2)\).
//   - Clamp each axis to caller and implementation bounds:
//     \(m_j \in [m_{\min},m_{\max}]\).
//   - Clamp \(m_{\min}\) itself so \(3m_{\min} \le M_{\max}\).
//   - While \(\sum_j m_j > M_{\max}\), decrement the largest reducible axis;
//     ties choose the lower axis id for deterministic output.
//   - Return the final \(m\), total \(\sum_j m_j\), and flags describing
//     whether clamping or downscaling occurred.
//
// References:
//   - Chris H. Hamilton and Andrew Rau-Chaplin, Compact Hilbert indices:
//     Space-filling curves for domains with unequal side lengths, 2008,
//     DOI: 10.1016/j.ipl.2007.08.034.
//   - Guy M. Morton, A Computer Oriented Geodetic Data Base and a New
//     Technique in File Sequencing, IBM Research Report, 1966.
// ----------------------------------------------------------------------------

#include <array>
#include <cstdint>
#include <span>

namespace rch::curves {

// Fixed curve dimensionality used by this 3D implementation.
inline constexpr std::uint8_t kCurveDimensions3 = 3U;
// Leaves one `uint64_t` bit unused by curve codes that reserve headroom.
inline constexpr std::uint8_t kMaxCurveTotalBits = 63U;
// Maximum supported source-coordinate precision per axis.
inline constexpr std::uint8_t kMaxCurveAxisBits = 32U;

// Result of enforcing per-axis and total bit limits.
struct BitBudgetResult {
    std::array<std::uint8_t, kCurveDimensions3> bits{};
    std::uint16_t total_bits{};
    bool downscaled{};
    bool axis_clamped{};
};

[[nodiscard]] constexpr auto
total_bits(const std::span<const std::uint8_t, kCurveDimensions3> bits) noexcept -> std::uint16_t {
    std::uint16_t total = 0U;
    total = static_cast<std::uint16_t>(total + static_cast<std::uint16_t>(bits[0]));
    total = static_cast<std::uint16_t>(total + static_cast<std::uint16_t>(bits[1]));
    total = static_cast<std::uint16_t>(total + static_cast<std::uint16_t>(bits[2]));
    return total;
}

[[nodiscard]] constexpr auto within_uint64_budget(
    const std::span<const std::uint8_t, kCurveDimensions3> bits,
    const std::uint8_t max_total_bits = kMaxCurveTotalBits
) noexcept -> bool {
    const std::uint8_t effective_total =
        max_total_bits > kMaxCurveTotalBits ? kMaxCurveTotalBits : max_total_bits;
    return total_bits(bits) <= static_cast<std::uint16_t>(effective_total);
}

// Clamps axis bits, then greedily reduces the largest axes until the budget fits.
[[nodiscard]] constexpr auto enforce_bit_budget(
    const std::span<const std::uint8_t, kCurveDimensions3> requested,
    const std::uint8_t max_total_bits = kMaxCurveTotalBits,
    std::uint8_t min_axis_bits = 0U,
    const std::uint8_t max_axis_bits = kMaxCurveAxisBits
) noexcept -> BitBudgetResult {
    const std::uint8_t effective_total =
        max_total_bits > kMaxCurveTotalBits ? kMaxCurveTotalBits : max_total_bits;
    const std::uint8_t effective_axis_max =
        max_axis_bits > kMaxCurveAxisBits ? kMaxCurveAxisBits : max_axis_bits;

    if (min_axis_bits > effective_axis_max) {
        min_axis_bits = effective_axis_max;
    }
    if (static_cast<std::uint16_t>(min_axis_bits) * kCurveDimensions3 >
        static_cast<std::uint16_t>(effective_total)) {
        min_axis_bits = static_cast<std::uint8_t>(effective_total / kCurveDimensions3);
    }

    BitBudgetResult result{};
    for (std::size_t axis = 0; axis < kCurveDimensions3; ++axis) {
        std::uint8_t bits = requested[axis];
        if (bits > effective_axis_max) {
            bits = effective_axis_max;
            result.axis_clamped = true;
        }
        if (bits < min_axis_bits) {
            bits = min_axis_bits;
            result.axis_clamped = true;
        }
        result.bits[axis] = bits;
    }

    auto current_total = total_bits(std::span<const std::uint8_t, kCurveDimensions3>{result.bits});
    while (current_total > effective_total) {
        std::size_t selected_axis = kCurveDimensions3;
        for (std::size_t axis = 0; axis < kCurveDimensions3; ++axis) {
            if (result.bits[axis] <= min_axis_bits) {
                continue;
            }
            if (selected_axis == kCurveDimensions3 ||
                result.bits[axis] > result.bits[selected_axis] ||
                (result.bits[axis] == result.bits[selected_axis] && axis < selected_axis)) {
                selected_axis = axis;
            }
        }

        if (selected_axis == kCurveDimensions3) {
            break;
        }
        --result.bits[selected_axis];
        --current_total;
        result.downscaled = true;
    }

    result.total_bits = current_total;
    return result;
}

} // namespace rch::curves
