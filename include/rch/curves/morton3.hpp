#pragma once

// ----------------------------------------------------------------------------
// morton3.hpp - 3D Morton/Z-order keys built by coordinate-bit interleaving.
//
// Algorithm:
//   - For equal precision \(m\), validate that each coordinate satisfies
//     \(0 \le x_j < 2^m\) and \(3m \le 63\).
//   - Build the Morton key by interleaving coordinate bits from low to high:
//     \(H_{3b}=x_b\), \(H_{3b+1}=y_b\), \(H_{3b+2}=z_b\).
//   - For per-axis precision \(m_j\), emit only active axis bits at level
//     \(b\), preserving axis order \(x,y,z\); total emitted bits are
//     \(M=\sum_j m_j\).
//   - The unchecked interleave helpers assume range validation already passed;
//     public encoders perform validation and return nullopt on overflow.
//
// References:
//   - Guy M. Morton, A Computer Oriented Geodetic Data Base and a New
//     Technique in File Sequencing, IBM Research Report, 1966.
//   - Bongki Moon, H. V. Jagadish, Christos Faloutsos, and Joel H. Saltz,
//     Analysis of the clustering properties of the Hilbert space-filling
//     curve, 2001, DOI: 10.1109/69.908985.
//   - Michael Connor and Piyush Kumar, Parallel Construction of k-Nearest
//     Neighbor Graphs for Point Clouds, 2008,
//     DOI: 10.2312/VG/VG-PBG08/025-031.
// ----------------------------------------------------------------------------

#include <algorithm>
#include <array>
#include <cstdint>
#include <optional>
#include <span>

#include "rch/curves/bit_budget.hpp"

namespace rch::curves {

// Morton key builder for equal or per-axis 3D precision.
struct Morton3 {
    static constexpr std::uint8_t dimensions = 3U;
    static constexpr std::uint8_t max_bits = 21U;
    static constexpr std::uint32_t max_coordinate = (std::uint32_t{1U} << max_bits) - 1U;

    // Checks equal per-axis precision against the `uint64_t` key capacity.
    [[nodiscard]] static constexpr auto valid_bits(const std::uint8_t bits) noexcept -> bool {
        return bits <= max_bits;
    }

    // Checks per-axis precision and total `uint64_t` budget.
    [[nodiscard]] static constexpr auto
    valid_bits(const std::span<const std::uint8_t, dimensions> bits_axis) noexcept -> bool {
        for (const std::uint8_t bits : bits_axis) {
            if (bits > kMaxCurveAxisBits) {
                return false;
            }
        }
        return within_uint64_budget(bits_axis);
    }

    // Verifies that all coordinates fit an equal bit depth.
    [[nodiscard]] static constexpr auto coordinates_fit(
        const std::span<const std::uint32_t, dimensions> point, const std::uint8_t bits
    ) noexcept -> bool {
        if (!valid_bits(bits)) {
            return false;
        }
        if (bits == 0U) {
            return point[0] == 0U && point[1] == 0U && point[2] == 0U;
        }
        for (std::uint32_t coordinate : point) {
            if ((coordinate >> bits) != 0U) {
                return false;
            }
        }
        return true;
    }

    // Verifies that each coordinate fits its own axis bit depth.
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

    // Interleaves \(x,y,z\) bits without validating coordinate ranges.
    [[nodiscard]] static constexpr auto interleave_unchecked(
        const std::span<const std::uint32_t, dimensions> point, const std::uint8_t bits
    ) noexcept -> std::uint64_t {
        std::uint64_t key = 0U;
        for (std::uint8_t bit = 0U; bit < bits; ++bit) {
            const std::uint64_t x = (static_cast<std::uint64_t>(point[0]) >> bit) & 1ULL;
            const std::uint64_t y = (static_cast<std::uint64_t>(point[1]) >> bit) & 1ULL;
            const std::uint64_t z = (static_cast<std::uint64_t>(point[2]) >> bit) & 1ULL;
            const auto base = static_cast<std::uint8_t>(dimensions * bit);
            key |= x << base;
            key |= y << static_cast<std::uint8_t>(base + 1U);
            key |= z << static_cast<std::uint8_t>(base + 2U);
        }
        return key;
    }

    // Interleaves only active per-axis bits without validating ranges.
    [[nodiscard]] static constexpr auto interleave_unchecked(
        const std::span<const std::uint32_t, dimensions> point,
        const std::span<const std::uint8_t, dimensions> bits_axis
    ) noexcept -> std::uint64_t {
        const std::uint8_t max_bits_axis = std::max({bits_axis[0], bits_axis[1], bits_axis[2]});
        std::uint64_t key = 0U;
        std::uint8_t out_bit = 0U;
        for (std::uint8_t bit = 0U; bit < max_bits_axis; ++bit) {
            for (std::uint8_t axis = 0U; axis < dimensions; ++axis) {
                if (bits_axis[axis] <= bit) {
                    continue;
                }
                const std::uint64_t value = (static_cast<std::uint64_t>(point[axis]) >> bit) & 1ULL;
                key |= value << out_bit;
                ++out_bit;
            }
        }
        return key;
    }

    // Validates and encodes a point with equal per-axis precision.
    [[nodiscard]] static constexpr auto
    encode(const std::span<const std::uint32_t, dimensions> point, const std::uint8_t bits) noexcept
        -> std::optional<std::uint64_t> {
        if (!coordinates_fit(point, bits)) {
            return std::nullopt;
        }
        return interleave_unchecked(point, bits);
    }

    // Validates and encodes a point with per-axis precision.
    [[nodiscard]] static constexpr auto encode(
        const std::span<const std::uint32_t, dimensions> point,
        const std::span<const std::uint8_t, dimensions> bits_axis
    ) noexcept -> std::optional<std::uint64_t> {
        if (!coordinates_fit(point, bits_axis)) {
            return std::nullopt;
        }
        return interleave_unchecked(point, bits_axis);
    }

    [[nodiscard]] static constexpr auto
    encode(const std::array<std::uint32_t, dimensions>& point, const std::uint8_t bits) noexcept
        -> std::optional<std::uint64_t> {
        return encode(std::span<const std::uint32_t, dimensions>{point}, bits);
    }

    [[nodiscard]] static constexpr auto encode(
        const std::array<std::uint32_t, dimensions>& point,
        const std::array<std::uint8_t, dimensions>& bits_axis
    ) noexcept -> std::optional<std::uint64_t> {
        return encode(
            std::span<const std::uint32_t, dimensions>{point},
            std::span<const std::uint8_t, dimensions>{bits_axis}
        );
    }
};

[[nodiscard]] constexpr auto morton3_encode(
    const std::array<std::uint32_t, Morton3::dimensions>& point, const std::uint8_t bits
) noexcept -> std::optional<std::uint64_t> {
    return Morton3::encode(point, bits);
}

} // namespace rch::curves
