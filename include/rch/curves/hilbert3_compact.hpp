#pragma once

// ----------------------------------------------------------------------------
// hilbert3_compact.hpp - 3D compact Hilbert encoder/decoder for unequal
// per-axis bit depths.
//
// Algorithm:
//   - Accept per-axis precisions \(m_j\) with total budget
//     \(M=\sum_j m_j \le 63\).
//   - Iterate levels from \(\max_j m_j-1\) down to 0, following the same
//     standard Hilbert orientation state \((e,d_r)\).
//   - At each level \(\ell\), define active axes
//     \(A_\ell=\{j \mid m_j > \ell\}\). Rotate this mask into canonical space
//     to get the free-bit mask \(F_\ell\).
//   - Compute the standard 3D child index \(h_\ell\), but append only the rank
//     of the Gray bits selected by \(F_\ell\). The key grows by
//     \(|A_\ell|\) bits rather than always 3 bits.
//   - Decode by reading \(|A_\ell|\) rank bits, combining them with the fixed
//     inactive pattern, reconstructing the full Gray child, and applying the
//     inverse orientation transform.
//
// References:
//   - Chris H. Hamilton and Andrew Rau-Chaplin, Compact Hilbert indices:
//     Space-filling curves for domains with unequal side lengths, 2008,
//     DOI: 10.1016/j.ipl.2007.08.034.
//   - Chris Hamilton, Compact Hilbert Indices, Technical Report CS-2006-07,
//     2006.
//   - John Skilling, Programming the Hilbert curve, 2004,
//     DOI: 10.1063/1.1751381.
// ----------------------------------------------------------------------------

#include <algorithm>
#include <array>
#include <bit>
#include <cstdint>
#include <optional>
#include <span>

#include "rch/curves/bit_budget.hpp"
#include "rch/curves/detail/hilbert_transform.hpp"
#include "rch/curves/hilbert3_standard.hpp"

namespace rch::curves {

// Per-axis precision for compact 3D Hilbert keys.
using BitsAxis3 = std::array<std::uint8_t, 3>;

// Compact Hilbert mapping that stores only active axis bits at each level.
struct Hilbert3Compact {
    static constexpr std::uint8_t dimensions = 3U;

    // Checks per-axis precision and total `uint64_t` budget.
    [[nodiscard]] static constexpr auto
    valid_bits(const std::span<const std::uint8_t, dimensions> bits_axis) noexcept -> bool {
        for (std::uint8_t bits : bits_axis) {
            if (bits > kMaxCurveAxisBits) {
                return false;
            }
        }
        return within_uint64_budget(bits_axis);
    }

    // Verifies that every coordinate fits its axis-specific bit count.
    [[nodiscard]] static constexpr auto coordinates_fit(
        const std::span<const std::uint32_t, dimensions> point,
        const std::span<const std::uint8_t, dimensions> bits_axis
    ) noexcept -> bool {
        if (!valid_bits(bits_axis)) {
            return false;
        }
        for (std::uint8_t axis = 0U; axis < dimensions; ++axis) {
            const std::uint8_t bits = bits_axis[axis];
            if (bits == 0U) {
                if (point[axis] != 0U) {
                    return false;
                }
                continue;
            }
            if (bits < 32U && ((point[axis] >> bits) != 0U)) {
                return false;
            }
        }
        return true;
    }

    // Encodes by ranking only the active canonical Gray bits at each level.
    [[nodiscard]] static constexpr auto encode(
        const std::span<const std::uint32_t, dimensions> point,
        const std::span<const std::uint8_t, dimensions> bits_axis
    ) noexcept -> std::optional<std::uint64_t> {
        if (!coordinates_fit(point, bits_axis)) {
            return std::nullopt;
        }

        const auto max_bits = std::max({bits_axis[0], bits_axis[1], bits_axis[2]});
        std::uint64_t index = 0U;
        std::uint8_t entry = 0U;
        std::uint8_t direction = 0U;

        for (int level = static_cast<int>(max_bits) - 1; level >= 0; --level) {
            const auto bit_index = static_cast<std::uint8_t>(level);
            const std::uint8_t active_mask = detail::active_axis_mask3(bits_axis, bit_index);
            const std::uint8_t free_mask = detail::rotate_right<dimensions>(active_mask, direction);
            const auto free_bits = static_cast<std::uint8_t>(std::popcount(free_mask));
            const std::uint8_t label = detail::cell_label3(point, bit_index);
            const std::uint8_t canonical =
                detail::transform_to_canonical<dimensions>(label, entry, direction);
            const std::uint8_t gray_index = detail::gray_decode<dimensions>(canonical);
            const std::uint8_t rank = detail::gray_rank3(free_mask, gray_index);

            index = (index << free_bits) | static_cast<std::uint64_t>(rank);
            entry = detail::compose_entry<dimensions>(entry, gray_index, direction);
            direction = detail::compose_direction<dimensions>(direction, gray_index);
        }

        return index;
    }

    [[nodiscard]] static constexpr auto
    encode(const Point3u32& point, const BitsAxis3& bits_axis) noexcept
        -> std::optional<std::uint64_t> {
        return encode(
            std::span<const std::uint32_t, dimensions>{point},
            std::span<const std::uint8_t, dimensions>{bits_axis}
        );
    }

    // Decodes a compact key, reconstructing inactive bits from the current pattern.
    [[nodiscard]] static constexpr auto decode(
        const std::uint64_t index, const std::span<const std::uint8_t, dimensions> bits_axis
    ) noexcept -> std::optional<Point3u32> {
        if (!valid_bits(bits_axis)) {
            return std::nullopt;
        }

        const std::uint16_t total = total_bits(bits_axis);
        if (total < 64U && ((index >> total) != 0U)) {
            return std::nullopt;
        }

        const auto max_bits = std::max({bits_axis[0], bits_axis[1], bits_axis[2]});
        Point3u32 point{};
        std::uint16_t remaining = total;
        std::uint8_t entry = 0U;
        std::uint8_t direction = 0U;

        for (int level = static_cast<int>(max_bits) - 1; level >= 0; --level) {
            const auto bit_index = static_cast<std::uint8_t>(level);
            const std::uint8_t active_mask = detail::active_axis_mask3(bits_axis, bit_index);
            const std::uint8_t free_mask = detail::rotate_right<dimensions>(active_mask, direction);
            const auto free_bits = static_cast<std::uint8_t>(std::popcount(free_mask));
            remaining = static_cast<std::uint16_t>(remaining - free_bits);

            const std::uint8_t rank_mask =
                static_cast<std::uint8_t>((std::uint8_t{1U} << free_bits) - std::uint8_t{1U});
            const std::uint8_t rank = static_cast<std::uint8_t>((index >> remaining) & rank_mask);
            const std::uint8_t pattern = static_cast<std::uint8_t>(
                detail::rotate_right<dimensions>(entry, direction) &
                static_cast<std::uint8_t>(~free_mask & 0x7U)
            );

            const detail::GrayRankInverse3 inverse =
                detail::gray_rank_inverse3(free_mask, pattern, rank);
            const std::uint8_t label = detail::inverse_transform_from_canonical<dimensions>(
                inverse.gray_code, entry, direction
            );

            for (std::uint8_t axis = 0U; axis < dimensions; ++axis) {
                const std::uint8_t bit = static_cast<std::uint8_t>((label >> axis) & 1U);
                if (bits_axis[axis] <= bit_index) {
                    if (bit != 0U) {
                        return std::nullopt;
                    }
                    continue;
                }
                point[axis] |= static_cast<std::uint32_t>(bit) << bit_index;
            }

            entry = detail::compose_entry<dimensions>(entry, inverse.gray_index, direction);
            direction = detail::compose_direction<dimensions>(direction, inverse.gray_index);
        }

        return point;
    }

    [[nodiscard]] static constexpr auto
    decode(const std::uint64_t index, const BitsAxis3& bits_axis) noexcept
        -> std::optional<Point3u32> {
        return decode(index, std::span<const std::uint8_t, dimensions>{bits_axis});
    }
};

[[nodiscard]] constexpr auto
hilbert3_compact_encode(const Point3u32& point, const BitsAxis3& bits_axis) noexcept
    -> std::optional<std::uint64_t> {
    return Hilbert3Compact::encode(point, bits_axis);
}

[[nodiscard]] constexpr auto
hilbert3_compact_decode(const std::uint64_t index, const BitsAxis3& bits_axis) noexcept
    -> std::optional<Point3u32> {
    return Hilbert3Compact::decode(index, bits_axis);
}

} // namespace rch::curves
