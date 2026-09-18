#include <limits>
#include <string>
#include <string_view>

#include "rch/core/version.hpp"

#include <gtest/gtest.h>

TEST(VersionMacros, MacrosAreDefined) {
#ifndef RCH_VERSION_MAJOR
    FAIL() << "RCH_VERSION_MAJOR is not defined";
#endif
#ifndef RCH_VERSION_MINOR
    FAIL() << "RCH_VERSION_MINOR is not defined";
#endif
#ifndef RCH_VERSION_PATCH
    FAIL() << "RCH_VERSION_PATCH is not defined";
#endif
    EXPECT_GE(RCH_VERSION_MAJOR, 0);
    EXPECT_GE(RCH_VERSION_MINOR, 0);
    EXPECT_GE(RCH_VERSION_PATCH, 0);
}

TEST(VersionMacros, ConstexprAccessorsMatchMacros) {
    EXPECT_EQ(rch::core::version::major, RCH_VERSION_MAJOR);
    EXPECT_EQ(rch::core::version::minor, RCH_VERSION_MINOR);
    EXPECT_EQ(rch::core::version::patch, RCH_VERSION_PATCH);
}

TEST(VersionMacros, StringIsDottedTriple) {
    const std::string s = RCH_VERSION_STRING;
    const std::string expected = std::to_string(RCH_VERSION_MAJOR) + "." +
                                 std::to_string(RCH_VERSION_MINOR) + "." +
                                 std::to_string(RCH_VERSION_PATCH);
    EXPECT_EQ(s, expected);
    EXPECT_EQ(std::string_view{rch::core::version::string}, expected);
}

TEST(FloatingPointContract, DoubleIsIEC559) {
    EXPECT_TRUE(std::numeric_limits<double>::is_iec559);
    EXPECT_TRUE(std::numeric_limits<float>::is_iec559);
}
