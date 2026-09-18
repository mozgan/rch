#pragma once

// ----------------------------------------------------------------------------
// quantization.hpp - deterministic mapping from a closed floating-point range
// to fixed-width integer coordinate codes.
//
// Portability scope:
//   The arithmetic below intentionally uses long double. Boundary-adjacent
//   inputs are claimed bit-stable only inside the tested toolchain envelope,
//   not as a universal floating-point theorem across all long-double models.
//
// Algorithm:
//   - For bit depth \(m\), define \(C_{\max}=2^m-1\), capped at the `uint32_t`
//     maximum when \(m \ge 32\).
//   - Reject non-finite inputs or invalid ranges \(lo \not< hi\) by returning
//     zero.
//   - Clamp boundary values: \(x \le lo \mapsto 0\) and
//     \(x \ge hi \mapsto C_{\max}\).
//   - For interior values, compute
//     \(q=\lfloor ((x-lo)/(hi-lo))\,2^m \rfloor\) in long double and clamp
//     the result to \([0,C_{\max}]\).
//
// Scope: this header provides the uniform mapper only. A companded variant that
// reserves code fractions for the tails outside the core interval was evaluated
// during the design study but is not implemented here, so out-of-core values are
// Winsorized onto the endpoint codes 0 and \(C_{\max}\) rather than resolved.
//
// References:
//   - David Goldberg, What Every Computer Scientist Should Know About
//     Floating-Point Arithmetic, 1991, DOI: 10.1145/103162.103163.
//   - IEEE, IEEE Standard for Floating-Point Arithmetic, 2019,
//     DOI: 10.1109/IEEESTD.2019.8766229.
//   - Robert M. Gray and David L. Neuhoff, Quantization, 1998,
//     DOI: 10.1109/18.720541.
// ----------------------------------------------------------------------------

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <limits>

namespace rch::curves {

// Maximum coordinate precision that fits the `uint32_t` code type.
inline constexpr std::uint8_t kMaxQuantizationBits = 32U;

[[nodiscard]] constexpr auto quantization_max_code(const std::uint8_t bits) noexcept
    -> std::uint32_t {
    if (bits == 0U) {
        return 0U;
    }
    if (bits >= kMaxQuantizationBits) {
        return std::numeric_limits<std::uint32_t>::max();
    }
    return (std::uint32_t{1U} << bits) - std::uint32_t{1U};
}

[[nodiscard]] inline auto quantize_axis(
    const double value, const double lo, const double hi, const std::uint8_t bits
) noexcept -> std::uint32_t {
    if (bits == 0U) {
        return 0U;
    }

    const std::uint8_t effective_bits = std::min(bits, kMaxQuantizationBits);
    const std::uint32_t max_code = quantization_max_code(effective_bits);

    if (!std::isfinite(value) || !std::isfinite(lo) || !std::isfinite(hi) || !(lo < hi)) {
        return 0U;
    }
    if (value <= lo) {
        return 0U;
    }
    if (value >= hi) {
        return max_code;
    }

    const long double width = static_cast<long double>(hi) - static_cast<long double>(lo);
    const long double shifted = static_cast<long double>(value) - static_cast<long double>(lo);
    const long double scaled =
        (shifted / width) * std::ldexp(1.0L, static_cast<int>(effective_bits));
    const long double floored = std::floor(scaled);

    if (!(floored > 0.0L)) {
        return 0U;
    }
    if (floored >= static_cast<long double>(max_code)) {
        return max_code;
    }
    return static_cast<std::uint32_t>(floored);
}

} // namespace rch::curves
