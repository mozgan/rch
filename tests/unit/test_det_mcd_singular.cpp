#include <cstddef>
#include <span>
#include <vector>

#include "rch/core/matrix3.hpp"
#include "rch/robust/det_mcd.hpp"
#include "rch/robust/fallback_policy.hpp"

#include <gtest/gtest.h>

namespace {

using rch::core::Vec3;
using rch::robust::det_mcd;
using rch::robust::FallbackPolicy;

TEST(DetMcd, SmallSamplesAreExplicitlyDisabled) {
    const std::vector<Vec3<double>> points{
        {0.0, 0.0, 0.0},
        {1.0, 0.0, 0.0},
        {0.0, 1.0, 0.0},
        {0.0, 0.0, 1.0},
    };

    const auto result = det_mcd(std::span<const Vec3<double>>{points});
    EXPECT_EQ(result.policy, FallbackPolicy::disabled_small_n);
}

TEST(DetMcd, CoplanarCloudReturnsRankDeficientFallback) {
    std::vector<Vec3<double>> points;
    points.reserve(30U);
    for (std::size_t i = 0U; i < 30U; ++i) {
        const double x = static_cast<double>(i % 10U);
        const double y = static_cast<double>(i / 10U);
        points.push_back({x, y, 2.0 * x - y});
    }

    const auto result = det_mcd(std::span<const Vec3<double>>{points});
    EXPECT_EQ(result.policy, FallbackPolicy::disabled_rank_deficient);
    EXPECT_TRUE(result.subset_indices.empty());
}

TEST(DetMcd, CollinearCloudReturnsRankDeficientFallback) {
    std::vector<Vec3<double>> points;
    points.reserve(30U);
    for (std::size_t i = 0U; i < 30U; ++i) {
        const double t = static_cast<double>(i);
        points.push_back({t, 2.0 * t, -0.5 * t});
    }

    const auto result = det_mcd(std::span<const Vec3<double>>{points});
    EXPECT_EQ(result.policy, FallbackPolicy::disabled_rank_deficient);
    EXPECT_TRUE(result.subset_indices.empty());
}

} // namespace
