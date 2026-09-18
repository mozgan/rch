#pragma once

// ----------------------------------------------------------------------------
// morton_order.hpp - Morton/Z-order strategy wrapper.
//
// Algorithm:
//   - Set `config.method = Morton`.
//   - Delegate to `order_point_cloud`, which quantizes points and sorts Morton
//     interleaving keys.
//
// References:
//   - G. M. Morton, A Computer Oriented Geodetic Data Base and a New Technique
//     in File Sequencing, 1966.
//   - Jeroen Baert, libmorton, 2016.
// ----------------------------------------------------------------------------

#include <span>

#include "rch/orderings/orderer.hpp"

namespace rch::orderings {

[[nodiscard]] inline auto
morton_order(std::span<const double> points_xyz, OrderingConfig config = {}) -> OrderingExpected {
    config.method = OrderingMethod::Morton;
    return order_point_cloud(points_xyz, config);
}

} // namespace rch::orderings
