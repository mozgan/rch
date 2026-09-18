#include <cmath>
#include <cstddef>
#include <limits>
#include <span>
#include <vector>

#include "rch/core/matrix3.hpp"
#include "rch/robust/median_mad.hpp"

#include <gtest/gtest.h>

namespace {

using rch::core::Vec3;

TEST(MedianMadEdge, EmptyInputReturnsNullopt) {
    const std::vector<double> empty;
    EXPECT_FALSE(rch::robust::median(std::span<const double>{empty}).has_value());
    EXPECT_FALSE(rch::robust::lower_median(std::span<const double>{empty}).has_value());
}

TEST(MedianMadEdge, SingleValueReturnsThatValue) {
    const std::vector<double> single{42.0};
    EXPECT_EQ(rch::robust::median(std::span<const double>{single}), 42.0);
    EXPECT_EQ(rch::robust::lower_median(std::span<const double>{single}), 42.0);
}

TEST(MedianMadEdge, OddNUsesMiddle) {
    const std::vector<double> values{3.0, 1.0, 2.0, 5.0, 4.0}; // sorted: 1,2,3,4,5
    EXPECT_EQ(rch::robust::median(std::span<const double>{values}), 3.0);
    EXPECT_EQ(rch::robust::lower_median(std::span<const double>{values}), 3.0);
}

TEST(MedianMadEdge, EvenNDistinguishesMedianAndLowerMedian) {
    const std::vector<double> values{1.0, 2.0, 3.0, 4.0};
    EXPECT_EQ(rch::robust::median(std::span<const double>{values}), 2.5);
    EXPECT_EQ(rch::robust::lower_median(std::span<const double>{values}), 2.0);
}

TEST(MedianMadEdge, EvenMedianAvoidsIntermediateOverflow) {
    const std::vector<double> values{
        std::numeric_limits<double>::max(),
        std::numeric_limits<double>::max(),
    };

    const auto result = rch::robust::median(std::span<const double>{values});

    ASSERT_TRUE(result.has_value());
    EXPECT_EQ(*result, std::numeric_limits<double>::max());
}

TEST(MedianMadEdge, AllSameValuesGiveZeroMad) {
    const std::vector<double> values{7.0, 7.0, 7.0, 7.0};
    EXPECT_EQ(rch::robust::mad(std::span<const double>{values}, 7.0), 0.0);
}

TEST(MedianMadEdge, MadWithCustomConsistencyOne) {
    const std::vector<double> values{0.0, 1.0, 2.0, 3.0};
    EXPECT_NEAR(rch::robust::mad(std::span<const double>{values}, 1.5, 1.0), 1.0, 1.0e-14);
}

TEST(MedianMadEdge, MadWithDefaultConsistencyMatchesPinnedConstant) {
    const std::vector<double> values{0.0, 1.0, 2.0, 3.0};
    EXPECT_NEAR(rch::robust::mad(std::span<const double>{values}, 1.5), 1.482602218505602, 1.0e-14);
}

TEST(MedianMadComponentwise, AxisAlignedMedian) {
    const std::vector<Vec3<double>> points{
        Vec3<double>{1.0, 4.0, 7.0},
        Vec3<double>{2.0, 5.0, 8.0},
        Vec3<double>{3.0, 6.0, 9.0},
    };
    const auto med = rch::robust::componentwise_median(std::span<const Vec3<double>>{points});
    EXPECT_EQ(med[0], 2.0);
    EXPECT_EQ(med[1], 5.0);
    EXPECT_EQ(med[2], 8.0);
}

TEST(MedianMadComponentwise, ZeroMadAxisFallsToScaleFloor) {
    const std::vector<Vec3<double>> points{
        Vec3<double>{1.0, 1.0, 1.0},
        Vec3<double>{2.0, 1.0, 5.0},
        Vec3<double>{3.0, 1.0, 9.0},
    };
    const auto center = rch::robust::componentwise_median(std::span<const Vec3<double>>{points});
    const auto scale =
        rch::robust::componentwise_mad_scale(std::span<const Vec3<double>>{points}, center);
    EXPECT_NEAR(scale[0], rch::robust::kMadNormalConsistency, 1.0e-15);
    EXPECT_NEAR(scale[1], 1.0e-12, 1.0e-25);
    EXPECT_NEAR(scale[2], 4.0 * rch::robust::kMadNormalConsistency, 1.0e-14);
}

TEST(MedianMadConstants, NormalConsistencyMatchesPinnedValue) {
    EXPECT_EQ(rch::robust::kMadNormalConsistency, 1.482602218505602);
}

} // namespace
