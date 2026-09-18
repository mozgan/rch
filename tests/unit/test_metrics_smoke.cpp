#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <limits>
#include <numeric>
#include <span>
#include <utility>
#include <vector>

#include "rch/curves/hilbert3_standard.hpp"
#include "rch/curves/morton3.hpp"
#include "rch/metrics/summary.hpp"

#include <gtest/gtest.h>

namespace {

using rch::core::Matrix3;
using rch::core::Vec3;

[[nodiscard]] auto colinear_cloud() -> std::vector<Vec3<double>> {
    return {{0.0, 0.0, 0.0}, {1.0, 0.0, 0.0}, {2.0, 0.0, 0.0}, {3.0, 0.0, 0.0}};
}

TEST(MetricsLocality, MiadOnUnitGridMatchesUnit) {
    const auto points = colinear_cloud();
    const std::array<std::size_t, 4> order{0U, 1U, 2U, 3U};
    EXPECT_DOUBLE_EQ(
        rch::metrics::mean_inter_adjacent_distance<std::size_t>(
            std::span<const Vec3<double>>{points}, std::span<const std::size_t>{order}
        ),
        1.0
    );
}

TEST(MetricsLocality, L1LocalityMaxesAtLargestRatio) {
    const auto points = colinear_cloud();
    const std::array<std::size_t, 4> order{0U, 1U, 2U, 3U};
    EXPECT_DOUBLE_EQ(
        rch::metrics::l1_locality<std::size_t>(
            std::span<const Vec3<double>>{points}, std::span<const std::size_t>{order}
        ),
        9.0
    );
}

TEST(MetricsLocality, L2LocalityMinsAtSmallestRatio) {
    const auto points = colinear_cloud();
    const std::array<std::size_t, 4> order{0U, 1U, 2U, 3U};
    EXPECT_DOUBLE_EQ(
        rch::metrics::l2_locality<std::size_t>(
            std::span<const Vec3<double>>{points}, std::span<const std::size_t>{order}
        ),
        1.0
    );
}

TEST(MetricsLocality, MiadOnEmptyAndSinglePointReturnsZero) {
    const std::array<rch::core::Vec3<double>, 0> empty_points{};
    const std::array<std::size_t, 0> empty_order{};
    EXPECT_DOUBLE_EQ(
        rch::metrics::mean_inter_adjacent_distance<std::size_t>(
            std::span<const rch::core::Vec3<double>>{empty_points},
            std::span<const std::size_t>{empty_order}
        ),
        0.0
    );

    const std::array<rch::core::Vec3<double>, 1> one_point{rch::core::Vec3<double>{1.0, 2.0, 3.0}};
    const std::array<std::size_t, 1> one_order{0U};
    EXPECT_DOUBLE_EQ(
        rch::metrics::mean_inter_adjacent_distance<std::size_t>(
            std::span<const rch::core::Vec3<double>>{one_point},
            std::span<const std::size_t>{one_order}
        ),
        0.0
    );
}

TEST(MetricsLocality, MiadOnAllIdenticalPointsReturnsZero) {
    const std::array<rch::core::Vec3<double>, 4> identical{
        rch::core::Vec3<double>{1.5, -2.5, 3.5},
        rch::core::Vec3<double>{1.5, -2.5, 3.5},
        rch::core::Vec3<double>{1.5, -2.5, 3.5},
        rch::core::Vec3<double>{1.5, -2.5, 3.5},
    };
    const std::array<std::size_t, 4> order{0U, 1U, 2U, 3U};
    const double miad = rch::metrics::mean_inter_adjacent_distance<std::size_t>(
        std::span<const rch::core::Vec3<double>>{identical}, std::span<const std::size_t>{order}
    );
    EXPECT_DOUBLE_EQ(miad, 0.0);
    EXPECT_FALSE(std::isnan(miad));
}

TEST(MetricsLocality, MiadRejectsOutOfRangeOrderIndexFailClosed) {
    const auto points = colinear_cloud();
    const std::array<std::size_t, 4> malformed{0U, 1U, 99U, 2U};
    EXPECT_DOUBLE_EQ(
        rch::metrics::mean_inter_adjacent_distance<std::size_t>(
            std::span<const Vec3<double>>{points}, std::span<const std::size_t>{malformed}
        ),
        0.0
    );
}

TEST(MetricsLocality, PairwiseLocalityRejectsMalformedPermutationFailClosed) {
    const auto points = colinear_cloud();
    const std::array<std::size_t, 4> duplicate{0U, 1U, 1U, 3U};
    const std::array<std::size_t, 3> missing{0U, 1U, 2U};

    EXPECT_DOUBLE_EQ(
        rch::metrics::l1_locality<std::size_t>(
            std::span<const Vec3<double>>{points}, std::span<const std::size_t>{duplicate}
        ),
        0.0
    );
    EXPECT_DOUBLE_EQ(
        rch::metrics::l2_locality<std::size_t>(
            std::span<const Vec3<double>>{points}, std::span<const std::size_t>{missing}
        ),
        0.0
    );
}

TEST(MetricsLocality, DistanceMetricsRejectNonFinitePointsFailClosed) {
    auto points = colinear_cloud();
    points[2][1] = std::numeric_limits<double>::infinity();
    const std::array<std::size_t, 4> order{0U, 1U, 2U, 3U};

    EXPECT_DOUBLE_EQ(
        rch::metrics::mean_inter_adjacent_distance<std::size_t>(
            std::span<const Vec3<double>>{points}, std::span<const std::size_t>{order}
        ),
        0.0
    );
    EXPECT_DOUBLE_EQ(
        rch::metrics::l1_locality<std::size_t>(
            std::span<const Vec3<double>>{points}, std::span<const std::size_t>{order}
        ),
        0.0
    );
    EXPECT_DOUBLE_EQ(
        rch::metrics::l2_locality<std::size_t>(
            std::span<const Vec3<double>>{points}, std::span<const std::size_t>{order}
        ),
        0.0
    );
    const auto [mean, p95] = rch::metrics::block_read_locality<std::size_t>(
        std::span<const Vec3<double>>{points}, std::span<const std::size_t>{order}, 4U
    );
    EXPECT_DOUBLE_EQ(mean, 0.0);
    EXPECT_DOUBLE_EQ(p95, 0.0);
}

TEST(MetricsLocality, L1LocalityOnAllIdenticalPointsReturnsZero) {
    const std::array<rch::core::Vec3<double>, 5> identical{
        rch::core::Vec3<double>{0.0, 0.0, 0.0},
        rch::core::Vec3<double>{0.0, 0.0, 0.0},
        rch::core::Vec3<double>{0.0, 0.0, 0.0},
        rch::core::Vec3<double>{0.0, 0.0, 0.0},
        rch::core::Vec3<double>{0.0, 0.0, 0.0},
    };
    const std::array<std::size_t, 5> order{0U, 1U, 2U, 3U, 4U};
    EXPECT_DOUBLE_EQ(
        rch::metrics::l1_locality<std::size_t>(
            std::span<const rch::core::Vec3<double>>{identical}, std::span<const std::size_t>{order}
        ),
        0.0
    );
    EXPECT_DOUBLE_EQ(
        rch::metrics::l2_locality<std::size_t>(
            std::span<const rch::core::Vec3<double>>{identical}, std::span<const std::size_t>{order}
        ),
        0.0
    );
}

TEST(MetricsLocality, BlockReadRejectsOutOfRangeOrderIndexFailClosed) {
    const auto points = colinear_cloud();
    const std::array<std::size_t, 4> malformed{0U, 1U, 4U, 2U};
    const auto [mean, p95] = rch::metrics::block_read_locality<std::size_t>(
        std::span<const Vec3<double>>{points}, std::span<const std::size_t>{malformed}, 4U
    );
    EXPECT_DOUBLE_EQ(mean, 0.0);
    EXPECT_DOUBLE_EQ(p95, 0.0);
}

TEST(MetricsLocality, BlockReadSkipsSinglePointTrailingBlock) {
    constexpr std::size_t kN = 33U;
    std::vector<rch::core::Vec3<double>> points(kN);
    for (std::size_t i = 0U; i < kN; ++i) {
        points[i] = {static_cast<double>(i), 0.0, 0.0};
    }
    points[32U] = {1.0e6, 0.0, 0.0};
    std::vector<std::size_t> order(kN);
    std::iota(order.begin(), order.end(), std::size_t{0U});

    const auto [mean, p95] = rch::metrics::block_read_locality<std::size_t>(
        std::span<const rch::core::Vec3<double>>{points}, std::span<const std::size_t>{order}, 32U
    );
    // First block diameter = |31 - 0| = 31; only one block contributes.
    EXPECT_DOUBLE_EQ(mean, 31.0);
    EXPECT_DOUBLE_EQ(p95, 31.0);
}

TEST(MetricsLocality, BlockReadReturnsZeroOnSinglePointBlocks) {
    const auto points = colinear_cloud();
    const std::array<std::size_t, 4> order{0U, 1U, 2U, 3U};
    // block_size = 4 → single block, all 4 points; max pairwise distance is
    // 3. Mean = 3, p95 = 3.
    const auto [mean, p95] = rch::metrics::block_read_locality<std::size_t>(
        std::span<const Vec3<double>>{points}, std::span<const std::size_t>{order}, 4U
    );
    EXPECT_DOUBLE_EQ(mean, 3.0);
    EXPECT_DOUBLE_EQ(p95, 3.0);
}

TEST(MetricsLocality, BlockReadP95UsesCeilEmpiricalIndex) {
    const std::array<Vec3<double>, 6> points{
        Vec3<double>{0.0, 0.0, 0.0},
        Vec3<double>{1.0, 0.0, 0.0},
        Vec3<double>{10.0, 0.0, 0.0},
        Vec3<double>{20.0, 0.0, 0.0},
        Vec3<double>{100.0, 0.0, 0.0},
        Vec3<double>{200.0, 0.0, 0.0},
    };
    const std::array<std::size_t, 6> order{0U, 1U, 2U, 3U, 4U, 5U};

    const auto [mean, p95] = rch::metrics::block_read_locality<std::size_t>(
        std::span<const Vec3<double>>{points}, std::span<const std::size_t>{order}, 2U
    );

    EXPECT_DOUBLE_EQ(mean, 37.0);
    EXPECT_DOUBLE_EQ(p95, 100.0);
}

TEST(MetricsOrdering, RecallWithKZeroShortCircuitsToOne) {
    const std::array<rch::core::Vec3<double>, 4> points{
        rch::core::Vec3<double>{0.0, 0.0, 0.0},
        rch::core::Vec3<double>{1.0, 0.0, 0.0},
        rch::core::Vec3<double>{2.0, 0.0, 0.0},
        rch::core::Vec3<double>{3.0, 0.0, 0.0},
    };
    const std::array<std::size_t, 4> order{0U, 1U, 2U, 3U};
    EXPECT_DOUBLE_EQ(
        rch::metrics::recall_at_k_window<std::size_t>(
            std::span<const rch::core::Vec3<double>>{points},
            std::span<const std::size_t>{order},
            0U,
            64U
        ),
        1.0
    );
}

TEST(MetricsOrdering, RecallReturnsOneForVacuouslySmallCloud) {
    const std::vector<Vec3<double>> singleton{{0.0, 0.0, 0.0}};
    const std::array<std::size_t, 1> order{0U};
    EXPECT_DOUBLE_EQ(
        rch::metrics::recall_at_k_window<std::size_t>(
            std::span<const Vec3<double>>{singleton}, std::span<const std::size_t>{order}
        ),
        1.0
    );
}

TEST(MetricsOrdering, RecallRejectsMalformedSmallCloudOrdersFailClosed) {
    const std::array<Vec3<double>, 0> empty_points{};
    const std::array<std::size_t, 1> non_empty_order{0U};
    EXPECT_DOUBLE_EQ(
        rch::metrics::recall_at_k_window<std::size_t>(
            std::span<const Vec3<double>>{empty_points},
            std::span<const std::size_t>{non_empty_order}
        ),
        0.0
    );

    const std::array<Vec3<double>, 1> singleton{Vec3<double>{0.0, 0.0, 0.0}};
    const std::array<std::size_t, 0> missing_order{};
    EXPECT_DOUBLE_EQ(
        rch::metrics::recall_at_k_window<std::size_t>(
            std::span<const Vec3<double>>{singleton}, std::span<const std::size_t>{missing_order}
        ),
        0.0
    );
}

TEST(MetricsOrdering, RecallRejectsMalformedPermutationFailClosed) {
    const auto points = colinear_cloud();
    const std::array<std::size_t, 4> duplicate{0U, 1U, 1U, 3U};
    const std::array<std::size_t, 4> out_of_range{0U, 1U, 2U, 99U};

    EXPECT_DOUBLE_EQ(
        rch::metrics::recall_at_k_window<std::size_t>(
            std::span<const Vec3<double>>{points}, std::span<const std::size_t>{duplicate}, 2U, 4U
        ),
        0.0
    );
    EXPECT_DOUBLE_EQ(
        rch::metrics::recall_at_k_window<std::size_t>(
            std::span<const Vec3<double>>{points},
            std::span<const std::size_t>{out_of_range},
            2U,
            4U
        ),
        0.0
    );
}

TEST(MetricsOrdering, RecallRejectsNonFinitePointsFailClosed) {
    auto points = colinear_cloud();
    points[1][0] = std::numeric_limits<double>::quiet_NaN();
    const std::array<std::size_t, 4> order{0U, 1U, 2U, 3U};

    EXPECT_DOUBLE_EQ(
        rch::metrics::recall_at_k_window<std::size_t>(
            std::span<const Vec3<double>>{points}, std::span<const std::size_t>{order}, 2U, 4U
        ),
        0.0
    );
}

TEST(MetricsOutlier, KendallTauReturnsOneForIdenticalOrders) {
    const std::array<std::size_t, 4> clean{0U, 1U, 2U, 3U};
    EXPECT_DOUBLE_EQ(
        rch::metrics::kendall_tau_against_clean<std::size_t>(
            std::span<const std::size_t>{clean}, std::span<const std::size_t>{clean}, 4U
        ),
        1.0
    );
}

TEST(MetricsOutlier, KendallTauReturnsMinusOneForReversedOrder) {
    const std::array<std::size_t, 4> clean{0U, 1U, 2U, 3U};
    const std::array<std::size_t, 4> reversed{3U, 2U, 1U, 0U};
    EXPECT_DOUBLE_EQ(
        rch::metrics::kendall_tau_against_clean<std::size_t>(
            std::span<const std::size_t>{clean}, std::span<const std::size_t>{reversed}, 4U
        ),
        -1.0
    );
}

TEST(MetricsOutlier, KendallTauComputesMixedConcordance) {
    const std::array<std::size_t, 3> clean{0U, 1U, 2U};
    const std::array<std::size_t, 3> mixed{0U, 2U, 1U};

    EXPECT_DOUBLE_EQ(
        rch::metrics::kendall_tau_against_clean<std::size_t>(
            std::span<const std::size_t>{clean}, std::span<const std::size_t>{mixed}, 3U
        ),
        1.0 / 3.0
    );
}

TEST(MetricsOutlier, KendallTauFiltersOutlierIdsButRejectsDuplicateCleanIds) {
    const std::array<std::size_t, 4> clean{0U, 1U, 2U, 3U};
    const std::array<std::size_t, 6> contaminated_with_outliers{0U, 1U, 99U, 2U, 100U, 3U};
    const std::array<std::size_t, 4> duplicate_clean{0U, 1U, 1U, 3U};

    EXPECT_DOUBLE_EQ(
        rch::metrics::kendall_tau_against_clean<std::size_t>(
            std::span<const std::size_t>{clean},
            std::span<const std::size_t>{contaminated_with_outliers},
            4U
        ),
        1.0
    );
    EXPECT_DOUBLE_EQ(
        rch::metrics::kendall_tau_against_clean<std::size_t>(
            std::span<const std::size_t>{clean}, std::span<const std::size_t>{duplicate_clean}, 4U
        ),
        0.0
    );
}

TEST(MetricsOutlier, FrameAngleIsZeroForIdenticalAxesAndSignInvariant) {
    Matrix3<double> axes{};
    axes(0, 0) = 1.0;
    axes(1, 1) = 1.0;
    axes(2, 2) = 1.0;
    Matrix3<double> flipped{};
    flipped(0, 0) = -1.0;
    flipped(1, 1) = 1.0;
    flipped(2, 2) = -1.0;
    const auto same = rch::metrics::frame_angle_rad(axes, axes);
    ASSERT_TRUE(same.has_value());
    EXPECT_DOUBLE_EQ(*same, 0.0);
    const auto signs = rch::metrics::frame_angle_rad(axes, flipped);
    ASSERT_TRUE(signs.has_value());
    EXPECT_NEAR(*signs, 0.0, 1e-12);
}

TEST(MetricsOutlier, FrameAngleReportsQuarterTurn) {
    Matrix3<double> axes{};
    axes(0, 0) = 1.0;
    axes(1, 1) = 1.0;
    axes(2, 2) = 1.0;

    Matrix3<double> quarter_turn{};
    quarter_turn(1, 0) = 1.0;
    quarter_turn(0, 1) = -1.0;
    quarter_turn(2, 2) = 1.0;

    const auto angle = rch::metrics::frame_angle_rad(axes, quarter_turn);
    ASSERT_TRUE(angle.has_value());
    EXPECT_NEAR(*angle, std::acos(0.0), 1e-12);
}

TEST(MetricsOutlier, FrameAngleHandlesLargeFiniteAlignedAxes) {
    Matrix3<double> axes{};
    axes(0, 0) = 1.0e154;
    axes(1, 1) = 1.0e154;
    axes(2, 2) = 1.0e154;

    const auto angle = rch::metrics::frame_angle_rad(axes, axes);
    ASSERT_TRUE(angle.has_value());
    EXPECT_NEAR(*angle, 0.0, 1e-12);
}

TEST(MetricsOutlier, FrameAngleRejectsNonFiniteAxes) {
    Matrix3<double> axes{};
    axes(0, 0) = 1.0;
    axes(1, 1) = 1.0;
    axes(2, 2) = 1.0;

    Matrix3<double> bad = axes;
    bad(0, 0) = std::numeric_limits<double>::quiet_NaN();

    EXPECT_FALSE(rch::metrics::frame_angle_rad(axes, bad).has_value());
}

TEST(MetricsOutlier, FrameAngleRejectsZeroAxes) {
    Matrix3<double> axes{};
    axes(0, 0) = 1.0;
    axes(1, 1) = 1.0;
    axes(2, 2) = 1.0;

    Matrix3<double> zero_axis = axes;
    zero_axis(0, 0) = 0.0;

    EXPECT_FALSE(rch::metrics::frame_angle_rad(axes, zero_axis).has_value());
}

TEST(MetricsTiming, MeasureMedianReturnsFiniteSecondsAcrossElevenRuns) {
    int counter = 0;
    const double median = rch::metrics::measure_median_seconds([&]() noexcept { ++counter; }, 11U);
    EXPECT_GE(median, 0.0);
    EXPECT_EQ(counter, 11);
}

TEST(MetricsTiming, SampleMedianOnEmptyRangeReturnsZero) {
    const std::vector<double> empty{};
    EXPECT_DOUBLE_EQ(rch::metrics::sample_median(empty), 0.0);
}

TEST(MetricsTiming, SampleMedianOnSingleValueReturnsThatValue) {
    const std::vector<double> single{42.5};
    EXPECT_DOUBLE_EQ(rch::metrics::sample_median(single), 42.5);
}

TEST(MetricsTiming, SampleMedianAveragesMiddlePairForEvenLengthInput) {
    const std::vector<double> four{1.0, 2.0, 3.0, 4.0};
    EXPECT_DOUBLE_EQ(rch::metrics::sample_median(four), 2.5);
}

TEST(MetricsTiming, SampleMedianHandlesUnsortedEvenLengthInput) {
    const std::vector<double> four{10.0, 1.0, 4.0, 2.0};
    EXPECT_DOUBLE_EQ(rch::metrics::sample_median(four), 3.0);
}

TEST(MetricsTiming, MeasureMedianWithZeroRepeatsShortCircuits) {
    int call_count = 0;
    const double value = rch::metrics::measure_median_seconds([&]() noexcept { ++call_count; }, 0U);
    EXPECT_DOUBLE_EQ(value, 0.0);
    EXPECT_EQ(call_count, 0);
}

TEST(MetricsMemory, ReadPeakRssKbReturnsValueOnLinux) {
    const auto value = rch::metrics::read_peak_rss_kb();
#if defined(__linux__)
    ASSERT_TRUE(value.has_value());
    EXPECT_GT(*value, 0U);
#else
    // Non-Linux platforms: explicit nullopt is the contract.
    EXPECT_FALSE(value.has_value());
#endif
}

TEST(MetricsMemory, PeakRssParserAcceptsLinuxStatusFields) {
    EXPECT_EQ(
        rch::metrics::detail::parse_peak_rss_kb_line(
            "VmHWM:\t   1234 kB", rch::metrics::PeakRssField::VmHighWaterMark
        ),
        1234U
    );
    EXPECT_EQ(
        rch::metrics::detail::parse_peak_rss_kb_line(
            "VmPeak:  987654 kB", rch::metrics::PeakRssField::VmPeak
        ),
        987654U
    );
}

TEST(MetricsMemory, PeakRssParserRejectsWrongMalformedAndOverflowLines) {
    EXPECT_FALSE(
        rch::metrics::detail::parse_peak_rss_kb_line(
            "VmRSS:\t   1234 kB", rch::metrics::PeakRssField::VmHighWaterMark
        )
            .has_value()
    );
    EXPECT_FALSE(
        rch::metrics::detail::parse_peak_rss_kb_line(
            "VmHWM:\t   kB", rch::metrics::PeakRssField::VmHighWaterMark
        )
            .has_value()
    );
    EXPECT_FALSE(
        rch::metrics::detail::parse_peak_rss_kb_line(
            "VmHWM:\t   -123 kB", rch::metrics::PeakRssField::VmHighWaterMark
        )
            .has_value()
    );
    EXPECT_FALSE(
        rch::metrics::detail::parse_peak_rss_kb_line(
            "VmHWM:\tabc123 kB", rch::metrics::PeakRssField::VmHighWaterMark
        )
            .has_value()
    );
    EXPECT_FALSE(
        rch::metrics::detail::parse_peak_rss_kb_line(
            "VmHWM:\t   18446744073709551616 kB", rch::metrics::PeakRssField::VmHighWaterMark
        )
            .has_value()
    );
}

TEST(MetricsCache, CacheMissRateReturnsNulloptWhenCountersMissing) {
    rch::metrics::CacheCounters counters{};
    EXPECT_FALSE(rch::metrics::cache_miss_rate(counters).has_value());

    counters.cache_references = 100U;
    EXPECT_FALSE(rch::metrics::cache_miss_rate(counters).has_value());

    counters.cache_references.reset();
    counters.cache_misses = 5U;
    EXPECT_FALSE(rch::metrics::cache_miss_rate(counters).has_value());
}

TEST(MetricsCache, CacheMissRateReturnsNulloptOnZeroReferences) {
    const rch::metrics::CacheCounters zero_refs{
        .cache_references = 0U,
        .cache_misses = 0U,
    };
    EXPECT_FALSE(rch::metrics::cache_miss_rate(zero_refs).has_value());

    const rch::metrics::CacheCounters zero_refs_with_misses{
        .cache_references = 0U,
        .cache_misses = 42U,
    };
    EXPECT_FALSE(rch::metrics::cache_miss_rate(zero_refs_with_misses).has_value());
}

TEST(MetricsCache, CacheMissRateComputesCanonicalRatio) {
    const rch::metrics::CacheCounters counters{
        .cache_references = 1000U,
        .cache_misses = 250U,
    };
    const auto rate = rch::metrics::cache_miss_rate(counters);
    ASSERT_TRUE(rate.has_value());
    EXPECT_DOUBLE_EQ(*rate, 0.25);
}

TEST(MetricsCache, CacheMissRateAllowsOversaturationGreaterThanOne) {
    const rch::metrics::CacheCounters counters{
        .cache_references = 100U,
        .cache_misses = 150U,
    };
    const auto rate = rch::metrics::cache_miss_rate(counters);
    ASSERT_TRUE(rate.has_value());
    EXPECT_DOUBLE_EQ(*rate, 1.5);
}

TEST(MetricsMemory, ReadPeakRssKbAcceptsVmPeakField) {
    const auto value = rch::metrics::read_peak_rss_kb(rch::metrics::PeakRssField::VmPeak);
#if defined(__linux__)
    ASSERT_TRUE(value.has_value());
    EXPECT_GT(*value, 0U);
#else
    EXPECT_FALSE(value.has_value());
#endif
}

TEST(MetricsDeterminism, U64LittleEndianSerializationCoversAllBytePositions) {
    const auto bytes = rch::metrics::u64_to_bytes_little_endian(UINT64_C(0x0123456789ABCDEF));
    const std::array<std::uint8_t, 8U> expected{
        0xEFU,
        0xCDU,
        0xABU,
        0x89U,
        0x67U,
        0x45U,
        0x23U,
        0x01U,
    };
    EXPECT_EQ(bytes, expected);
}

TEST(MetricsDeterminism, ComposeIntegerPayloadHasContractedByteLayout) {
    const std::vector<std::uint64_t> permutation{
        UINT64_C(0x0102030405060708),
    };
    const std::array<std::uint8_t, 3> bits_axis{0xAAU, 0xBBU, 0xCCU};
    const std::vector<std::uint64_t> keys{
        UINT64_C(0x1122334455667788),
    };
    const auto bytes = rch::metrics::compose_integer_payload(
        std::span<const std::uint64_t>{permutation},
        std::span<const std::uint8_t, 3U>{bits_axis},
        std::span<const std::uint64_t>{keys}
    );
    ASSERT_EQ(bytes.size(), 8U + 3U + 8U);
    // Permutation LE bytes: 0x08, 0x07, ..., 0x01.
    EXPECT_EQ(bytes[0], 0x08U);
    EXPECT_EQ(bytes[7], 0x01U);
    // bits_axis is appended raw (no endian transform).
    EXPECT_EQ(bytes[8], 0xAAU);
    EXPECT_EQ(bytes[9], 0xBBU);
    EXPECT_EQ(bytes[10], 0xCCU);
    // Keys LE bytes: 0x88, 0x77, ..., 0x11.
    EXPECT_EQ(bytes[11], 0x88U);
    EXPECT_EQ(bytes[18], 0x11U);
}

TEST(MetricsDeterminism, ComposeIntegerPayloadAllowsEmptyIntegerSegments) {
    const std::vector<std::uint64_t> empty{};
    const std::array<std::uint8_t, 3> bits_axis{0x01U, 0x02U, 0x03U};

    const auto bytes = rch::metrics::compose_integer_payload(
        std::span<const std::uint64_t>{empty},
        std::span<const std::uint8_t, 3U>{bits_axis},
        std::span<const std::uint64_t>{empty}
    );

    ASSERT_EQ(bytes.size(), 3U);
    EXPECT_EQ(bytes[0], 0x01U);
    EXPECT_EQ(bytes[1], 0x02U);
    EXPECT_EQ(bytes[2], 0x03U);
}

TEST(MetricsDeterminism, CompareDigestsReportsFirstDifferingByte) {
    rch::metrics::Sha256Digest a{};
    rch::metrics::Sha256Digest b{};
    for (std::size_t i = 0U; i < a.size(); ++i) {
        a[i] = static_cast<std::uint8_t>(i);
        b[i] = static_cast<std::uint8_t>(i);
    }
    {
        const auto report = rch::metrics::compare_digests(a, b);
        EXPECT_TRUE(report.identical);
        EXPECT_EQ(report.first_diff_byte, a.size());
    }
    {
        rch::metrics::Sha256Digest c = b;
        c[0] = 0xFFU;
        const auto report = rch::metrics::compare_digests(a, c);
        EXPECT_FALSE(report.identical);
        EXPECT_EQ(report.first_diff_byte, 0U);
    }
    {
        rch::metrics::Sha256Digest d = b;
        d[31] = 0xFFU;
        const auto report = rch::metrics::compare_digests(a, d);
        EXPECT_FALSE(report.identical);
        EXPECT_EQ(report.first_diff_byte, 31U);
    }
}

TEST(MetricsDeterminism, ComposePayloadDigestIsStableAcrossInvocations) {
    const std::vector<std::uint64_t> permutation{1ULL, 2ULL, 3ULL};
    const std::array<std::uint8_t, 3> bits_axis{4U, 5U, 6U};
    const std::vector<std::uint64_t> keys{42ULL, 1729ULL};
    const auto a = rch::metrics::sha256_integer_payload(
        std::span<const std::uint64_t>{permutation},
        std::span<const std::uint8_t, 3U>{bits_axis},
        std::span<const std::uint64_t>{keys}
    );
    const auto b = rch::metrics::sha256_integer_payload(
        std::span<const std::uint64_t>{permutation},
        std::span<const std::uint8_t, 3U>{bits_axis},
        std::span<const std::uint64_t>{keys}
    );
    EXPECT_TRUE(rch::metrics::compare_digests(a, b).identical);
}

TEST(MetricsDeterminism, DigestChangesWhenAnyPayloadSegmentChanges) {
    const std::vector<std::uint64_t> permutation{1ULL, 2ULL};
    const std::array<std::uint8_t, 3> bits_axis{3U, 4U, 5U};
    const std::vector<std::uint64_t> keys{10ULL, 20ULL};
    const auto baseline = rch::metrics::sha256_integer_payload(
        std::span<const std::uint64_t>{permutation},
        std::span<const std::uint8_t, 3U>{bits_axis},
        std::span<const std::uint64_t>{keys}
    );

    const std::vector<std::uint64_t> different_permutation{2ULL, 1ULL};
    const auto permutation_changed = rch::metrics::sha256_integer_payload(
        std::span<const std::uint64_t>{different_permutation},
        std::span<const std::uint8_t, 3U>{bits_axis},
        std::span<const std::uint64_t>{keys}
    );
    EXPECT_FALSE(rch::metrics::compare_digests(baseline, permutation_changed).identical);

    const std::array<std::uint8_t, 3> different_bits_axis{3U, 4U, 6U};
    const auto bits_changed = rch::metrics::sha256_integer_payload(
        std::span<const std::uint64_t>{permutation},
        std::span<const std::uint8_t, 3U>{different_bits_axis},
        std::span<const std::uint64_t>{keys}
    );
    EXPECT_FALSE(rch::metrics::compare_digests(baseline, bits_changed).identical);

    const std::vector<std::uint64_t> different_keys{10ULL, 21ULL};
    const auto keys_changed = rch::metrics::sha256_integer_payload(
        std::span<const std::uint64_t>{permutation},
        std::span<const std::uint8_t, 3U>{bits_axis},
        std::span<const std::uint64_t>{different_keys}
    );
    EXPECT_FALSE(rch::metrics::compare_digests(baseline, keys_changed).identical);
}

// Pins l1_locality/l2_locality to the published numerical results of the primary
// source, Gotsman & Lindenbaum 1996 (DOI 10.1109/83.499920), rather than to values
// this implementation produced. Their eq (3) is
//   \(L_1(C)=\max_{i<j} d(C(i),C(j))^m/|i-j|\), with \(m=3\),
// so laying the points out in curve order with the identity ordering makes the
// metric's rank gap exactly their \(|i-j|\) and the unit grid spacing exactly their \(d\).
[[nodiscard]] auto hilbert_curve_points(const std::uint8_t bits) -> std::vector<Vec3<double>> {
    const std::size_t side = std::size_t{1} << bits;
    const std::size_t n = side * side * side;
    std::vector<Vec3<double>> points(n);
    for (std::size_t i = 0U; i < n; ++i) {
        const auto cell =
            rch::curves::Hilbert3Standard::decode(static_cast<std::uint64_t>(i), bits);
        EXPECT_TRUE(cell.has_value());
        points[i] = {
            static_cast<double>((*cell)[0]),
            static_cast<double>((*cell)[1]),
            static_cast<double>((*cell)[2])
        };
    }
    return points;
}

TEST(MetricsLocalityGotsmanLindenbaum, HilbertL1RespectsPublishedBounds) {
    for (std::uint8_t bits = 2U; bits <= 4U; ++bits) {
        const auto points = hilbert_curve_points(bits);
        std::vector<std::size_t> identity(points.size());
        std::iota(identity.begin(), identity.end(), 0U);
        const double l1 = rch::metrics::l1_locality<std::size_t>(
            std::span<const Vec3<double>>{points}, std::span<const std::size_t>{identity}
        );

        // Theorem 1 lower bound for any \(m\)-dimensional curve:
        // \(L_1>(2^m-1)(1-1/N)^m\).
        const double side = static_cast<double>(std::size_t{1} << bits);
        EXPECT_GT(l1, 7.0 * std::pow(1.0 - (1.0 / side), 3.0));
        // Theorem 3 upper bound for the 3D Hilbert family, as stated by the authors.
        EXPECT_LE(l1, 117.56);
        // The authors' own simulation result for the 3D Hilbert family.
        EXPECT_LE(l1, 23.0);
    }
}

TEST(MetricsLocalityGotsmanLindenbaum, HilbertL1BeatsMortonOnTheSameGrid) {
    constexpr std::uint8_t bits = 3U;
    const std::size_t side = std::size_t{1} << bits;
    const auto hilbert_points = hilbert_curve_points(bits);

    // Same grid, ordered by Morton key instead.
    std::vector<Vec3<double>> morton_points;
    morton_points.reserve(hilbert_points.size());
    std::vector<std::pair<std::uint64_t, Vec3<double>>> keyed;
    keyed.reserve(hilbert_points.size());
    for (std::uint32_t z = 0U; z < side; ++z) {
        for (std::uint32_t y = 0U; y < side; ++y) {
            for (std::uint32_t x = 0U; x < side; ++x) {
                const auto key =
                    rch::curves::Morton3::encode(std::array<std::uint32_t, 3>{x, y, z}, bits);
                ASSERT_TRUE(key.has_value());
                keyed.emplace_back(
                    *key,
                    Vec3<double>{
                        static_cast<double>(x), static_cast<double>(y), static_cast<double>(z)
                    }
                );
            }
        }
    }
    std::ranges::sort(keyed, [](const auto& lhs, const auto& rhs) noexcept {
        return lhs.first < rhs.first;
    });
    for (const auto& entry : keyed) {
        morton_points.push_back(entry.second);
    }

    std::vector<std::size_t> identity(hilbert_points.size());
    std::iota(identity.begin(), identity.end(), 0U);
    const auto span_order = std::span<const std::size_t>{identity};
    const double hilbert_l1 = rch::metrics::l1_locality<std::size_t>(
        std::span<const Vec3<double>>{hilbert_points}, span_order
    );
    const double morton_l1 = rch::metrics::l1_locality<std::size_t>(
        std::span<const Vec3<double>>{morton_points}, span_order
    );

    // Gotsman & Lindenbaum Fig. 2: curves without the Hilbert recursion have
    // \(L_1=\Omega(N^{m-1})\). The metric must be able to separate the two.
    EXPECT_LT(hilbert_l1, morton_l1);
    EXPECT_LE(hilbert_l1, 23.0);
    EXPECT_GT(morton_l1, 23.0);
}

TEST(MetricsLocalityGotsmanLindenbaum, HilbertL2IsTheMinimumRatioAndDecays) {
    // Their eq. (4) defines \(L_2\) as the minimum ratio, and Theorem 2 gives
    // \(L_2(C)=O(N^{1-m})\), i.e. it decays to zero as the grid refines.
    double previous = std::numeric_limits<double>::infinity();
    for (std::uint8_t bits = 2U; bits <= 4U; ++bits) {
        const auto points = hilbert_curve_points(bits);
        std::vector<std::size_t> identity(points.size());
        std::iota(identity.begin(), identity.end(), 0U);
        const double l2 = rch::metrics::l2_locality<std::size_t>(
            std::span<const Vec3<double>>{points}, std::span<const std::size_t>{identity}
        );
        const double side = static_cast<double>(std::size_t{1} << bits);
        EXPECT_GT(l2, 0.0);
        EXPECT_LE(l2, std::pow(side, -2.0)); // \(O(N^{1-m})\) with \(m=3\)
        EXPECT_LT(l2, previous);
        previous = l2;
    }
}

} // namespace
