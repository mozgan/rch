// ----------------------------------------------------------------------------
// fuzz_quantizer.cpp — libFuzzer (LLVM) harness: `quantize_axis` + occupancy
// `allocate_occupancy_bits` invariants
//
// ----------------------------------------------------------------------------

#include <algorithm>
#include <array>
#include <bit>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <cstring>

#include "rch/core/matrix3.hpp"
#include "rch/curves/bit_allocation_occupancy.hpp"
#include "rch/curves/quantization.hpp"

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

} // namespace

extern "C" int LLVMFuzzerTestOneInput(const std::uint8_t* data, const std::size_t size) {
    const double value = read_double(data, size, 0U);
    const double lo = read_double(data, size, 8U);
    const double hi = read_double(data, size, 16U);
    const auto bits = static_cast<std::uint8_t>(read_u64(data, size, 24U) & 0xFFU);

    const std::uint32_t code = rch::curves::quantize_axis(value, lo, hi, bits);
    const std::uint8_t effective_bits = std::min(bits, rch::curves::kMaxQuantizationBits);
    if (code > rch::curves::quantization_max_code(effective_bits)) {
        std::abort();
    }

    const rch::core::Vec3<double> half_extents{
        read_double(data, size, 32U),
        read_double(data, size, 40U),
        read_double(data, size, 48U),
    };
    const std::size_t n_core =
        static_cast<std::size_t>((read_u64(data, size, 56U) % UINT64_C(4096)) + UINT64_C(1));
    const auto allocation = rch::curves::allocate_occupancy_bits(half_extents, n_core);
    if (!rch::curves::within_uint64_budget(allocation.budget.bits)) {
        std::abort();
    }
    return 0;
}
