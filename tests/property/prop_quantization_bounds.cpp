#include <algorithm>
#include <cmath>
#include <cstdint>
#include <limits>
#include <vector>

#include "rch/curves/quantization.hpp"

#include <gtest/gtest.h>

#include "tests/property/property_generators.hpp"

namespace {

struct QuantizationCase {
    double value{};
    double lo{};
    double hi{};
    std::uint8_t bits{};
};

[[nodiscard]] auto make_quantization_cases() -> std::vector<QuantizationCase> {
    rch::tests::property::DeterministicGenerator rng{0xF70001U};
    std::vector<QuantizationCase> cases;
    cases.reserve(1000U);
    for (std::size_t i = 0U; i < 1000U; ++i) {
        const double lo = rng.finite_double(-100.0, 100.0);
        const double width = rng.finite_double(1.0e-9, 1000.0);
        const double alpha = rng.finite_double(-0.25, 1.25);
        cases.push_back(
            QuantizationCase{
                lo + (alpha * width),
                lo,
                lo + width,
                static_cast<std::uint8_t>(rng.next_u64() % 40U),
            }
        );
    }
    return cases;
}

TEST(QuantizationBoundsProperty, RandomFiniteInputsStayWithinClosedIntegerDomain) {
    const auto cases = make_quantization_cases();
    for (std::size_t case_index = 0U; case_index < cases.size(); ++case_index) {
        const QuantizationCase test_case = cases[case_index];
        const std::uint8_t effective_bits =
            std::min(test_case.bits, rch::curves::kMaxQuantizationBits);
        const std::uint32_t max_code = rch::curves::quantization_max_code(effective_bits);
        const std::uint32_t code =
            rch::curves::quantize_axis(test_case.value, test_case.lo, test_case.hi, test_case.bits);

        SCOPED_TRACE(::testing::Message{} << "case=" << case_index);
        EXPECT_LE(code, max_code);
        if (test_case.bits == 0U) {
            EXPECT_EQ(code, 0U);
        }
        if (test_case.value <= test_case.lo) {
            EXPECT_EQ(code, 0U);
        }
        if (test_case.value >= test_case.hi && test_case.bits > 0U) {
            EXPECT_EQ(code, max_code);
        }
    }
}

TEST(QuantizationBoundsEdges, InvalidInputsFailClosedToOrigin) {
    const double nan = std::numeric_limits<double>::quiet_NaN();
    const double inf = std::numeric_limits<double>::infinity();

    EXPECT_EQ(rch::curves::quantize_axis(nan, 0.0, 1.0, 8U), 0U);
    EXPECT_EQ(rch::curves::quantize_axis(inf, 0.0, 1.0, 8U), 0U);
    EXPECT_EQ(rch::curves::quantize_axis(0.5, nan, 1.0, 8U), 0U);
    EXPECT_EQ(rch::curves::quantize_axis(0.5, 0.0, inf, 8U), 0U);
    EXPECT_EQ(rch::curves::quantize_axis(0.5, 1.0, 0.0, 8U), 0U);
    EXPECT_EQ(rch::curves::quantize_axis(0.5, 0.0, 1.0, 0U), 0U);
}

} // namespace
