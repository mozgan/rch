#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <span>
#include <vector>

#include "rch/orderings/orderer.hpp"

#include <gtest/gtest.h>

#include "tests/property/property_generators.hpp"

namespace {

using rch::orderings::OrderingMethod;
using rch::tests::property::DeterministicGenerator;

TEST(PropertyGeneratorsRng, NextIndexZeroBoundIsDefensive) {
    DeterministicGenerator rng{0xF7AA00U};
    EXPECT_EQ(rng.next_index(0U), 0U);
    EXPECT_EQ(rng.next_index(0U), 0U);
}

TEST(PropertyGeneratorsRng, NextIndexStaysInBounds) {
    DeterministicGenerator rng{0xF7AA01U};
    for (std::size_t i = 0U; i < 1000U; ++i) {
        const std::size_t bound = rng.next_index(1024U) + 1U;
        EXPECT_LT(rng.next_index(bound), bound);
    }
}

TEST(PropertyGeneratorsRng, UnitDoubleStaysInClosedOpenInterval) {
    DeterministicGenerator rng{0xF7AA02U};
    for (std::size_t i = 0U; i < 10000U; ++i) {
        const double value = rng.unit_double();
        EXPECT_GE(value, 0.0);
        EXPECT_LT(value, 1.0);
    }
}

TEST(PropertyGeneratorsRng, SameSeedProducesIdenticalStream) {
    DeterministicGenerator rng_a{0xF7AA03U};
    DeterministicGenerator rng_b{0xF7AA03U};
    for (std::size_t i = 0U; i < 64U; ++i) {
        EXPECT_EQ(rng_a.next_u64(), rng_b.next_u64());
    }
}

TEST(PropertyGeneratorsRng, DifferentSeedsProduceDifferentStreams) {
    DeterministicGenerator rng_a{0xF7AA04U};
    DeterministicGenerator rng_b{0xF7AA05U};
    bool diverged = false;
    for (std::size_t i = 0U; i < 8U && !diverged; ++i) {
        if (rng_a.next_u64() != rng_b.next_u64()) {
            diverged = true;
        }
    }
    EXPECT_TRUE(diverged);
}

TEST(PropertyGeneratorsCloud, GeneratedCloudWithZeroPointsIsEmpty) {
    const auto cloud = rch::tests::property::generated_cloud(0xF7AB00U, 0U);
    EXPECT_TRUE(cloud.empty());
}

TEST(PropertyGeneratorsCloud, GeneratedCloudReturnsThreeDoublesPerPoint) {
    const auto cloud = rch::tests::property::generated_cloud(0xF7AB01U, 12U);
    EXPECT_EQ(cloud.size(), 3U * 12U);
}

TEST(PropertyGeneratorsCloud, GeneratedCloudIsDeterministicForSameSeed) {
    const auto a = rch::tests::property::generated_cloud(0xF7AB02U, 24U);
    const auto b = rch::tests::property::generated_cloud(0xF7AB02U, 24U);
    EXPECT_EQ(a, b);
}

TEST(PropertyGeneratorsPermute, PermutedEmptyCloudReturnsEmpty) {
    const std::vector<double> empty;
    const auto out = rch::tests::property::permuted_cloud(empty, 0xF7AC00U);
    EXPECT_TRUE(out.empty());
}

TEST(PropertyGeneratorsPermute, PermutedSinglePointEqualsInput) {
    const std::vector<double> single{1.5, 2.5, 3.5};
    const auto out = rch::tests::property::permuted_cloud(single, 0xF7AC01U);
    EXPECT_EQ(out, single);
}

TEST(PropertyGeneratorsPermute, PermutedCloudPreservesMultiset) {
    const auto original = rch::tests::property::generated_cloud(0xF7AC02U, 16U);
    const auto permuted = rch::tests::property::permuted_cloud(original, 0xF7AC02U);
    ASSERT_EQ(original.size(), permuted.size());

    auto to_point_set = [](const std::vector<double>& cloud) {
        std::vector<std::array<double, 3>> points;
        points.reserve(cloud.size() / 3U);
        for (std::size_t i = 0U; i < cloud.size(); i += 3U) {
            points.push_back({cloud[i], cloud[i + 1U], cloud[i + 2U]});
        }
        std::ranges::sort(points);
        return points;
    };
    EXPECT_EQ(to_point_set(original), to_point_set(permuted));
}

TEST(PropertyGeneratorsPermute, PermutedCloudIsDeterministicForSameSeed) {
    const auto original = rch::tests::property::generated_cloud(0xF7AC03U, 24U);
    const auto a = rch::tests::property::permuted_cloud(original, 0xDEADBEEF12U);
    const auto b = rch::tests::property::permuted_cloud(original, 0xDEADBEEF12U);
    EXPECT_EQ(a, b);
}

TEST(PropertyGeneratorsValidate, IsPermutationRejectsMalformedResults) {
    rch::orderings::OrderingResult result{};
    result.permutation = {0U, 1U, 2U};
    result.primary_keys = {0U, 1U, 2U};
    EXPECT_TRUE(rch::tests::property::is_permutation_of_size(result, 3U));

    result.permutation = {0U, 1U, 2U};
    result.primary_keys = {0U, 1U, 2U, 3U};
    EXPECT_FALSE(rch::tests::property::is_permutation_of_size(result, 3U));

    result.permutation = {0U, 1U, 1U}; // duplicate raw_index
    result.primary_keys = {0U, 1U, 2U};
    EXPECT_FALSE(rch::tests::property::is_permutation_of_size(result, 3U));

    result.permutation = {0U, 1U, 5U}; // out-of-range
    result.primary_keys = {0U, 1U, 2U};
    EXPECT_FALSE(rch::tests::property::is_permutation_of_size(result, 3U));

    result.permutation = {0U, 1U};
    result.primary_keys = {0U, 1U};
    EXPECT_FALSE(rch::tests::property::is_permutation_of_size(result, 3U));
}

TEST(PropertyGeneratorsMethods, AllOrderingMethodsListsEightUniqueStrategies) {
    constexpr auto methods = rch::tests::property::all_ordering_methods();
    static_assert(methods.size() == 8U);
    EXPECT_EQ(methods[0], OrderingMethod::InputOrder);
    EXPECT_EQ(methods[1], OrderingMethod::Lexicographic);
    EXPECT_EQ(methods[2], OrderingMethod::Morton);
    EXPECT_EQ(methods[3], OrderingMethod::IsotropicHilbert);
    EXPECT_EQ(methods[4], OrderingMethod::CompactHilbertAABB);
    EXPECT_EQ(methods[5], OrderingMethod::PcaCompactHilbert);
    EXPECT_EQ(methods[6], OrderingMethod::RobustFrameMorton);
    EXPECT_EQ(methods[7], OrderingMethod::RCH);
}

} // namespace
