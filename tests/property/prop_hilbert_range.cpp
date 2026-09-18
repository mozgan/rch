#include <array>
#include <cstdint>
#include <string>
#include <vector>

#include "rch/curves/bit_budget.hpp"
#include "rch/curves/hilbert3_compact.hpp"
#include "rch/curves/hilbert3_standard.hpp"

#include <gtest/gtest.h>

#include "tests/property/property_generators.hpp"

namespace {

struct HilbertRangeCase {
    rch::curves::BitsAxis3 bits_axis{};
    rch::curves::Point3u32 compact_point{};
    std::uint8_t standard_bits{};
    rch::curves::Point3u32 standard_point{};
};

[[nodiscard]] auto make_hilbert_cases() -> std::vector<HilbertRangeCase> {
    rch::tests::property::DeterministicGenerator rng{0xF70002U};
    std::vector<HilbertRangeCase> cases;
    cases.reserve(1000U);
    for (std::size_t i = 0U; i < 1000U; ++i) {
        rch::curves::BitsAxis3 bits_axis{
            static_cast<std::uint8_t>(rng.next_index(11U)),
            static_cast<std::uint8_t>(rng.next_index(11U)),
            static_cast<std::uint8_t>(rng.next_index(11U)),
        };
        rch::curves::Point3u32 compact_point{};
        for (std::size_t axis = 0U; axis < bits_axis.size(); ++axis) {
            const std::uint8_t bits = bits_axis[axis];
            const std::uint32_t upper = bits == 0U ? 1U : (std::uint32_t{1U} << bits);
            compact_point[axis] = static_cast<std::uint32_t>(rng.next_u64() % upper);
        }

        const auto standard_bits = static_cast<std::uint8_t>(rng.next_index(11U));
        rch::curves::Point3u32 standard_point{};
        const std::uint32_t standard_upper =
            standard_bits == 0U ? 1U : (std::uint32_t{1U} << standard_bits);
        for (std::uint32_t& coordinate : standard_point) {
            coordinate = static_cast<std::uint32_t>(rng.next_u64() % standard_upper);
        }

        cases.push_back(HilbertRangeCase{bits_axis, compact_point, standard_bits, standard_point});
    }
    return cases;
}

class HilbertRangeProperty : public ::testing::TestWithParam<HilbertRangeCase> {};

TEST_P(HilbertRangeProperty, StandardAndCompactKeysStayInRangeAndRoundTrip) {
    const HilbertRangeCase test_case = GetParam();

    const auto standard =
        rch::curves::Hilbert3Standard::encode(test_case.standard_point, test_case.standard_bits);
    ASSERT_TRUE(standard.has_value());
    const std::uint64_t standard_upper = UINT64_C(1) << (3U * test_case.standard_bits);
    EXPECT_LT(*standard, standard_upper);
    EXPECT_EQ(
        rch::curves::Hilbert3Standard::decode(*standard, test_case.standard_bits),
        test_case.standard_point
    );

    const auto compact =
        rch::curves::Hilbert3Compact::encode(test_case.compact_point, test_case.bits_axis);
    ASSERT_TRUE(compact.has_value());
    const std::uint16_t compact_total = rch::curves::total_bits(test_case.bits_axis);
    const std::uint64_t compact_upper = UINT64_C(1) << compact_total;
    EXPECT_LT(*compact, compact_upper);
    EXPECT_EQ(
        rch::curves::Hilbert3Compact::decode(*compact, test_case.bits_axis), test_case.compact_point
    );
}

TEST(HilbertRangeEdges, InvalidBitsAndCoordinatesFailClosed) {
    EXPECT_FALSE(
        rch::curves::Hilbert3Standard::encode(rch::curves::Point3u32{1U, 0U, 0U}, 0U).has_value()
    );
    EXPECT_FALSE(
        rch::curves::Hilbert3Standard::encode(rch::curves::Point3u32{0U, 0U, 0U}, 22U).has_value()
    );

    const rch::curves::BitsAxis3 over_budget{32U, 32U, 0U};
    EXPECT_FALSE(
        rch::curves::Hilbert3Compact::encode(rch::curves::Point3u32{0U, 0U, 0U}, over_budget)
            .has_value()
    );
    EXPECT_FALSE(rch::curves::Hilbert3Compact::decode(0U, over_budget).has_value());
    EXPECT_FALSE(
        rch::curves::Hilbert3Compact::encode(
            rch::curves::Point3u32{2U, 0U, 0U}, rch::curves::BitsAxis3{1U, 1U, 1U}
        )
            .has_value()
    );
}

TEST(HilbertRangeEdges, ZeroBitCompactDomainContainsOnlyOrigin) {
    const rch::curves::BitsAxis3 zero_bits{0U, 0U, 0U};
    const auto encoded =
        rch::curves::Hilbert3Compact::encode(rch::curves::Point3u32{0U, 0U, 0U}, zero_bits);
    ASSERT_TRUE(encoded.has_value());
    EXPECT_EQ(*encoded, 0U);
    EXPECT_EQ(
        rch::curves::Hilbert3Compact::decode(*encoded, zero_bits),
        (rch::curves::Point3u32{0U, 0U, 0U})
    );
}

INSTANTIATE_TEST_SUITE_P(
    Random1000,
    HilbertRangeProperty,
    ::testing::ValuesIn(make_hilbert_cases()),
    [](const ::testing::TestParamInfo<HilbertRangeCase>& param_info) {
        return "case_" + std::to_string(param_info.index);
    }
);

} // namespace
