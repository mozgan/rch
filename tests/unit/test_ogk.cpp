#include <bit>
#include <cmath>
#include <cstdint>
#include <limits>
#include <vector>

#include "rch/core/matrix3.hpp"
#include "rch/robust/fallback_policy.hpp"
#include "rch/robust/ogk.hpp"

#include <gtest/gtest.h>

namespace {

using rch::core::Matrix3;
using rch::core::Vec3;

[[nodiscard]] auto fixture_cloud() -> std::vector<Vec3<double>> {
    return {
        {-2.0, -1.0, 0.0},
        {-1.0, 0.0, 2.0},
        {0.0, 2.0, -1.0},
        {1.0, -2.0, 1.0},
        {2.0, 1.0, -2.0},
        {3.0, 0.0, 0.0},
        {-3.0, 1.0, 1.0},
        {0.0, -3.0, 2.0},
        {2.0, 2.0, 2.0},
    };
}

[[nodiscard]] auto shifted_cloud(const std::vector<Vec3<double>>& points, const Vec3<double>& shift)
    -> std::vector<Vec3<double>> {
    std::vector<Vec3<double>> shifted;
    shifted.reserve(points.size());
    for (const auto& point : points) {
        shifted.push_back({point[0] + shift[0], point[1] + shift[1], point[2] + shift[2]});
    }
    return shifted;
}

[[nodiscard]] auto same_bits(const double lhs, const double rhs) noexcept -> bool {
    return std::bit_cast<std::uint64_t>(lhs) == std::bit_cast<std::uint64_t>(rhs);
}

TEST(Ogk, RejectsTooSmallOrNonFiniteInput) {
    const std::vector<Vec3<double>> one_point{{1.0, 2.0, 3.0}};
    const auto small = rch::robust::ogk(one_point);
    EXPECT_EQ(small.policy, rch::robust::FallbackPolicy::disabled_small_n);

    const std::vector<Vec3<double>> nonfinite{
        {1.0, 2.0, 3.0},
        {4.0, std::numeric_limits<double>::quiet_NaN(), 6.0},
    };
    const auto bad = rch::robust::ogk(nonfinite);
    EXPECT_EQ(bad.policy, rch::robust::FallbackPolicy::disabled_rank_deficient);
}

TEST(Ogk, ZeroMadAxisIsExplicitlyDisabled) {
    const std::vector<Vec3<double>> zero_axis{
        {5.0, -2.0, 0.0},
        {5.0, -1.0, 2.0},
        {5.0, 0.0, -1.0},
        {5.0, 1.0, 1.0},
        {5.0, 2.0, -2.0},
    };

    const auto result = rch::robust::ogk(zero_axis);

    EXPECT_EQ(result.policy, rch::robust::FallbackPolicy::disabled_rank_deficient);
}

TEST(Ogk, ProducesFiniteSymmetricPositiveScatter) {
    const auto result = rch::robust::ogk(fixture_cloud());

    EXPECT_TRUE(
        result.policy == rch::robust::FallbackPolicy::none ||
        result.policy == rch::robust::FallbackPolicy::chi2_regularized
    );
    EXPECT_TRUE(rch::core::is_finite(result.center));
    EXPECT_TRUE(rch::core::is_finite(result.scatter));
    for (std::size_t row = 0U; row < 3U; ++row) {
        EXPECT_GT(result.scatter(row, row), 0.0);
        for (std::size_t col = 0U; col < 3U; ++col) {
            EXPECT_NEAR(result.scatter(row, col), result.scatter(col, row), 1.0e-12);
        }
    }
    EXPECT_GT(rch::core::determinant(result.scatter), 0.0);
}

TEST(Ogk, TranslationShiftsLocationButKeepsScatter) {
    const auto base_points = fixture_cloud();
    const Vec3<double> shift{10.0, -5.0, 3.5};
    const auto shifted_points = shifted_cloud(base_points, shift);

    const auto base = rch::robust::ogk(base_points);
    const auto shifted = rch::robust::ogk(shifted_points);

    ASSERT_TRUE(
        base.policy == rch::robust::FallbackPolicy::none ||
        base.policy == rch::robust::FallbackPolicy::chi2_regularized
    );
    ASSERT_TRUE(
        shifted.policy == rch::robust::FallbackPolicy::none ||
        shifted.policy == rch::robust::FallbackPolicy::chi2_regularized
    );
    for (std::size_t axis = 0U; axis < 3U; ++axis) {
        EXPECT_NEAR(shifted.center[axis] - base.center[axis], shift[axis], 1.0e-10);
    }
    for (std::size_t row = 0U; row < 3U; ++row) {
        for (std::size_t col = 0U; col < 3U; ++col) {
            EXPECT_NEAR(shifted.scatter(row, col), base.scatter(row, col), 1.0e-10);
        }
    }
}

[[nodiscard]] auto scaled_cloud(const std::vector<Vec3<double>>& points, const Vec3<double>& scale)
    -> std::vector<Vec3<double>> {
    std::vector<Vec3<double>> scaled;
    scaled.reserve(points.size());
    for (const auto& point : points) {
        scaled.push_back({point[0] * scale[0], point[1] * scale[1], point[2] * scale[2]});
    }
    return scaled;
}

TEST(Ogk, PositiveDiagonalScalingScalesScatterByOuterProduct) {
    const auto base_points = fixture_cloud();
    const Vec3<double> scale{2.0, 0.5, 4.0};

    const auto base = rch::robust::ogk(base_points);
    const auto scaled = rch::robust::ogk(scaled_cloud(base_points, scale));

    ASSERT_TRUE(
        base.policy == rch::robust::FallbackPolicy::none ||
        base.policy == rch::robust::FallbackPolicy::chi2_regularized
    );
    ASSERT_TRUE(
        scaled.policy == rch::robust::FallbackPolicy::none ||
        scaled.policy == rch::robust::FallbackPolicy::chi2_regularized
    );
    for (std::size_t axis = 0U; axis < 3U; ++axis) {
        EXPECT_NEAR(scaled.center[axis], base.center[axis] * scale[axis], 1.0e-10);
    }
    for (std::size_t row = 0U; row < 3U; ++row) {
        for (std::size_t col = 0U; col < 3U; ++col) {
            EXPECT_NEAR(
                scaled.scatter(row, col), base.scatter(row, col) * scale[row] * scale[col], 1.0e-10
            );
        }
    }
}

TEST(OgkPairwise, DiagonalIsOneAndOffDiagonalsStayInsideOpenUnitInterval) {
    const auto points = fixture_cloud();
    rch::core::Vec3<double> scales{};
    for (std::size_t axis = 0U; axis < 3U; ++axis) {
        scales[axis] = rch::robust::detail::robust_scale(
            rch::robust::detail::axis_values(points, axis), 1.0e-12
        );
        ASSERT_GT(scales[axis], 0.0);
    }
    const auto scaled =
        rch::robust::detail::transform_to_scaled_coordinates(points, scales);
    const auto pairwise = rch::robust::detail::pairwise_correlation_matrix(
        std::span<const rch::core::Vec3<double>>{scaled}, 1.0e-12
    );

    for (std::size_t row = 0U; row < 3U; ++row) {
        EXPECT_EQ(pairwise(row, row), 1.0);
    }
    for (std::size_t row = 0U; row < 3U; ++row) {
        for (std::size_t col = 0U; col < 3U; ++col) {
            if (row == col) {
                continue;
            }
            EXPECT_GE(pairwise(row, col), -0.999);
            EXPECT_LE(pairwise(row, col), 0.999);
            EXPECT_EQ(pairwise(row, col), pairwise(col, row));
        }
    }
}

TEST(OgkPairwise, ResultMatrixIsSymmetricByConstruction) {
    const auto points = fixture_cloud();
    rch::core::Vec3<double> scales{};
    for (std::size_t axis = 0U; axis < 3U; ++axis) {
        scales[axis] = rch::robust::detail::robust_scale(
            rch::robust::detail::axis_values(points, axis), 1.0e-12
        );
        ASSERT_GT(scales[axis], 0.0);
    }
    const auto scaled =
        rch::robust::detail::transform_to_scaled_coordinates(points, scales);
    const auto pairwise = rch::robust::detail::pairwise_correlation_matrix(
        std::span<const rch::core::Vec3<double>>{scaled}, 1.0e-12
    );

    for (std::size_t row = 0U; row < 3U; ++row) {
        for (std::size_t col = 0U; col < 3U; ++col) {
            EXPECT_EQ(pairwise(row, col), pairwise(col, row));
        }
    }
}

TEST(Ogk, RepeatedCallsAreBitStableWithinToolchain) {
    const auto points = fixture_cloud();

    const auto first = rch::robust::ogk(points);
    const auto second = rch::robust::ogk(points);

    EXPECT_EQ(first.policy, second.policy);
    EXPECT_EQ(first.used_regularization, second.used_regularization);
    for (std::size_t axis = 0U; axis < 3U; ++axis) {
        EXPECT_TRUE(same_bits(first.center[axis], second.center[axis]));
    }
    for (std::size_t row = 0U; row < 3U; ++row) {
        for (std::size_t col = 0U; col < 3U; ++col) {
            EXPECT_TRUE(same_bits(first.scatter(row, col), second.scatter(row, col)));
        }
    }
}

} // namespace
