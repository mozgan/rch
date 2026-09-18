#include <algorithm>
#include <bit>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <random>
#include <span>
#include <vector>

#include "rch/core/matrix3.hpp"
#include "rch/robust/c_step.hpp"
#include "rch/robust/det_mcd.hpp"
#include "rch/robust/fallback_policy.hpp"
#include "rch/robust/hardin_rocke_cutoff.hpp"
#include "rch/robust/mcd_correction.hpp"
#include "rch/robust/median_mad.hpp"

#include <gtest/gtest.h>

namespace {

using rch::core::Vec3;
using rch::robust::adaptive_mcd_pilot;
using rch::robust::det_mcd;
using rch::robust::FallbackPolicy;
using rch::robust::mcd_h_size;

[[nodiscard]] auto deterministic_cloud(const std::size_t n) -> std::vector<Vec3<double>> {
    const std::size_t h = mcd_h_size(n);
    std::vector<Vec3<double>> points;
    points.reserve(n);
    for (std::size_t i = 0U; i < h; ++i) {
        const double a = static_cast<double>((i % 9U)) - 4.0;
        const double b = static_cast<double>(((i / 3U) % 7U)) - 3.0;
        const double c = static_cast<double>(((i * 5U) % 11U)) - 5.0;
        points.push_back({0.08 * a, 0.05 * b + 0.01 * a, 0.04 * c - 0.02 * b});
    }
    for (std::size_t i = h; i < n; ++i) {
        const double k = static_cast<double>(i - h + 1U);
        points.push_back({20.0 + k, -15.0 - (2.0 * k), 10.0 + (3.0 * k)});
    }
    return points;
}

[[nodiscard]] auto same_double_bits(const double lhs, const double rhs) -> bool {
    return std::bit_cast<std::uint64_t>(lhs) == std::bit_cast<std::uint64_t>(rhs);
}

TEST(MedianMad, ComputesMedianLowerMedianAndMad) {
    const std::vector<double> values{9.0, 1.0, 5.0, 3.0};

    EXPECT_EQ(rch::robust::lower_median(std::span<const double>{values}), 3.0);
    EXPECT_EQ(rch::robust::median(std::span<const double>{values}), 4.0);
    EXPECT_NEAR(rch::robust::mad(std::span<const double>{values}, 4.0), 2.965204437011204, 1.0e-15);
}

TEST(DetMcd, HSizeMatchesFastMcdAlphaFormula) {
    EXPECT_EQ(mcd_h_size(100U, 3U, 0.5), 52U);
    EXPECT_EQ(mcd_h_size(100U, 3U, 0.75), 76U);
    EXPECT_EQ(mcd_h_size(100U, 3U, 1.0), 100U);
    EXPECT_EQ(mcd_h_size(15U, 3U, 0.5), 9U);

    // Alpha is intentionally clamped to the MCD-supported interval.
    EXPECT_EQ(mcd_h_size(100U, 3U, 0.1), 52U);
    EXPECT_EQ(mcd_h_size(100U, 3U, 1.5), 100U);
    EXPECT_EQ(mcd_h_size(100U, 3U, std::numeric_limits<double>::quiet_NaN()), 52U);
}

TEST(McdCorrection, ConsistencyFactorIsReciprocalOfHardinRockeCasy) {
    const auto casy = rch::robust::hardin_rocke_casy(100U, 3U, 52U);
    const auto consistency = rch::robust::mcd_consistency_factor(100U, 3U, 52U);

    ASSERT_TRUE(casy.has_value());
    ASSERT_TRUE(consistency.has_value());
    EXPECT_NEAR((*casy) * (*consistency), 1.0, 1.0e-13);
}

TEST(McdCorrection, ScatterCorrectionCombinesConsistencyAndSmallSampleFactors) {
    const auto consistency = rch::robust::mcd_consistency_factor(100U, 3U, 52U);
    const auto small_sample = rch::robust::mcd_small_sample_factor(100U, 3U, 0.5);
    const auto combined = rch::robust::mcd_scatter_correction(100U, 3U, 52U, 0.5, true);
    const auto consistency_only = rch::robust::mcd_scatter_correction(100U, 3U, 52U, 0.5, false);

    ASSERT_TRUE(consistency.has_value());
    ASSERT_TRUE(small_sample.has_value());
    ASSERT_TRUE(combined.has_value());
    ASSERT_TRUE(consistency_only.has_value());
    EXPECT_NEAR(*combined, (*consistency) * (*small_sample), 1.0e-13);
    EXPECT_DOUBLE_EQ(*consistency_only, *consistency);
    EXPECT_GT(*combined, 0.0);
}

TEST(DetMcd, RepeatsProduceBitStableSubsetAndStableDoubles) {
    const auto points = deterministic_cloud(100U);
    const auto first = det_mcd(std::span<const Vec3<double>>{points});

    ASSERT_NE(first.policy, FallbackPolicy::disabled_small_n);
    ASSERT_NE(first.policy, FallbackPolicy::disabled_rank_deficient);
    ASSERT_EQ(first.h, 52U);
    ASSERT_EQ(first.subset_indices.size(), first.h);
    ASSERT_LE(first.cstep_iterations, 200U);

    for (std::size_t repeat = 0U; repeat < 10U; ++repeat) {
        const auto next = det_mcd(std::span<const Vec3<double>>{points});
        EXPECT_EQ(next.subset_indices, first.subset_indices);
        for (std::size_t axis = 0U; axis < 3U; ++axis) {
            EXPECT_TRUE(same_double_bits(next.center[axis], first.center[axis]));
            for (std::size_t col = 0U; col < 3U; ++col) {
                EXPECT_TRUE(same_double_bits(next.scatter(axis, col), first.scatter(axis, col)));
            }
        }
    }
}

// Hubert, Rousseeuw & Verdonck (2012) state the defining trade-off of DetMCD in
// their abstract: FASTMCD is "affine equivariant but not permutation invariant",
// whereas "DetMCD is permutation invariant and very close to affine equivariant"
// (Sec. 5.1 spells out that full affine equivariance is given up because of the
// deterministic initial estimates). Permutation invariance is therefore the hard
// invariant this estimator must satisfy, and it is what makes the ordering
// pipeline reproducible.
TEST(DetMcd, IsInvariantUnderInputPermutation) {
    const auto points = deterministic_cloud(120U);
    const auto reference = det_mcd(std::span<const Vec3<double>>{points});
    ASSERT_NE(reference.policy, FallbackPolicy::disabled_small_n);
    ASSERT_NE(reference.policy, FallbackPolicy::disabled_rank_deficient);

    std::mt19937_64 rng(20260811U);
    for (std::size_t trial = 0U; trial < 8U; ++trial) {
        auto shuffled = points;
        std::shuffle(shuffled.begin(), shuffled.end(), rng);
        const auto permuted = det_mcd(std::span<const Vec3<double>>{shuffled});

        EXPECT_EQ(permuted.h, reference.h);
        for (std::size_t axis = 0U; axis < 3U; ++axis) {
            EXPECT_NEAR(permuted.center[axis], reference.center[axis], 1.0e-9);
            for (std::size_t col = 0U; col < 3U; ++col) {
                EXPECT_NEAR(permuted.scatter(axis, col), reference.scatter(axis, col), 1.0e-9);
            }
        }
    }
}

TEST(CStep, DeterminantDoesNotIncreaseFromInitialScatter) {
    const auto points = deterministic_cloud(50U);
    const std::size_t h = mcd_h_size(points.size());
    const rch::robust::CStepRunner runner{};
    const auto state = runner.run(
        std::span<const Vec3<double>>{points},
        Vec3<double>{0.0, 0.0, 0.0},
        rch::core::identity_matrix3<double>(),
        rch::robust::CStepOptions{h, 50U, 1.0e-12}
    );

    EXPECT_EQ(state.subset_indices.size(), h);
    EXPECT_LE(state.determinant, 1.0 + 1.0e-12);
    EXPECT_TRUE(std::isfinite(state.determinant));
}

TEST(CStep, InvalidSubsetSizeFailsClosedToInitialState) {
    const auto points = deterministic_cloud(8U);
    const rch::robust::CStepRunner runner{};
    const auto state = runner.run(
        std::span<const Vec3<double>>{points},
        Vec3<double>{1.0, 2.0, 3.0},
        rch::core::identity_matrix3<double>(),
        rch::robust::CStepOptions{points.size() + 1U, 50U, 1.0e-12}
    );

    EXPECT_TRUE(state.subset_indices.empty());
    EXPECT_FALSE(state.converged);
    EXPECT_DOUBLE_EQ(state.center[0], 1.0);
    EXPECT_DOUBLE_EQ(state.center[1], 2.0);
    EXPECT_DOUBLE_EQ(state.center[2], 3.0);
    EXPECT_DOUBLE_EQ(state.determinant, 1.0);
}

TEST(CStep, EqualDistanceBoundaryUsesCoordinateTieBreakBeforeInputIndex) {
    const std::vector<Vec3<double>> points{
        {1.0, 0.0, 0.0},
        {-1.0, 0.0, 0.0},
        {0.0, 2.0, 0.0},
    };

    const auto selected = rch::robust::detail::select_h_smallest_distances(
        std::span<const Vec3<double>>{points},
        Vec3<double>{0.0, 0.0, 0.0},
        rch::core::identity_matrix3<double>(),
        1U
    );

    ASSERT_EQ(selected.size(), 1U);
    EXPECT_EQ(selected[0], 1U);
}

TEST(DetMcd, AdaptivePilotMapsContaminationToAlphaAndH) {
    const std::vector<Vec3<double>> clean{
        {0.0, 0.0, 0.0},
        {0.0, 0.0, 0.0},
        {0.0, 0.0, 0.0},
        {0.0, 0.0, 0.0},
        {0.0, 0.0, 0.0},
    };
    const auto clean_pilot = adaptive_mcd_pilot(std::span<const Vec3<double>>{clean});
    EXPECT_DOUBLE_EQ(clean_pilot.eps_hat, 0.0);
    EXPECT_DOUBLE_EQ(clean_pilot.alpha, 0.90);
    EXPECT_EQ(clean_pilot.h, mcd_h_size(clean.size(), 3U, clean_pilot.alpha));

    auto contaminated = clean;
    contaminated.back() = {100.0, 100.0, 100.0};
    const auto contaminated_pilot = adaptive_mcd_pilot(std::span<const Vec3<double>>{contaminated});
    EXPECT_DOUBLE_EQ(contaminated_pilot.eps_hat, 0.2);
    EXPECT_DOUBLE_EQ(contaminated_pilot.alpha, 0.70);
    EXPECT_EQ(contaminated_pilot.h, mcd_h_size(contaminated.size(), 3U, contaminated_pilot.alpha));
}

TEST(DetMcd, NegativeRankToleranceDoesNotHideRankDeficiency) {
    const std::vector<Vec3<double>> points{
        {0.0, 0.0, 0.0},
        {1.0, 2.0, 3.0},
        {2.0, 4.0, 6.0},
        {3.0, 6.0, 9.0},
    };

    EXPECT_TRUE(
        rch::robust::sample_rank_deficient(
            std::span<const Vec3<double>>{points}, std::numeric_limits<double>::quiet_NaN()
        )
    );
    EXPECT_TRUE(rch::robust::sample_rank_deficient(std::span<const Vec3<double>>{points}, -1.0));
}

TEST(DetMcd, TinyFullRankSampleIsNotRejectedByAbsoluteDeterminantFloor) {
    const double s = 1.0e-150;
    const std::vector<Vec3<double>> points{
        {0.0, 0.0, 0.0},
        {s, 0.0, 0.0},
        {0.0, s, 0.0},
        {0.0, 0.0, s},
        {s, s, s},
    };

    EXPECT_FALSE(
        rch::robust::sample_rank_deficient(std::span<const Vec3<double>>{points}, 1.0e-12)
    );
}

TEST(HardinRockeCutoff, FQuantileIsMonotoneInProbability) {
    const auto lower = rch::robust::hardin_rocke_f_cutoff(100U, 3U, 52U, 0.95);
    const auto upper = rch::robust::hardin_rocke_f_cutoff(100U, 3U, 52U, 0.975);

    ASSERT_TRUE(lower.has_value());
    ASSERT_TRUE(upper.has_value());
    EXPECT_LT(*lower, *upper);
    EXPECT_NEAR(*upper, 37.04472, 1.0e-4);
}

} // namespace
