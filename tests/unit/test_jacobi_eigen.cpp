#include <array>
#include <cmath>
#include <cstddef>
#include <limits>

#include "rch/core/matrix3.hpp"
#include "rch/frames/eigen3x3.hpp"

#include <gtest/gtest.h>

namespace {

using rch::core::frobenius_norm;
using rch::core::Matrix3;
using rch::core::multiply;
using rch::core::Vec3;
using rch::frames::cyclic_jacobi_eigen_symmetric3;

[[nodiscard]] auto diagonal_from(const Vec3<double>& values) -> Matrix3<double> {
    Matrix3<double> matrix{};
    for (std::size_t axis = 0U; axis < 3U; ++axis) {
        matrix(axis, axis) = values[axis];
    }
    return matrix;
}

[[nodiscard]] auto reconstruct(const Vec3<double>& values, const Matrix3<double>& vectors)
    -> Matrix3<double> {
    Matrix3<double> result{};
    for (std::size_t row = 0U; row < 3U; ++row) {
        for (std::size_t col = 0U; col < 3U; ++col) {
            for (std::size_t k = 0U; k < 3U; ++k) {
                result(row, col) += vectors(row, k) * values[k] * vectors(col, k);
            }
        }
    }
    return result;
}

void expect_orthonormal_columns(const Matrix3<double>& vectors, const double tolerance = 1.0e-12) {
    for (std::size_t lhs = 0U; lhs < 3U; ++lhs) {
        for (std::size_t rhs = 0U; rhs < 3U; ++rhs) {
            double dot = 0.0;
            for (std::size_t row = 0U; row < 3U; ++row) {
                dot += vectors(row, lhs) * vectors(row, rhs);
            }
            const double expected = lhs == rhs ? 1.0 : 0.0;
            EXPECT_NEAR(dot, expected, tolerance);
        }
    }
}

TEST(Matrix3, DeterminantInverseAndFrobeniusNorm) {
    const Matrix3<double> matrix{{
        std::array<double, 3>{4.0, 7.0, 2.0},
        std::array<double, 3>{3.0, 6.0, 1.0},
        std::array<double, 3>{2.0, 5.0, 3.0},
    }};

    EXPECT_NEAR(rch::core::determinant(matrix), 9.0, 1.0e-14);
    EXPECT_NEAR(frobenius_norm(matrix), std::sqrt(153.0), 1.0e-14);

    const auto inverse = rch::core::inverse(matrix);
    ASSERT_TRUE(inverse.has_value());
    const auto product = multiply(matrix, multiply(*inverse, Vec3<double>{1.0, -2.0, 0.5}));
    EXPECT_NEAR(product[0], 1.0, 1.0e-12);
    EXPECT_NEAR(product[1], -2.0, 1.0e-12);
    EXPECT_NEAR(product[2], 0.5, 1.0e-12);
}

TEST(JacobiEigen3x3, MatchesPinnedNumpyEigenvalues) {
    struct Case {
        Matrix3<double> matrix;
        Vec3<double> expected;
    };

    const std::array<Case, 5> cases{{
        {
            Matrix3<double>{{
                std::array<double, 3>{4.375, 1.125, -0.5},
                std::array<double, 3>{1.125, 3.375, 0.75},
                std::array<double, 3>{-0.5, 0.75, 2.25},
            }},
            Vec3<double>{1.524335305827238, 3.369513318334494, 5.106151375838270},
        },
        {
            Matrix3<double>{{
                std::array<double, 3>{9.25, -2.0, 1.5},
                std::array<double, 3>{-2.0, 5.5, 0.875},
                std::array<double, 3>{1.5, 0.875, 4.75},
            }},
            Vec3<double>{3.215809453129087, 5.965241043386324, 10.318949503484589},
        },
        {
            Matrix3<double>{{
                std::array<double, 3>{1.0, 0.125, 0.0},
                std::array<double, 3>{0.125, 1.75, -0.25},
                std::array<double, 3>{0.0, -0.25, 3.5},
            }},
            Vec3<double>{0.979059129426401, 1.735808167948319, 3.535132702625281},
        },
        {
            Matrix3<double>{{
                std::array<double, 3>{12.0, 3.0, 2.0},
                std::array<double, 3>{3.0, 7.0, -1.0},
                std::array<double, 3>{2.0, -1.0, 5.0},
            }},
            Vec3<double>{3.403733341286131, 6.958110933998418, 13.638155724715450},
        },
        {
            Matrix3<double>{{
                std::array<double, 3>{2.25, -0.375, 0.625},
                std::array<double, 3>{-0.375, 4.5, 1.125},
                std::array<double, 3>{0.625, 1.125, 6.0},
            }},
            Vec3<double>{2.012022787377795, 4.102904684591139, 6.635072528031067},
        },
    }};

    for (const auto& test_case : cases) {
        const auto eigen = cyclic_jacobi_eigen_symmetric3(test_case.matrix);
        ASSERT_TRUE(eigen.converged);
        for (std::size_t axis = 0U; axis < 3U; ++axis) {
            EXPECT_NEAR(eigen.eigenvalues[axis], test_case.expected[axis], 1.0e-12);
        }

        const auto rebuilt = reconstruct(eigen.eigenvalues, eigen.eigenvectors);
        EXPECT_LE(frobenius_norm(rebuilt - test_case.matrix), 1.0e-11);
        expect_orthonormal_columns(eigen.eigenvectors);
    }
}

TEST(JacobiEigen3x3, HandlesAlreadyDiagonalSpdMatrix) {
    const Vec3<double> diagonal{1.0, 2.0, 8.0};
    const auto eigen = cyclic_jacobi_eigen_symmetric3(diagonal_from(diagonal));

    ASSERT_TRUE(eigen.converged);
    EXPECT_EQ(eigen.eigenvalues, diagonal);
    EXPECT_LE(
        frobenius_norm(
            reconstruct(eigen.eigenvalues, eigen.eigenvectors) - diagonal_from(diagonal)
        ),
        1.0e-14
    );
}

TEST(JacobiEigen3x3, RejectsNonFiniteDiagonalAsUnconverged) {
    auto matrix = diagonal_from(Vec3<double>{1.0, 2.0, 3.0});
    matrix(1U, 1U) = std::numeric_limits<double>::quiet_NaN();

    const auto eigen = cyclic_jacobi_eigen_symmetric3(matrix);

    EXPECT_FALSE(eigen.converged);
}

TEST(JacobiEigen3x3, BadToleranceFallsBackToDefaultTolerance) {
    const auto matrix = diagonal_from(Vec3<double>{1.0, 2.0, 8.0});

    const auto nan_tolerance =
        cyclic_jacobi_eigen_symmetric3(matrix, 32U, std::numeric_limits<double>::quiet_NaN());
    EXPECT_TRUE(nan_tolerance.converged);
    EXPECT_EQ(nan_tolerance.sweeps, 0U);

    const auto negative_tolerance = cyclic_jacobi_eigen_symmetric3(matrix, 32U, -1.0);
    EXPECT_TRUE(negative_tolerance.converged);
    EXPECT_EQ(negative_tolerance.sweeps, 0U);

    // A zero tolerance is unsatisfiable whenever rotate_pair skips every pivot, so it is
    // repaired to the default rather than accepted. Without the repair this converges
    // false after max_sweeps even though the input is already diagonal.
    const auto zero_tolerance = cyclic_jacobi_eigen_symmetric3(matrix, 32U, 0.0);
    EXPECT_TRUE(zero_tolerance.converged);
    EXPECT_EQ(zero_tolerance.sweeps, 0U);
}

TEST(JacobiEigen3x3, ZeroToleranceDoesNotStallOnSubEpsilonOffDiagonals) {
    // Exact zero tolerance is repaired to the default so roundoff-level residuals cannot
    // force all sweeps to be spent chasing bit-exact diagonalization.
    auto matrix = diagonal_from(Vec3<double>{1.0, 1.0, 1.0});
    matrix(0U, 1U) = matrix(1U, 0U) = 1.0e-17;
    matrix(0U, 2U) = matrix(2U, 0U) = 1.0e-17;
    matrix(1U, 2U) = matrix(2U, 1U) = 1.0e-17;

    const auto zero_tolerance = cyclic_jacobi_eigen_symmetric3(matrix, 32U, 0.0);
    EXPECT_TRUE(zero_tolerance.converged);
    EXPECT_LT(zero_tolerance.sweeps, 32U);
}

TEST(JacobiEigen3x3, TinyRotatedMatrixIsSolvedRelativeToItsOwnScale) {
    constexpr double inv_sqrt2 = 0.70710678118654752440;
    const Vec3<double> expected{1.0e-300, 2.0e-300, 4.0e-300};
    Matrix3<double> vectors{};
    vectors(0U, 0U) = inv_sqrt2;
    vectors(1U, 0U) = inv_sqrt2;
    vectors(0U, 1U) = -inv_sqrt2;
    vectors(1U, 1U) = inv_sqrt2;
    vectors(2U, 2U) = 1.0;
    const auto matrix = reconstruct(expected, vectors);

    const auto eigen = cyclic_jacobi_eigen_symmetric3(matrix, 64U);

    ASSERT_TRUE(eigen.converged);
    for (std::size_t axis = 0U; axis < 3U; ++axis) {
        EXPECT_NEAR(eigen.eigenvalues[axis] / expected[axis], 1.0, 1.0e-12);
    }
    const auto rebuilt = reconstruct(eigen.eigenvalues, eigen.eigenvectors);
    EXPECT_LE(frobenius_norm(rebuilt - matrix) / frobenius_norm(matrix), 1.0e-12);
    expect_orthonormal_columns(eigen.eigenvectors);
}

TEST(JacobiEigen3x3, LargeFiniteMatrixDoesNotShortCircuitFromNormOverflow) {
    Matrix3<double> matrix{};
    matrix(0U, 0U) = 1.0e300;
    matrix(1U, 1U) = 2.0e300;
    matrix(2U, 2U) = 3.0e300;
    matrix(0U, 1U) = 1.0e299;
    matrix(1U, 0U) = 1.0e299;

    const auto eigen = cyclic_jacobi_eigen_symmetric3(matrix, 64U);

    EXPECT_TRUE(eigen.converged);
    EXPECT_GT(eigen.sweeps, 0U);
    expect_orthonormal_columns(eigen.eigenvectors, 1.0e-12);
}

} // namespace
