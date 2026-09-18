#pragma once

// ----------------------------------------------------------------------------
// pca_compact_hilbert_order.hpp - sample-PCA compact Hilbert wrapper.
//
// Algorithm:
//   - Set `config.method = PcaCompactHilbert`.
//   - Force `FrameEstimator::SampleCovariance`.
//   - Delegate to `order_point_cloud`, which builds a covariance eigenframe and
//     sorts compact Hilbert keys in frame coordinates.
//
// References:
//   - I. T. Jolliffe, Principal Component Analysis, 1986,
//     DOI: 10.1007/978-1-4757-1904-8.
//   - Chris H. Hamilton and Andrew Rau-Chaplin, Compact Hilbert indices:
//     Space-filling curves for domains with unequal side lengths, 2008,
//     DOI: 10.1016/j.ipl.2007.08.034.
// ----------------------------------------------------------------------------

#include <span>

#include "rch/orderings/orderer.hpp"

namespace rch::orderings {

[[nodiscard]] inline auto
pca_compact_hilbert_order(std::span<const double> points_xyz, OrderingConfig config = {})
    -> OrderingExpected {
    config.method = OrderingMethod::PcaCompactHilbert;
    config.frame = FrameEstimator::SampleCovariance;
    return order_point_cloud(points_xyz, config);
}

} // namespace rch::orderings
