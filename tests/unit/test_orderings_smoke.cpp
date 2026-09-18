#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <span>
#include <vector>

#include "rch/curves/hilbert3_standard.hpp"
#include "rch/curves/quantization.hpp"
#include "rch/orderings/compact_hilbert_order.hpp"
#include "rch/orderings/hilbert_order.hpp"
#include "rch/orderings/input_order.hpp"
#include "rch/orderings/lexicographic_order.hpp"
#include "rch/orderings/morton_order.hpp"
#include "rch/orderings/pca_compact_hilbert_order.hpp"
#include "rch/orderings/robust_compact_hilbert_order.hpp"
#include "rch/orderings/robust_frame_morton_order.hpp"

#include <gtest/gtest.h>

namespace {

using rch::orderings::OrderingMethod;

[[nodiscard]] auto sample_points() -> std::vector<double> {
    std::vector<double> points;
    points.reserve(16U * 3U);
    for (std::size_t i = 0U; i < 16U; ++i) {
        const double x = static_cast<double>(i);
        const double y = static_cast<double>((i * i) % 7U);
        const double z = static_cast<double>((3U * i + 1U) % 5U);
        points.push_back(x);
        points.push_back(y);
        points.push_back(z);
    }
    return points;
}

[[nodiscard]] auto sample_count_points(const std::size_t count) -> std::vector<double> {
    std::vector<double> points;
    points.reserve(count * 3U);
    for (std::size_t i = 0U; i < count; ++i) {
        points.push_back(static_cast<double>(i % 5U));
        points.push_back(static_cast<double>((i / 5U) % 5U));
        points.push_back(static_cast<double>(i / 25U));
    }
    return points;
}

[[nodiscard]] auto sorted_copy(std::vector<std::uint64_t> values) -> std::vector<std::uint64_t> {
    std::ranges::sort(values);
    return values;
}

[[nodiscard]] auto axes_are_finite_orthonormal(const rch::core::Matrix3<double>& axes) -> bool {
    for (std::size_t col = 0U; col < 3U; ++col) {
        double norm2 = 0.0;
        for (std::size_t row = 0U; row < 3U; ++row) {
            if (!std::isfinite(axes(row, col))) {
                return false;
            }
            norm2 += axes(row, col) * axes(row, col);
        }
        if (std::abs(norm2 - 1.0) > 1.0e-10) {
            return false;
        }
    }
    for (std::size_t left = 0U; left < 3U; ++left) {
        for (std::size_t right = left + 1U; right < 3U; ++right) {
            double dot = 0.0;
            for (std::size_t row = 0U; row < 3U; ++row) {
                dot += axes(row, left) * axes(row, right);
            }
            if (std::abs(dot) > 1.0e-10) {
                return false;
            }
        }
    }
    return true;
}

TEST(OrderingsSmoke, AllEightStrategiesReturnPermutation) {
    const auto points = sample_points();
    constexpr std::array methods{
        OrderingMethod::InputOrder,
        OrderingMethod::Lexicographic,
        OrderingMethod::Morton,
        OrderingMethod::IsotropicHilbert,
        OrderingMethod::CompactHilbertAABB,
        OrderingMethod::PcaCompactHilbert,
        OrderingMethod::RobustFrameMorton,
        OrderingMethod::RCH,
    };

    std::vector<std::uint64_t> expected(points.size() / 3U);
    std::iota(expected.begin(), expected.end(), std::uint64_t{0U});

    for (OrderingMethod method : methods) {
        rch::orderings::OrderingConfig config{};
        config.method = method;
        const auto result =
            rch::orderings::order_point_cloud(std::span<const double>{points}, config);
        ASSERT_TRUE(result.has_value()) << static_cast<int>(method);
        EXPECT_EQ(result->permutation.size(), expected.size());
        EXPECT_EQ(sorted_copy(result->permutation), expected);
        EXPECT_EQ(result->primary_keys.size(), expected.size());
        EXPECT_TRUE(result->finite_only_passed);
        EXPECT_TRUE(axes_are_finite_orthonormal(result->frame_axes));
    }
}

TEST(OrderingsSmoke, WrapperFunctionsCompileAndDispatch) {
    const auto points = sample_points();
    EXPECT_TRUE(rch::orderings::input_order(points).has_value());
    EXPECT_TRUE(rch::orderings::lexicographic_order(points).has_value());
    EXPECT_TRUE(rch::orderings::morton_order(points).has_value());
    EXPECT_TRUE(rch::orderings::hilbert_order(points).has_value());
    EXPECT_TRUE(rch::orderings::compact_hilbert_order(points).has_value());
    EXPECT_TRUE(rch::orderings::pca_compact_hilbert_order(points).has_value());
    EXPECT_TRUE(rch::orderings::robust_frame_morton_order(points).has_value());
    EXPECT_TRUE(rch::orderings::robust_compact_hilbert_order(points).has_value());
}

TEST(OrderingsSmoke, RobustCompactWrapperPreservesBitAllocatorConfig) {
    const auto points = sample_points();

    rch::orderings::OrderingConfig wrapper_config{};
    wrapper_config.bit_alloc = rch::orderings::BitAllocator::Uniform;
    wrapper_config.uniform_bits = 3U;

    rch::orderings::OrderingConfig direct_config = wrapper_config;
    direct_config.method = OrderingMethod::RCH;
    direct_config.frame = rch::orderings::FrameEstimator::DetMCD;

    const auto wrapped = rch::orderings::robust_compact_hilbert_order(points, wrapper_config);
    const auto direct = rch::orderings::order_point_cloud(points, direct_config);

    ASSERT_TRUE(wrapped.has_value());
    ASSERT_TRUE(direct.has_value());
    EXPECT_EQ(wrapped->bits_axis, (std::array<std::uint8_t, 3>{3U, 3U, 3U}));
    EXPECT_EQ(wrapped->bits_axis, direct->bits_axis);
    EXPECT_EQ(wrapped->permutation, direct->permutation);
}

TEST(OrderingsSmoke, DefaultConfigUsesFrameCoreOccupancy) {
    // The in-repo runlists define C3_frame_core_occupancy as the default RCH
    // bit-rule contract. C4_hybrid remains available only when explicitly
    // selected by a runlist or caller config.
    EXPECT_EQ(
        rch::orderings::OrderingConfig{}.bit_alloc, rch::orderings::BitAllocator::FrameCoreOccupancy
    );
    EXPECT_NE(
        rch::orderings::OrderingConfig{}.bit_alloc, rch::orderings::BitAllocator::HybridOccupancy
    );
}

TEST(OrderingsSmoke, SampleCountUniformBitsFitPointCountWithinEqualDepthGrid) {
    rch::orderings::OrderingConfig config{};
    config.bit_alloc = rch::orderings::BitAllocator::SampleCountUniform;
    config.uniform_bits = 10U;
    config.bit_sum_max = rch::curves::kMaxCurveTotalBits;

    EXPECT_EQ(rch::orderings::detail::sample_count_uniform_bits(0U, config), 10U);
    EXPECT_EQ(rch::orderings::detail::sample_count_uniform_bits(1U, config), 10U);
    EXPECT_EQ(
        rch::orderings::detail::sample_count_uniform_bits(std::size_t{1U} << 30U, config), 10U
    );
    EXPECT_EQ(
        rch::orderings::detail::sample_count_uniform_bits((std::size_t{1U} << 30U) + 1U, config),
        11U
    );

    config.uniform_bits = 0U;
    EXPECT_EQ(rch::orderings::detail::sample_count_uniform_bits(64U, config), 2U);
    EXPECT_EQ(rch::orderings::detail::sample_count_uniform_bits(65U, config), 3U);
    const std::uint8_t max_size_t_expected = std::min<std::uint8_t>(
        static_cast<std::uint8_t>((std::numeric_limits<std::size_t>::digits + 2U) / 3U),
        rch::curves::Hilbert3Standard::max_bits
    );
    EXPECT_EQ(
        rch::orderings::detail::sample_count_uniform_bits(
            std::numeric_limits<std::size_t>::max(), config
        ),
        max_size_t_expected
    );

    config.uniform_bits = 10U;
    config.bit_sum_max = 12U;
    EXPECT_EQ(
        rch::orderings::detail::sample_count_uniform_bits(std::size_t{1U} << 30U, config), 4U
    );
}

TEST(OrderingsSmoke, NonFiniteInputFailsDeterministically) {
    const std::vector<double> points{
        0.0, 0.0, 0.0, std::numeric_limits<double>::quiet_NaN(), 1.0, 2.0
    };

    const auto result = rch::orderings::robust_compact_hilbert_order(points);

    ASSERT_FALSE(result.has_value());
    EXPECT_EQ(result.error().code, rch::orderings::OrderingErrorCode::invalid_input);
}

constexpr std::array kAllOrderingMethods{
    OrderingMethod::InputOrder,
    OrderingMethod::Lexicographic,
    OrderingMethod::Morton,
    OrderingMethod::IsotropicHilbert,
    OrderingMethod::CompactHilbertAABB,
    OrderingMethod::PcaCompactHilbert,
    OrderingMethod::RobustFrameMorton,
    OrderingMethod::RCH,
};

TEST(OrderingsSmoke, EmptyInputProducesEmptyPermutationAcrossMethods) {
    const std::vector<double> points{};
    for (OrderingMethod method : kAllOrderingMethods) {
        rch::orderings::OrderingConfig config{};
        config.method = method;
        const auto result = rch::orderings::order_point_cloud(points, config);
        ASSERT_TRUE(result.has_value()) << static_cast<int>(method);
        EXPECT_TRUE(result->permutation.empty());
        EXPECT_TRUE(result->primary_keys.empty());
        EXPECT_TRUE(result->finite_only_passed);
    }
}

TEST(OrderingsSmoke, InvalidShapeRejectedDeterministically) {
    const std::vector<double> points{0.0, 1.0}; // size % 3 != 0
    for (OrderingMethod method : kAllOrderingMethods) {
        rch::orderings::OrderingConfig config{};
        config.method = method;
        const auto result = rch::orderings::order_point_cloud(points, config);
        ASSERT_FALSE(result.has_value()) << static_cast<int>(method);
        EXPECT_EQ(result.error().code, rch::orderings::OrderingErrorCode::invalid_shape);
    }
}

TEST(OrderingsSmoke, SinglePointTriviallyOrderedAcrossMethods) {
    const std::vector<double> points{1.5, -2.5, 3.5};
    for (OrderingMethod method : kAllOrderingMethods) {
        rch::orderings::OrderingConfig config{};
        config.method = method;
        const auto result = rch::orderings::order_point_cloud(points, config);
        ASSERT_TRUE(result.has_value()) << static_cast<int>(method);
        ASSERT_EQ(result->permutation.size(), 1U);
        EXPECT_EQ(result->permutation[0], 0U);
    }
}

TEST(OrderingsSmoke, AllIdenticalPointsBreakTieByInputIndex) {
    std::vector<double> points;
    for (std::size_t i = 0U; i < 5U; ++i) {
        points.push_back(2.0);
        points.push_back(-1.0);
        points.push_back(0.5);
    }

    for (OrderingMethod method : kAllOrderingMethods) {
        rch::orderings::OrderingConfig config{};
        config.method = method;
        const auto result = rch::orderings::order_point_cloud(points, config);
        ASSERT_TRUE(result.has_value()) << static_cast<int>(method);
        ASSERT_EQ(result->permutation.size(), 5U);
        // Tie-break by raw_idx must produce identity permutation when all
        // primary fields match (curve key, x, y, z all equal).
        for (std::size_t rank = 0U; rank < 5U; ++rank) {
            EXPECT_EQ(result->permutation[rank], rank) << "method=" << static_cast<int>(method);
        }
    }
}

TEST(OrderingsSmoke, StaticOrderingStrategyTemplateRespectsMethodTag) {
    const auto points = sample_points();
    const rch::orderings::StaticOrderingStrategy<OrderingMethod::Morton> morton{};
    const rch::orderings::StaticOrderingStrategy<OrderingMethod::RCH> rch{};

    EXPECT_EQ(morton.method(), OrderingMethod::Morton);
    EXPECT_EQ(rch.method(), OrderingMethod::RCH);

    rch::orderings::OrderingConfig override_config{};
    override_config.method = OrderingMethod::InputOrder; // must be overridden by template
    const auto morton_result = morton.order(points, override_config);
    const auto rch_result = rch.order(points, override_config);

    ASSERT_TRUE(morton_result.has_value());
    ASSERT_TRUE(rch_result.has_value());
    EXPECT_EQ(morton_result->method, OrderingMethod::Morton);
    EXPECT_EQ(rch_result->method, OrderingMethod::RCH);
}

TEST(OrderingsSmoke, MortonAndCompactAabbUseMonotoneHalfBitAllocator) {
    const std::vector<double> points{
        0.0,
        0.0,
        0.0,
        10.0,
        0.0,
        0.0,
        10.0,
        2.0,
        0.0,
        0.0,
        2.0,
        0.0,
    };
    constexpr std::array methods{
        OrderingMethod::Morton,
        OrderingMethod::CompactHilbertAABB,
    };

    for (const OrderingMethod method : methods) {
        rch::orderings::OrderingConfig config{};
        config.method = method;
        config.bit_alloc = rch::orderings::BitAllocator::MonotoneHalf;
        config.uniform_bits = 10U;

        const auto result = rch::orderings::order_point_cloud(points, config);

        ASSERT_TRUE(result.has_value()) << static_cast<int>(method);
        EXPECT_EQ(result->bits_axis, (std::array<std::uint8_t, 3>{10U, 4U, 1U}))
            << static_cast<int>(method);
    }
}

TEST(OrderingsSmoke, OccupancyFloorModesSeparateAdaptiveAndLegacyFloors) {
    const std::vector<double> points{
        0.0, 0.0, 0.0, 10.0, 0.0, 0.0, 10.0, 2.0, 0.0, 0.0, 2.0, 0.0,
        0.0, 0.0, 2.0, 10.0, 0.0, 2.0, 10.0, 2.0, 2.0, 0.0, 2.0, 2.0,
    };

    rch::orderings::OrderingConfig floor1{};
    floor1.method = OrderingMethod::CompactHilbertAABB;
    floor1.bit_alloc = rch::orderings::BitAllocator::OccupancyFloor1;
    floor1.uniform_bits = 10U;

    rch::orderings::OrderingConfig floor10 = floor1;
    floor10.bit_alloc = rch::orderings::BitAllocator::OccupancyFloor10;

    const auto adaptive =
        rch::orderings::order_point_cloud(std::span<const double>{points}, floor1);
    const auto legacy = rch::orderings::order_point_cloud(std::span<const double>{points}, floor10);

    ASSERT_TRUE(adaptive.has_value());
    ASSERT_TRUE(legacy.has_value());
    EXPECT_EQ(adaptive->bits_axis, (std::array<std::uint8_t, 3>{3U, 1U, 1U}));
    EXPECT_EQ(legacy->bits_axis, (std::array<std::uint8_t, 3>{10U, 10U, 10U}));
}

TEST(OrderingsSmoke, SampleCountUniformAllocatorAppliesToAllCurveMethodsSymmetrically) {
    const auto points = sample_count_points(65U);
    constexpr std::array methods{
        OrderingMethod::Morton,
        OrderingMethod::IsotropicHilbert,
        OrderingMethod::CompactHilbertAABB,
        OrderingMethod::PcaCompactHilbert,
        OrderingMethod::RobustFrameMorton,
        OrderingMethod::RCH,
    };

    for (const OrderingMethod method : methods) {
        rch::orderings::OrderingConfig config{};
        config.method = method;
        config.frame = rch::orderings::FrameEstimator::SampleCovariance;
        config.bit_alloc = rch::orderings::BitAllocator::SampleCountUniform;
        config.uniform_bits = 2U;

        const auto result = rch::orderings::order_point_cloud(points, config);

        ASSERT_TRUE(result.has_value()) << static_cast<int>(method);
        EXPECT_EQ(result->bits_axis, (std::array<std::uint8_t, 3>{3U, 3U, 3U}))
            << static_cast<int>(method);
    }
}

TEST(OrderingsSmoke, UniformAllocatorRemainsFixedResolutionBaseline) {
    const auto points = sample_count_points(65U);
    constexpr std::array methods{
        OrderingMethod::Morton,
        OrderingMethod::IsotropicHilbert,
        OrderingMethod::CompactHilbertAABB,
        OrderingMethod::PcaCompactHilbert,
        OrderingMethod::RobustFrameMorton,
        OrderingMethod::RCH,
    };

    for (const OrderingMethod method : methods) {
        rch::orderings::OrderingConfig config{};
        config.method = method;
        config.frame = rch::orderings::FrameEstimator::SampleCovariance;
        config.bit_alloc = rch::orderings::BitAllocator::Uniform;
        config.uniform_bits = 2U;

        const auto result = rch::orderings::order_point_cloud(points, config);

        ASSERT_TRUE(result.has_value()) << static_cast<int>(method);
        EXPECT_EQ(result->bits_axis, (std::array<std::uint8_t, 3>{2U, 2U, 2U}))
            << static_cast<int>(method);
    }
}

TEST(OrderingsSmoke, RobustAndHybridOccupancyUseStatisticalBitDomain) {
    std::vector<double> points;
    for (std::size_t ix = 0U; ix < 4U; ++ix) {
        for (std::size_t iy = 0U; iy < 4U; ++iy) {
            for (std::size_t iz = 0U; iz < 4U; ++iz) {
                points.push_back(-2.0 + (static_cast<double>(ix) * (4.0 / 3.0)));
                points.push_back(-2.0 + (static_cast<double>(iy) * (4.0 / 3.0)));
                points.push_back(-2.0 + (static_cast<double>(iz) * (4.0 / 3.0)));
            }
        }
    }
    points.push_back(20.0);
    points.push_back(0.0);
    points.push_back(0.0);

    rch::orderings::detail::FramePreparation prepared{};
    prepared.center = {0.0, 0.0, 0.0};
    prepared.frame.axes = rch::core::identity_matrix3<double>();
    prepared.frame.half_extents = {2.0, 2.0, 2.0};
    // \(N_{\mathrm{core}}\) is no longer hand-set: order_frame_curve counts the projections
    // inside the core box. The 64 grid points lie in \([-2,2]^3\) and the \((20,0,0)\)
    // outlier does not, so it derives exactly the 64 this test used to assert.

    rch::orderings::OrderingConfig floor1{};
    floor1.method = OrderingMethod::RCH;
    floor1.bit_alloc = rch::orderings::BitAllocator::OccupancyFloor1;
    floor1.refinement = rch::orderings::RefinementMode::Off;

    rch::orderings::OrderingConfig robust = floor1;
    robust.bit_alloc = rch::orderings::BitAllocator::FrameCoreOccupancy;

    rch::orderings::OrderingConfig hybrid = floor1;
    hybrid.bit_alloc = rch::orderings::BitAllocator::HybridOccupancy;

    const auto adaptive =
        rch::orderings::detail::order_frame_curve(points, floor1, OrderingMethod::RCH, prepared);
    const auto robust_result =
        rch::orderings::detail::order_frame_curve(points, robust, OrderingMethod::RCH, prepared);
    const auto hybrid_result =
        rch::orderings::detail::order_frame_curve(points, hybrid, OrderingMethod::RCH, prepared);

    ASSERT_TRUE(adaptive.has_value());
    ASSERT_TRUE(robust_result.has_value());
    ASSERT_TRUE(hybrid_result.has_value());
    // Robust: bits and bounds from the \(3\sigma\) core box; out-of-core points clamp.
    EXPECT_EQ(robust_result->bits_axis, (std::array<std::uint8_t, 3>{2U, 2U, 2U}));
    EXPECT_EQ(robust_result->half_extent, (rch::core::Vec3<double>{2.0, 2.0, 2.0}));
    // Hybrid: same target cell size \(\delta\) as robust, but sized so the covering
    // box is quantized at \(\delta\), giving more bits than robust on the inflated axis,
    // and bounds cover every point (no clamp).
    EXPECT_EQ(hybrid_result->bits_axis, (std::array<std::uint8_t, 3>{6U, 2U, 2U}));
    EXPECT_EQ(hybrid_result->half_extent, (rch::core::Vec3<double>{20.0, 2.0, 2.0}));
    EXPECT_GT(hybrid_result->bits_axis[0], robust_result->bits_axis[0]);
    // Floor1: covering box plus total point count, distinct from both.
    EXPECT_EQ(adaptive->bits_axis, (std::array<std::uint8_t, 3>{5U, 1U, 1U}));
    EXPECT_EQ(adaptive->half_extent, (rch::core::Vec3<double>{20.0, 2.0, 2.0}));
}

TEST(OrderingsSmoke, IsotropicHilbertUsesStandardEqualDepthKeys) {
    const std::vector<double> points{
        0.0,
        0.0,
        0.0,
        10.0,
        0.0,
        0.0,
        10.0,
        2.0,
        0.0,
        0.0,
        2.0,
        0.0,
        6.0,
        1.0,
        0.0,
    };

    rch::orderings::OrderingConfig isotropic_config{};
    isotropic_config.method = OrderingMethod::IsotropicHilbert;
    isotropic_config.bit_alloc = rch::orderings::BitAllocator::MonotoneHalf;
    isotropic_config.uniform_bits = 10U;

    const auto isotropic =
        rch::orderings::order_point_cloud(std::span<const double>{points}, isotropic_config);
    ASSERT_TRUE(isotropic.has_value());
    EXPECT_EQ(isotropic->bits_axis, (std::array<std::uint8_t, 3>{10U, 10U, 10U}));

    rch::orderings::OrderingConfig compact_config = isotropic_config;
    compact_config.method = OrderingMethod::CompactHilbertAABB;
    const auto compact =
        rch::orderings::order_point_cloud(std::span<const double>{points}, compact_config);
    ASSERT_TRUE(compact.has_value());
    EXPECT_NE(isotropic->bits_axis, compact->bits_axis);
    EXPECT_NE(isotropic->primary_keys, compact->primary_keys);

    constexpr double lo_x = 0.0;
    constexpr double hi_x = 10.0;
    constexpr double lo_y = 0.0;
    constexpr double hi_y = 2.0;
    constexpr double lo_z = 0.0;
    constexpr double hi_z = 0.0;
    constexpr std::uint8_t bits = 10U;
    for (std::size_t i = 0U; i < points.size() / 3U; ++i) {
        const std::size_t base = 3U * i;
        const rch::curves::Point3u32 q{
            rch::curves::quantize_axis(points[base], lo_x, hi_x, bits),
            rch::curves::quantize_axis(points[base + 1U], lo_y, hi_y, bits),
            rch::curves::quantize_axis(points[base + 2U], lo_z, hi_z, bits),
        };
        const auto expected = rch::curves::Hilbert3Standard::encode(q, bits);
        ASSERT_TRUE(expected.has_value()) << i;
        EXPECT_EQ(isotropic->primary_keys[i], *expected) << i;
    }
}

TEST(OrderingsSmoke, FrameMortonUsesMonotoneHalfBitAllocator) {
    const auto points = sample_points();

    rch::orderings::OrderingConfig config{};
    config.method = OrderingMethod::RobustFrameMorton;
    config.frame = rch::orderings::FrameEstimator::SampleCovariance;
    config.bit_alloc = rch::orderings::BitAllocator::MonotoneHalf;
    config.uniform_bits = 10U;

    const auto result = rch::orderings::order_point_cloud(points, config);

    ASSERT_TRUE(result.has_value());
    const auto total_bits = static_cast<unsigned int>(result->bits_axis[0]) +
                            static_cast<unsigned int>(result->bits_axis[1]) +
                            static_cast<unsigned int>(result->bits_axis[2]);
    EXPECT_EQ(total_bits, 15U);
    EXPECT_NE(result->bits_axis, (std::array<std::uint8_t, 3>{10U, 10U, 10U}));
}

TEST(OrderingsSmoke, FrameQuantizationDomainUsesHalfExtents) {
    const rch::core::Vec3<double> half_extents{2.0, 3.0, 4.0};

    const auto bounds = rch::orderings::detail::bounds_from_half_extents(half_extents);

    EXPECT_EQ(bounds.lo, (rch::core::Vec3<double>{-2.0, -3.0, -4.0}));
    EXPECT_EQ(bounds.hi, (rch::core::Vec3<double>{2.0, 3.0, 4.0}));
}

TEST(OrderingsSmoke, RchAcceptsOgkFrameEstimator) {
    const std::vector<double> points{
        -2.0, -1.0, 0.0, -1.0, 0.0,  2.0, 0.0, 2.0, -1.0, 1.0, -2.0, 1.0, 2.0, 1.0,
        -2.0, 3.0,  0.0, 0.0,  -3.0, 1.0, 1.0, 0.0, -3.0, 2.0, 2.0,  2.0, 2.0,
    };

    rch::orderings::OrderingConfig config{};
    config.method = OrderingMethod::RCH;
    config.frame = rch::orderings::FrameEstimator::OGK;

    const auto result = rch::orderings::order_point_cloud(points, config);

    ASSERT_TRUE(result.has_value());
    EXPECT_EQ(result->method, OrderingMethod::RCH);
    EXPECT_FALSE(result->permutation.empty());
    EXPECT_FALSE(result->robust_fallback_used);
    EXPECT_TRUE(axes_are_finite_orthonormal(result->frame_axes));
}

TEST(OrderingsSmoke, RchAcceptsMrcdFrameEstimator) {
    const std::vector<double> points{
        -3.0, -1.0, 0.0,  -2.0, 1.0,  2.0,  -1.0, 3.0,  -1.0, 0.0, -2.0, 1.0,  1.0,  0.0,
        -2.0, 2.0,  2.0,  0.0,  3.0,  -3.0, 2.0,  -4.0, 2.0,  1.0, 4.0,  -1.0, -1.0, -2.0,
        -4.0, 3.0,  2.0,  4.0,  -3.0, 5.0,  1.0,  2.0,  -5.0, 0.0, -2.0, 1.5,  -3.5, 1.0,
        -1.5, 3.5,  -1.0, 3.5,  2.5,  3.0,  -3.5, -2.5, -3.0, 0.5, 1.5,  -2.5,
    };

    rch::orderings::OrderingConfig config{};
    config.method = OrderingMethod::RCH;
    config.frame = rch::orderings::FrameEstimator::MRCD;

    const auto result = rch::orderings::order_point_cloud(points, config);

    ASSERT_TRUE(result.has_value());
    EXPECT_EQ(result->method, OrderingMethod::RCH);
    EXPECT_FALSE(result->permutation.empty());
    EXPECT_FALSE(result->robust_fallback_used);
    EXPECT_TRUE(axes_are_finite_orthonormal(result->frame_axes));
}

} // namespace
