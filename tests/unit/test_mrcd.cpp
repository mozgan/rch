#include <bit>
#include <cmath>
#include <cstdint>
#include <limits>
#include <span>
#include <vector>

#include "rch/core/matrix3.hpp"
#include "rch/robust/fallback_policy.hpp"
#include "rch/robust/mrcd.hpp"

#include <gtest/gtest.h>

namespace {

using rch::core::Vec3;

[[nodiscard]] auto fixture_cloud() -> std::vector<Vec3<double>> {
    return {
        {-3.0, -1.0, 0.0},
        {-2.0, 1.0, 2.0},
        {-1.0, 3.0, -1.0},
        {0.0, -2.0, 1.0},
        {1.0, 0.0, -2.0},
        {2.0, 2.0, 0.0},
        {3.0, -3.0, 2.0},
        {-4.0, 2.0, 1.0},
        {4.0, -1.0, -1.0},
        {-2.0, -4.0, 3.0},
        {2.0, 4.0, -3.0},
        {5.0, 1.0, 2.0},
        {-5.0, 0.0, -2.0},
        {1.5, -3.5, 1.0},
        {-1.5, 3.5, -1.0},
        {3.5, 2.5, 3.0},
        {-3.5, -2.5, -3.0},
        {0.5, 1.5, -2.5},
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

[[nodiscard]] auto scaled_cloud(const std::vector<Vec3<double>>& points, const Vec3<double>& scale)
    -> std::vector<Vec3<double>> {
    std::vector<Vec3<double>> scaled;
    scaled.reserve(points.size());
    for (const auto& point : points) {
        scaled.push_back({point[0] * scale[0], point[1] * scale[1], point[2] * scale[2]});
    }
    return scaled;
}

[[nodiscard]] auto coplanar_cloud() -> std::vector<Vec3<double>> {
    std::vector<Vec3<double>> points;
    points.reserve(18U);
    for (int x = -3; x <= 2; ++x) {
        for (int y = -1; y <= 1; ++y) {
            points.push_back({
                static_cast<double>(x),
                static_cast<double>(y),
                static_cast<double>(x + y),
            });
        }
    }
    return points;
}

[[nodiscard]] auto same_bits(const double lhs, const double rhs) noexcept -> bool {
    return std::bit_cast<std::uint64_t>(lhs) == std::bit_cast<std::uint64_t>(rhs);
}

[[nodiscard]] auto robust_ok(const rch::robust::FallbackPolicy policy) noexcept -> bool {
    return policy == rch::robust::FallbackPolicy::none ||
           policy == rch::robust::FallbackPolicy::chi2_regularized;
}

TEST(Mrcd, RejectsTooSmallNonFiniteAndZeroMadInputs) {
    const std::vector<Vec3<double>> one_point{{1.0, 2.0, 3.0}};
    EXPECT_EQ(rch::robust::mrcd(one_point).policy, rch::robust::FallbackPolicy::disabled_small_n);

    auto nonfinite = fixture_cloud();
    nonfinite[3][1] = std::numeric_limits<double>::quiet_NaN();
    EXPECT_EQ(
        rch::robust::mrcd(nonfinite).policy, rch::robust::FallbackPolicy::disabled_rank_deficient
    );

    auto zero_axis = fixture_cloud();
    for (auto& point : zero_axis) {
        point[0] = 7.0;
    }
    EXPECT_EQ(
        rch::robust::mrcd(zero_axis).policy, rch::robust::FallbackPolicy::disabled_rank_deficient
    );
}

TEST(Mrcd, ProducesFiniteSymmetricPositiveScatter) {
    const auto result = rch::robust::mrcd(fixture_cloud());

    ASSERT_TRUE(robust_ok(result.policy));
    EXPECT_EQ(result.subset_indices.size(), result.h);
    EXPECT_GE(result.rho, 0.0);
    EXPECT_LE(result.rho, 1.0);
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

TEST(Mrcd, CoplanarCloudUsesPositiveRegularization) {
    const auto result = rch::robust::mrcd(coplanar_cloud());

    ASSERT_TRUE(robust_ok(result.policy));
    EXPECT_GT(result.rho, 0.0);
    EXPECT_TRUE(result.used_regularization);
    EXPECT_GT(rch::core::determinant(result.scatter), 0.0);
}

TEST(Mrcd, TranslationAndPositiveDiagonalScalingTransformLocationAndScatter) {
    const auto points = fixture_cloud();
    const Vec3<double> shift{8.0, -4.0, 2.0};
    const Vec3<double> scale{2.0, 0.5, 4.0};

    const auto base = rch::robust::mrcd(points);
    const auto shifted = rch::robust::mrcd(shifted_cloud(points, shift));
    const auto scaled = rch::robust::mrcd(scaled_cloud(points, scale));

    ASSERT_TRUE(robust_ok(base.policy));
    ASSERT_TRUE(robust_ok(shifted.policy));
    ASSERT_TRUE(robust_ok(scaled.policy));
    EXPECT_NEAR(shifted.rho, base.rho, 1.0e-14);
    EXPECT_NEAR(scaled.rho, base.rho, 1.0e-14);
    for (std::size_t axis = 0U; axis < 3U; ++axis) {
        EXPECT_NEAR(shifted.center[axis] - base.center[axis], shift[axis], 1.0e-10);
        EXPECT_NEAR(scaled.center[axis], base.center[axis] * scale[axis], 1.0e-10);
    }
    for (std::size_t row = 0U; row < 3U; ++row) {
        for (std::size_t col = 0U; col < 3U; ++col) {
            EXPECT_NEAR(shifted.scatter(row, col), base.scatter(row, col), 1.0e-9);
            EXPECT_NEAR(
                scaled.scatter(row, col), base.scatter(row, col) * scale[row] * scale[col], 1.0e-9
            );
        }
    }
}

TEST(MrcdRegularizedCovariance, RhoZeroReturnsScatterAsIs) {
    rch::core::Matrix3<double> scatter{};
    scatter(0U, 0U) = 4.0;
    scatter(1U, 1U) = 9.0;
    scatter(2U, 2U) = 16.0;
    scatter(0U, 1U) = 1.0;
    scatter(1U, 0U) = 1.0;

    const auto out = rch::robust::detail::mrcd_regularized_covariance(scatter, 0.0);

    for (std::size_t row = 0U; row < 3U; ++row) {
        for (std::size_t col = 0U; col < 3U; ++col) {
            EXPECT_NEAR(out(row, col), scatter(row, col), 1.0e-15);
        }
    }
}

TEST(MrcdRegularizedCovariance, RhoOneCollapsesToIdentityTarget) {
    rch::core::Matrix3<double> scatter{};
    scatter(0U, 0U) = 5.0;
    scatter(1U, 1U) = 7.0;
    scatter(2U, 2U) = 11.0;
    scatter(0U, 1U) = 0.5;
    scatter(1U, 0U) = 0.5;

    const auto out = rch::robust::detail::mrcd_regularized_covariance(scatter, 1.0);

    for (std::size_t row = 0U; row < 3U; ++row) {
        for (std::size_t col = 0U; col < 3U; ++col) {
            const double expected = (row == col) ? 1.0 : 0.0;
            EXPECT_NEAR(out(row, col), expected, 1.0e-15);
        }
    }
}

TEST(MrcdRho, ConditionCapAtOrBelowOneReturnsFullRegularization) {
    rch::core::Matrix3<double> scatter{};
    scatter(0U, 0U) = 1.0;
    scatter(1U, 1U) = 1.0;
    scatter(2U, 2U) = 1.0;

    EXPECT_DOUBLE_EQ(rch::robust::detail::mrcd_rho_for_condition_cap(scatter, 1.0), 1.0);
    EXPECT_DOUBLE_EQ(rch::robust::detail::mrcd_rho_for_condition_cap(scatter, 0.5), 1.0);
}

TEST(MrcdRho, WellConditionedScatterRequiresNoRegularization) {
    rch::core::Matrix3<double> scatter{};
    scatter(0U, 0U) = 4.0;
    scatter(1U, 1U) = 9.0;
    scatter(2U, 2U) = 16.0;

    const double rho = rch::robust::detail::mrcd_rho_for_condition_cap(scatter, 50.0);

    EXPECT_DOUBLE_EQ(rho, 0.0);
}

TEST(MrcdRho, RankDeficientDiagonalRequiresPositiveRegularization) {
    rch::core::Matrix3<double> scatter{};
    scatter(0U, 0U) = 1.0e-30;
    scatter(1U, 1U) = 1.0;
    scatter(2U, 2U) = 1.0;

    const double rho = rch::robust::detail::mrcd_rho_for_condition_cap(scatter, 50.0);

    EXPECT_GT(rho, 0.0);
    EXPECT_LE(rho, 1.0);
}

TEST(MrcdRho, RhoFormulaMeetsRequestedConditionCapOnDiagonalScatter) {
    rch::core::Matrix3<double> scatter{};
    scatter(0U, 0U) = 1.0;
    scatter(1U, 1U) = 25.0;
    scatter(2U, 2U) = 100.0;

    constexpr double cap = 10.0;
    const double rho = rch::robust::detail::mrcd_rho_for_condition_cap(scatter, cap);
    const auto regularized = rch::robust::detail::mrcd_regularized_covariance(scatter, rho);
    const double condition = regularized(2U, 2U) / regularized(0U, 0U);

    EXPECT_GT(rho, 0.0);
    EXPECT_LT(rho, 1.0);
    EXPECT_NEAR(condition, cap, 1.0e-12);
}

TEST(Mrcd, AlphaParameterAffectsSubsetSize) {
    const auto points = fixture_cloud();
    rch::robust::MrcdOptions opt_a{};
    opt_a.alpha = 0.5;
    rch::robust::MrcdOptions opt_b{};
    opt_b.alpha = 0.75;

    const auto a = rch::robust::mrcd(points, opt_a);
    const auto b = rch::robust::mrcd(points, opt_b);

    ASSERT_TRUE(robust_ok(a.policy));
    ASSERT_TRUE(robust_ok(b.policy));
    EXPECT_GT(b.h, a.h);
}

TEST(Mrcd, InvalidNumericOptionsFallBackWithoutNaNPropagation) {
    auto options = rch::robust::MrcdOptions{};
    options.scale_floor = std::numeric_limits<double>::quiet_NaN();
    options.condition_number_cap = std::numeric_limits<double>::quiet_NaN();
    options.rho_guardrail = std::numeric_limits<double>::quiet_NaN();
    options.determinant_tolerance = std::numeric_limits<double>::quiet_NaN();

    const auto result = rch::robust::mrcd(fixture_cloud(), options);

    ASSERT_TRUE(robust_ok(result.policy));
    EXPECT_TRUE(std::isfinite(result.rho));
    EXPECT_GE(result.rho, 0.0);
    EXPECT_LE(result.rho, 1.0);
    EXPECT_TRUE(rch::core::is_finite(result.center));
    EXPECT_TRUE(rch::core::is_finite(result.scatter));
}

TEST(Mrcd, RepeatedCallsAreBitStableWithinToolchain) {
    const auto points = fixture_cloud();

    const auto first = rch::robust::mrcd(points);
    const auto second = rch::robust::mrcd(points);

    EXPECT_EQ(first.policy, second.policy);
    EXPECT_EQ(first.used_regularization, second.used_regularization);
    EXPECT_TRUE(same_bits(first.rho, second.rho));
    EXPECT_EQ(first.subset_indices, second.subset_indices);
    for (std::size_t axis = 0U; axis < 3U; ++axis) {
        EXPECT_TRUE(same_bits(first.center[axis], second.center[axis]));
    }
    for (std::size_t row = 0U; row < 3U; ++row) {
        for (std::size_t col = 0U; col < 3U; ++col) {
            EXPECT_TRUE(same_bits(first.scatter(row, col), second.scatter(row, col)));
        }
    }
}

TEST(Mrcd, EqualDistanceBoundaryUsesCoordinateTieBreakBeforeInputIndex) {
    const std::vector<Vec3<double>> points{
        {1.0, 0.0, 0.0},
        {-1.0, 0.0, 0.0},
        {0.0, 2.0, 0.0},
    };

    const auto selected = rch::robust::detail::mrcd_select_h_smallest_distances(
        std::span<const Vec3<double>>{points},
        Vec3<double>{0.0, 0.0, 0.0},
        rch::core::identity_matrix3<double>(),
        1U
    );

    ASSERT_EQ(selected.size(), 1U);
    EXPECT_EQ(selected[0], 1U);
}

TEST(Mrcd, SelectHGreaterThanPointCountClampsToAvailablePoints) {
    const std::vector<Vec3<double>> points{
        {1.0, 0.0, 0.0},
        {-1.0, 0.0, 0.0},
        {0.0, 2.0, 0.0},
    };

    const auto selected = rch::robust::detail::mrcd_select_h_smallest_distances(
        std::span<const Vec3<double>>{points},
        Vec3<double>{0.0, 0.0, 0.0},
        rch::core::identity_matrix3<double>(),
        points.size() + 2U
    );

    EXPECT_EQ(selected.size(), points.size());
    EXPECT_EQ(selected, (std::vector<std::size_t>{0U, 1U, 2U}));
}

} // namespace
