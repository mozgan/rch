#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <iostream>
#include <limits>
#include <string>
#include <string_view>
#include <vector>

#include "rch/orderings/orderer.hpp"

#include <gtest/gtest.h>

namespace {

using BitsAxis3 = rch::curves::BitsAxis3;
using Vec3 = rch::core::Vec3<double>;

enum class DomainAllocator {
    Uniform,
    SampleCountUniform,
    MonotoneHalf,
    OccupancyFloor1,
    OccupancyFloor10,
    FrameCoreOccupancy,
    HybridOccupancy,
};

struct DomainScenario {
    std::size_t total_count;
    std::size_t core_count;
    Vec3 core_half_extents;
    Vec3 covering_half_extents;
};

struct DomainSummary {
    std::string_view name;
    DomainAllocator allocator;
    Vec3 domain_half_extents;
    BitsAxis3 bits;
    bool contains_support_box;
    std::size_t inside_count;
    std::size_t outside_or_clamped_count;
    std::string_view note;
};

[[nodiscard]] auto base_config() noexcept -> rch::orderings::OrderingConfig {
    rch::orderings::OrderingConfig config{};
    config.uniform_bits = 10U;
    config.min_axis_bits = 1U;
    config.bit_sum_max = rch::curves::kMaxCurveTotalBits;
    config.refinement = rch::orderings::RefinementMode::Off;
    return config;
}

[[nodiscard]] auto contains_support_box(const Vec3& domain, const Vec3& support) noexcept -> bool {
    for (std::size_t axis = 0U; axis < 3U; ++axis) {
        if (!(std::isfinite(domain[axis]) && std::isfinite(support[axis]) &&
              domain[axis] >= support[axis])) {
            return false;
        }
    }
    return true;
}

[[nodiscard]] auto vec_to_string(const Vec3& value) -> std::string {
    return "[" + std::to_string(value[0]) + "," + std::to_string(value[1]) + "," +
           std::to_string(value[2]) + "]";
}

[[nodiscard]] auto bits_to_string(const BitsAxis3& bits) -> std::string {
    return "[" + std::to_string(static_cast<unsigned>(bits[0])) + "," +
           std::to_string(static_cast<unsigned>(bits[1])) + "," +
           std::to_string(static_cast<unsigned>(bits[2])) + "]";
}

[[nodiscard]] auto total_bits(const BitsAxis3& bits) noexcept -> std::uint8_t {
    return static_cast<std::uint8_t>(bits[0] + bits[1] + bits[2]);
}

[[nodiscard]] auto cell_capacity(const BitsAxis3& bits) noexcept -> std::size_t {
    const std::uint8_t total = total_bits(bits);
    if (total >= std::numeric_limits<std::size_t>::digits) {
        return std::numeric_limits<std::size_t>::max();
    }
    return std::size_t{1U} << total;
}

[[nodiscard]] auto has_cell_capacity(const BitsAxis3& bits, const std::size_t n) noexcept -> bool {
    return n <= cell_capacity(bits);
}

[[nodiscard]] auto
domain_for(const DomainAllocator allocator, const DomainScenario& scenario) noexcept -> Vec3 {
    if (allocator == DomainAllocator::FrameCoreOccupancy) {
        return scenario.core_half_extents;
    }
    return scenario.covering_half_extents;
}

[[nodiscard]] auto bits_for(const DomainAllocator allocator, const DomainScenario& scenario)
    -> BitsAxis3 {
    auto config = base_config();
    switch (allocator) {
    case DomainAllocator::Uniform:
        config.bit_alloc = rch::orderings::BitAllocator::Uniform;
        return rch::orderings::detail::compact_bits_for(
            scenario.covering_half_extents, scenario.total_count, config
        );
    case DomainAllocator::SampleCountUniform:
        config.bit_alloc = rch::orderings::BitAllocator::SampleCountUniform;
        return rch::orderings::detail::compact_bits_for(
            scenario.covering_half_extents, scenario.total_count, config
        );
    case DomainAllocator::MonotoneHalf:
        config.bit_alloc = rch::orderings::BitAllocator::MonotoneHalf;
        return rch::orderings::detail::compact_bits_for(
            scenario.covering_half_extents, scenario.total_count, config
        );
    case DomainAllocator::OccupancyFloor1:
        config.bit_alloc = rch::orderings::BitAllocator::OccupancyFloor1;
        return rch::orderings::detail::compact_bits_for(
            scenario.covering_half_extents, scenario.total_count, config
        );
    case DomainAllocator::OccupancyFloor10:
        config.bit_alloc = rch::orderings::BitAllocator::OccupancyFloor10;
        return rch::orderings::detail::compact_bits_for(
            scenario.covering_half_extents, scenario.total_count, config
        );
    case DomainAllocator::FrameCoreOccupancy:
        config.bit_alloc = rch::orderings::BitAllocator::FrameCoreOccupancy;
        return rch::orderings::detail::occupancy_bits_for(
            scenario.core_half_extents, scenario.core_count, config, config.min_axis_bits
        );
    case DomainAllocator::HybridOccupancy:
        config.bit_alloc = rch::orderings::BitAllocator::HybridOccupancy;
        return rch::orderings::detail::hybrid_occupancy_bits_for(
            scenario.core_half_extents, scenario.covering_half_extents, scenario.core_count, config
        );
    default:
        return {};
    }
}

[[nodiscard]] auto summarize(
    const std::string_view name,
    const DomainAllocator allocator,
    const DomainScenario& scenario,
    const std::string_view note
) -> DomainSummary {
    const Vec3 domain = domain_for(allocator, scenario);
    const bool contains_all = contains_support_box(domain, scenario.covering_half_extents);
    const std::size_t inside = contains_all ? scenario.total_count : scenario.core_count;
    return {
        name,
        allocator,
        domain,
        bits_for(allocator, scenario),
        contains_all,
        inside,
        scenario.total_count - inside,
        note,
    };
}

[[nodiscard]] auto best_by_containment_then_bits(const std::vector<DomainSummary>& summaries)
    -> const DomainSummary& {
    const DomainSummary* best = &summaries.front();
    for (const DomainSummary& item : summaries) {
        if (item.inside_count > best->inside_count ||
            (item.inside_count == best->inside_count &&
             total_bits(item.bits) < total_bits(best->bits))) {
            best = &item;
        }
    }
    return *best;
}

} // namespace

TEST(QuantizationDomainSelection, CoveringDomainsMaximizeGeometricContainmentWithoutPoints) {
    const DomainScenario scenario{
        1000U,
        990U,
        {2.0, 2.0, 2.0},
        {20.0, 3.0, 2.0},
    };
    const std::vector<DomainSummary> summaries{
        summarize(
            "uniform",
            DomainAllocator::Uniform,
            scenario,
            "covering frame domain; fixed equal-depth bits"
        ),
        summarize(
            "sample_count_uniform",
            DomainAllocator::SampleCountUniform,
            scenario,
            "covering frame domain; count-sized equal-depth bits"
        ),
        summarize(
            "monotone_half",
            DomainAllocator::MonotoneHalf,
            scenario,
            "covering frame domain; extent-ranked half-budget bits"
        ),
        summarize(
            "occupancy_floor1",
            DomainAllocator::OccupancyFloor1,
            scenario,
            "covering frame domain; occupancy bits with 1-bit floor"
        ),
        summarize(
            "occupancy_floor10",
            DomainAllocator::OccupancyFloor10,
            scenario,
            "covering frame domain; occupancy bits with 10-bit floor"
        ),
        summarize(
            "frame_core_occupancy",
            DomainAllocator::FrameCoreOccupancy,
            scenario,
            "core frame domain; out-of-core support is clamped"
        ),
        summarize(
            "hybrid_occupancy",
            DomainAllocator::HybridOccupancy,
            scenario,
            "covering frame domain; robust-core delta drives bit budget"
        ),
    };

    std::cout << "\nquantization,domain_half_extents,bits_axis,total_bits,contains_all_support,"
                 "inside_points,outside_or_clamped_points,note\n";
    for (const DomainSummary& item : summaries) {
        std::cout << item.name << "," << vec_to_string(item.domain_half_extents) << ","
                  << bits_to_string(item.bits) << ","
                  << static_cast<unsigned>(total_bits(item.bits)) << ","
                  << (item.contains_support_box ? "true" : "false") << "," << item.inside_count
                  << "," << item.outside_or_clamped_count << "," << item.note << "\n";
    }

    for (const DomainSummary& item : summaries) {
        if (item.allocator == DomainAllocator::FrameCoreOccupancy) {
            EXPECT_FALSE(item.contains_support_box);
            EXPECT_EQ(item.inside_count, scenario.core_count);
            EXPECT_EQ(item.outside_or_clamped_count, 10U);
        } else {
            EXPECT_TRUE(item.contains_support_box) << item.name;
            EXPECT_EQ(item.inside_count, scenario.total_count) << item.name;
            EXPECT_EQ(item.outside_or_clamped_count, 0U) << item.name;
        }
    }

    const DomainSummary& best = best_by_containment_then_bits(summaries);
    EXPECT_EQ(best.name, "occupancy_floor1");
    EXPECT_EQ(best.inside_count, scenario.total_count);
    EXPECT_EQ(total_bits(best.bits), 12U);

    const auto hybrid = std::ranges::find_if(summaries, [](const DomainSummary& item) {
        return item.allocator == DomainAllocator::HybridOccupancy;
    });
    const auto frame_core = std::ranges::find_if(summaries, [](const DomainSummary& item) {
        return item.allocator == DomainAllocator::FrameCoreOccupancy;
    });
    ASSERT_NE(hybrid, summaries.end());
    ASSERT_NE(frame_core, summaries.end());
    EXPECT_EQ(hybrid->inside_count, scenario.total_count);
    EXPECT_EQ(frame_core->inside_count, scenario.core_count);
    EXPECT_GT(total_bits(hybrid->bits), total_bits(frame_core->bits));
}

TEST(QuantizationDomainSelection, TotalCountAloneCannotChooseTheDomain) {
    const std::size_t same_total_count = 1000U;
    const DomainScenario compact_support{
        same_total_count,
        same_total_count,
        {2.0, 2.0, 2.0},
        {2.0, 2.0, 2.0},
    };
    const DomainScenario out_of_core_support{
        same_total_count,
        990U,
        {2.0, 2.0, 2.0},
        {20.0, 3.0, 2.0},
    };

    const auto compact_frame_core = summarize(
        "frame_core_occupancy",
        DomainAllocator::FrameCoreOccupancy,
        compact_support,
        "same n, support equals core"
    );
    const auto outlier_frame_core = summarize(
        "frame_core_occupancy",
        DomainAllocator::FrameCoreOccupancy,
        out_of_core_support,
        "same n, support extends outside core"
    );

    EXPECT_EQ(compact_support.total_count, out_of_core_support.total_count);
    EXPECT_TRUE(compact_frame_core.contains_support_box);
    EXPECT_FALSE(outlier_frame_core.contains_support_box);
    EXPECT_EQ(compact_frame_core.inside_count, same_total_count);
    EXPECT_EQ(outlier_frame_core.inside_count, out_of_core_support.core_count);
}

TEST(QuantizationDomainSelection, CountSweepSeparatesContainmentFromCellCapacity) {
    if (std::numeric_limits<std::size_t>::digits <= rch::curves::kMaxCurveTotalBits) {
        GTEST_SKIP() << "63-bit count sweep requires size_t to represent 2^63";
    }

    const std::size_t curve_capacity = std::size_t{1U} << rch::curves::kMaxCurveTotalBits;
    const std::vector<std::size_t> counts{
        1000U,
        std::size_t{1U} << 30U,
        std::size_t{1U} << 40U,
        std::size_t{1U} << 50U,
        std::size_t{1U} << 60U,
        curve_capacity,
        curve_capacity + 1U,
    };

    const std::vector<std::pair<std::string_view, DomainAllocator>> allocators{
        {"uniform", DomainAllocator::Uniform},
        {"sample_count_uniform", DomainAllocator::SampleCountUniform},
        {"monotone_half", DomainAllocator::MonotoneHalf},
        {"occupancy_floor1", DomainAllocator::OccupancyFloor1},
        {"occupancy_floor10", DomainAllocator::OccupancyFloor10},
        {"frame_core_occupancy", DomainAllocator::FrameCoreOccupancy},
        {"hybrid_occupancy", DomainAllocator::HybridOccupancy},
    };

    std::cout << "\nn_total,quantization,bits_axis,total_bits,contains_all_support,"
                 "has_cell_capacity,inside_points,outside_or_clamped_points\n";
    for (const std::size_t n : counts) {
        const DomainScenario scenario{
            n,
            n - 10U,
            {2.0, 2.0, 2.0},
            {20.0, 3.0, 2.0},
        };

        bool all_containment_false = true;
        bool all_capacity_false = true;
        for (const auto& [name, allocator] : allocators) {
            const DomainSummary summary = summarize(name, allocator, scenario, "count sweep");
            const bool capacity_ok = has_cell_capacity(summary.bits, scenario.total_count);

            std::cout << scenario.total_count << "," << summary.name << ","
                      << bits_to_string(summary.bits) << ","
                      << static_cast<unsigned>(total_bits(summary.bits)) << ","
                      << (summary.contains_support_box ? "true" : "false") << ","
                      << (capacity_ok ? "true" : "false") << "," << summary.inside_count << ","
                      << summary.outside_or_clamped_count << "\n";

            all_containment_false = all_containment_false && !summary.contains_support_box;
            all_capacity_false = all_capacity_false && !capacity_ok;

            if (allocator == DomainAllocator::FrameCoreOccupancy) {
                EXPECT_FALSE(summary.contains_support_box) << n;
                EXPECT_EQ(summary.outside_or_clamped_count, 10U) << n;
            } else {
                EXPECT_TRUE(summary.contains_support_box) << summary.name << " n=" << n;
                EXPECT_EQ(summary.inside_count, scenario.total_count) << summary.name << " n=" << n;
            }
        }

        EXPECT_FALSE(all_containment_false) << n;
        if (n == curve_capacity + 1U) {
            EXPECT_TRUE(all_capacity_false);
        }
    }
}
