#include <array>
#include <cstddef>
#include <cstdint>
#include <iostream>
#include <limits>
#include <span>
#include <string>
#include <string_view>
#include <vector>

#include "rch/orderings/orderer.hpp"

#include <gtest/gtest.h>

namespace {

using BitsAxis3 = rch::curves::BitsAxis3;

enum class CapacityAllocator {
    Uniform,
    SampleCountUniform,
    MonotoneHalf,
    OccupancyFloor1,
    OccupancyFloor10,
    FrameCoreOccupancy,
    HybridOccupancy,
};

[[nodiscard]] constexpr auto cube_half_extent() noexcept -> rch::core::Vec3<double> {
    return {1.0, 1.0, 1.0};
}

[[nodiscard]] constexpr auto monotone_half_extent() noexcept -> rch::core::Vec3<double> {
    return {10.0, 2.0, 1.0};
}

[[nodiscard]] auto base_config() noexcept -> rch::orderings::OrderingConfig {
    rch::orderings::OrderingConfig config{};
    config.uniform_bits = 10U;
    config.min_axis_bits = 1U;
    config.bit_sum_max = rch::curves::kMaxCurveTotalBits;
    config.refinement = rch::orderings::RefinementMode::Off;
    return config;
}

[[nodiscard]] auto capacity_point_count(const std::uint8_t total_bits) -> std::size_t {
    EXPECT_LT(total_bits, std::numeric_limits<std::size_t>::digits);
    return std::size_t{1U} << total_bits;
}

[[nodiscard]] auto decimal_power_of_two(const std::uint8_t exponent) -> std::string {
    std::string digits{"1"};
    for (std::uint8_t step = 0U; step < exponent; ++step) {
        int carry = 0;
        for (auto it = digits.rbegin(); it != digits.rend(); ++it) {
            const int doubled = ((*it - '0') * 2) + carry;
            *it = static_cast<char>('0' + (doubled % 10));
            carry = doubled / 10;
        }
        if (carry != 0) {
            digits.insert(digits.begin(), static_cast<char>('0' + carry));
        }
    }
    return digits;
}

[[nodiscard]] auto bits_to_string(const BitsAxis3& bits) -> std::string {
    return "[" + std::to_string(static_cast<unsigned>(bits[0])) + "," +
           std::to_string(static_cast<unsigned>(bits[1])) + "," +
           std::to_string(static_cast<unsigned>(bits[2])) + "]";
}

[[nodiscard]] auto total_bits(const BitsAxis3& bits) noexcept -> std::uint8_t {
    return static_cast<std::uint8_t>(bits[0] + bits[1] + bits[2]);
}

[[nodiscard]] auto bits_for(const CapacityAllocator allocator, const std::size_t n) -> BitsAxis3 {
    auto config = base_config();
    switch (allocator) {
    case CapacityAllocator::Uniform:
        config.bit_alloc = rch::orderings::BitAllocator::Uniform;
        return rch::orderings::detail::uniform_bits_axis(
            rch::orderings::detail::equal_bits(config)
        );
    case CapacityAllocator::SampleCountUniform:
        config.bit_alloc = rch::orderings::BitAllocator::SampleCountUniform;
        return rch::orderings::detail::uniform_bits_axis(
            rch::orderings::detail::sample_count_uniform_bits(n, config)
        );
    case CapacityAllocator::MonotoneHalf:
        config.bit_alloc = rch::orderings::BitAllocator::MonotoneHalf;
        return rch::orderings::detail::compact_bits_for(monotone_half_extent(), n, config);
    case CapacityAllocator::OccupancyFloor1:
        config.bit_alloc = rch::orderings::BitAllocator::OccupancyFloor1;
        return rch::orderings::detail::compact_bits_for(cube_half_extent(), n, config);
    case CapacityAllocator::OccupancyFloor10:
        config.bit_alloc = rch::orderings::BitAllocator::OccupancyFloor10;
        return rch::orderings::detail::compact_bits_for(cube_half_extent(), n, config);
    case CapacityAllocator::FrameCoreOccupancy:
        config.bit_alloc = rch::orderings::BitAllocator::FrameCoreOccupancy;
        return rch::orderings::detail::occupancy_bits_for(
            cube_half_extent(), n, config, config.min_axis_bits
        );
    case CapacityAllocator::HybridOccupancy:
        config.bit_alloc = rch::orderings::BitAllocator::HybridOccupancy;
        return rch::orderings::detail::hybrid_occupancy_bits_for(
            cube_half_extent(), cube_half_extent(), n, config
        );
    default:
        return {};
    }
}

struct CapacitySpec {
    std::string_view name;
    CapacityAllocator allocator;
    std::size_t sizing_n;
    BitsAxis3 expected_bits;
    std::string_view note;
};

} // namespace

TEST(BitAllocationCapacity, CanonicalCapacityAndInverseRoundTrip) {
    if (std::numeric_limits<std::size_t>::digits <= rch::curves::kMaxCurveTotalBits) {
        GTEST_SKIP() << "63-bit capacity requires size_t to represent 2^63";
    }

    const std::size_t curve_capacity = capacity_point_count(rch::curves::kMaxCurveTotalBits);
    const std::vector<CapacitySpec> specs{
        {
            "uniform",
            CapacityAllocator::Uniform,
            1U,
            {10U, 10U, 10U},
            "fixed 10-bit/axis C0 baseline; n-independent",
        },
        {
            "sample_count_uniform",
            CapacityAllocator::SampleCountUniform,
            curve_capacity,
            {21U, 21U, 21U},
            "minimal equal-depth count rule, capped by the 63-bit key budget",
        },
        {
            "monotone_half",
            CapacityAllocator::MonotoneHalf,
            1U,
            {10U, 4U, 1U},
            "extent-ranked half-budget heuristic; n-independent",
        },
        {
            "occupancy_floor1",
            CapacityAllocator::OccupancyFloor1,
            curve_capacity,
            {21U, 21U, 21U},
            "cube-domain occupancy rule with 1-bit floor",
        },
        {
            "occupancy_floor10",
            CapacityAllocator::OccupancyFloor10,
            curve_capacity,
            {21U, 21U, 21U},
            "cube-domain occupancy rule with fixed 10-bit floor",
        },
        {
            "frame_core_occupancy",
            CapacityAllocator::FrameCoreOccupancy,
            curve_capacity,
            {21U, 21U, 21U},
            "core-domain occupancy; assumes all counted points are inside the core",
        },
        {
            "hybrid_occupancy",
            CapacityAllocator::HybridOccupancy,
            curve_capacity,
            {21U, 21U, 21U},
            "hybrid with core and covering domains equal in this capacity oracle",
        },
    };

    std::cout << "\nallocator,bits_axis,total_bits,max_point_cells,roundtrip_bits_axis,note\n";
    for (const CapacitySpec& spec : specs) {
        const BitsAxis3 bits = bits_for(spec.allocator, spec.sizing_n);
        ASSERT_EQ(bits, spec.expected_bits) << spec.name;

        const std::uint8_t total = total_bits(bits);
        ASSERT_LE(total, rch::curves::kMaxCurveTotalBits) << spec.name;

        const std::size_t max_points = capacity_point_count(total);
        const BitsAxis3 roundtrip_bits = bits_for(spec.allocator, max_points);
        EXPECT_EQ(roundtrip_bits, bits) << spec.name;

        std::cout << spec.name << "," << bits_to_string(bits) << "," << static_cast<unsigned>(total)
                  << "," << decimal_power_of_two(total) << "," << bits_to_string(roundtrip_bits)
                  << "," << spec.note << "\n";
    }
}
