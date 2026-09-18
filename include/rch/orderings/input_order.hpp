#pragma once

// ----------------------------------------------------------------------------
// input_order.hpp - identity baseline wrapper.
//
// Algorithm:
//   - Set `config.method = InputOrder`.
//   - Delegate to `order_point_cloud`, which returns \(o_i=i\).
//
// References:
//   - ISO/IEC, ISO/IEC 14882:2020 Programming languages - C++, 2020.
// ----------------------------------------------------------------------------

#include <span>

#include "rch/orderings/orderer.hpp"

namespace rch::orderings {

[[nodiscard]] inline auto
input_order(std::span<const double> points_xyz, OrderingConfig config = {}) -> OrderingExpected {
    config.method = OrderingMethod::InputOrder;
    return order_point_cloud(points_xyz, config);
}

} // namespace rch::orderings
