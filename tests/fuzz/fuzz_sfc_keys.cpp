// ----------------------------------------------------------------------------
// fuzz_sfc_keys.cpp — libFuzzer harness: space-filling curve encoder/decoder
// round-trip + CurveKey sorting invariants
//
// ----------------------------------------------------------------------------

#include <algorithm>
#include <array>
#include <bit>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <vector>

#include "rch/curves/curve_key.hpp"
#include "rch/curves/hilbert3_compact.hpp"
#include "rch/curves/hilbert3_standard.hpp"
#include "rch/curves/morton3.hpp"

namespace {

[[nodiscard]] auto read_u64(const std::uint8_t* data, const std::size_t size, const std::size_t off)
    -> std::uint64_t {
    std::uint64_t value = 0U;
    if (off < size) {
        const std::size_t available = std::min<std::size_t>(sizeof(value), size - off);
        std::memcpy(&value, data + off, available);
    }
    return value;
}

[[nodiscard]] auto
read_double(const std::uint8_t* data, const std::size_t size, const std::size_t off) -> double {
    return std::bit_cast<double>(read_u64(data, size, off));
}

void exercise_space_filling_curves(
    const rch::curves::Point3u32& point, const rch::curves::BitsAxis3& bits_axis
) {
    const auto compact = rch::curves::Hilbert3Compact::encode(point, bits_axis);
    if (compact.has_value()) {
        const auto decoded = rch::curves::Hilbert3Compact::decode(*compact, bits_axis);
        if (!decoded.has_value() || *decoded != point) {
            std::abort();
        }
    }

    const auto standard_sum = static_cast<std::uint16_t>(
        static_cast<std::uint16_t>(bits_axis[0]) + static_cast<std::uint16_t>(bits_axis[1]) +
        static_cast<std::uint16_t>(bits_axis[2])
    );
    const std::uint8_t standard_bits = static_cast<std::uint8_t>(standard_sum % 24U);
    const auto standard = rch::curves::Hilbert3Standard::encode(point, standard_bits);
    if (standard.has_value()) {
        const auto decoded = rch::curves::Hilbert3Standard::decode(*standard, standard_bits);
        if (!decoded.has_value() || *decoded != point) {
            std::abort();
        }
    }

    (void)rch::curves::Morton3::encode(point, standard_bits);
}

} // namespace

extern "C" int LLVMFuzzerTestOneInput(const std::uint8_t* data, const std::size_t size) {
    const rch::curves::Point3u32 point{
        static_cast<std::uint32_t>(read_u64(data, size, 0U)),
        static_cast<std::uint32_t>(read_u64(data, size, 8U)),
        static_cast<std::uint32_t>(read_u64(data, size, 16U)),
    };
    const rch::curves::BitsAxis3 bits_axis{
        static_cast<std::uint8_t>(read_u64(data, size, 24U) & 0x3FU),
        static_cast<std::uint8_t>(read_u64(data, size, 25U) & 0x3FU),
        static_cast<std::uint8_t>(read_u64(data, size, 26U) & 0x3FU),
    };
    exercise_space_filling_curves(point, bits_axis);

    const std::size_t key_count =
        static_cast<std::size_t>((read_u64(data, size, 27U) % UINT64_C(16)) + UINT64_C(1));
    std::vector<rch::curves::CurveKey> keys;
    keys.reserve(key_count);
    for (std::size_t i = 0U; i < key_count; ++i) {
        const std::size_t off = 35U + (32U * i);
        keys.push_back(
            rch::curves::CurveKey{
                read_u64(data, size, off),
                read_double(data, size, off + 8U),
                read_double(data, size, off + 16U),
                read_double(data, size, off + 24U),
                i,
            }
        );
    }
    std::ranges::sort(keys, [](const rch::curves::CurveKey& lhs, const rch::curves::CurveKey& rhs) {
        return lhs < rhs;
    });
    return 0;
}
