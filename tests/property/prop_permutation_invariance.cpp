#include <cstdint>
#include <string>
#include <vector>

#include "rch/orderings/orderer.hpp"

#include <gtest/gtest.h>

#include "tests/property/property_generators.hpp"

namespace {

struct PermutationCase {
    rch::orderings::OrderingMethod method{rch::orderings::OrderingMethod::RCH};
    std::uint64_t seed{};
};

[[nodiscard]] auto make_permutation_cases() -> std::vector<PermutationCase> {
    std::vector<PermutationCase> cases;
    for (std::uint64_t seed = 0U; seed < 10U; ++seed) {
        cases.push_back(
            PermutationCase{
                rch::orderings::OrderingMethod::CompactHilbertAABB,
                UINT64_C(0xF7000400) + seed,
            }
        );
        cases.push_back(
            PermutationCase{rch::orderings::OrderingMethod::RCH, UINT64_C(0xF7000500) + seed}
        );
    }
    return cases;
}

[[nodiscard]] auto primary_keys_in_sorted_order(const rch::orderings::OrderingResult& result)
    -> std::vector<std::uint64_t> {
    std::vector<std::uint64_t> keys;
    keys.reserve(result.permutation.size());
    for (const std::uint64_t raw_index_u64 : result.permutation) {
        keys.push_back(result.primary_keys[static_cast<std::size_t>(raw_index_u64)]);
    }
    return keys;
}

class PermutationInvarianceProperty : public ::testing::TestWithParam<PermutationCase> {};

TEST_P(PermutationInvarianceProperty, PermutedInputKeepsSortedCoordinateSequence) {
    const PermutationCase test_case = GetParam();
    const auto original = rch::tests::property::generated_cloud(test_case.seed, 27U);
    const auto permuted = rch::tests::property::permuted_cloud(original, test_case.seed ^ 0x55U);

    rch::orderings::OrderingConfig config{};
    config.method = test_case.method;
    const auto first = rch::orderings::order_point_cloud(original, config);
    const auto second = rch::orderings::order_point_cloud(permuted, config);

    ASSERT_TRUE(first.has_value());
    ASSERT_TRUE(second.has_value());
    EXPECT_EQ(first->bits_axis, second->bits_axis);
    EXPECT_EQ(primary_keys_in_sorted_order(*first), primary_keys_in_sorted_order(*second));
    EXPECT_EQ(
        rch::tests::property::ordered_coordinate_keys(original, *first),
        rch::tests::property::ordered_coordinate_keys(permuted, *second)
    );
}

INSTANTIATE_TEST_SUITE_P(
    CompactAndRchTenSeeds,
    PermutationInvarianceProperty,
    ::testing::ValuesIn(make_permutation_cases()),
    [](const ::testing::TestParamInfo<PermutationCase>& param_info) {
        return std::string{rch::orderings::to_string(param_info.param.method)} + "_" +
               std::to_string(param_info.index);
    }
);

[[nodiscard]] auto make_coordinate_only_permutation_cases() -> std::vector<PermutationCase> {
    std::vector<PermutationCase> cases;
    for (std::uint64_t seed = 0U; seed < 5U; ++seed) {
        cases.push_back(
            PermutationCase{
                rch::orderings::OrderingMethod::Lexicographic,
                UINT64_C(0xF7000800) + seed,
            }
        );
        cases.push_back(
            PermutationCase{rch::orderings::OrderingMethod::Morton, UINT64_C(0xF7000900) + seed}
        );
        cases.push_back(
            PermutationCase{
                rch::orderings::OrderingMethod::IsotropicHilbert,
                UINT64_C(0xF7000A00) + seed,
            }
        );
    }
    return cases;
}

class CoordinateOnlyPermutationInvarianceProperty
    : public ::testing::TestWithParam<PermutationCase> {};

TEST_P(CoordinateOnlyPermutationInvarianceProperty, PermutedInputKeepsSortedCoordinateSequence) {
    const PermutationCase test_case = GetParam();
    const auto original = rch::tests::property::generated_cloud(test_case.seed, 27U);
    const auto permuted = rch::tests::property::permuted_cloud(original, test_case.seed ^ 0xAAU);

    rch::orderings::OrderingConfig config{};
    config.method = test_case.method;
    const auto first = rch::orderings::order_point_cloud(original, config);
    const auto second = rch::orderings::order_point_cloud(permuted, config);

    ASSERT_TRUE(first.has_value());
    ASSERT_TRUE(second.has_value());
    EXPECT_EQ(
        rch::tests::property::ordered_coordinate_keys(original, *first),
        rch::tests::property::ordered_coordinate_keys(permuted, *second)
    );
}

INSTANTIATE_TEST_SUITE_P(
    CoordinateOnlyFiveSeeds,
    CoordinateOnlyPermutationInvarianceProperty,
    ::testing::ValuesIn(make_coordinate_only_permutation_cases()),
    [](const ::testing::TestParamInfo<PermutationCase>& param_info) {
        return std::string{rch::orderings::to_string(param_info.param.method)} + "_" +
               std::to_string(param_info.index);
    }
);

} // namespace
