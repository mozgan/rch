#include <string_view>

#include "rch/robust/fallback_policy.hpp"

#include <gtest/gtest.h>

namespace {

using rch::robust::FallbackPolicy;
using rch::robust::to_string;

TEST(FallbackPolicy, ToStringMapsAllEnumValues) {
    EXPECT_EQ(to_string(FallbackPolicy::none), std::string_view{"none"});
    EXPECT_EQ(to_string(FallbackPolicy::disabled_small_n), std::string_view{"disabled_small_n"});
    EXPECT_EQ(
        to_string(FallbackPolicy::disabled_rank_deficient),
        std::string_view{"disabled_rank_deficient"}
    );
    EXPECT_EQ(to_string(FallbackPolicy::chi2_regularized), std::string_view{"chi2_regularized"});
    EXPECT_EQ(to_string(FallbackPolicy::hr_adjusted_f), std::string_view{"hr_adjusted_f"});
}

} // namespace
