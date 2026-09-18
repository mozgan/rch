#pragma once

// ----------------------------------------------------------------------------
// detail/hilbert_transform.hpp - low-level Gray-code and orientation helpers
// for the standard and compact 3D Hilbert encoders.
//
// Algorithm:
//   - Represent each Hilbert child cell by a \(d\)-bit label and keep only the
//     low \(d\) bits with \(2^d-1\) masks.
//   - Convert between binary child index and reflected Gray code with
//     \(g = i \oplus (i >> 1)\), then recover \(i\) by prefix XOR.
//   - Track the current Hilbert orientation with an entry vertex \(e\) and a
//     direction \(d_r\). Canonicalization uses
//     \(T_{e,d_r}(x)=\operatorname{rotr}(x \oplus e,d_r)\).
//   - After visiting child \(i\), compose the next entry and direction from
//     Hamilton's subcube entry/direction rules.
//   - For compact Hilbert indices, rank only active Gray bits selected by
//     \(F\); inverse ranking reconstructs the full Gray label from fixed
//     pattern bits and compact rank bits.
//
// References:
//   - Chris Hamilton, Compact Hilbert Indices, Technical Report CS-2006-07,
//     2006.
//   - Chris H. Hamilton and Andrew Rau-Chaplin, Compact Hilbert indices:
//     Space-filling curves for domains with unequal side lengths, 2008,
//     DOI: 10.1016/j.ipl.2007.08.034.
//   - Arthur R. Butz, Alternative Algorithm for Hilbert's Space-Filling
//     Curve, 1971, DOI: 10.1109/T-C.1971.223258.
// ----------------------------------------------------------------------------

#include <array>
#include <bit>
#include <cstdint>
#include <span>

namespace rch::curves::detail {

// Bit mask containing the active dimension bits.
template <std::uint8_t Dimensions>
inline constexpr std::uint8_t kDimensionMask =
    static_cast<std::uint8_t>((std::uint16_t{1U} << Dimensions) - std::uint16_t{1U});

// Rotates a dimension label left inside the active bit width.
template <std::uint8_t Dimensions>
[[nodiscard]] constexpr auto
rotate_left(const std::uint8_t value, const std::uint8_t distance) noexcept -> std::uint8_t {
    static_assert(Dimensions > 0U);
    static_assert(Dimensions < 8U);
    const std::uint8_t shift = static_cast<std::uint8_t>(distance % Dimensions);
    const std::uint8_t masked = static_cast<std::uint8_t>(value & kDimensionMask<Dimensions>);
    if (shift == 0U) {
        return masked;
    }
    return static_cast<std::uint8_t>(
        ((masked << shift) | (masked >> (Dimensions - shift))) & kDimensionMask<Dimensions>
    );
}

// Rotates a dimension label right inside the active bit width.
template <std::uint8_t Dimensions>
[[nodiscard]] constexpr auto
rotate_right(const std::uint8_t value, const std::uint8_t distance) noexcept -> std::uint8_t {
    static_assert(Dimensions > 0U);
    static_assert(Dimensions < 8U);
    const std::uint8_t shift = static_cast<std::uint8_t>(distance % Dimensions);
    const std::uint8_t masked = static_cast<std::uint8_t>(value & kDimensionMask<Dimensions>);
    if (shift == 0U) {
        return masked;
    }
    return static_cast<std::uint8_t>(
        ((masked >> shift) | (masked << (Dimensions - shift))) & kDimensionMask<Dimensions>
    );
}

// Reads one bit from a coordinate, returning zero for out-of-range bit indices.
[[nodiscard]] constexpr auto
bit_at(const std::uint32_t value, const std::uint8_t bit_index) noexcept -> std::uint8_t {
    if (bit_index >= 32U) {
        return 0U;
    }
    return static_cast<std::uint8_t>((value >> bit_index) & std::uint32_t{1U});
}

// Converts a binary subcube index to reflected Gray code.
template <std::uint8_t Dimensions>
[[nodiscard]] constexpr auto gray_encode(const std::uint8_t value) noexcept -> std::uint8_t {
    static_assert(Dimensions > 0U);
    static_assert(Dimensions < 8U);
    return static_cast<std::uint8_t>((value ^ (value >> 1U)) & kDimensionMask<Dimensions>);
}

// Converts reflected Gray code back to a binary subcube index.
template <std::uint8_t Dimensions>
[[nodiscard]] constexpr auto gray_decode(const std::uint8_t gray) noexcept -> std::uint8_t {
    static_assert(Dimensions > 0U);
    static_assert(Dimensions < 8U);
    std::uint8_t value = 0U;
    std::uint8_t parity = 0U;
    for (int bit = static_cast<int>(Dimensions) - 1; bit >= 0; --bit) {
        parity = static_cast<std::uint8_t>(parity ^ ((gray >> bit) & 1U));
        value = static_cast<std::uint8_t>(value | (parity << bit));
    }
    return static_cast<std::uint8_t>(value & kDimensionMask<Dimensions>);
}

// Counts consecutive low-order one bits, bounded by the dimension count.
template <std::uint8_t Dimensions>
[[nodiscard]] constexpr auto trailing_set_bits(std::uint8_t value) noexcept -> std::uint8_t {
    static_assert(Dimensions > 0U);
    static_assert(Dimensions < 8U);
    std::uint8_t count = 0U;
    while (count < Dimensions && (value & 1U) != 0U) {
        ++count;
        value = static_cast<std::uint8_t>(value >> 1U);
    }
    return count;
}

// Computes the Hilbert subcube direction for a Gray-order child.
template <std::uint8_t Dimensions>
[[nodiscard]] constexpr auto subcube_direction(const std::uint8_t gray_index) noexcept
    -> std::uint8_t {
    static_assert(Dimensions > 0U);
    static_assert(Dimensions < 8U);
    if (gray_index == 0U) {
        return 0U;
    }
    const std::uint8_t source =
        (gray_index % 2U == 0U) ? static_cast<std::uint8_t>(gray_index - 1U) : gray_index;
    return static_cast<std::uint8_t>(trailing_set_bits<Dimensions>(source) % Dimensions);
}

// Computes the Hilbert subcube entry vertex for a Gray-order child.
template <std::uint8_t Dimensions>
[[nodiscard]] constexpr auto subcube_entry(const std::uint8_t gray_index) noexcept -> std::uint8_t {
    static_assert(Dimensions > 0U);
    static_assert(Dimensions < 8U);
    if (gray_index == 0U) {
        return 0U;
    }
    const std::uint8_t paired =
        static_cast<std::uint8_t>(2U * static_cast<std::uint8_t>((gray_index - 1U) / 2U));
    return gray_encode<Dimensions>(paired);
}

// Applies the current entry/direction transform to canonical orientation.
template <std::uint8_t Dimensions>
[[nodiscard]] constexpr auto transform_to_canonical(
    const std::uint8_t label, const std::uint8_t entry, const std::uint8_t direction
) noexcept -> std::uint8_t {
    static_assert(Dimensions > 0U);
    static_assert(Dimensions < 8U);
    return rotate_right<Dimensions>(static_cast<std::uint8_t>(label ^ entry), direction);
}

// Reverses the canonical transform back to the current orientation.
template <std::uint8_t Dimensions>
[[nodiscard]] constexpr auto inverse_transform_from_canonical(
    const std::uint8_t canonical_label, const std::uint8_t entry, const std::uint8_t direction
) noexcept -> std::uint8_t {
    static_assert(Dimensions > 0U);
    static_assert(Dimensions < 8U);
    return static_cast<std::uint8_t>(rotate_left<Dimensions>(canonical_label, direction) ^ entry);
}

// Updates the entry vertex after descending into a child subcube.
template <std::uint8_t Dimensions>
[[nodiscard]] constexpr auto compose_entry(
    const std::uint8_t entry, const std::uint8_t gray_index, const std::uint8_t direction
) noexcept -> std::uint8_t {
    static_assert(Dimensions > 0U);
    static_assert(Dimensions < 8U);
    return static_cast<std::uint8_t>(
        entry ^ rotate_left<Dimensions>(subcube_entry<Dimensions>(gray_index), direction)
    );
}

// Updates the direction after descending into a child subcube.
template <std::uint8_t Dimensions>
[[nodiscard]] constexpr auto
compose_direction(const std::uint8_t direction, const std::uint8_t gray_index) noexcept
    -> std::uint8_t {
    static_assert(Dimensions > 0U);
    static_assert(Dimensions < 8U);
    return static_cast<std::uint8_t>(
        (direction + subcube_direction<Dimensions>(gray_index) + 1U) % Dimensions
    );
}

// Packs the selected \(x,y,z\) coordinate bits into a 3-bit cell label.
[[nodiscard]] constexpr auto
cell_label3(const std::span<const std::uint32_t, 3> point, const std::uint8_t bit_index) noexcept
    -> std::uint8_t {
    return static_cast<std::uint8_t>(
        bit_at(point[0], bit_index) | static_cast<std::uint8_t>(bit_at(point[1], bit_index) << 1U) |
        static_cast<std::uint8_t>(bit_at(point[2], bit_index) << 2U)
    );
}

// Marks axes that still contribute a bit at the requested level.
[[nodiscard]] constexpr auto active_axis_mask3(
    const std::span<const std::uint8_t, 3> bits_axis, const std::uint8_t level
) noexcept -> std::uint8_t {
    std::uint8_t mask = 0U;
    for (std::uint8_t axis = 0U; axis < 3U; ++axis) {
        if (bits_axis[axis] > level) {
            mask = static_cast<std::uint8_t>(mask | (1U << axis));
        }
    }
    return mask;
}

// Extracts the compact rank bits from a 3D Gray index.
[[nodiscard]] constexpr auto
gray_rank3(const std::uint8_t free_mask, const std::uint8_t gray_index) noexcept -> std::uint8_t {
    const std::uint8_t masked_free_mask = static_cast<std::uint8_t>(free_mask & kDimensionMask<3U>);
    const std::uint8_t masked_gray_index =
        static_cast<std::uint8_t>(gray_index & kDimensionMask<3U>);
    std::uint8_t rank = 0U;
    for (int bit = 2; bit >= 0; --bit) {
        if (((masked_free_mask >> bit) & 1U) != 0U) {
            const auto shift = static_cast<unsigned int>(bit);
            const auto rank_prefix = static_cast<unsigned int>(rank) << 1U;
            const auto index_bit = (static_cast<unsigned int>(masked_gray_index) >> shift) & 1U;
            rank = static_cast<std::uint8_t>(rank_prefix | index_bit);
        }
    }
    return rank;
}

// Carries both binary and Gray forms reconstructed from compact rank bits.
struct GrayRankInverse3 {
    std::uint8_t gray_index{};
    std::uint8_t gray_code{};
};

// Rebuilds the full 3D Gray index from compact rank bits and fixed pattern bits.
[[nodiscard]] constexpr auto gray_rank_inverse3(
    const std::uint8_t free_mask, const std::uint8_t pattern, const std::uint8_t rank
) noexcept -> GrayRankInverse3 {
    GrayRankInverse3 result{};
    const std::uint8_t masked_free_mask = static_cast<std::uint8_t>(free_mask & kDimensionMask<3U>);
    const auto free_bits = static_cast<unsigned int>(std::popcount(masked_free_mask));
    const std::uint8_t rank_mask =
        free_bits == 0U
            ? std::uint8_t{0U}
            : static_cast<std::uint8_t>((std::uint32_t{1U} << free_bits) - std::uint32_t{1U});
    const std::uint8_t masked_pattern = static_cast<std::uint8_t>(pattern & kDimensionMask<3U>);
    const std::uint8_t masked_rank = static_cast<std::uint8_t>(rank & rank_mask);
    int rank_bit = static_cast<int>(free_bits) - 1;
    std::uint8_t next_index_bit = 0U;

    for (int bit = 2; bit >= 0; --bit) {
        std::uint8_t index_bit = 0U;
        std::uint8_t gray_bit = 0U;

        if (((masked_free_mask >> bit) & 1U) != 0U) {
            index_bit = static_cast<std::uint8_t>((masked_rank >> rank_bit) & 1U);
            gray_bit = static_cast<std::uint8_t>(index_bit ^ next_index_bit);
            --rank_bit;
        } else {
            gray_bit = static_cast<std::uint8_t>((masked_pattern >> bit) & 1U);
            index_bit = static_cast<std::uint8_t>(gray_bit ^ next_index_bit);
        }

        result.gray_index = static_cast<std::uint8_t>(result.gray_index | (index_bit << bit));
        result.gray_code = static_cast<std::uint8_t>(result.gray_code | (gray_bit << bit));
        next_index_bit = index_bit;
    }

    result.gray_index &= kDimensionMask<3U>;
    result.gray_code &= kDimensionMask<3U>;
    return result;
}

} // namespace rch::curves::detail
