#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <iostream>
#include <limits>
#include <sstream>

#include "rch/core/matrix3.hpp"
#include "rch/curves/bit_allocation_occupancy.hpp"

#include <gtest/gtest.h>

namespace {

using rch::core::Vec3;
using rch::curves::allocate_hybrid_occupancy_bits;
using rch::curves::allocate_occupancy_bits;
using rch::curves::enforce_bit_budget;
using rch::curves::total_bits;
using rch::curves::within_uint64_budget;

[[nodiscard]] auto bits_to_string(const std::array<std::uint8_t, 3>& bits) -> std::string {
    std::ostringstream out;
    out << "[" << static_cast<unsigned>(bits[0]) << "," << static_cast<unsigned>(bits[1])
        << "," << static_cast<unsigned>(bits[2]) << "]";
    return out.str();
}

[[nodiscard]] auto max_cell_edge(
    const Vec3<double>& half_extents,
    const std::array<std::uint8_t, 3>& bits
) -> double {
    double worst = 0.0;
    for (std::size_t axis = 0U; axis < 3U; ++axis) {
        worst = std::max(
            worst,
            std::ldexp(half_extents[axis], 1 - static_cast<int>(bits[axis]))
        );
    }
    return worst;
}

TEST(OccupancyBitAllocation, AnisotropicFiveToOneToOneGivesLongAxisMoreBits) {
    const Vec3<double> half_extents{5.0, 1.0, 1.0};
    const auto allocation = allocate_occupancy_bits(half_extents, 1000U);

    ASSERT_TRUE(allocation.finite_positive_domain);
    EXPECT_NEAR(allocation.volume_core, 40.0, 1.0e-14);
    EXPECT_GT(allocation.delta_target, 0.0);
    EXPECT_EQ(allocation.raw_bits, (std::array<std::uint8_t, 3>{5U, 3U, 3U}));

    EXPECT_GT(allocation.budget.bits[0], allocation.budget.bits[1]);
    EXPECT_EQ(allocation.budget.bits[1], allocation.budget.bits[2]);
    EXPECT_TRUE(within_uint64_budget(allocation.budget.bits));
    EXPECT_LE(allocation.budget.total_bits, 63U);
}

TEST(OccupancyBitAllocation, NonpositiveDomainFailsClosedToMinimumBits) {
    const Vec3<double> half_extents{5.0, 0.0, 1.0};
    const auto allocation = allocate_occupancy_bits(half_extents, 0U);

    EXPECT_FALSE(allocation.finite_positive_domain);
    EXPECT_EQ(allocation.n_core, 1U);
    EXPECT_EQ(allocation.raw_bits, (std::array<std::uint8_t, 3>{1U, 1U, 1U}));
    EXPECT_EQ(allocation.budget.bits, allocation.raw_bits);
}

TEST(OccupancyBitAllocation, IsotropicExtentGivesEqualBitsAcrossAxes) {
    const Vec3<double> half_extents{2.0, 2.0, 2.0};
    const auto allocation = allocate_occupancy_bits(half_extents, 100U);

    ASSERT_TRUE(allocation.finite_positive_domain);
    EXPECT_NEAR(allocation.volume_core, 64.0, 1.0e-14);
    EXPECT_EQ(allocation.raw_bits[0], allocation.raw_bits[1]);
    EXPECT_EQ(allocation.raw_bits[1], allocation.raw_bits[2]);
    EXPECT_EQ(allocation.budget.bits[0], allocation.budget.bits[1]);
    EXPECT_EQ(allocation.budget.bits[1], allocation.budget.bits[2]);
}

TEST(OccupancyBitAllocation, MoreInliersDemandFinerResolution) {
    const Vec3<double> half_extents{5.0, 5.0, 5.0};
    const auto sparse = allocate_occupancy_bits(half_extents, 1U);
    const auto dense = allocate_occupancy_bits(half_extents, 1000000U);

    ASSERT_TRUE(sparse.finite_positive_domain);
    ASSERT_TRUE(dense.finite_positive_domain);
    EXPECT_GT(dense.delta_target, 0.0);
    EXPECT_LT(dense.delta_target, sparse.delta_target);
    for (std::size_t axis = 0U; axis < 3U; ++axis) {
        EXPECT_GE(dense.raw_bits[axis], sparse.raw_bits[axis]);
    }
}

TEST(OccupancyBitAllocation, MinimumAxisBitsCanPreserveUniformFloor) {
    const Vec3<double> half_extents{5.0, 1.0, 1.0};
    const rch::curves::OccupancyBitAllocationOptions options{
        10U,
        rch::curves::kMaxCurveTotalBits,
        rch::curves::kMaxCurveAxisBits,
    };
    const auto allocation = allocate_occupancy_bits(half_extents, 8U, options);

    ASSERT_TRUE(allocation.finite_positive_domain);
    EXPECT_EQ(allocation.budget.bits, (std::array<std::uint8_t, 3>{10U, 10U, 10U}));
    EXPECT_TRUE(within_uint64_budget(allocation.budget.bits));
}

TEST(OccupancyBitAllocation, HybridPreservesCoreCellSizeOverCoveringDomain) {
    const Vec3<double> core{2.0, 2.0, 2.0};
    const Vec3<double> covering{20.0, 2.0, 2.0};
    const rch::curves::OccupancyBitAllocationOptions options{
        1U,
        rch::curves::kMaxCurveTotalBits,
        rch::curves::kMaxCurveAxisBits,
    };
    const auto core_only = allocate_occupancy_bits(core, 64U, options);
    const auto hybrid = allocate_hybrid_occupancy_bits(core, covering, 64U, options);

    // Same target cell size as the robust-core allocation ...
    EXPECT_DOUBLE_EQ(hybrid.delta_target, core_only.delta_target);
    EXPECT_EQ(core_only.budget.bits, (std::array<std::uint8_t, 3>{2U, 2U, 2U}));
    // ... but enough bits so the (wider) covering box keeps that resolution.
    EXPECT_EQ(hybrid.budget.bits, (std::array<std::uint8_t, 3>{6U, 2U, 2U}));
    EXPECT_TRUE(within_uint64_budget(hybrid.budget.bits));
}

TEST(OccupancyBitAllocation, HybridCoincidesWithCoreWhenNoOutOfCorePoints) {
    const Vec3<double> core{5.0, 1.0, 1.0};
    const rch::curves::OccupancyBitAllocationOptions options{
        1U,
        rch::curves::kMaxCurveTotalBits,
        rch::curves::kMaxCurveAxisBits,
    };
    const auto core_only = allocate_occupancy_bits(core, 1000U, options);
    const auto hybrid = allocate_hybrid_occupancy_bits(core, core, 1000U, options);

    EXPECT_EQ(hybrid.budget.bits, core_only.budget.bits);
    EXPECT_DOUBLE_EQ(hybrid.delta_target, core_only.delta_target);
}

TEST(OccupancyBitAllocation, HybridDegenerateCoreFallsBackToMinimumBits) {
    const Vec3<double> degenerate_core{5.0, 0.0, 1.0};
    const Vec3<double> covering{20.0, 2.0, 2.0};
    const rch::curves::OccupancyBitAllocationOptions options{
        1U,
        rch::curves::kMaxCurveTotalBits,
        rch::curves::kMaxCurveAxisBits,
    };
    const auto hybrid = allocate_hybrid_occupancy_bits(degenerate_core, covering, 64U, options);

    EXPECT_FALSE(hybrid.finite_positive_domain);
    EXPECT_EQ(hybrid.budget.bits, (std::array<std::uint8_t, 3>{1U, 1U, 1U}));
}

TEST(OccupancyBitAllocation, HybridBudgetProjectionMinimizesWorstCoveringCellEdge) {
    const double target_delta = 1.5 * std::ldexp(1.0, -30);
    const Vec3<double> core{target_delta, target_delta, target_delta};
    const Vec3<double> covering{1.0, 1.0, 2.5};
    const rch::curves::OccupancyBitAllocationOptions options{
        1U,
        rch::curves::kMaxCurveTotalBits,
        rch::curves::kMaxCurveAxisBits,
    };

    const auto hybrid = allocate_hybrid_occupancy_bits(core, covering, 8U, options);
    const auto greedy = enforce_bit_budget(
        std::span<const std::uint8_t, 3>{hybrid.raw_bits},
        options.max_total_bits,
        options.min_axis_bits,
        options.max_axis_bits
    );

    ASSERT_TRUE(hybrid.finite_positive_domain);
    EXPECT_NEAR(hybrid.delta_target, target_delta, 1.0e-22);
    EXPECT_EQ(hybrid.raw_bits, (std::array<std::uint8_t, 3>{31U, 31U, 32U}));
    EXPECT_EQ(greedy.bits, (std::array<std::uint8_t, 3>{21U, 21U, 21U}));
    EXPECT_EQ(hybrid.budget.bits, (std::array<std::uint8_t, 3>{21U, 20U, 22U}));
    EXPECT_EQ(hybrid.budget.total_bits, rch::curves::kMaxCurveTotalBits);
    const double greedy_worst = max_cell_edge(covering, greedy.bits);
    const double optimized_worst = max_cell_edge(covering, hybrid.budget.bits);
    EXPECT_LT(optimized_worst, greedy_worst);

    std::cout << "\nallocator,raw_bits,legacy_greedy_bits,optimized_bits,"
                 "legacy_worst_cell_edge,optimized_worst_cell_edge,improvement_ratio\n";
    std::cout << "hybrid_occupancy," << bits_to_string(hybrid.raw_bits) << ","
              << bits_to_string(greedy.bits) << "," << bits_to_string(hybrid.budget.bits)
              << "," << greedy_worst << "," << optimized_worst << ","
              << (greedy_worst / optimized_worst) << "\n";

    const double chosen_worst = optimized_worst;
    for (std::uint16_t b0 = options.min_axis_bits; b0 <= hybrid.raw_bits[0]; ++b0) {
        for (std::uint16_t b1 = options.min_axis_bits; b1 <= hybrid.raw_bits[1]; ++b1) {
            for (std::uint16_t b2 = options.min_axis_bits; b2 <= hybrid.raw_bits[2]; ++b2) {
                const std::array<std::uint8_t, 3> candidate{
                    static_cast<std::uint8_t>(b0),
                    static_cast<std::uint8_t>(b1),
                    static_cast<std::uint8_t>(b2),
                };
                if (total_bits(std::span<const std::uint8_t, 3>{candidate}) !=
                    hybrid.budget.total_bits) {
                    continue;
                }
                EXPECT_LE(chosen_worst, max_cell_edge(covering, candidate) + 1.0e-18);
            }
        }
    }
}

TEST(OccupancyBitAllocation, VeryLargeExtentClampsToAxisCap) {
    const Vec3<double> half_extents{
        static_cast<double>(1ULL << 25U),
        static_cast<double>(1ULL << 25U),
        static_cast<double>(1ULL << 25U),
    };
    const auto allocation = allocate_occupancy_bits(half_extents, 1U);

    ASSERT_TRUE(allocation.finite_positive_domain);
    for (std::size_t axis = 0U; axis < 3U; ++axis) {
        EXPECT_LE(allocation.raw_bits[axis], 21U);
    }
    EXPECT_LE(allocation.budget.total_bits, 63U);
    EXPECT_TRUE(within_uint64_budget(allocation.budget.bits));
}

TEST(OccupancyBitAllocation, NegativeAxisIsNonpositiveDomain) {
    const Vec3<double> half_extents{5.0, -1.0, 1.0};
    const auto allocation = allocate_occupancy_bits(half_extents, 100U);
    EXPECT_FALSE(allocation.finite_positive_domain);
    EXPECT_EQ(allocation.raw_bits, (std::array<std::uint8_t, 3>{1U, 1U, 1U}));
}

TEST(OccupancyBitAllocation, NaNAxisIsNonpositiveDomain) {
    const Vec3<double> half_extents{5.0, std::numeric_limits<double>::quiet_NaN(), 1.0};
    const auto allocation = allocate_occupancy_bits(half_extents, 100U);
    EXPECT_FALSE(allocation.finite_positive_domain);
    EXPECT_EQ(allocation.raw_bits, (std::array<std::uint8_t, 3>{1U, 1U, 1U}));
}

} // namespace
