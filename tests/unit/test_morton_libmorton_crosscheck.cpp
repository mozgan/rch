#include <libmorton/morton.h>

#include <array>
#include <cstdint>
#include <limits>
#include <random>

#include "rch/curves/morton3.hpp"

#include <gtest/gtest.h>

namespace {

using rch::curves::Morton3;

TEST(Morton3, MatchesDocumentedBitInterleaveExample) {
    const std::array<std::uint32_t, Morton3::dimensions> point{5U, 9U, 1U};

    const auto encoded = Morton3::encode(point, 4U);

    ASSERT_TRUE(encoded.has_value());
    EXPECT_EQ(*encoded, 1095ULL);
}

TEST(Morton3, RejectsInvalidBitsAndOutOfRangeCoordinates) {
    EXPECT_FALSE(Morton3::encode(std::array<std::uint32_t, 3>{1U, 0U, 0U}, 0U).has_value());
    EXPECT_FALSE(Morton3::encode(std::array<std::uint32_t, 3>{1U << 4U, 0U, 0U}, 4U).has_value());
    EXPECT_FALSE(Morton3::encode(std::array<std::uint32_t, 3>{0U, 0U, 0U}, 22U).has_value());
}

TEST(Morton3, PerAxisBitsMatchEqualBitEncoderWhenUniform) {
    const std::array<std::uint32_t, Morton3::dimensions> point{5U, 9U, 1U};
    const std::array<std::uint8_t, Morton3::dimensions> bits_axis{4U, 4U, 4U};

    const auto equal_bits = Morton3::encode(point, 4U);
    const auto per_axis = Morton3::encode(point, bits_axis);

    ASSERT_TRUE(equal_bits.has_value());
    ASSERT_TRUE(per_axis.has_value());
    EXPECT_EQ(*per_axis, *equal_bits);
}

TEST(Morton3, PerAxisBitsPackOnlyActiveAxes) {
    const std::array<std::uint32_t, Morton3::dimensions> point{3U, 1U, 1U};
    const std::array<std::uint8_t, Morton3::dimensions> bits_axis{2U, 1U, 1U};

    const auto encoded = Morton3::encode(point, bits_axis);

    ASSERT_TRUE(encoded.has_value());
    EXPECT_EQ(*encoded, 15ULL);
}

TEST(Morton3, PerAxisBitsRejectOverBudgetAndOutOfRangeCoordinates) {
    EXPECT_FALSE(
        Morton3::encode(
            std::array<std::uint32_t, 3>{0U, 0U, 0U}, std::array<std::uint8_t, 3>{32U, 32U, 0U}
        )
            .has_value()
    );
    EXPECT_FALSE(
        Morton3::encode(
            std::array<std::uint32_t, 3>{0U, 1U, 0U}, std::array<std::uint8_t, 3>{4U, 0U, 4U}
        )
            .has_value()
    );
}

TEST(Morton3, MatchesLibmortonBoundaryCases) {
    const std::array<std::array<std::uint32_t, Morton3::dimensions>, 5> points{
        std::array<std::uint32_t, Morton3::dimensions>{0U, 0U, 0U},
        std::array<std::uint32_t, Morton3::dimensions>{1U, 0U, 0U},
        std::array<std::uint32_t, Morton3::dimensions>{0U, 1U, 0U},
        std::array<std::uint32_t, Morton3::dimensions>{0U, 0U, 1U},
        std::array<std::uint32_t, Morton3::dimensions>{
            Morton3::max_coordinate, Morton3::max_coordinate, Morton3::max_coordinate
        }
    };

    for (const auto& point : points) {
        const auto encoded = Morton3::encode(point, Morton3::max_bits);
        const auto expected = libmorton::morton3D_64_encode(point[0], point[1], point[2]);

        ASSERT_TRUE(encoded.has_value());
        EXPECT_EQ(*encoded, expected);
    }
}

TEST(Morton3, OriginEncodesToZeroAtEveryValidBitDepth) {
    for (std::uint8_t bits = 0U; bits <= Morton3::max_bits; ++bits) {
        const auto encoded =
            Morton3::encode(std::array<std::uint32_t, Morton3::dimensions>{0U, 0U, 0U}, bits);
        ASSERT_TRUE(encoded.has_value()) << "bits=" << static_cast<unsigned>(bits);
        EXPECT_EQ(*encoded, 0ULL) << "bits=" << static_cast<unsigned>(bits);
    }
}

TEST(Morton3, SingleAxisEncodesAreMonotonicInCoordinate) {
    constexpr std::uint8_t bits = 8U;
    const std::uint32_t side = std::uint32_t{1U} << bits;

    for (std::uint8_t axis = 0U; axis < Morton3::dimensions; ++axis) {
        std::uint64_t previous = 0U;
        for (std::uint32_t coordinate = 0U; coordinate < side; ++coordinate) {
            std::array<std::uint32_t, Morton3::dimensions> point{0U, 0U, 0U};
            point[axis] = coordinate;
            const auto encoded = Morton3::encode(point, bits);
            ASSERT_TRUE(encoded.has_value());
            if (coordinate > 0U) {
                EXPECT_LT(previous, *encoded)
                    << "axis=" << static_cast<unsigned>(axis) << " coord=" << coordinate;
            }
            previous = *encoded;
        }
    }
}

TEST(Morton3, MatchesLibmortonCrossCheckAtIntermediateBitDepths) {
    constexpr std::array<std::uint8_t, 4> probe_bits{1U, 5U, 10U, 15U};
    constexpr std::size_t samples_per_bits = 200U;

    for (std::uint8_t bits : probe_bits) {
        const std::uint32_t coord_max = (std::uint32_t{1U} << bits) - 1U;
        std::mt19937_64 rng{static_cast<std::uint64_t>(bits) * 0x9E3779B97F4A7C15ULL};
        std::uniform_int_distribution<std::uint32_t> coord_dist{0U, coord_max};

        for (std::size_t sample = 0U; sample < samples_per_bits; ++sample) {
            const std::array<std::uint32_t, Morton3::dimensions> point{
                coord_dist(rng), coord_dist(rng), coord_dist(rng)
            };
            const auto encoded = Morton3::encode(point, bits);
            // libmorton encodes the full 21-bit code; mask the high bits the
            // partial-precision interleave would not have set yet.
            const auto full_expected = libmorton::morton3D_64_encode(point[0], point[1], point[2]);
            const std::uint64_t mask = bits == 0U ? 0ULL
                                                  : ((bits == Morton3::max_bits)
                                                         ? std::numeric_limits<std::uint64_t>::max()
                                                         : ((UINT64_C(1) << (3U * bits)) - 1ULL));
            const auto expected = full_expected & mask;

            ASSERT_TRUE(encoded.has_value())
                << "bits=" << static_cast<unsigned>(bits) << " sample=" << sample;
            EXPECT_EQ(*encoded, expected)
                << "bits=" << static_cast<unsigned>(bits) << " sample=" << sample;
        }
    }
}

TEST(Morton3, MatchesLibmortonCrossCheckForDeterministicRandomSamples) {
    constexpr std::size_t sample_count = 1000U;
    std::mt19937_64 rng{0x5A17C0DEC0FFEEULL};
    std::uniform_int_distribution<std::uint32_t> coordinate_dist{0U, Morton3::max_coordinate};

    for (std::size_t sample = 0U; sample < sample_count; ++sample) {
        const std::array<std::uint32_t, Morton3::dimensions> point{
            coordinate_dist(rng), coordinate_dist(rng), coordinate_dist(rng)
        };

        const auto encoded = Morton3::encode(point, Morton3::max_bits);
        const auto expected = libmorton::morton3D_64_encode(point[0], point[1], point[2]);

        ASSERT_TRUE(encoded.has_value()) << "sample=" << sample;
        EXPECT_EQ(*encoded, expected) << "sample=" << sample;
    }
}

} // namespace
