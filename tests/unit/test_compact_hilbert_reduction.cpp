#include <algorithm>
#include <array>
#include <cstdint>
#include <limits>
#include <tuple>
#include <vector>

#include "rch/curves/hilbert3_compact.hpp"
#include "rch/curves/hilbert3_standard.hpp"

#include <gtest/gtest.h>

namespace {

using rch::curves::BitsAxis3;
using rch::curves::Hilbert3Compact;
using rch::curves::Hilbert3Standard;
using rch::curves::Point3u32;

[[nodiscard]] auto enumerate_domain(const BitsAxis3& bits_axis) -> std::vector<Point3u32> {
    std::vector<Point3u32> points;
    const std::uint32_t nx = std::uint32_t{1U} << bits_axis[0];
    const std::uint32_t ny = std::uint32_t{1U} << bits_axis[1];
    const std::uint32_t nz = std::uint32_t{1U} << bits_axis[2];
    points.reserve(
        static_cast<std::size_t>(nx) * static_cast<std::size_t>(ny) * static_cast<std::size_t>(nz)
    );

    for (std::uint32_t x = 0U; x < nx; ++x) {
        for (std::uint32_t y = 0U; y < ny; ++y) {
            for (std::uint32_t z = 0U; z < nz; ++z) {
                points.push_back(Point3u32{x, y, z});
            }
        }
    }
    return points;
}

TEST(StandardHilbert3, DecodeEncodeRoundTripExhaustiveSmallDomains) {
    for (std::uint8_t bits = 0U; bits <= 4U; ++bits) {
        const std::uint32_t side = std::uint32_t{1U} << bits;
        for (std::uint32_t x = 0U; x < side; ++x) {
            for (std::uint32_t y = 0U; y < side; ++y) {
                for (std::uint32_t z = 0U; z < side; ++z) {
                    const Point3u32 point{x, y, z};
                    const auto encoded = Hilbert3Standard::encode(point, bits);
                    ASSERT_TRUE(encoded.has_value());
                    const auto decoded = Hilbert3Standard::decode(*encoded, bits);
                    ASSERT_TRUE(decoded.has_value());
                    EXPECT_EQ(*decoded, point);
                }
            }
        }
    }
}

TEST(CompactHilbert3, EqualBitsReduceToStandardHilbert) {
    for (std::uint8_t bits = 0U; bits <= 4U; ++bits) {
        const BitsAxis3 bits_axis{bits, bits, bits};
        const std::uint32_t side = std::uint32_t{1U} << bits;
        for (std::uint32_t x = 0U; x < side; ++x) {
            for (std::uint32_t y = 0U; y < side; ++y) {
                for (std::uint32_t z = 0U; z < side; ++z) {
                    const Point3u32 point{x, y, z};
                    const auto standard = Hilbert3Standard::encode(point, bits);
                    const auto compact = Hilbert3Compact::encode(point, bits_axis);
                    ASSERT_TRUE(standard.has_value());
                    ASSERT_TRUE(compact.has_value());
                    EXPECT_EQ(*compact, *standard);

                    const auto decoded = Hilbert3Compact::decode(*compact, bits_axis);
                    ASSERT_TRUE(decoded.has_value());
                    EXPECT_EQ(*decoded, point);
                }
            }
        }
    }
}

TEST(CompactHilbert3, MixedBitsPreservePaddedHilbertOrderingByDefinition) {
    const std::array<BitsAxis3, 4> cases{
        BitsAxis3{3U, 2U, 1U},
        BitsAxis3{1U, 3U, 2U},
        BitsAxis3{2U, 1U, 3U},
        BitsAxis3{2U, 0U, 3U},
    };

    for (const BitsAxis3& bits_axis : cases) {
        const auto max_bits = *std::max_element(bits_axis.begin(), bits_axis.end());
        std::vector<std::tuple<std::uint64_t, Point3u32>> padded_order;
        for (const Point3u32& point : enumerate_domain(bits_axis)) {
            const auto padded = Hilbert3Standard::encode(point, max_bits);
            ASSERT_TRUE(padded.has_value());
            padded_order.emplace_back(*padded, point);
        }
        std::sort(padded_order.begin(), padded_order.end());

        for (std::uint64_t rank = 0U; rank < padded_order.size(); ++rank) {
            const Point3u32& point = std::get<1>(padded_order[rank]);
            const auto compact = Hilbert3Compact::encode(point, bits_axis);
            ASSERT_TRUE(compact.has_value());
            EXPECT_EQ(*compact, rank);

            const auto decoded = Hilbert3Compact::decode(rank, bits_axis);
            ASSERT_TRUE(decoded.has_value());
            EXPECT_EQ(*decoded, point);
        }
    }
}

TEST(CompactHilbert3, RejectsOutOfRangeCoordinatesAndOverflowBudgets) {
    EXPECT_FALSE(Hilbert3Standard::encode(Point3u32{8U, 0U, 0U}, 3U).has_value());
    EXPECT_FALSE(Hilbert3Standard::decode(512U, 3U).has_value());

    EXPECT_FALSE(Hilbert3Compact::encode(Point3u32{4U, 0U, 0U}, BitsAxis3{2U, 2U, 2U}).has_value());
    EXPECT_FALSE(
        Hilbert3Compact::encode(Point3u32{0U, 0U, 0U}, BitsAxis3{32U, 32U, 1U}).has_value()
    );
}

TEST(StandardHilbert3, RejectsBitsAboveMaximum) {
    EXPECT_FALSE(Hilbert3Standard::encode(Point3u32{0U, 0U, 0U}, 22U).has_value());
    EXPECT_FALSE(Hilbert3Standard::decode(0U, 22U).has_value());
}

TEST(StandardHilbert3, ZeroBitsAcceptsOriginOnly) {
    const auto origin_encode = Hilbert3Standard::encode(Point3u32{0U, 0U, 0U}, 0U);
    ASSERT_TRUE(origin_encode.has_value());
    EXPECT_EQ(*origin_encode, 0U);

    EXPECT_FALSE(Hilbert3Standard::encode(Point3u32{1U, 0U, 0U}, 0U).has_value());
    EXPECT_FALSE(Hilbert3Standard::encode(Point3u32{0U, 1U, 0U}, 0U).has_value());
    EXPECT_FALSE(Hilbert3Standard::encode(Point3u32{0U, 0U, 1U}, 0U).has_value());

    const auto origin_decode = Hilbert3Standard::decode(0U, 0U);
    ASSERT_TRUE(origin_decode.has_value());
    EXPECT_EQ(*origin_decode, (Point3u32{0U, 0U, 0U}));
    EXPECT_FALSE(Hilbert3Standard::decode(1U, 0U).has_value());
}

TEST(CompactHilbert3, AllZeroBitsAxisAcceptsOriginOnly) {
    const BitsAxis3 zero_bits{0U, 0U, 0U};

    const auto origin_encode = Hilbert3Compact::encode(Point3u32{0U, 0U, 0U}, zero_bits);
    ASSERT_TRUE(origin_encode.has_value());
    EXPECT_EQ(*origin_encode, 0U);

    EXPECT_FALSE(Hilbert3Compact::encode(Point3u32{1U, 0U, 0U}, zero_bits).has_value());
    EXPECT_FALSE(Hilbert3Compact::encode(Point3u32{0U, 1U, 0U}, zero_bits).has_value());
    EXPECT_FALSE(Hilbert3Compact::encode(Point3u32{0U, 0U, 1U}, zero_bits).has_value());

    const auto origin_decode = Hilbert3Compact::decode(0U, zero_bits);
    ASSERT_TRUE(origin_decode.has_value());
    EXPECT_EQ(*origin_decode, (Point3u32{0U, 0U, 0U}));
    EXPECT_FALSE(Hilbert3Compact::decode(1U, zero_bits).has_value());
}

TEST(CompactHilbert3, SingleActiveAxisYieldsBijectiveRankOnSubspace) {
    const std::array<BitsAxis3, 3> single_axis_cases{
        BitsAxis3{4U, 0U, 0U},
        BitsAxis3{0U, 4U, 0U},
        BitsAxis3{0U, 0U, 4U},
    };

    for (const BitsAxis3& bits_axis : single_axis_cases) {
        std::uint8_t active_axis = 0U;
        for (std::uint8_t axis = 0U; axis < 3U; ++axis) {
            if (bits_axis[axis] != 0U) {
                active_axis = axis;
            }
        }
        const std::uint32_t side = std::uint32_t{1U} << bits_axis[active_axis];

        std::vector<std::uint8_t> seen(side, 0U);
        for (std::uint32_t coordinate = 0U; coordinate < side; ++coordinate) {
            Point3u32 point{0U, 0U, 0U};
            point[active_axis] = coordinate;
            const auto encoded = Hilbert3Compact::encode(point, bits_axis);
            ASSERT_TRUE(encoded.has_value());
            ASSERT_LT(*encoded, side);
            ASSERT_EQ(seen[*encoded], 0U) << "compact rank collision on active strip";
            seen[*encoded] = 1U;

            const auto decoded = Hilbert3Compact::decode(*encoded, bits_axis);
            ASSERT_TRUE(decoded.has_value());
            EXPECT_EQ(*decoded, point);
        }
        for (std::uint8_t flag : seen) {
            EXPECT_EQ(flag, 1U) << "every rank in [0, side) must be assigned";
        }
    }
}

TEST(CompactHilbert3, DecodeRejectsIndicesAboveBudget) {
    const BitsAxis3 bits_axis{2U, 2U, 2U};
    const std::uint64_t cell_count = UINT64_C(1) << 6;

    EXPECT_FALSE(Hilbert3Compact::decode(cell_count, bits_axis).has_value());
    EXPECT_FALSE(Hilbert3Compact::decode(cell_count + 17U, bits_axis).has_value());

    const BitsAxis3 mixed_bits{3U, 2U, 1U};
    const std::uint64_t mixed_count = UINT64_C(1) << 6;
    EXPECT_FALSE(Hilbert3Compact::decode(mixed_count, mixed_bits).has_value());
    EXPECT_FALSE(Hilbert3Compact::decode(UINT64_MAX, mixed_bits).has_value());
}

TEST(CompactHilbert3, MaximumBudgetExhaustiveSampleRoundTrip) {
    const BitsAxis3 bits_axis{21U, 21U, 21U};
    const std::uint32_t side = std::uint32_t{1U} << 21U;
    const std::uint32_t edge = side - 1U;

    const std::array<Point3u32, 7> samples{
        Point3u32{0U, 0U, 0U},
        Point3u32{edge, 0U, 0U},
        Point3u32{0U, edge, 0U},
        Point3u32{0U, 0U, edge},
        Point3u32{edge, edge, edge},
        Point3u32{edge / 2U, edge / 3U, edge / 5U},
        Point3u32{edge, edge / 2U, 1U},
    };

    for (const Point3u32& point : samples) {
        const auto encoded = Hilbert3Compact::encode(point, bits_axis);
        ASSERT_TRUE(encoded.has_value());
        EXPECT_LE(*encoded, (UINT64_C(1) << 63) - 1U);

        const auto decoded = Hilbert3Compact::decode(*encoded, bits_axis);
        ASSERT_TRUE(decoded.has_value());
        EXPECT_EQ(*decoded, point);
    }
}

TEST(CompactHilbert3, AsymmetricMaximumBudgetRoundTrip) {
    const BitsAxis3 bits_axis{32U, 1U, 30U};
    const std::uint32_t edge_x = std::numeric_limits<std::uint32_t>::max();
    const std::uint32_t edge_z = (std::uint32_t{1U} << 30U) - 1U;

    const std::array<Point3u32, 5> samples{
        Point3u32{0U, 0U, 0U},
        Point3u32{edge_x, 0U, 0U},
        Point3u32{0U, 1U, 0U},
        Point3u32{0U, 0U, edge_z},
        Point3u32{edge_x, 1U, edge_z},
    };

    for (const Point3u32& point : samples) {
        const auto encoded = Hilbert3Compact::encode(point, bits_axis);
        ASSERT_TRUE(encoded.has_value());
        const auto decoded = Hilbert3Compact::decode(*encoded, bits_axis);
        ASSERT_TRUE(decoded.has_value());
        EXPECT_EQ(*decoded, point);
    }
}

} // namespace
