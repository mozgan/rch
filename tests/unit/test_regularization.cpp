#include <cstddef>
#include <limits>

#include "rch/core/matrix3.hpp"
#include "rch/robust/regularization.hpp"

#include <gtest/gtest.h>

namespace {

using rch::core::Matrix3;
using rch::robust::regularize_spd;

TEST(RegularizeSpd, WellConditionedReturnsUntouched) {
    Matrix3<double> spd{};
    spd(0U, 0U) = 4.0;
    spd(1U, 1U) = 5.0;
    spd(2U, 2U) = 6.0;

    const auto result = regularize_spd(spd);
    EXPECT_FALSE(result.applied);
    EXPECT_FALSE(result.rank_deficient);
    EXPECT_EQ(result.ridge, 0.0);
    for (std::size_t axis = 0U; axis < 3U; ++axis) {
        EXPECT_EQ(result.scatter(axis, axis), spd(axis, axis));
    }
}

TEST(RegularizeSpd, ZeroEigenvalueTriggersRidgeAndRankDeficient) {
    Matrix3<double> rank2{};
    rank2(0U, 0U) = 1.0;
    rank2(1U, 1U) = 1.0;
    rank2(2U, 2U) = 0.0;

    const auto result = regularize_spd(rank2);
    EXPECT_TRUE(result.applied);
    EXPECT_TRUE(result.rank_deficient);
    EXPECT_GT(result.ridge, 0.0);
    EXPECT_GT(result.scatter(2U, 2U), 0.0); // 0 + ridge > 0
    EXPECT_GT(result.scatter(0U, 0U), 1.0); // 1 + ridge > 1
}

TEST(RegularizeSpd, NaNComponentMarksRankDeficient) {
    Matrix3<double> nan_matrix{};
    nan_matrix(0U, 0U) = std::numeric_limits<double>::quiet_NaN();
    nan_matrix(1U, 1U) = 1.0;
    nan_matrix(2U, 2U) = 1.0;

    const auto result = regularize_spd(nan_matrix);
    EXPECT_TRUE(result.rank_deficient);
    EXPECT_FALSE(result.applied);
    EXPECT_EQ(result.ridge, 0.0);
}

TEST(RegularizeSpd, NaNRelativeFloorUsesDefaultFloor) {
    Matrix3<double> spd{};
    spd(0U, 0U) = 4.0;
    spd(1U, 1U) = 5.0;
    spd(2U, 2U) = 6.0;

    const auto result = regularize_spd(spd, std::numeric_limits<double>::quiet_NaN());

    EXPECT_FALSE(result.applied);
    EXPECT_FALSE(result.rank_deficient);
    EXPECT_EQ(result.ridge, 0.0);
}

TEST(RegularizeSpd, LargeFiniteSpdDoesNotRegularizeFromDeterminantFloorOverflow) {
    Matrix3<double> spd{};
    spd(0U, 0U) = 1.0e150;
    spd(1U, 1U) = 2.0e150;
    spd(2U, 2U) = 3.0e150;

    const auto result = regularize_spd(spd);

    EXPECT_FALSE(result.applied);
    EXPECT_FALSE(result.rank_deficient);
    EXPECT_EQ(result.ridge, 0.0);
    EXPECT_DOUBLE_EQ(result.scatter(0U, 0U), spd(0U, 0U));
    EXPECT_DOUBLE_EQ(result.scatter(1U, 1U), spd(1U, 1U));
    EXPECT_DOUBLE_EQ(result.scatter(2U, 2U), spd(2U, 2U));
}

TEST(RegularizeSpd, TinyWellConditionedSpdDoesNotRegularizeFromAbsoluteFloor) {
    Matrix3<double> spd{};
    spd(0U, 0U) = 1.0e-300;
    spd(1U, 1U) = 2.0e-300;
    spd(2U, 2U) = 3.0e-300;

    const auto result = regularize_spd(spd);

    EXPECT_FALSE(result.applied);
    EXPECT_FALSE(result.rank_deficient);
    EXPECT_EQ(result.ridge, 0.0);
    EXPECT_DOUBLE_EQ(result.scatter(0U, 0U), spd(0U, 0U));
    EXPECT_DOUBLE_EQ(result.scatter(1U, 1U), spd(1U, 1U));
    EXPECT_DOUBLE_EQ(result.scatter(2U, 2U), spd(2U, 2U));
}

TEST(RegularizeSpd, LargeRelativeFloorForcesRegularizationOnSpd) {
    Matrix3<double> spd{};
    spd(0U, 0U) = 1.0;
    spd(1U, 1U) = 1.0;
    spd(2U, 2U) = 1.0;

    const auto result = regularize_spd(spd, 1.0);
    EXPECT_TRUE(result.applied);
    EXPECT_FALSE(result.rank_deficient); // min_eigenvalue=1 > 0
    EXPECT_GT(result.ridge, 0.0);
}

} // namespace
