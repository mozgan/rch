#include <algorithm>
#include <cmath>
#include <cstdint>
#include <limits>
#include <vector>

#include "rch/curves/curve_key.hpp"

#include <gtest/gtest.h>

namespace {

using rch::curves::CurveKey;
using rch::curves::double_total_order_key;

TEST(CurveKey, OrdersByHilbertThenContinuousTiesThenRawIndex) {
    std::vector<CurveKey> keys{
        CurveKey{2U, 0.0, 0.0, 0.0, 0U},
        CurveKey{1U, 0.0, 0.0, 0.0, 2U},
        CurveKey{1U, 0.0, 0.0, 0.0, 1U},
        CurveKey{1U, -1.0, 0.0, 0.0, 9U},
        CurveKey{1U, 0.0, -1.0, 0.0, 3U},
    };

    std::sort(keys.begin(), keys.end());

    EXPECT_EQ(keys[0].raw_idx, 9U);
    EXPECT_EQ(keys[1].raw_idx, 3U);
    EXPECT_EQ(keys[2].raw_idx, 1U);
    EXPECT_EQ(keys[3].raw_idx, 2U);
    EXPECT_EQ(keys[4].hilbert, 2U);
}

TEST(CurveKey, DoubleTotalOrderDistinguishesSignedZeroAndNaNBits) {
    const double negative_zero = -0.0;
    const double positive_zero = 0.0;
    const double quiet_nan = std::numeric_limits<double>::quiet_NaN();

    EXPECT_LT(double_total_order_key(negative_zero), double_total_order_key(positive_zero));
    EXPECT_NE(double_total_order_key(quiet_nan), double_total_order_key(positive_zero));

    std::vector<CurveKey> keys{
        CurveKey{0U, quiet_nan, 0.0, 0.0, 2U},
        CurveKey{0U, positive_zero, 0.0, 0.0, 1U},
        CurveKey{0U, negative_zero, 0.0, 0.0, 0U},
    };

    std::sort(keys.begin(), keys.end());
    EXPECT_EQ(keys.front().raw_idx, 0U);
    EXPECT_EQ(keys.back().raw_idx, 2U);
}

TEST(CurveKey, DoubleTotalOrderPlacesInfinitiesAtBoundaries) {
    const double pos_inf = std::numeric_limits<double>::infinity();
    const double neg_inf = -std::numeric_limits<double>::infinity();
    const double pos_min = std::numeric_limits<double>::min();
    const double neg_min = -pos_min;

    EXPECT_LT(double_total_order_key(neg_inf), double_total_order_key(neg_min));
    EXPECT_LT(double_total_order_key(neg_min), double_total_order_key(0.0));
    EXPECT_LT(double_total_order_key(0.0), double_total_order_key(pos_min));
    EXPECT_LT(double_total_order_key(pos_min), double_total_order_key(pos_inf));
}

TEST(CurveKey, FullTieBreakChainOrdersByRawIndexLast) {
    std::vector<CurveKey> keys{
        CurveKey{42U, 1.0, 2.0, 3.0, 7U},
        CurveKey{42U, 1.0, 2.0, 3.0, 5U},
        CurveKey{42U, 1.0, 2.0, 3.0, 9U},
    };

    std::sort(keys.begin(), keys.end());
    EXPECT_EQ(keys[0].raw_idx, 5U);
    EXPECT_EQ(keys[1].raw_idx, 7U);
    EXPECT_EQ(keys[2].raw_idx, 9U);
}

TEST(CurveKey, EqualityRespectsTotalOrderingNotIeeeNanRule) {
    const double quiet_nan = std::numeric_limits<double>::quiet_NaN();
    const CurveKey lhs{0U, quiet_nan, 0.0, 0.0, 0U};
    const CurveKey rhs{0U, quiet_nan, 0.0, 0.0, 0U};
    EXPECT_TRUE(lhs == rhs);
}

} // namespace
