#pragma once

// ----------------------------------------------------------------------------
// robust_compact_hilbert_order.hpp - RCH robust compact Hilbert wrapper.
//
// Algorithm:
//   - Set `config.method = RCH`.
//   - Force the default robust frame estimator to DetMCD.
//   - Preserve the caller's bit allocator; the library default is
//     `FrameCoreOccupancy`.
//   - Delegate to `order_point_cloud`, which builds the robust frame and sorts
//     compact Hilbert keys in frame coordinates.
//
// References:
//   - Mia Hubert, Peter J. Rousseeuw, and Tim Verdonck, A Deterministic
//     Algorithm for Robust Location and Scatter, 2012,
//     DOI: 10.1080/10618600.2012.672100.
//   - Chris H. Hamilton and Andrew Rau-Chaplin, Compact Hilbert indices:
//     Space-filling curves for domains with unequal side lengths, 2008,
//     DOI: 10.1016/j.ipl.2007.08.034.
// ----------------------------------------------------------------------------

#include <span>

#include "rch/orderings/orderer.hpp"

namespace rch::orderings {

[[nodiscard]] inline auto
robust_compact_hilbert_order(std::span<const double> points_xyz, OrderingConfig config = {})
    -> OrderingExpected {
    config.method = OrderingMethod::RCH;
    config.frame = FrameEstimator::DetMCD;
    return order_point_cloud(points_xyz, config);
}

} // namespace rch::orderings
