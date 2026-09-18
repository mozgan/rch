#include <array>
#include <cstdint>

#include "rch/core/matrix3.hpp"
#include "rch/curves/bit_allocation_monotone.hpp"

#include <gtest/gtest.h>

namespace {

using rch::core::Vec3;
using rch::curves::allocate_monotone_half_bits;
using rch::curves::MonotoneHalfBitAllocationOptions;
using rch::curves::within_uint64_budget;

TEST(MonotoneHalfBitAllocation, ZeroMinimumMatchesHamiltonHalfBudgetShape) {
    const Vec3<double> half_extents{3.0, 2.0, 1.0};
    const MonotoneHalfBitAllocationOptions options{
        0U,
        63U,
        21U,
    };

    const auto allocation = allocate_monotone_half_bits(half_extents, 10U, options);

    EXPECT_EQ(allocation.target_total_bits, 15U);
    EXPECT_EQ(allocation.ranked_axes, (std::array<std::uint8_t, 3>{0U, 1U, 2U}));
    EXPECT_EQ(allocation.raw_bits, (std::array<std::uint8_t, 3>{10U, 5U, 0U}));
    EXPECT_EQ(allocation.budget.bits, allocation.raw_bits);
    EXPECT_TRUE(within_uint64_budget(allocation.budget.bits));
}

TEST(MonotoneHalfBitAllocation, DefaultMinimumKeepsAllAxesRepresentable) {
    const Vec3<double> half_extents{3.0, 2.0, 1.0};

    const auto allocation = allocate_monotone_half_bits(half_extents, 10U);

    EXPECT_EQ(allocation.target_total_bits, 15U);
    EXPECT_EQ(allocation.raw_bits, (std::array<std::uint8_t, 3>{10U, 4U, 1U}));
    EXPECT_EQ(allocation.budget.total_bits, 15U);
}

TEST(MonotoneHalfBitAllocation, AxisRankingFollowsFinitePositiveExtent) {
    const Vec3<double> half_extents{5.0, 1.0, 2.0};

    const auto allocation = allocate_monotone_half_bits(half_extents, 10U);

    EXPECT_EQ(allocation.ranked_axes, (std::array<std::uint8_t, 3>{0U, 2U, 1U}));
    EXPECT_EQ(allocation.raw_bits, (std::array<std::uint8_t, 3>{10U, 1U, 4U}));
}

TEST(MonotoneHalfBitAllocation, NonFiniteOrNonpositiveAxesAreLowestRank) {
    const Vec3<double> half_extents{0.0, 4.0, 2.0};

    const auto allocation = allocate_monotone_half_bits(half_extents, 8U);

    EXPECT_EQ(allocation.ranked_axes, (std::array<std::uint8_t, 3>{1U, 2U, 0U}));
    EXPECT_GE(allocation.raw_bits[1], allocation.raw_bits[2]);
    EXPECT_GE(allocation.raw_bits[2], allocation.raw_bits[0]);
}

TEST(MonotoneHalfBitAllocation, EqualExtentsUseStableAxisIdTieBreak) {
    const Vec3<double> half_extents{1.0, 1.0, 1.0};

    const auto allocation = allocate_monotone_half_bits(half_extents, 8U);

    EXPECT_EQ(allocation.ranked_axes, (std::array<std::uint8_t, 3>{0U, 1U, 2U}));
}

TEST(MonotoneHalfBitAllocation, AllNonPositiveExtentsFallBackToStableOrderAndMinBits) {
    const Vec3<double> half_extents{
        0.0,
        -1.0,
        std::numeric_limits<double>::quiet_NaN(),
    };
    const MonotoneHalfBitAllocationOptions options{2U, 63U, 21U};

    const auto allocation = allocate_monotone_half_bits(half_extents, 6U, options);

    EXPECT_EQ(allocation.ranked_axes, (std::array<std::uint8_t, 3>{0U, 1U, 2U}));
    EXPECT_GE(allocation.raw_bits[0], 2U);
    EXPECT_GE(allocation.raw_bits[1], 2U);
    EXPECT_GE(allocation.raw_bits[2], 2U);
    EXPECT_TRUE(within_uint64_budget(allocation.budget.bits));
}

TEST(MonotoneHalfBitAllocation, RequestedPrecisionAboveAxisCapIsClampedToCap) {
    const Vec3<double> half_extents{4.0, 2.0, 1.0};

    const auto allocation = allocate_monotone_half_bits(half_extents, 250U);

    for (const auto bits : allocation.raw_bits) {
        EXPECT_LE(bits, rch::curves::kMaxCurveAxisBits);
    }
    EXPECT_TRUE(within_uint64_budget(allocation.budget.bits));
}

TEST(MonotoneHalfBitAllocation, MinAxisBitsAboveAxisCapIsClampedDown) {
    const Vec3<double> half_extents{2.0, 2.0, 2.0};
    const MonotoneHalfBitAllocationOptions options{15U, 63U, 21U};

    const auto allocation = allocate_monotone_half_bits(half_extents, 4U, options);

    for (const auto bits : allocation.raw_bits) {
        EXPECT_LE(bits, 4U);
    }
}

TEST(MonotoneHalfBitAllocation, HonorsTotalBudgetCap) {
    const Vec3<double> half_extents{9.0, 3.0, 1.0};
    const MonotoneHalfBitAllocationOptions options{
        1U,
        6U,
        21U,
    };

    const auto allocation = allocate_monotone_half_bits(half_extents, 10U, options);

    EXPECT_LE(allocation.budget.total_bits, 6U);
    EXPECT_EQ(allocation.budget.bits, (std::array<std::uint8_t, 3>{4U, 1U, 1U}));
}

} // namespace
