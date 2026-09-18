#include <cmath>
#include <limits>

#include "rch/robust/hardin_rocke_cutoff.hpp"

#include <gtest/gtest.h>

namespace {

TEST(FDistributionCdf, ZeroAndNegativeArgumentsReturnZero) {
    EXPECT_EQ(rch::robust::f_cdf(0.0, 3.0, 5.0), 0.0);
    EXPECT_EQ(rch::robust::f_cdf(-1.0, 3.0, 5.0), 0.0);
}

TEST(FDistributionCdf, InvalidDegreesOfFreedomReturnZero) {
    EXPECT_EQ(rch::robust::f_cdf(1.0, 0.0, 5.0), 0.0);
    EXPECT_EQ(rch::robust::f_cdf(1.0, 3.0, 0.0), 0.0);
}

TEST(FDistributionCdf, InfiniteArgumentReturnsOne) {
    EXPECT_EQ(rch::robust::f_cdf(std::numeric_limits<double>::infinity(), 3.0, 5.0), 1.0);
    EXPECT_GT(rch::robust::f_cdf(std::numeric_limits<double>::max(), 3.0, 5.0), 0.999);
}

TEST(FDistributionCdf, MonotoneInArgument) {
    const double a = rch::robust::f_cdf(0.5, 3.0, 100.0);
    const double b = rch::robust::f_cdf(1.0, 3.0, 100.0);
    const double c = rch::robust::f_cdf(2.0, 3.0, 100.0);
    EXPECT_LT(a, b);
    EXPECT_LT(b, c);
    EXPECT_GE(a, 0.0);
    EXPECT_LE(c, 1.0);
}

TEST(FDistributionQuantile, IsLeftInverseOfCdf) {
    constexpr double target = 0.95;
    const auto quantile = rch::robust::f_quantile(target, 3.0, 100.0);
    ASSERT_TRUE(quantile.has_value());
    const double recovered = rch::robust::f_cdf(*quantile, 3.0, 100.0);
    EXPECT_NEAR(recovered, target, 1.0e-9);
}

TEST(FDistributionQuantile, RejectsInvalidProbability) {
    EXPECT_FALSE(rch::robust::f_quantile(0.0, 3.0, 5.0).has_value());
    EXPECT_FALSE(rch::robust::f_quantile(1.0, 3.0, 5.0).has_value());
    EXPECT_FALSE(rch::robust::f_quantile(0.5, 0.0, 5.0).has_value());
    EXPECT_FALSE(rch::robust::f_quantile(0.5, 3.0, 0.0).has_value());
}

TEST(ChiSquareCdf, MatchesClosedFormForDof2) {
    constexpr double x = 2.0;
    const double expected = 1.0 - std::exp(-x / 2.0);
    EXPECT_NEAR(rch::robust::chi_square_cdf(x, 2.0), expected, 1.0e-10);
}

TEST(ChiSquareCdf, ZeroAndNegativeArgumentsReturnZero) {
    EXPECT_EQ(rch::robust::chi_square_cdf(0.0, 3.0), 0.0);
    EXPECT_EQ(rch::robust::chi_square_cdf(-1.0, 3.0), 0.0);
    EXPECT_EQ(rch::robust::chi_square_cdf(1.0, 0.0), 0.0);
}

TEST(ChiSquareCdf, InfiniteArgumentReturnsOne) {
    EXPECT_EQ(rch::robust::chi_square_cdf(std::numeric_limits<double>::infinity(), 3.0), 1.0);
}

TEST(ChiSquareQuantile, IsLeftInverseOfCdf) {
    constexpr double target = 0.975;
    const auto quantile = rch::robust::chi_square_quantile(target, 3.0);
    ASSERT_TRUE(quantile.has_value());
    EXPECT_NEAR(rch::robust::chi_square_cdf(*quantile, 3.0), target, 1.0e-10);
}

TEST(ChiSquareQuantile, RejectsInvalidInputs) {
    EXPECT_FALSE(rch::robust::chi_square_quantile(0.0, 3.0).has_value());
    EXPECT_FALSE(rch::robust::chi_square_quantile(1.0, 3.0).has_value());
    EXPECT_FALSE(rch::robust::chi_square_quantile(0.5, 0.0).has_value());
}

TEST(HardinRockeCutoff, RejectsInvalidDimensions) {
    EXPECT_FALSE(rch::robust::hardin_rocke_f_cutoff(10U, 3U, 3U).has_value());
    EXPECT_FALSE(rch::robust::hardin_rocke_f_cutoff(3U, 3U, 5U).has_value());
    EXPECT_FALSE(rch::robust::hardin_rocke_f_cutoff(10U, 0U, 5U).has_value());
}

TEST(HardinRockeCutoff, CasyAtFullSubsetUsesClassicalCovarianceLimit) {
    const auto casy = rch::robust::hardin_rocke_casy(20U, 3U, 20U);

    ASSERT_TRUE(casy.has_value());
    EXPECT_DOUBLE_EQ(*casy, 1.0);
}

TEST(HardinRockeCutoff, BothAdjustedAndRawFlavorsReturnFiniteCutoff) {
    const auto adj = rch::robust::hardin_rocke_f_cutoff(100U, 3U, 52U, 0.975, true);
    const auto raw = rch::robust::hardin_rocke_f_cutoff(100U, 3U, 52U, 0.975, false);
    ASSERT_TRUE(adj.has_value());
    ASSERT_TRUE(raw.has_value());
    EXPECT_GT(*adj, 0.0);
    EXPECT_GT(*raw, 0.0);
    EXPECT_TRUE(std::isfinite(*adj));
    EXPECT_TRUE(std::isfinite(*raw));
    EXPECT_NE(*adj, *raw);
}

} // namespace
