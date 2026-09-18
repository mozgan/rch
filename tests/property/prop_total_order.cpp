#include <algorithm>
#include <bit>
#include <cstdint>
#include <limits>
#include <vector>

#include "rch/curves/curve_key.hpp"

#include <gtest/gtest.h>

#include "tests/property/property_generators.hpp"

namespace {

[[nodiscard]] auto double_from_bits(const std::uint64_t bits) noexcept -> double {
    return std::bit_cast<double>(bits);
}

[[nodiscard]] auto make_curve_keys() -> std::vector<rch::curves::CurveKey> {
    rch::tests::property::DeterministicGenerator rng{0xF70006U};
    std::vector<rch::curves::CurveKey> keys;
    keys.reserve(96U);

    const std::vector<double> specials{
        -std::numeric_limits<double>::infinity(),
        -0.0,
        0.0,
        std::numeric_limits<double>::infinity(),
        std::numeric_limits<double>::quiet_NaN(),
        double_from_bits(UINT64_C(0x7ff8000000000001)),
    };
    for (std::size_t i = 0U; i < specials.size(); ++i) {
        keys.push_back(rch::curves::CurveKey{0U, specials[i], specials[i], specials[i], i});
    }

    for (std::size_t i = 0U; i < 90U; ++i) {
        keys.push_back(
            rch::curves::CurveKey{
                rng.next_u64() & UINT64_C(0xffff),
                rng.finite_double(-10.0, 10.0),
                rng.finite_double(-10.0, 10.0),
                rng.finite_double(-10.0, 10.0),
                i,
            }
        );
    }
    return keys;
}

TEST(TotalOrderProperty, CurveKeyOrderingIsIrreflexiveAntisymmetricAndTransitive) {
    const auto keys = make_curve_keys();

    for (const auto& key : keys) {
        EXPECT_FALSE(key < key);
    }

    for (const auto& lhs : keys) {
        for (const auto& rhs : keys) {
            if (lhs < rhs) {
                EXPECT_FALSE(rhs < lhs);
            }
        }
    }

    for (const auto& lhs : keys) {
        for (const auto& mid : keys) {
            for (const auto& rhs : keys) {
                if ((lhs < mid) && (mid < rhs)) {
                    EXPECT_TRUE(lhs < rhs);
                }
            }
        }
    }
}

TEST(TotalOrderEdges, SignedZeroAndNanPayloadsHaveDeterministicKeys) {
    const rch::curves::CurveKey negative_zero{0U, -0.0, 0.0, 0.0, 0U};
    const rch::curves::CurveKey positive_zero{0U, 0.0, 0.0, 0.0, 0U};
    EXPECT_LT(negative_zero, positive_zero);

    const rch::curves::CurveKey nan_a{
        0U, double_from_bits(UINT64_C(0x7ff8000000000001)), 0.0, 0.0, 0U
    };
    const rch::curves::CurveKey nan_b{
        0U, double_from_bits(UINT64_C(0x7ff8000000000002)), 0.0, 0.0, 0U
    };
    EXPECT_NE(nan_a.order_tuple(), nan_b.order_tuple());
    EXPECT_TRUE((nan_a < nan_b) || (nan_b < nan_a));
}

} // namespace
