#pragma once

// ----------------------------------------------------------------------------
// metrics/determinism.hpp - determinism metric wrappers.
//
// Algorithm:
//   - Encode each integer into canonical little-endian bytes so host endianness
//     cannot change the payload.
//   - Concatenate permutation ids, per-axis bit counts, and quantized keys.
//   - Hash the byte payload with SHA-256 to obtain a reproducibility digest.
//   - Compare two digests bytewise and report the first differing byte.
//
// References:
//   - National Institute of Standards and Technology, Secure Hash Standard
//     (SHS), FIPS PUB 180-4, 2015, DOI: 10.6028/NIST.FIPS.180-4.
//   - ISO/IEC, ISO/IEC 14882:2020 Programming languages - C++, 2020.
// ----------------------------------------------------------------------------

#include <array>
#include <bit>
#include <cstddef>
#include <cstdint>
#include <span>
#include <vector>

#include "rch/core/sha256.hpp"

namespace rch::metrics {

// Fixed-size SHA-256 digest.
using Sha256Digest = std::array<std::uint8_t, 32U>;

// Serializes a 64-bit integer with a stable little-endian byte order.
[[nodiscard]] inline auto u64_to_bytes_little_endian(std::uint64_t value)
    -> std::array<std::uint8_t, 8U> {
    if constexpr (std::endian::native == std::endian::little) {
        return std::bit_cast<std::array<std::uint8_t, 8U>>(value);
    } else {
        std::array<std::uint8_t, 8U> bytes{};
        for (std::size_t i = 0U; i < 8U; ++i) {
            bytes[i] = static_cast<std::uint8_t>((value >> (8U * i)) & 0xFFU);
        }
        return bytes;
    }
}

// Builds the canonical integer payload used for determinism checks.
[[nodiscard]] inline auto compose_integer_payload(
    std::span<const std::uint64_t> permutation,
    std::span<const std::uint8_t, 3U> bits_axis,
    std::span<const std::uint64_t> quantized_keys
) -> std::vector<std::uint8_t> {
    std::vector<std::uint8_t> buffer;
    buffer.reserve(
        (permutation.size() + quantized_keys.size()) * sizeof(std::uint64_t) + bits_axis.size()
    );
    for (const auto v : permutation) {
        const auto bytes = u64_to_bytes_little_endian(v);
        buffer.insert(buffer.end(), bytes.begin(), bytes.end());
    }
    buffer.insert(buffer.end(), bits_axis.begin(), bits_axis.end());
    for (const auto v : quantized_keys) {
        const auto bytes = u64_to_bytes_little_endian(v);
        buffer.insert(buffer.end(), bytes.begin(), bytes.end());
    }
    return buffer;
}

// Hashes the canonical payload with SHA-256.
[[nodiscard]] inline auto sha256_integer_payload(
    std::span<const std::uint64_t> permutation,
    std::span<const std::uint8_t, 3U> bits_axis,
    std::span<const std::uint64_t> quantized_keys
) -> Sha256Digest {
    const auto bytes = compose_integer_payload(permutation, bits_axis, quantized_keys);
    return rch::core::sha256_bytes(std::span<const std::uint8_t>{bytes});
}

// Byte-level equality result for two SHA-256 digests.
struct DivergenceReport {
    bool identical{};
    std::size_t first_diff_byte{};
};

// Compares two digests and returns the first mismatch location.
[[nodiscard]] inline constexpr auto
compare_digests(const Sha256Digest& lhs, const Sha256Digest& rhs) noexcept -> DivergenceReport {
    DivergenceReport report{};
    report.identical = true;
    report.first_diff_byte = lhs.size();
    for (std::size_t i = 0U; i < lhs.size(); ++i) {
        if (lhs[i] != rhs[i]) {
            report.identical = false;
            report.first_diff_byte = i;
            return report;
        }
    }
    return report;
}

} // namespace rch::metrics
