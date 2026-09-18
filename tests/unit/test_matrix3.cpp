#include <array>
#include <bit>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <span>
#include <vector>

#include "rch/core/matrix3.hpp"

#include <gtest/gtest.h>

namespace {

using rch::core::Matrix3;
using rch::core::Vec3;
using rch::core::operator*;
using rch::core::operator+;
using rch::core::operator-;
using rch::core::operator/;

constexpr double kTol = 1.0e-12;

template <typename T>
concept HasFloatingMean3 = requires(std::span<const Vec3<T>> points) { rch::core::mean3(points); };

template <typename T>
concept HasFloatingInverse = requires(Matrix3<T> matrix) { rch::core::inverse(matrix); };

template <typename T>
concept HasFloatingFrobeniusNorm =
    requires(Matrix3<T> matrix) { rch::core::frobenius_norm(matrix); };

static_assert(!HasFloatingMean3<int>);
static_assert(!HasFloatingInverse<int>);
static_assert(!HasFloatingFrobeniusNorm<int>);
static_assert(HasFloatingMean3<double>);
static_assert(HasFloatingInverse<double>);
static_assert(HasFloatingFrobeniusNorm<double>);

auto product(const Matrix3<double>& lhs, const Matrix3<double>& rhs) -> Matrix3<double> {
    Matrix3<double> result{};
    for (std::size_t row = 0U; row < 3U; ++row) {
        for (std::size_t col = 0U; col < 3U; ++col) {
            for (std::size_t axis = 0U; axis < 3U; ++axis) {
                result(row, col) += lhs(row, axis) * rhs(axis, col);
            }
        }
    }
    return result;
}

auto expect_matrix_near(
    const Matrix3<double>& actual, const Matrix3<double>& expected, const double tolerance = kTol
) -> void {
    for (std::size_t row = 0U; row < 3U; ++row) {
        for (std::size_t col = 0U; col < 3U; ++col) {
            SCOPED_TRACE(row);
            SCOPED_TRACE(col);
            EXPECT_NEAR(actual(row, col), expected(row, col), tolerance);
        }
    }
}

auto expect_vec_near(
    const Vec3<double>& actual, const Vec3<double>& expected, const double tolerance = kTol
) -> void {
    for (std::size_t axis = 0U; axis < 3U; ++axis) {
        SCOPED_TRACE(axis);
        EXPECT_NEAR(actual[axis], expected[axis], tolerance);
    }
}

TEST(Matrix3Factory, ZeroAndIdentityMatricesHaveExpectedEntries) {
    const auto zero = rch::core::zero_matrix3<double>();
    const auto identity = rch::core::identity_matrix3<double>();

    for (std::size_t row = 0U; row < 3U; ++row) {
        for (std::size_t col = 0U; col < 3U; ++col) {
            EXPECT_EQ(zero(row, col), 0.0);
            EXPECT_EQ(identity(row, col), row == col ? 1.0 : 0.0);
        }
    }
}

TEST(Matrix3Inverse, RejectsSingularMatrix) {
    const Matrix3<double> singular{{
        std::array<double, 3>{1.0, 2.0, 3.0},
        std::array<double, 3>{2.0, 4.0, 6.0},
        std::array<double, 3>{1.0, 1.0, 1.0},
    }};
    EXPECT_NEAR(rch::core::determinant(singular), 0.0, 1.0e-14);
    EXPECT_FALSE(rch::core::inverse(singular).has_value());
}

TEST(Matrix3Inverse, RejectsNonFiniteMatrix) {
    Matrix3<double> nan_matrix{};
    nan_matrix(0U, 0U) = 1.0;
    nan_matrix(1U, 1U) = std::numeric_limits<double>::quiet_NaN();
    nan_matrix(2U, 2U) = 1.0;
    EXPECT_FALSE(rch::core::inverse(nan_matrix).has_value());
}

TEST(Matrix3Inverse, InvertsNonSingularMatrix) {
    const Matrix3<double> matrix{{
        std::array<double, 3>{4.0, 7.0, 2.0},
        std::array<double, 3>{3.0, 6.0, 1.0},
        std::array<double, 3>{2.0, 5.0, 3.0},
    }};

    const auto inverse = rch::core::inverse(matrix);
    ASSERT_TRUE(inverse.has_value());

    const auto identity = rch::core::identity_matrix3<double>();
    expect_matrix_near(product(matrix, *inverse), identity);
    expect_matrix_near(product(*inverse, matrix), identity);
}

TEST(Matrix3Inverse, AcceptsSmallWellConditionedScaledMatrix) {
    Matrix3<double> matrix{};
    matrix(0U, 0U) = 1.0e-6;
    matrix(1U, 1U) = 1.0e-6;
    matrix(2U, 2U) = 1.0e-6;

    const auto inverse = rch::core::inverse(matrix);
    ASSERT_TRUE(inverse.has_value());

    Matrix3<double> expected{};
    expected(0U, 0U) = 1.0e6;
    expected(1U, 1U) = 1.0e6;
    expected(2U, 2U) = 1.0e6;
    expect_matrix_near(*inverse, expected, 1.0e-6);
}

TEST(Matrix3Inverse, AcceptsLargeWellConditionedScaledMatrix) {
    Matrix3<double> matrix{};
    matrix(0U, 0U) = 1.0e150;
    matrix(1U, 1U) = 1.0e150;
    matrix(2U, 2U) = 1.0e150;

    const auto inverse = rch::core::inverse(matrix);
    ASSERT_TRUE(inverse.has_value());

    Matrix3<double> expected{};
    expected(0U, 0U) = 1.0e-150;
    expected(1U, 1U) = 1.0e-150;
    expected(2U, 2U) = 1.0e-150;
    expect_matrix_near(*inverse, expected, 1.0e-165);
}

TEST(Matrix3Inverse, AcceptsTinyWellConditionedScaledMatrix) {
    Matrix3<double> matrix{};
    matrix(0U, 0U) = 1.0e-200;
    matrix(1U, 1U) = 1.0e-200;
    matrix(2U, 2U) = 1.0e-200;

    const auto inverse = rch::core::inverse(matrix);
    ASSERT_TRUE(inverse.has_value());

    Matrix3<double> expected{};
    expected(0U, 0U) = 1.0e200;
    expected(1U, 1U) = 1.0e200;
    expected(2U, 2U) = 1.0e200;
    expect_matrix_near(*inverse, expected, 1.0e185);
}

TEST(Matrix3Inverse, RejectsScaleRelativeNearSingularMatrix) {
    Matrix3<double> matrix{};
    matrix(0U, 0U) = 1.0;
    matrix(1U, 1U) = 1.0;
    matrix(2U, 2U) = 1.0e-18;

    EXPECT_FALSE(rch::core::inverse(matrix).has_value());
}

TEST(Matrix3IsFinite, RejectsNaNVec3) {
    const Vec3<double> nan_vec{1.0, std::numeric_limits<double>::quiet_NaN(), 0.0};
    EXPECT_FALSE(rch::core::is_finite(nan_vec));
}

TEST(Matrix3IsFinite, RejectsInfMatrix) {
    Matrix3<double> inf_matrix{};
    inf_matrix(0U, 0U) = std::numeric_limits<double>::infinity();
    EXPECT_FALSE(rch::core::is_finite(inf_matrix));
}

TEST(Matrix3IsFinite, AcceptsAllFiniteMatrix) {
    Matrix3<double> ok_matrix{};
    ok_matrix(0U, 0U) = 1.0;
    ok_matrix(1U, 1U) = 2.0;
    ok_matrix(2U, 2U) = 3.0;
    EXPECT_TRUE(rch::core::is_finite(ok_matrix));
}

TEST(Matrix3Operations, VectorArithmeticOperators) {
    const Vec3<double> lhs{1.0, -2.0, 4.0};
    const Vec3<double> rhs{0.5, 3.0, -1.0};

    expect_vec_near(lhs + rhs, Vec3<double>{1.5, 1.0, 3.0});
    expect_vec_near(lhs - rhs, Vec3<double>{0.5, -5.0, 5.0});
    expect_vec_near(lhs * 2.0, Vec3<double>{2.0, -4.0, 8.0});
    expect_vec_near(lhs / 2.0, Vec3<double>{0.5, -1.0, 2.0});
}

TEST(Matrix3Operations, MatrixArithmeticOperators) {
    const Matrix3<double> lhs{{
        std::array<double, 3>{1.0, -2.0, 3.0},
        std::array<double, 3>{4.0, 5.0, -6.0},
        std::array<double, 3>{7.0, -8.0, 9.0},
    }};
    const Matrix3<double> rhs{{
        std::array<double, 3>{9.0, 8.0, 7.0},
        std::array<double, 3>{-6.0, 5.0, 4.0},
        std::array<double, 3>{3.0, 2.0, -1.0},
    }};

    const Matrix3<double> expected_sum{{
        std::array<double, 3>{10.0, 6.0, 10.0},
        std::array<double, 3>{-2.0, 10.0, -2.0},
        std::array<double, 3>{10.0, -6.0, 8.0},
    }};
    const Matrix3<double> expected_difference{{
        std::array<double, 3>{-8.0, -10.0, -4.0},
        std::array<double, 3>{10.0, 0.0, -10.0},
        std::array<double, 3>{4.0, -10.0, 10.0},
    }};
    const Matrix3<double> expected_scaled{{
        std::array<double, 3>{2.0, -4.0, 6.0},
        std::array<double, 3>{8.0, 10.0, -12.0},
        std::array<double, 3>{14.0, -16.0, 18.0},
    }};
    const Matrix3<double> expected_divided{{
        std::array<double, 3>{0.5, -1.0, 1.5},
        std::array<double, 3>{2.0, 2.5, -3.0},
        std::array<double, 3>{3.5, -4.0, 4.5},
    }};

    expect_matrix_near(lhs + rhs, expected_sum);
    expect_matrix_near(lhs - rhs, expected_difference);
    expect_matrix_near(lhs * 2.0, expected_scaled);
    expect_matrix_near(lhs / 2.0, expected_divided);
}

TEST(Matrix3Determinant, ComputesNonZeroCofactorExpansion) {
    const Matrix3<double> matrix{{
        std::array<double, 3>{6.0, 1.0, 1.0},
        std::array<double, 3>{4.0, -2.0, 5.0},
        std::array<double, 3>{2.0, 8.0, 7.0},
    }};
    EXPECT_NEAR(rch::core::determinant(matrix), -306.0, 1.0e-14);
}

TEST(Matrix3Norms, ComputesSquaredVectorAndFrobeniusNorm) {
    EXPECT_NEAR(rch::core::squared_norm(Vec3<double>{2.0, -3.0, 6.0}), 49.0, 1.0e-14);

    const Matrix3<double> matrix{{
        std::array<double, 3>{1.0, 2.0, 3.0},
        std::array<double, 3>{4.0, 5.0, 6.0},
        std::array<double, 3>{7.0, 8.0, 9.0},
    }};
    EXPECT_NEAR(rch::core::frobenius_norm(matrix), std::sqrt(285.0), 1.0e-14);
}

TEST(Matrix3Norms, FrobeniusNormAvoidsIntermediateOverflow) {
    Matrix3<double> matrix{};
    matrix(1U, 2U) = std::numeric_limits<double>::max();

    const double norm = rch::core::frobenius_norm(matrix);
    EXPECT_TRUE(std::isfinite(norm));
    EXPECT_EQ(norm, std::numeric_limits<double>::max());
}

TEST(Matrix3TieBreak, DoubleTotalOrderKeyOrdersFiniteValuesAndSignedZero) {
    EXPECT_LT(
        rch::core::double_total_order_key(-std::numeric_limits<double>::infinity()),
        rch::core::double_total_order_key(-1.0)
    );
    EXPECT_LT(rch::core::double_total_order_key(-1.0), rch::core::double_total_order_key(-0.0));
    EXPECT_LT(rch::core::double_total_order_key(-0.0), rch::core::double_total_order_key(+0.0));
    EXPECT_LT(rch::core::double_total_order_key(+0.0), rch::core::double_total_order_key(1.0));
    EXPECT_LT(
        rch::core::double_total_order_key(1.0),
        rch::core::double_total_order_key(std::numeric_limits<double>::infinity())
    );
}

TEST(Matrix3TieBreak, DoubleTotalOrderKeyOrdersPreferredNanEncodings) {
    const auto negative_quiet_nan = std::bit_cast<double>(UINT64_C(0xfff8000000000001));
    const auto negative_signaling_nan = std::bit_cast<double>(UINT64_C(0xfff0000000000001));
    const auto positive_signaling_nan = std::bit_cast<double>(UINT64_C(0x7ff0000000000001));
    const auto positive_quiet_nan = std::bit_cast<double>(UINT64_C(0x7ff8000000000001));

    EXPECT_LT(
        rch::core::double_total_order_key(negative_quiet_nan),
        rch::core::double_total_order_key(negative_signaling_nan)
    );
    EXPECT_LT(
        rch::core::double_total_order_key(negative_signaling_nan),
        rch::core::double_total_order_key(-std::numeric_limits<double>::infinity())
    );
    EXPECT_LT(
        rch::core::double_total_order_key(std::numeric_limits<double>::infinity()),
        rch::core::double_total_order_key(positive_signaling_nan)
    );
    EXPECT_LT(
        rch::core::double_total_order_key(positive_signaling_nan),
        rch::core::double_total_order_key(positive_quiet_nan)
    );
}

TEST(Matrix3TieBreak, ExactlyEqualTreatsSignedZeroAsEqualButPreservesBitIdentity) {
    EXPECT_TRUE(rch::core::exactly_equal_for_tie_break(+0.0, -0.0));
    EXPECT_FALSE(rch::core::exactly_equal_for_tie_break(1.0, std::nextafter(1.0, 2.0)));

    const auto nan_bits = UINT64_C(0x7ff8000000000042);
    const auto same_nan = std::bit_cast<double>(nan_bits);
    const auto different_nan = std::bit_cast<double>(UINT64_C(0x7ff8000000000043));
    EXPECT_TRUE(rch::core::exactly_equal_for_tie_break(same_nan, same_nan));
    EXPECT_FALSE(rch::core::exactly_equal_for_tie_break(same_nan, different_nan));
}

TEST(Matrix3TieBreak, LexicographicPointLessUsesTotalOrderKeys) {
    const Vec3<double> negative_zero_first{-0.0, 1.0, 0.0};
    const Vec3<double> positive_zero_first{+0.0, -100.0, 0.0};
    EXPECT_TRUE(
        rch::core::lexicographic_point_less_for_tie_break(negative_zero_first, positive_zero_first)
    );
    EXPECT_FALSE(
        rch::core::lexicographic_point_less_for_tie_break(positive_zero_first, negative_zero_first)
    );

    const Vec3<double> differs_after_equal_first_axis{1.0, -0.0, 2.0};
    const Vec3<double> signed_zero_decides_second_axis{1.0, +0.0, -999.0};
    EXPECT_TRUE(
        rch::core::lexicographic_point_less_for_tie_break(
            differs_after_equal_first_axis, signed_zero_decides_second_axis
        )
    );
    EXPECT_FALSE(
        rch::core::lexicographic_point_less_for_tie_break(
            differs_after_equal_first_axis, differs_after_equal_first_axis
        )
    );
}

TEST(Matrix3Mean, EmptyReturnsZero) {
    const std::vector<Vec3<double>> empty;
    const auto mean = rch::core::mean3(std::span<const Vec3<double>>{empty});
    EXPECT_EQ(mean[0], 0.0);
    EXPECT_EQ(mean[1], 0.0);
    EXPECT_EQ(mean[2], 0.0);
}

TEST(Matrix3Mean, SinglePointReturnsThatPoint) {
    const std::vector<Vec3<double>> single{Vec3<double>{1.5, 2.5, 3.5}};
    const auto mean = rch::core::mean3(std::span<const Vec3<double>>{single});
    EXPECT_EQ(mean[0], 1.5);
    EXPECT_EQ(mean[1], 2.5);
    EXPECT_EQ(mean[2], 3.5);
}

TEST(Matrix3Covariance, FewerThanTwoPointsReturnsZero) {
    const std::vector<Vec3<double>> single{Vec3<double>{1.0, 2.0, 3.0}};
    const auto cov =
        rch::core::covariance3(std::span<const Vec3<double>>{single}, Vec3<double>{1.0, 2.0, 3.0});
    for (std::size_t row = 0U; row < 3U; ++row) {
        for (std::size_t col = 0U; col < 3U; ++col) {
            EXPECT_EQ(cov(row, col), 0.0);
        }
    }
}

TEST(Matrix3Covariance, EmptyInputReturnsZero) {
    const std::vector<Vec3<double>> empty;
    const auto cov =
        rch::core::covariance3(std::span<const Vec3<double>>{empty}, Vec3<double>{0.0, 0.0, 0.0});
    for (std::size_t row = 0U; row < 3U; ++row) {
        for (std::size_t col = 0U; col < 3U; ++col) {
            EXPECT_EQ(cov(row, col), 0.0);
        }
    }
}

TEST(Matrix3Operations, TraceTransposeMultiplyAndDot) {
    const Matrix3<double> matrix{{
        std::array<double, 3>{1.0, 2.0, 3.0},
        std::array<double, 3>{4.0, 5.0, 6.0},
        std::array<double, 3>{7.0, 8.0, 9.0},
    }};
    EXPECT_NEAR(rch::core::trace(matrix), 1.0 + 5.0 + 9.0, 1.0e-14);

    const auto transposed = rch::core::transpose(matrix);
    for (std::size_t row = 0U; row < 3U; ++row) {
        for (std::size_t col = 0U; col < 3U; ++col) {
            EXPECT_EQ(transposed(row, col), matrix(col, row));
        }
    }

    const auto matrix_vec = rch::core::multiply(matrix, Vec3<double>{1.0, 0.0, 0.0});
    EXPECT_EQ(matrix_vec[0], 1.0);
    EXPECT_EQ(matrix_vec[1], 4.0);
    EXPECT_EQ(matrix_vec[2], 7.0);

    // \((1,2,3)\cdot(4,5,6)=4+10+18=32\).
    EXPECT_EQ(rch::core::dot(Vec3<double>{1.0, 2.0, 3.0}, Vec3<double>{4.0, 5.0, 6.0}), 32.0);
}

TEST(Matrix3Covariance, TwoPointDiagonalCovariance) {
    const std::vector<Vec3<double>> two_points{
        Vec3<double>{0.0, 0.0, 0.0},
        Vec3<double>{1.0, 1.0, 1.0},
    };
    const auto center = rch::core::mean3(std::span<const Vec3<double>>{two_points});
    const auto cov = rch::core::covariance3(std::span<const Vec3<double>>{two_points}, center);
    for (std::size_t axis = 0U; axis < 3U; ++axis) {
        EXPECT_NEAR(cov(axis, axis), 0.5, 1.0e-14);
    }
    for (std::size_t row = 0U; row < 3U; ++row) {
        for (std::size_t col = 0U; col < 3U; ++col) {
            EXPECT_NEAR(cov(row, col), cov(col, row), 1.0e-14);
        }
    }
}

TEST(Matrix3Covariance, MatchesNistVarianceCovarianceExample) {
    const std::vector<Vec3<double>> points{
        Vec3<double>{4.0, 2.0, 0.60},
        Vec3<double>{4.2, 2.1, 0.59},
        Vec3<double>{3.9, 2.0, 0.58},
        Vec3<double>{4.3, 2.1, 0.62},
        Vec3<double>{4.1, 2.2, 0.63},
    };

    const auto center = rch::core::mean3(std::span<const Vec3<double>>{points});
    expect_vec_near(center, Vec3<double>{4.10, 2.08, 0.604});

    const Matrix3<double> expected{{
        std::array<double, 3>{0.025, 0.0075, 0.00175},
        std::array<double, 3>{0.0075, 0.0070, 0.00135},
        std::array<double, 3>{0.00175, 0.00135, 0.00043},
    }};
    const auto cov = rch::core::covariance3(std::span<const Vec3<double>>{points}, center);
    expect_matrix_near(cov, expected, 5.0e-6);
}

} // namespace
