#include <array>
#include <cstdint>
#include <limits>

#include "rch/curves/bit_budget.hpp"
#include "rch/curves/quantization.hpp"

#include <gtest/gtest.h>

namespace {

using rch::curves::enforce_bit_budget;
using rch::curves::quantize_axis;
using rch::curves::within_uint64_budget;

TEST(BitBudget, AcceptsUint64Boundary) {
    const std::array<std::uint8_t, 3> bits{21U, 21U, 21U};
    EXPECT_TRUE(within_uint64_budget(bits));

    const auto enforced = enforce_bit_budget(bits);
    EXPECT_EQ(enforced.bits, bits);
    EXPECT_EQ(enforced.total_bits, 63U);
    EXPECT_FALSE(enforced.downscaled);
    EXPECT_FALSE(enforced.axis_clamped);
}

TEST(BitBudget, ClampsCallerBudgetToUint64Authority) {
    const std::array<std::uint8_t, 3> over_budget{32U, 32U, 0U};

    EXPECT_FALSE(within_uint64_budget(over_budget, 255U));
}

TEST(BitBudget, DownscalesDeterministically) {
    const std::array<std::uint8_t, 3> requested{32U, 32U, 32U};
    const auto enforced = enforce_bit_budget(requested);

    EXPECT_EQ(enforced.bits, (std::array<std::uint8_t, 3>{21U, 21U, 21U}));
    EXPECT_EQ(enforced.total_bits, 63U);
    EXPECT_TRUE(enforced.downscaled);
    EXPECT_TRUE(within_uint64_budget(enforced.bits));
}

TEST(BitBudget, SnapshotTieBreakReducesXBeforeYBeforeZ) {
    const std::array<std::uint8_t, 3> xy_tie{22U, 22U, 20U};
    const auto xy_enforced = enforce_bit_budget(xy_tie);
    EXPECT_EQ(xy_enforced.bits, (std::array<std::uint8_t, 3>{21U, 22U, 20U}));
    EXPECT_EQ(xy_enforced.total_bits, 63U);

    const std::array<std::uint8_t, 3> yz_tie{20U, 22U, 22U};
    const auto yz_enforced = enforce_bit_budget(yz_tie);
    EXPECT_EQ(yz_enforced.bits, (std::array<std::uint8_t, 3>{20U, 21U, 22U}));
    EXPECT_EQ(yz_enforced.total_bits, 63U);
}

TEST(BitBudget, HandlesDegenerateZeroResolution) {
    const std::array<std::uint8_t, 3> requested{0U, 0U, 0U};
    const auto zero_min = enforce_bit_budget(requested);
    EXPECT_EQ(zero_min.bits, requested);
    EXPECT_EQ(zero_min.total_bits, 0U);

    const auto one_min = enforce_bit_budget(requested, 63U, 1U);
    EXPECT_EQ(one_min.bits, (std::array<std::uint8_t, 3>{1U, 1U, 1U}));
    EXPECT_EQ(one_min.total_bits, 3U);
    EXPECT_TRUE(one_min.axis_clamped);
}

TEST(BitBudget, KeepsSinglePointMinimumBudgetWithinAuthority) {
    const std::array<std::uint8_t, 3> requested{1U, 1U, 1U};
    const auto enforced = enforce_bit_budget(requested, 63U, 1U);

    EXPECT_EQ(enforced.bits, requested);
    EXPECT_EQ(enforced.total_bits, 3U);
    EXPECT_FALSE(enforced.downscaled);
}

TEST(BitBudget, ClampsUnrepresentableAxisPrecision) {
    const std::array<std::uint8_t, 3> requested{64U, 1U, 1U};
    const auto enforced = enforce_bit_budget(requested);

    EXPECT_EQ(enforced.bits, (std::array<std::uint8_t, 3>{32U, 1U, 1U}));
    EXPECT_EQ(enforced.total_bits, 34U);
    EXPECT_TRUE(enforced.axis_clamped);
    EXPECT_FALSE(enforced.downscaled);
}

TEST(Quantization, SaturatesToClosedIntegerDomain) {
    EXPECT_EQ(quantize_axis(-1.0, 0.0, 1.0, 2U), 0U);
    EXPECT_EQ(quantize_axis(0.0, 0.0, 1.0, 2U), 0U);
    EXPECT_EQ(quantize_axis(0.25, 0.0, 1.0, 2U), 1U);
    EXPECT_EQ(quantize_axis(0.999, 0.0, 1.0, 2U), 3U);
    EXPECT_EQ(quantize_axis(1.0, 0.0, 1.0, 2U), 3U);
}

TEST(Quantization, FailsClosedForInvalidInput) {
    EXPECT_EQ(quantize_axis(0.5, 1.0, 1.0, 4U), 0U);
    EXPECT_EQ(quantize_axis(0.5, 2.0, 1.0, 4U), 0U);
    EXPECT_EQ(quantize_axis(0.5, 0.0, 1.0, 0U), 0U);
}

TEST(Quantization, RejectsNonFiniteInputs) {
    constexpr double quiet_nan = std::numeric_limits<double>::quiet_NaN();
    constexpr double pos_inf = std::numeric_limits<double>::infinity();
    constexpr double neg_inf = -std::numeric_limits<double>::infinity();

    EXPECT_EQ(quantize_axis(quiet_nan, 0.0, 1.0, 4U), 0U);
    EXPECT_EQ(quantize_axis(pos_inf, 0.0, 1.0, 4U), 0U);
    EXPECT_EQ(quantize_axis(neg_inf, 0.0, 1.0, 4U), 0U);
    EXPECT_EQ(quantize_axis(0.5, quiet_nan, 1.0, 4U), 0U);
    EXPECT_EQ(quantize_axis(0.5, 0.0, quiet_nan, 4U), 0U);
    EXPECT_EQ(quantize_axis(0.5, neg_inf, pos_inf, 4U), 0U);
}

TEST(Quantization, MapsNegativeRangeProportionally) {
    EXPECT_EQ(quantize_axis(-1.0, -1.0, 1.0, 2U), 0U);
    EXPECT_EQ(quantize_axis(-0.5, -1.0, 1.0, 2U), 1U);
    EXPECT_EQ(quantize_axis(0.0, -1.0, 1.0, 2U), 2U);
    EXPECT_EQ(quantize_axis(0.499, -1.0, 1.0, 2U), 2U);
    EXPECT_EQ(quantize_axis(1.0, -1.0, 1.0, 2U), 3U);
}

TEST(Quantization, ClampsRequestsAboveMaxSupportedBits) {
    constexpr std::uint32_t expected_max = std::numeric_limits<std::uint32_t>::max();
    EXPECT_EQ(quantize_axis(1.0, 0.0, 1.0, 32U), expected_max);
    EXPECT_EQ(quantize_axis(1.0, 0.0, 1.0, 64U), expected_max);
    EXPECT_EQ(quantize_axis(0.0, 0.0, 1.0, 32U), 0U);
    EXPECT_EQ(quantize_axis(0.0, 0.0, 1.0, 64U), 0U);
}

TEST(BitBudget, ClampsMinAxisAboveAxisCeiling) {
    const std::array<std::uint8_t, 3> requested{0U, 0U, 0U};
    const auto enforced =
        enforce_bit_budget(requested, /*max_total_bits=*/63U, /*min_axis_bits=*/40U);

    for (std::uint8_t bits : enforced.bits) {
        EXPECT_LE(bits, 21U) << "min must collapse when 3*min > total budget";
    }
    EXPECT_LE(enforced.total_bits, 63U);
    EXPECT_TRUE(enforced.axis_clamped);
}

TEST(BitBudget, AsymmetricRequestPreservedWhenWithinBudget) {
    const std::array<std::uint8_t, 3> requested{21U, 1U, 1U};
    const auto enforced = enforce_bit_budget(requested);

    EXPECT_EQ(enforced.bits, requested);
    EXPECT_EQ(enforced.total_bits, 23U);
    EXPECT_FALSE(enforced.downscaled);
    EXPECT_FALSE(enforced.axis_clamped);
}

TEST(BitBudget, EnforcementIsIdempotent) {
    const std::array<std::uint8_t, 3> requested{32U, 32U, 32U};
    const auto first = enforce_bit_budget(requested);
    const auto second = enforce_bit_budget(first.bits);

    EXPECT_EQ(first.bits, second.bits);
    EXPECT_EQ(second.total_bits, first.total_bits);
    EXPECT_FALSE(second.downscaled);
}

TEST(BitBudget, BoundaryAtMaxAxisBitsHonoured) {
    const std::array<std::uint8_t, 3> requested{32U, 32U, 0U};
    const auto enforced = enforce_bit_budget(requested);

    EXPECT_LE(enforced.total_bits, 63U);
    EXPECT_LE(enforced.bits[0], 32U);
    EXPECT_LE(enforced.bits[1], 32U);
    EXPECT_EQ(enforced.bits[2], 0U);
    EXPECT_TRUE(enforced.downscaled);
    EXPECT_TRUE(within_uint64_budget(enforced.bits));
}

} // namespace
