#pragma once

// ----------------------------------------------------------------------------
// lexicographic_order.hpp - coordinate lexicographic baseline wrapper.
//
// Algorithm:
//   - Set `config.method = Lexicographic`.
//   - Delegate to `order_point_cloud`, which sorts by \((x,y,z,i)\).
//
// References:
//   - ISO/IEC, ISO/IEC 14882:2020 Programming languages - C++, 2020.
// ----------------------------------------------------------------------------

#include <span>

#include "rch/orderings/orderer.hpp"

namespace rch::orderings {

[[nodiscard]] inline auto
lexicographic_order(std::span<const double> points_xyz, OrderingConfig config = {})
    -> OrderingExpected {
    config.method = OrderingMethod::Lexicographic;
    return order_point_cloud(points_xyz, config);
}

} // namespace rch::orderings
