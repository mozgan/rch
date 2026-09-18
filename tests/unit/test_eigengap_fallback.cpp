#include <array>
#include <cmath>
#include <cstddef>
#include <limits>

#include "rch/core/matrix3.hpp"
#include "rch/frames/robust_principal_frame.hpp"

#include <gtest/gtest.h>

namespace {

using rch::core::Matrix3;
using rch::core::Vec3;
using rch::frames::make_robust_principal_frame;
using rch::frames::project_to_robust_frame;
using rch::frames::RobustFrameMode;

[[nodiscard]] auto diagonal_scatter(const Vec3<double>& diagonal) -> Matrix3<double> {
    Matrix3<double> matrix{};
    for (std::size_t axis = 0U; axis < 3U; ++axis) {
        matrix(axis, axis) = diagonal[axis];
    }
    return matrix;
}

void expect_identity_axes(const Matrix3<double>& axes) {
    for (std::size_t row = 0U; row < 3U; ++row) {
        for (std::size_t col = 0U; col < 3U; ++col) {
            const double expected = row == col ? 1.0 : 0.0;
            EXPECT_NEAR(axes(row, col), expected, 1.0e-14);
        }
    }
}

TEST(EigengapFallback, DegenerateSpectrumUsesCanonicalAxes) {
    const auto scatter = diagonal_scatter(Vec3<double>{2.0, 2.0, 2.0});
    const auto frame = make_robust_principal_frame(scatter, 9.0);

    ASSERT_TRUE(frame.eigensolver_converged);
    EXPECT_EQ(frame.mode, RobustFrameMode::canonical_axes_fallback);
    EXPECT_NEAR(frame.gap12, 0.0, 1.0e-14);
    EXPECT_NEAR(frame.gap23, 0.0, 1.0e-14);
    expect_identity_axes(frame.axes);

    const double expected_half_extent = std::sqrt(18.0);
    for (const double half_extent : frame.half_extents) {
        EXPECT_NEAR(half_extent, expected_half_extent, 1.0e-14);
    }

    const auto projected =
        project_to_robust_frame(Vec3<double>{3.0, 4.0, 5.0}, Vec3<double>{1.0, 1.0, 1.0}, frame);
    EXPECT_NEAR(projected[0], 2.0, 1.0e-14);
    EXPECT_NEAR(projected[1], 3.0, 1.0e-14);
    EXPECT_NEAR(projected[2], 4.0, 1.0e-14);
}

TEST(EigengapFallback, SeparatedSpectrumUsesPrincipalEigenframe) {
    const auto scatter = diagonal_scatter(Vec3<double>{1.0, 4.0, 25.0});
    const auto frame = make_robust_principal_frame(scatter, 4.0);

    ASSERT_TRUE(frame.eigensolver_converged);
    EXPECT_EQ(frame.mode, RobustFrameMode::principal_eigenframe);
    EXPECT_NEAR(frame.eigenvalues[0], 25.0, 1.0e-12);
    EXPECT_NEAR(frame.eigenvalues[1], 4.0, 1.0e-12);
    EXPECT_NEAR(frame.eigenvalues[2], 1.0, 1.0e-12);
    EXPECT_NEAR(frame.half_extents[0], 10.0, 1.0e-12);
    EXPECT_NEAR(frame.half_extents[1], 4.0, 1.0e-12);
    EXPECT_NEAR(frame.half_extents[2], 2.0, 1.0e-12);

    EXPECT_NEAR(frame.axes(2U, 0U), 1.0, 1.0e-14);
    EXPECT_NEAR(frame.axes(1U, 1U), 1.0, 1.0e-14);
    EXPECT_NEAR(frame.axes(0U, 2U), 1.0, 1.0e-14);

    const auto projected =
        project_to_robust_frame(Vec3<double>{0.0, 2.0, 5.0}, Vec3<double>{0.0, 0.0, 0.0}, frame);
    EXPECT_NEAR(projected[0], 5.0, 1.0e-14);
    EXPECT_NEAR(projected[1], 2.0, 1.0e-14);
    EXPECT_NEAR(projected[2], 0.0, 1.0e-14);
}

TEST(EigengapFallback, TinySeparatedSpectrumUsesPrincipalEigenframe) {
    const auto scatter = diagonal_scatter(Vec3<double>{1.0e-300, 4.0e-300, 25.0e-300});
    const auto frame = make_robust_principal_frame(scatter, 4.0);

    ASSERT_TRUE(frame.eigensolver_converged);
    EXPECT_EQ(frame.mode, RobustFrameMode::principal_eigenframe);
    EXPECT_NEAR(frame.eigenvalues[0] / 25.0e-300, 1.0, 1.0e-12);
    EXPECT_NEAR(frame.eigenvalues[1] / 4.0e-300, 1.0, 1.0e-12);
    EXPECT_NEAR(frame.eigenvalues[2] / 1.0e-300, 1.0, 1.0e-12);
    EXPECT_NEAR(frame.half_extents[0] / (2.0 * std::sqrt(25.0e-300)), 1.0, 1.0e-12);
    EXPECT_NEAR(frame.half_extents[1] / (2.0 * std::sqrt(4.0e-300)), 1.0, 1.0e-12);
    EXPECT_NEAR(frame.half_extents[2] / (2.0 * std::sqrt(1.0e-300)), 1.0, 1.0e-12);
}

TEST(EigengapFallback, NegativeToleranceFallsBackToDefault) {
    const auto scatter = diagonal_scatter(Vec3<double>{1.0, 4.0, 25.0});
    const auto frame = make_robust_principal_frame(scatter, 4.0, -1.0);
    EXPECT_TRUE(frame.eigensolver_converged);
    EXPECT_EQ(frame.mode, rch::frames::RobustFrameMode::principal_eigenframe);
}

TEST(EigengapFallback, NonFiniteToleranceFallsBackToDefault) {
    const auto scatter = diagonal_scatter(Vec3<double>{1.0, 4.0, 25.0});
    const auto frame =
        make_robust_principal_frame(scatter, 4.0, std::numeric_limits<double>::quiet_NaN());
    EXPECT_TRUE(frame.eigensolver_converged);
    EXPECT_EQ(frame.mode, rch::frames::RobustFrameMode::principal_eigenframe);
}

TEST(EigengapFallback, OverlyLooseToleranceForcesFallbackOnSeparatedSpectrum) {
    const auto scatter = diagonal_scatter(Vec3<double>{1.0, 4.0, 25.0});
    const auto frame = make_robust_principal_frame(scatter, 4.0, 1.0);
    EXPECT_TRUE(frame.eigensolver_converged);
    EXPECT_EQ(frame.mode, rch::frames::RobustFrameMode::canonical_axes_fallback);
}

TEST(EigengapFallback, NonFiniteTauQuantSquaredYieldsZeroHalfExtents) {
    const auto scatter = diagonal_scatter(Vec3<double>{1.0, 4.0, 25.0});
    const auto frame =
        make_robust_principal_frame(scatter, std::numeric_limits<double>::quiet_NaN());
    EXPECT_EQ(frame.mode, rch::frames::RobustFrameMode::principal_eigenframe);
    for (const double extent : frame.half_extents) {
        EXPECT_EQ(extent, 0.0);
    }
}

TEST(EigengapFallback, LargeFiniteHalfExtentsDoNotOverflow) {
    const auto scatter = diagonal_scatter(Vec3<double>{1.0e299, 4.0e299, 1.0e300});
    const auto frame = make_robust_principal_frame(scatter, 1.0e300);

    EXPECT_EQ(frame.mode, rch::frames::RobustFrameMode::principal_eigenframe);
    ASSERT_TRUE(std::isfinite(frame.half_extents[0]));
    ASSERT_TRUE(std::isfinite(frame.half_extents[1]));
    ASSERT_TRUE(std::isfinite(frame.half_extents[2]));
    EXPECT_NEAR(frame.half_extents[0] / 1.0e300, 1.0, 1.0e-12);
    EXPECT_NEAR(frame.half_extents[1] / (std::sqrt(1.0e300) * std::sqrt(4.0e299)), 1.0, 1.0e-12);
    EXPECT_NEAR(frame.half_extents[2] / (std::sqrt(1.0e300) * std::sqrt(1.0e299)), 1.0, 1.0e-12);
}

TEST(EigengapFallback, NaNOffDiagonalScatterTriggersCanonicalFallback) {
    Matrix3<double> nan_scatter{};
    nan_scatter(0U, 0U) = 1.0;
    nan_scatter(1U, 1U) = 1.0;
    nan_scatter(2U, 2U) = 1.0;
    nan_scatter(0U, 1U) = std::numeric_limits<double>::quiet_NaN();
    nan_scatter(1U, 0U) = std::numeric_limits<double>::quiet_NaN();
    const auto frame = make_robust_principal_frame(nan_scatter, 4.0);
    EXPECT_FALSE(frame.eigensolver_converged);
    EXPECT_EQ(frame.mode, rch::frames::RobustFrameMode::canonical_axes_fallback);
    expect_identity_axes(frame.axes);
    // \(\mathrm{half\_extents}[k]=\sqrt{\tau^2\,\mathrm{scatter}[k,k]}=\sqrt{4\cdot1}=2.0\).
    for (const double extent : frame.half_extents) {
        EXPECT_NEAR(extent, 2.0, 1.0e-14);
    }
}

TEST(EigengapFallback, NaNDiagonalScatterTriggersCanonicalFallback) {
    Matrix3<double> nan_scatter{};
    nan_scatter(0U, 0U) = 1.0;
    nan_scatter(1U, 1U) = std::numeric_limits<double>::quiet_NaN();
    nan_scatter(2U, 2U) = 9.0;

    const auto frame = make_robust_principal_frame(nan_scatter, 4.0);

    EXPECT_FALSE(frame.eigensolver_converged);
    EXPECT_EQ(frame.mode, rch::frames::RobustFrameMode::canonical_axes_fallback);
    expect_identity_axes(frame.axes);
    EXPECT_NEAR(frame.half_extents[0], 2.0, 1.0e-14);
    EXPECT_EQ(frame.half_extents[1], 0.0);
    EXPECT_NEAR(frame.half_extents[2], 6.0, 1.0e-14);
}

} // namespace
