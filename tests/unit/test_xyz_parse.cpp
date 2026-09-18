#include <array>
#include <bit>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <limits>
#include <string>

#include "rch/io/xyz_parse.hpp"

#include <gtest/gtest.h>

namespace {

TEST(XyzParseToken, AcceptsPlainInteger) {
    const auto value = rch::io::parse_double_token("42");
    ASSERT_TRUE(value.has_value());
    EXPECT_DOUBLE_EQ(*value, 42.0);
}

TEST(XyzParseToken, AcceptsFractionalAndSignedAndScientific) {
    EXPECT_DOUBLE_EQ(*rch::io::parse_double_token("-3.14"), -3.14);
    EXPECT_DOUBLE_EQ(*rch::io::parse_double_token("+0.5"), 0.5);
    EXPECT_DOUBLE_EQ(*rch::io::parse_double_token("1.0e2"), 100.0);
    EXPECT_DOUBLE_EQ(*rch::io::parse_double_token("2.5E-3"), 0.0025);
}

TEST(XyzParseToken, RejectsEmptyAndPurelyWhitespace) {
    EXPECT_FALSE(rch::io::parse_double_token("").has_value());
    EXPECT_FALSE(rch::io::parse_double_token("   ").has_value());
    EXPECT_FALSE(rch::io::parse_double_token("\t").has_value());
}

TEST(XyzParseToken, RejectsLeadingOrTrailingWhitespaceInsideRawToken) {
    EXPECT_FALSE(rch::io::parse_double_token(" 1.0").has_value());
    EXPECT_FALSE(rch::io::parse_double_token("1.0 ").has_value());
}

TEST(XyzParseToken, RejectsTrailingGarbage) {
    EXPECT_FALSE(rch::io::parse_double_token("1.0x").has_value());
    EXPECT_FALSE(rch::io::parse_double_token("3.14abc").has_value());
    EXPECT_FALSE(rch::io::parse_double_token("0,5").has_value()); // comma decimal not allowed
}

TEST(XyzParseToken, AcceptsNanAndInfinityTextual) {
    const auto inf = rch::io::parse_double_token("inf");
    ASSERT_TRUE(inf.has_value());
    EXPECT_TRUE(std::isinf(*inf));

    const auto nan = rch::io::parse_double_token("nan");
    ASSERT_TRUE(nan.has_value());
    EXPECT_TRUE(std::isnan(*nan));
}

TEST(XyzParseToken, RejectsDecimalOverflowButAcceptsFiniteMaximum) {
    const auto finite_max = rch::io::parse_double_token("1.7976931348623157e308");
    ASSERT_TRUE(finite_max.has_value());
    EXPECT_EQ(*finite_max, std::numeric_limits<double>::max());

    EXPECT_FALSE(rch::io::parse_double_token("1e309").has_value());
    EXPECT_FALSE(rch::io::parse_double_token("-1e309").has_value());
}

TEST(XyzParseTriplet, AcceptsWhitespaceSeparated) {
    const auto parsed = rch::io::parse_three_doubles("1.0 2.0 3.0");
    ASSERT_TRUE(parsed.has_value());
    EXPECT_DOUBLE_EQ((*parsed)[0], 1.0);
    EXPECT_DOUBLE_EQ((*parsed)[1], 2.0);
    EXPECT_DOUBLE_EQ((*parsed)[2], 3.0);
}

TEST(XyzParseTriplet, AcceptsCommaSeparated) {
    const auto parsed = rch::io::parse_three_doubles("1.0,2.0,3.0");
    ASSERT_TRUE(parsed.has_value());
    EXPECT_DOUBLE_EQ((*parsed)[0], 1.0);
    EXPECT_DOUBLE_EQ((*parsed)[1], 2.0);
    EXPECT_DOUBLE_EQ((*parsed)[2], 3.0);
}

TEST(XyzParseTriplet, AcceptsSemicolonSeparated) {
    const auto parsed = rch::io::parse_three_doubles("1.0;2.0;3.0");
    ASSERT_TRUE(parsed.has_value());
    EXPECT_DOUBLE_EQ((*parsed)[0], 1.0);
}

TEST(XyzParseTriplet, AcceptsMixedDelimitersAndExtraWhitespace) {
    const auto parsed = rch::io::parse_three_doubles("  1.0 ;  2.0 , 3.0  ");
    ASSERT_TRUE(parsed.has_value());
    EXPECT_DOUBLE_EQ((*parsed)[0], 1.0);
    EXPECT_DOUBLE_EQ((*parsed)[1], 2.0);
    EXPECT_DOUBLE_EQ((*parsed)[2], 3.0);
}

TEST(XyzParseTriplet, RejectsTwoTokens) {
    EXPECT_FALSE(rch::io::parse_three_doubles("1.0 2.0").has_value());
}

TEST(XyzParseTriplet, RejectsEmptyLine) {
    EXPECT_FALSE(rch::io::parse_three_doubles("").has_value());
}

TEST(XyzParseTriplet, RejectsTokenWithTrailingGarbage) {
    EXPECT_FALSE(rch::io::parse_three_doubles("1.0 2.0 3.0x").has_value());
}

TEST(XyzParseTriplet, RejectsOverflowingCoordinate) {
    EXPECT_FALSE(rch::io::parse_three_doubles("1.0 1e309 3.0").has_value());
}

TEST(XyzParseTriplet, AcceptsScientificCoordinates) {
    const auto parsed = rch::io::parse_three_doubles("1e-3 -2.5e2 3.14E0");
    ASSERT_TRUE(parsed.has_value());
    EXPECT_DOUBLE_EQ((*parsed)[0], 0.001);
    EXPECT_DOUBLE_EQ((*parsed)[1], -250.0);
    EXPECT_DOUBLE_EQ((*parsed)[2], 3.14);
}

TEST(XyzParseTriplet, IgnoresFourthTrailingToken) {
    const auto parsed = rch::io::parse_three_doubles("1.0 2.0 3.0 99.0");
    ASSERT_TRUE(parsed.has_value());
    EXPECT_DOUBLE_EQ((*parsed)[2], 3.0);
}

TEST(XyzParseTriplet, IgnoresMalformedFourthTrailingToken) {
    const auto parsed = rch::io::parse_three_doubles("1.0 2.0 3.0 malformed");
    ASSERT_TRUE(parsed.has_value());
    EXPECT_DOUBLE_EQ((*parsed)[0], 1.0);
    EXPECT_DOUBLE_EQ((*parsed)[1], 2.0);
    EXPECT_DOUBLE_EQ((*parsed)[2], 3.0);
}

// Signed zero must survive parsing bit-exactly. The ordering layer distinguishes
// -0.0 from +0.0 through `double_total_order_key`, and
// tests/regression/tiny_clouds/signed_zero.xyz is a pinned fixture built on it,
// so a parser that normalised -0.0 to +0.0 would silently change published output.
TEST(XyzParseToken, PreservesSignedZeroBitExactly) {
    const auto negative = rch::io::parse_double_token("-0.0");
    const auto positive = rch::io::parse_double_token("0.0");
    ASSERT_TRUE(negative.has_value());
    ASSERT_TRUE(positive.has_value());
    EXPECT_TRUE(std::signbit(*negative));
    EXPECT_FALSE(std::signbit(*positive));
    EXPECT_EQ(std::bit_cast<std::uint64_t>(*negative), UINT64_C(0x8000000000000000));
    EXPECT_EQ(std::bit_cast<std::uint64_t>(*positive), UINT64_C(0));

    const auto integral = rch::io::parse_double_token("-0");
    ASSERT_TRUE(integral.has_value());
    EXPECT_TRUE(std::signbit(*integral));
}

TEST(XyzParseTriplet, PreservesSignedZeroAcrossAllThreeAxes) {
    const auto parsed = rch::io::parse_three_doubles("-0.0 0.0 -0.0");
    ASSERT_TRUE(parsed.has_value());
    EXPECT_TRUE(std::signbit((*parsed)[0]));
    EXPECT_FALSE(std::signbit((*parsed)[1]));
    EXPECT_TRUE(std::signbit((*parsed)[2]));
}

// strtod reports ERANGE for underflow as well as overflow, but the guard is
// `errno == ERANGE && !isfinite(value)`, so only overflow is rejected. Underflow
// is a representable outcome and must survive.
TEST(XyzParseToken, AcceptsUnderflowAndSubnormalsWhileRejectingOverflow) {
    const auto underflow = rch::io::parse_double_token("1e-400");
    ASSERT_TRUE(underflow.has_value());
    EXPECT_TRUE(*underflow == 0.0 || std::fpclassify(*underflow) == FP_SUBNORMAL);

    const auto smallest = rch::io::parse_double_token("5e-324");
    ASSERT_TRUE(smallest.has_value());
    EXPECT_EQ(std::bit_cast<std::uint64_t>(*smallest), UINT64_C(1));

    EXPECT_FALSE(rch::io::parse_double_token("1e309").has_value());
}

// Reproducibility depends on a written-then-read coordinate coming back as the
// same double, so the 17-significant-digit round trip must be exact.
TEST(XyzParseToken, RoundTripsSeventeenDigitTextBitExactly) {
    const double values[] = {
        0.1,
        -3.14159265358979312,
        std::numeric_limits<double>::max(),
        std::numeric_limits<double>::min(),
        std::numeric_limits<double>::denorm_min(),
        -0.0,
        1.0 / 3.0,
    };
    for (const double value : values) {
        std::array<char, 64> buffer{};
        std::snprintf(buffer.data(), buffer.size(), "%.17g", value);
        const auto parsed = rch::io::parse_double_token(buffer.data());
        ASSERT_TRUE(parsed.has_value()) << buffer.data();
        EXPECT_EQ(std::bit_cast<std::uint64_t>(*parsed), std::bit_cast<std::uint64_t>(value))
            << buffer.data();
    }
}

// A trailing '\r' from a CRLF file is whitespace in the C locale, so the stream
// extraction drops it and the line still parses.
TEST(XyzParseTriplet, AcceptsCarriageReturnTerminatedLine) {
    const auto parsed = rch::io::parse_three_doubles("1.0 2.0 3.0\r");
    ASSERT_TRUE(parsed.has_value());
    EXPECT_DOUBLE_EQ((*parsed)[2], 3.0);
}

} // namespace
