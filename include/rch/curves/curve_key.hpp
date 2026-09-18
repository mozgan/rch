#pragma once

// ----------------------------------------------------------------------------
// curve_key.hpp - sortable curve key with deterministic floating-point
// tie-break fields.
//
// Algorithm:
//   - Build a lexicographic tuple
//     \((H,K_x,K_y,K_z,i)\), where \(H\) is the curve key and \(i\) is the
//     original row index.
//   - Convert each floating tie-break coordinate \(y_j\) to an integer
//     total-order key \(K_j\), so NaNs, infinities, signed zeros, and finite
//     values are compared deterministically.
//   - Implement equality and ordering by comparing the tuple directly.
//
// References:
//   - IEEE, IEEE Standard for Floating-Point Arithmetic, 2019,
//     DOI: 10.1109/IEEESTD.2019.8766229.
//   - Chris H. Hamilton and Andrew Rau-Chaplin, Compact Hilbert indices:
//     Space-filling curves for domains with unequal side lengths, 2008,
//     DOI: 10.1016/j.ipl.2007.08.034.
// ----------------------------------------------------------------------------

#include <cstdint>
#include <tuple>

#include "rch/core/matrix3.hpp"

namespace rch::curves {

// Delegates double ordering to the core IEEE-754 total-order key helper.
[[nodiscard]] constexpr auto double_total_order_key(const double value) noexcept -> std::uint64_t {
    return rch::core::double_total_order_key(value);
}

// Stores the curve index plus deterministic geometric and input-order tie-breakers.
struct CurveKey {
    std::uint64_t hilbert{};
    double y_x{};
    double y_y{};
    double y_z{};
    std::uint64_t raw_idx{};

    // Tuple form used by equality and strict ordering.
    using OrderTuple =
        std::tuple<std::uint64_t, std::uint64_t, std::uint64_t, std::uint64_t, std::uint64_t>;

    // Converts all ordering fields to comparable integer keys.
    [[nodiscard]] constexpr auto order_tuple() const noexcept -> OrderTuple {
        return {
            hilbert,
            double_total_order_key(y_x),
            double_total_order_key(y_y),
            double_total_order_key(y_z),
            raw_idx
        };
    }

    // Compares the complete deterministic ordering tuple.
    [[nodiscard]] friend constexpr auto
    operator==(const CurveKey& lhs, const CurveKey& rhs) noexcept -> bool {
        return lhs.order_tuple() == rhs.order_tuple();
    }

    // Orders first by curve index, then coordinates, then original row id.
    [[nodiscard]] friend constexpr auto operator<(const CurveKey& lhs, const CurveKey& rhs) noexcept
        -> bool {
        return lhs.order_tuple() < rhs.order_tuple();
    }
};

} // namespace rch::curves
