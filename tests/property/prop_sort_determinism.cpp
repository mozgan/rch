#include <array>
#include <cstdint>
#include <string>
#include <vector>

#include "rch/orderings/orderer.hpp"

#include <gtest/gtest.h>

#include "tests/property/property_generators.hpp"

namespace {

struct MethodSeedCase {
    rch::orderings::OrderingMethod method{rch::orderings::OrderingMethod::RCH};
    std::uint64_t seed{};
};

[[nodiscard]] auto make_method_seed_cases() -> std::vector<MethodSeedCase> {
    std::vector<MethodSeedCase> cases;
    for (const auto method : rch::tests::property::all_ordering_methods()) {
        for (std::uint64_t seed = 0U; seed < 6U; ++seed) {
            cases.push_back(MethodSeedCase{method, UINT64_C(0xF7000300) + seed});
        }
    }
    return cases;
}

class SortDeterminismProperty : public ::testing::TestWithParam<MethodSeedCase> {};

TEST_P(SortDeterminismProperty, RepeatedCallsProduceIdenticalIntegerOutputs) {
    const MethodSeedCase test_case = GetParam();
    const auto points = rch::tests::property::generated_cloud(test_case.seed, 24U);

    rch::orderings::OrderingConfig config{};
    config.method = test_case.method;
    const auto first = rch::orderings::order_point_cloud(points, config);
    const auto second = rch::orderings::order_point_cloud(points, config);

    ASSERT_TRUE(first.has_value());
    ASSERT_TRUE(second.has_value());
    ASSERT_TRUE(rch::tests::property::is_permutation_of_size(*first, points.size() / 3U));
    ASSERT_TRUE(rch::tests::property::is_permutation_of_size(*second, points.size() / 3U));
    EXPECT_EQ(first->method, second->method);
    EXPECT_EQ(first->permutation, second->permutation);
    EXPECT_EQ(first->primary_keys, second->primary_keys);
    EXPECT_EQ(first->bits_axis, second->bits_axis);
    EXPECT_EQ(first->robust_fallback_used, second->robust_fallback_used);
    EXPECT_EQ(first->output_hash, second->output_hash);
}

INSTANTIATE_TEST_SUITE_P(
    AllMethodsSixSeeds,
    SortDeterminismProperty,
    ::testing::ValuesIn(make_method_seed_cases()),
    [](const ::testing::TestParamInfo<MethodSeedCase>& param_info) {
        return std::string{rch::orderings::to_string(param_info.param.method)} + "_" +
               std::to_string(param_info.index);
    }
);

} // namespace
