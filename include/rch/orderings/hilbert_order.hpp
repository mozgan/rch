#pragma once

// ----------------------------------------------------------------------------
// hilbert_order.hpp - isotropic/equal-bit Hilbert strategy wrapper.
//
// Algorithm:
//   - Set `config.method = IsotropicHilbert`.
//   - Delegate to `order_point_cloud`, which quantizes all axes at equal depth
//     and sorts standard 3D Hilbert keys.
//
// References:
//   - David Hilbert, Ueber die stetige Abbildung einer Linie auf ein
//     Flaechenstueck, 1891, DOI: 10.1007/BF01199431.
//   - Bongki Moon, H. V. Jagadish, Christos Faloutsos, and Joel H. Saltz,
//     Analysis of the clustering properties of the Hilbert space-filling curve,
//     2001, DOI: 10.1109/69.908985.
// ----------------------------------------------------------------------------

#include <span>

#include "rch/orderings/orderer.hpp"

namespace rch::orderings {

[[nodiscard]] inline auto
hilbert_order(std::span<const double> points_xyz, OrderingConfig config = {}) -> OrderingExpected {
    config.method = OrderingMethod::IsotropicHilbert;
    return order_point_cloud(points_xyz, config);
}

} // namespace rch::orderings
