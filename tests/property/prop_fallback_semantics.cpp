#include <array>
#include <cstdint>
#include <limits>
#include <vector>

#include "rch/orderings/orderer.hpp"

#include <gtest/gtest.h>

#include "tests/property/property_generators.hpp"

namespace {

TEST(FallbackSemanticsProperty, InvalidShapeFailsBeforeOrdering) {
    const std::array<double, 2> malformed{0.0, 1.0};
    rch::orderings::OrderingConfig config{};
    config.method = rch::orderings::OrderingMethod::RCH;

    const auto result = rch::orderings::order_point_cloud(malformed, config);
    ASSERT_FALSE(result.has_value());
    EXPECT_EQ(result.error().code, rch::orderings::OrderingErrorCode::invalid_shape);
}

TEST(FallbackSemanticsProperty, NonFiniteInputsFailClosedForEveryMethod) {
    const double nan = std::numeric_limits<double>::quiet_NaN();
    const std::array<double, 6> invalid{0.0, 0.0, 0.0, 1.0, nan, 1.0};

    for (const auto method : rch::tests::property::all_ordering_methods()) {
        rch::orderings::OrderingConfig config{};
        config.method = method;
        const auto result = rch::orderings::order_point_cloud(invalid, config);
        ASSERT_FALSE(result.has_value());
        EXPECT_EQ(result.error().code, rch::orderings::OrderingErrorCode::invalid_input);
    }
}

TEST(FallbackSemanticsProperty, UnsupportedMethodIsExplicitError) {
    const auto points = rch::tests::property::generated_cloud(0xF7000700U, 8U);
    rch::orderings::OrderingConfig config{};
    config.method = static_cast<rch::orderings::OrderingMethod>(255);

    const auto result = rch::orderings::order_point_cloud(points, config);
    ASSERT_FALSE(result.has_value());
    EXPECT_EQ(result.error().code, rch::orderings::OrderingErrorCode::unsupported_method);
}

TEST(FallbackSemanticsProperty, TinyRobustStrategiesReportDeterministicSampleFallback) {
    const std::array<double, 12> tiny{
        0.0,
        0.0,
        0.0,
        1.0,
        0.0,
        0.0,
        0.0,
        1.0,
        0.0,
        0.0,
        0.0,
        1.0,
    };

    for (const auto method :
         {rch::orderings::OrderingMethod::RobustFrameMorton, rch::orderings::OrderingMethod::RCH}) {
        rch::orderings::OrderingConfig config{};
        config.method = method;
        const auto result = rch::orderings::order_point_cloud(tiny, config);
        ASSERT_TRUE(result.has_value());
        EXPECT_TRUE(result->robust_fallback_used);
        EXPECT_TRUE(rch::tests::property::is_permutation_of_size(*result, tiny.size() / 3U));
    }
}

TEST(FallbackSemanticsProperty, RankDeficientRobustStrategiesStillReturnPermutation) {
    std::vector<double> coplanar;
    coplanar.reserve(3U * 20U);
    for (std::size_t i = 0U; i < 20U; ++i) {
        coplanar.push_back(static_cast<double>(i % 5U));
        coplanar.push_back(static_cast<double>(i / 5U));
        coplanar.push_back(0.0);
    }

    rch::orderings::OrderingConfig config{};
    config.method = rch::orderings::OrderingMethod::RCH;
    const auto result = rch::orderings::order_point_cloud(coplanar, config);
    ASSERT_TRUE(result.has_value());
    EXPECT_TRUE(result->robust_fallback_used);
    EXPECT_TRUE(rch::tests::property::is_permutation_of_size(*result, coplanar.size() / 3U));
}

} // namespace
