#pragma once

// ----------------------------------------------------------------------------
// robust_frame_morton_order.hpp - robust-frame Morton ablation wrapper.
//
// Algorithm:
//   - Set `config.method = RobustFrameMorton`.
//   - Force the default robust frame estimator to DetMCD.
//   - Delegate to `order_point_cloud`, which builds the robust frame and sorts
//     Morton keys in frame coordinates.
//
// References:
//   - Mia Hubert, Peter J. Rousseeuw, and Tim Verdonck, A Deterministic
//     Algorithm for Robust Location and Scatter, 2012,
//     DOI: 10.1080/10618600.2012.672100.
//   - G. M. Morton, A Computer Oriented Geodetic Data Base and a New Technique
//     in File Sequencing, 1966.
// ----------------------------------------------------------------------------

#include <span>

#include "rch/orderings/orderer.hpp"

namespace rch::orderings {

[[nodiscard]] inline auto
robust_frame_morton_order(std::span<const double> points_xyz, OrderingConfig config = {})
    -> OrderingExpected {
    config.method = OrderingMethod::RobustFrameMorton;
    config.frame = FrameEstimator::DetMCD;
    return order_point_cloud(points_xyz, config);
}

} // namespace rch::orderings
