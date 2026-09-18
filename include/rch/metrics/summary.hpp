#pragma once

// ----------------------------------------------------------------------------
// metrics/summary.hpp - RCH metrics facade.
//
// Algorithm:
//   - Re-export metric helpers by including the cache, determinism, locality,
//     memory, ordering, outlier, and timing headers.
//   - This facade defines no separate runtime algorithm.
//
// References:
//   - Craig Gotsman and Michael Lindenbaum, On the metric properties of
//     discrete space-filling curves, 1996, DOI: 10.1109/83.499920.
//   - National Institute of Standards and Technology, Secure Hash Standard
//     (SHS), FIPS PUB 180-4, 2015, DOI: 10.6028/NIST.FIPS.180-4.
//   - M. G. Kendall, A New Measure of Rank Correlation, 1938,
//     DOI: 10.1093/biomet/30.1-2.81.
// ----------------------------------------------------------------------------

#include "rch/metrics/cache.hpp"
#include "rch/metrics/determinism.hpp"
#include "rch/metrics/locality.hpp"
#include "rch/metrics/memory.hpp"
#include "rch/metrics/ordering.hpp"
#include "rch/metrics/outlier.hpp"
#include "rch/metrics/timing.hpp"
