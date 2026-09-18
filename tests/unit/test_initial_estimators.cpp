#include <array>
#include <cmath>
#include <cstddef>
#include <span>
#include <string_view>
#include <vector>

#include "rch/core/matrix3.hpp"
#include "rch/robust/initial_estimators.hpp"

#include <gtest/gtest.h>

namespace {

using rch::core::Vec3;
using rch::robust::InitialEstimatorKind;
using rch::robust::make_initial_estimates;

[[nodiscard]] auto make_test_cloud(const std::size_t n) -> std::vector<Vec3<double>> {
    std::vector<Vec3<double>> points;
    points.reserve(n);
    for (std::size_t i = 0U; i < n; ++i) {
        const double t = static_cast<double>(i);
        points.push_back({t * 0.10, (t * 0.20) + 0.5, (t * 0.30) - 1.0});
    }
    return points;
}

TEST(InitialEstimators, ProducesAllSixStartsInCanonicalOrder) {
    const auto points = make_test_cloud(50U);
    const auto starts = make_initial_estimates(std::span<const Vec3<double>>{points}, 25U);

    constexpr std::array<InitialEstimatorKind, 6> expected_kinds{{
        InitialEstimatorKind::tanh,
        InitialEstimatorKind::spearman,
        InitialEstimatorKind::normal_score,
        InitialEstimatorKind::spatial_sign,
        InitialEstimatorKind::bacon,
        InitialEstimatorKind::ogk,
    }};
    for (std::size_t i = 0U; i < starts.size(); ++i) {
        EXPECT_EQ(starts[i].kind, expected_kinds[i]);
    }
}

TEST(InitialEstimators, NamesMatchKindsByEstimatorNameTable) {
    const auto points = make_test_cloud(50U);
    const auto starts = make_initial_estimates(std::span<const Vec3<double>>{points}, 25U);
    EXPECT_EQ(starts[0].name, std::string_view{"tanh"});
    EXPECT_EQ(starts[1].name, std::string_view{"spearman"});
    EXPECT_EQ(starts[2].name, std::string_view{"normal_score"});
    EXPECT_EQ(starts[3].name, std::string_view{"spatial_sign"});
    EXPECT_EQ(starts[4].name, std::string_view{"bacon"});
    EXPECT_EQ(starts[5].name, std::string_view{"ogk"});
}

TEST(InitialEstimators, AllSixProduceFiniteCenterAndScatter) {
    const auto points = make_test_cloud(50U);
    const auto starts = make_initial_estimates(std::span<const Vec3<double>>{points}, 25U);
    for (std::size_t i = 0U; i < starts.size(); ++i) {
        EXPECT_TRUE(rch::core::is_finite(starts[i].center)) << "kind=" << starts[i].name;
        EXPECT_TRUE(rch::core::is_finite(starts[i].scatter)) << "kind=" << starts[i].name;
    }
}

TEST(InitialEstimators, BaconStartProducesNontrivialScatter) {
    const auto points = make_test_cloud(100U);
    const auto starts = make_initial_estimates(std::span<const Vec3<double>>{points}, 50U);
    EXPECT_GT(rch::core::frobenius_norm(starts[4].scatter), 0.0);
}

TEST(InitialEstimators, BaconStartUsesCoordinateTieBreakBeforeInputIndex) {
    const std::vector<Vec3<double>> points{
        {1.0, 0.0, 0.0},
        {-1.0, 0.0, 0.0},
    };

    const auto start = rch::robust::detail::bacon_start(std::span<const Vec3<double>>{points}, 1U);

    EXPECT_DOUBLE_EQ(start.center[0], -1.0);
    EXPECT_DOUBLE_EQ(start.center[1], 0.0);
    EXPECT_DOUBLE_EQ(start.center[2], 0.0);
}

TEST(InitialEstimators, CorrelationConversionAvoidsVarianceProductOverflow) {
    rch::core::Matrix3<double> covariance{};
    covariance(0U, 0U) = 1.0e300;
    covariance(1U, 1U) = 1.0e300;
    covariance(2U, 2U) = 1.0;
    covariance(0U, 1U) = 5.0e299;
    covariance(1U, 0U) = 5.0e299;

    const auto correlation = rch::robust::detail::correlation_from_covariance(covariance);

    EXPECT_TRUE(rch::core::is_finite(correlation));
    EXPECT_NEAR(correlation(0U, 1U), 0.5, 1.0e-15);
    EXPECT_NEAR(correlation(1U, 0U), 0.5, 1.0e-15);
}

TEST(InitialEstimators, EuclideanNormAvoidsIntermediateOverflow) {
    const rch::core::Vec3<double> point{1.0e200, -1.0e200, 1.0e200};

    const double norm = rch::robust::detail::euclidean_norm(point);

    EXPECT_TRUE(std::isfinite(norm));
    EXPECT_GT(norm, 1.0e200);
}

TEST(InitialEstimators, BaconStartClampsSubsetSizeToAvailablePoints) {
    const std::vector<Vec3<double>> points{
        {1.0, 0.0, 0.0},
        {-1.0, 0.0, 0.0},
    };

    const auto start =
        rch::robust::detail::bacon_start(std::span<const Vec3<double>>{points}, points.size() + 3U);

    EXPECT_TRUE(rch::core::is_finite(start.center));
    EXPECT_TRUE(rch::core::is_finite(start.scatter));
    EXPECT_DOUBLE_EQ(start.center[0], 0.0);
}

TEST(InitialEstimators, RepeatedCallsAreDeterministic) {
    const auto points = make_test_cloud(50U);
    const auto first = make_initial_estimates(std::span<const Vec3<double>>{points}, 25U);
    const auto second = make_initial_estimates(std::span<const Vec3<double>>{points}, 25U);
    for (std::size_t i = 0U; i < first.size(); ++i) {
        EXPECT_EQ(first[i].kind, second[i].kind);
        EXPECT_EQ(first[i].name, second[i].name);
        for (std::size_t axis = 0U; axis < 3U; ++axis) {
            EXPECT_EQ(first[i].center[axis], second[i].center[axis]);
            for (std::size_t col = 0U; col < 3U; ++col) {
                EXPECT_EQ(first[i].scatter(axis, col), second[i].scatter(axis, col));
            }
        }
    }
}

} // namespace
