#pragma once

// ----------------------------------------------------------------------------
// compact_hilbert_order.hpp - AABB compact Hilbert strategy wrapper.
//
// Algorithm:
//   - Set `config.method = CompactHilbertAABB`.
//   - Delegate to `order_point_cloud`, which allocates per-axis bit depths,
//     quantizes the raw AABB, and sorts compact Hilbert keys.
//
// References:
//   - Chris H. Hamilton and Andrew Rau-Chaplin, Compact Hilbert indices:
//     Space-filling curves for domains with unequal side lengths, 2008,
//     DOI: 10.1016/j.ipl.2007.08.034.
//   - Craig Gotsman and Michael Lindenbaum, On the metric properties of
//     discrete space-filling curves, 1996, DOI: 10.1109/83.499920.
// ----------------------------------------------------------------------------

#include <span>

#include "rch/orderings/orderer.hpp"

namespace rch::orderings {

[[nodiscard]] inline auto
compact_hilbert_order(std::span<const double> points_xyz, OrderingConfig config = {})
    -> OrderingExpected {
    config.method = OrderingMethod::CompactHilbertAABB;
    return order_point_cloud(points_xyz, config);
}

} // namespace rch::orderings
