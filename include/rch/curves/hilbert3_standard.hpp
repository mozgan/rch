#pragma once

// ----------------------------------------------------------------------------
// hilbert3_standard.hpp - bit-exact 3D standard Hilbert encoder/decoder.
//
// Algorithm:
//   - Require equal per-axis precision \(m \le 21\), so the key uses
//     \(3m \le 63\) bits.
//   - Encode from most-significant to least-significant level. At level
//     \(\ell\), collect the three coordinate bits into a cell label \(x_\ell\).
//   - Transform \(x_\ell\) to canonical orientation with the current entry
//     \(e\) and direction \(d_r\), then Gray-decode it to the child index
//     \(h_\ell\).
//   - Append \(h_\ell\) to the key: \(H \leftarrow (H << 3) \,|\, h_\ell\),
//     then update \(e,d_r\) for the next subcube.
//   - Decode by reading each 3-bit \(h_\ell\), Gray-encoding it, applying the
//     inverse orientation transform, and writing the recovered bits back to
//     \(x,y,z\).
//
// References:
//   - Chris H. Hamilton and Andrew Rau-Chaplin, Compact Hilbert indices:
//     Space-filling curves for domains with unequal side lengths, 2008,
//     DOI: 10.1016/j.ipl.2007.08.034.
//   - Chris Hamilton, Compact Hilbert Indices, Technical Report CS-2006-07,
//     2006.
//   - Arthur R. Butz, Alternative Algorithm for Hilbert's Space-Filling
//     Curve, 1971, DOI: 10.1109/T-C.1971.223258.
// ----------------------------------------------------------------------------

#include <array>
#include <cstdint>
#include <optional>
#include <span>

#include "rch/curves/detail/hilbert_transform.hpp"

namespace rch::curves {

// Unsigned 3D integer point consumed by curve encoders.
using Point3u32 = std::array<std::uint32_t, 3>;

// Standard Hilbert mapping for equal per-axis precision.
struct Hilbert3Standard {
    static constexpr std::uint8_t dimensions = 3U;
    static constexpr std::uint8_t max_bits = 21U;

    // Checks the per-axis bit count against the `uint64_t` key capacity.
    [[nodiscard]] static constexpr auto valid_bits(const std::uint8_t bits) noexcept -> bool {
        return bits <= max_bits;
    }

    // Verifies that every coordinate fits in the requested bit count.
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

    // Encodes a point by walking Hilbert levels from most to least significant bit.
    [[nodiscard]] static constexpr auto
    encode(const std::span<const std::uint32_t, dimensions> point, const std::uint8_t bits) noexcept
        -> std::optional<std::uint64_t> {
        if (!coordinates_fit(point, bits)) {
            return std::nullopt;
        }

        std::uint64_t index = 0U;
        std::uint8_t entry = 0U;
        std::uint8_t direction = 0U;

        for (int level = static_cast<int>(bits) - 1; level >= 0; --level) {
            const auto bit_index = static_cast<std::uint8_t>(level);
            const std::uint8_t label = detail::cell_label3(point, bit_index);
            const std::uint8_t canonical =
                detail::transform_to_canonical<dimensions>(label, entry, direction);
            const std::uint8_t gray_index = detail::gray_decode<dimensions>(canonical);

            index = (index << dimensions) | static_cast<std::uint64_t>(gray_index);
            entry = detail::compose_entry<dimensions>(entry, gray_index, direction);
            direction = detail::compose_direction<dimensions>(direction, gray_index);
        }

        return index;
    }

    [[nodiscard]] static constexpr auto
    encode(const Point3u32& point, const std::uint8_t bits) noexcept
        -> std::optional<std::uint64_t> {
        return encode(std::span<const std::uint32_t, dimensions>{point}, bits);
    }

    // Decodes a Hilbert key back to 3D coordinates.
    [[nodiscard]] static constexpr auto
    decode(const std::uint64_t index, const std::uint8_t bits) noexcept
        -> std::optional<Point3u32> {
        if (!valid_bits(bits)) {
            return std::nullopt;
        }
        const std::uint8_t total = static_cast<std::uint8_t>(dimensions * bits);
        if (total < 64U && ((index >> total) != 0U)) {
            return std::nullopt;
        }

        Point3u32 point{};
        std::uint8_t entry = 0U;
        std::uint8_t direction = 0U;

        for (int level = static_cast<int>(bits) - 1; level >= 0; --level) {
            const auto bit_index = static_cast<std::uint8_t>(level);
            const std::uint8_t gray_index =
                static_cast<std::uint8_t>((index >> (dimensions * bit_index)) & 0x7ULL);
            const std::uint8_t canonical = detail::gray_encode<dimensions>(gray_index);
            const std::uint8_t label =
                detail::inverse_transform_from_canonical<dimensions>(canonical, entry, direction);

            for (std::uint8_t axis = 0U; axis < dimensions; ++axis) {
                const std::uint32_t bit =
                    (static_cast<std::uint32_t>(label) >> axis) & std::uint32_t{1U};
                point[axis] |= bit << bit_index;
            }

            entry = detail::compose_entry<dimensions>(entry, gray_index, direction);
            direction = detail::compose_direction<dimensions>(direction, gray_index);
        }

        return point;
    }
};

[[nodiscard]] constexpr auto
hilbert3_standard_encode(const Point3u32& point, const std::uint8_t bits) noexcept
    -> std::optional<std::uint64_t> {
    return Hilbert3Standard::encode(point, bits);
}

[[nodiscard]] constexpr auto
hilbert3_standard_decode(const std::uint64_t index, const std::uint8_t bits) noexcept
    -> std::optional<Point3u32> {
    return Hilbert3Standard::decode(index, bits);
}

} // namespace rch::curves
