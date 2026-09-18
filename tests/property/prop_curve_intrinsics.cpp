// ----------------------------------------------------------------------------
// prop_curve_intrinsics.cpp — implementation-independent properties of the
// three curve primitives.
//
// Why this file exists:
//   tests/oracle/standard_hilbert_vectors.jsonl and
//   tests/oracle/compact_hilbert_vectors.jsonl are *self-pinned* fixtures — see
//   compact_hilbert_vectors.provenance.md ("not an external third-party
//   oracle"). They detect regressions against current behaviour but cannot
//   detect an error in the construction itself.
//
//   The properties below hold for ANY correct Hilbert / Morton construction,
//   independently of Hamilton & Rau-Chaplin's particular formulation, so they
//   are genuine external evidence rather than a snapshot:
//
//     1. Standard Hilbert is a bijection \([0,2^b)^3 \to [0,2^{3b})\), round-trips,
//        and — the defining property of a Hilbert curve — successive indices
//        map to grid-adjacent cells (\(L_1\) distance exactly 1). Bit-manipulation
//        errors in the per-level state composition typically preserve
//        bijectivity while breaking adjacency, which is exactly what a
//        definition-pinned oracle cannot see.
//
//     2. The compact index equals the RANK of the point in the padded standard
//        Hilbert order, and preserves that order. This is Hamilton &
//        Rau-Chaplin's own definition:
//          "walk through all the points in P, calculate their Hilbert indices
//           and sort them based on these values. Then, assign to each point p
//           its rank in this sorted list as an index [...]
//           \(h_1<h_2 \iff H^U(p_1)<H^U(p_2)\)"
//        — Information Processing Letters 105 (2008) 155-163, Section 3
//          (references_txt/R_CHRIS_2.txt:218-284).
//        With equal per-axis bits the compact index must coincide exactly with
//        the standard one.
//
//     3. Morton agrees with a straightforward independent bit interleave, and
//        its per-axis-bits generalisation follows the same rank rule as (2).
//
//   Exhaustive, not sampled: the domains are small enough to enumerate.
// ----------------------------------------------------------------------------

#include <algorithm>
#include <array>
#include <cstdint>
#include <cstdlib>
#include <vector>

#include "rch/curves/hilbert3_compact.hpp"
#include "rch/curves/hilbert3_standard.hpp"
#include "rch/curves/morton3.hpp"

#include <gtest/gtest.h>

namespace {

using rch::curves::BitsAxis3;
using rch::curves::Hilbert3Compact;
using rch::curves::Hilbert3Standard;
using rch::curves::Morton3;
using rch::curves::Point3u32;

// Exhaustive bound: \(b=4\) gives 4096 cells per curve and 24 index bits.
constexpr std::uint8_t kMaxUniformBits = 4U;
// Per-axis bound for the unequal-bits sweep: \(5^3=125\) triples, \(\le2^{15}\) cells.
constexpr std::uint8_t kMaxAxisBits = 4U;

TEST(HilbertIntrinsics, StandardIsABijectionAndRoundTrips) {
    for (std::uint8_t bits = 1U; bits <= kMaxUniformBits; ++bits) {
        const std::uint32_t side = std::uint32_t{1U} << bits;
        const std::uint64_t cells = std::uint64_t{1U} << (3U * bits);
        std::vector<std::uint8_t> seen(cells, 0U);

        for (std::uint32_t x = 0U; x < side; ++x) {
            for (std::uint32_t y = 0U; y < side; ++y) {
                for (std::uint32_t z = 0U; z < side; ++z) {
                    const Point3u32 point{x, y, z};
                    const auto index = Hilbert3Standard::encode(point, bits);
                    ASSERT_TRUE(index.has_value()) << "bits=" << +bits;
                    ASSERT_LT(*index, cells);
                    ASSERT_EQ(seen[*index], 0U) << "collision at index " << *index;
                    seen[*index] = 1U;

                    const auto decoded = Hilbert3Standard::decode(*index, bits);
                    ASSERT_TRUE(decoded.has_value());
                    EXPECT_EQ((*decoded)[0], x);
                    EXPECT_EQ((*decoded)[1], y);
                    EXPECT_EQ((*decoded)[2], z);
                }
            }
        }
        EXPECT_TRUE(std::ranges::all_of(seen, [](const std::uint8_t v) { return v == 1U; }))
            << "not surjective for bits=" << +bits;
    }
}

// The defining property: consecutive Hilbert indices are grid neighbours.
TEST(HilbertIntrinsics, StandardVisitsGridNeighboursInSequence) {
    for (std::uint8_t bits = 1U; bits <= kMaxUniformBits; ++bits) {
        const std::uint64_t cells = std::uint64_t{1U} << (3U * bits);
        for (std::uint64_t index = 0U; index + 1U < cells; ++index) {
            const auto here = Hilbert3Standard::decode(index, bits);
            const auto next = Hilbert3Standard::decode(index + 1U, bits);
            ASSERT_TRUE(here.has_value() && next.has_value());

            std::uint32_t manhattan = 0U;
            for (std::size_t axis = 0U; axis < 3U; ++axis) {
                const auto a = static_cast<std::int64_t>((*here)[axis]);
                const auto b = static_cast<std::int64_t>((*next)[axis]);
                manhattan += static_cast<std::uint32_t>(std::abs(a - b));
            }
            ASSERT_EQ(manhattan, 1U)
                << "bits=" << +bits << " indices " << index << " and " << (index + 1U)
                << " are not grid-adjacent";
        }
    }
}

TEST(HilbertIntrinsics, CompactReducesToStandardWhenAxisBitsAreEqual) {
    for (std::uint8_t bits = 1U; bits <= kMaxUniformBits; ++bits) {
        const std::uint32_t side = std::uint32_t{1U} << bits;
        const BitsAxis3 bits_axis{bits, bits, bits};
        for (std::uint32_t x = 0U; x < side; ++x) {
            for (std::uint32_t y = 0U; y < side; ++y) {
                for (std::uint32_t z = 0U; z < side; ++z) {
                    const Point3u32 point{x, y, z};
                    const auto compact = Hilbert3Compact::encode(point, bits_axis);
                    const auto standard = Hilbert3Standard::encode(point, bits);
                    ASSERT_TRUE(compact.has_value() && standard.has_value());
                    ASSERT_EQ(*compact, *standard) << "bits=" << +bits;
                }
            }
        }
    }
}

// Hamilton & Rau-Chaplin IPL 105 (2008) Section 3: the compact index is the
// rank of the point in the padded standard Hilbert order, and
// \(h_1<h_2 \iff H^U(p_1)<H^U(p_2)\).
TEST(HilbertIntrinsics, CompactIndexIsTheRankInPaddedStandardOrder) {
    struct Row {
        std::uint64_t padded{};
        std::uint64_t compact{};
    };

    for (std::uint8_t bx = 0U; bx <= kMaxAxisBits; ++bx) {
        for (std::uint8_t by = 0U; by <= kMaxAxisBits; ++by) {
            for (std::uint8_t bz = 0U; bz <= kMaxAxisBits; ++bz) {
                const BitsAxis3 bits_axis{bx, by, bz};
                const std::uint8_t padded_bits = std::max({bx, by, bz});

                std::vector<Row> rows;
                for (std::uint32_t x = 0U; x < (std::uint32_t{1U} << bx); ++x) {
                    for (std::uint32_t y = 0U; y < (std::uint32_t{1U} << by); ++y) {
                        for (std::uint32_t z = 0U; z < (std::uint32_t{1U} << bz); ++z) {
                            const Point3u32 point{x, y, z};
                            const auto padded = Hilbert3Standard::encode(point, padded_bits);
                            const auto compact = Hilbert3Compact::encode(point, bits_axis);
                            ASSERT_TRUE(padded.has_value() && compact.has_value());

                            const auto decoded = Hilbert3Compact::decode(*compact, bits_axis);
                            ASSERT_TRUE(decoded.has_value());
                            EXPECT_EQ((*decoded)[0], x);
                            EXPECT_EQ((*decoded)[1], y);
                            EXPECT_EQ((*decoded)[2], z);

                            rows.push_back(Row{*padded, *compact});
                        }
                    }
                }

                std::ranges::sort(rows, [](const Row& lhs, const Row& rhs) {
                    return lhs.padded < rhs.padded;
                });
                for (std::size_t rank = 0U; rank < rows.size(); ++rank) {
                    ASSERT_EQ(rows[rank].compact, rank)
                        << "bits_axis=(" << +bx << "," << +by << "," << +bz << ")";
                }
            }
        }
    }
}

[[nodiscard]] constexpr auto reference_morton(
    const std::uint32_t x, const std::uint32_t y, const std::uint32_t z, const std::uint8_t bits
) noexcept -> std::uint64_t {
    std::uint64_t key = 0U;
    for (std::uint8_t i = 0U; i < bits; ++i) {
        key |= static_cast<std::uint64_t>((x >> i) & 1U) << ((3U * i) + 0U);
        key |= static_cast<std::uint64_t>((y >> i) & 1U) << ((3U * i) + 1U);
        key |= static_cast<std::uint64_t>((z >> i) & 1U) << ((3U * i) + 2U);
    }
    return key;
}

TEST(MortonIntrinsics, UniformBitsMatchAnIndependentInterleave) {
    for (std::uint8_t bits = 1U; bits <= kMaxUniformBits; ++bits) {
        const std::uint32_t side = std::uint32_t{1U} << bits;
        for (std::uint32_t x = 0U; x < side; ++x) {
            for (std::uint32_t y = 0U; y < side; ++y) {
                for (std::uint32_t z = 0U; z < side; ++z) {
                    const Point3u32 point{x, y, z};
                    const auto key = Morton3::encode(point, bits);
                    ASSERT_TRUE(key.has_value());
                    EXPECT_EQ(*key, reference_morton(x, y, z, bits));
                }
            }
        }
    }
}

// The per-axis-bits Morton overload is a generalisation defined by this project
// (Morton 1966 covers only the uniform case). Pin it to the same rank rule the
// compact Hilbert index follows, so the two "compact" curves stay consistent.
TEST(MortonIntrinsics, PerAxisBitsIsTheRankInPaddedMortonOrder) {
    struct Row {
        std::uint64_t padded{};
        std::uint64_t compact{};
    };

    for (std::uint8_t bx = 0U; bx <= kMaxAxisBits; ++bx) {
        for (std::uint8_t by = 0U; by <= kMaxAxisBits; ++by) {
            for (std::uint8_t bz = 0U; bz <= kMaxAxisBits; ++bz) {
                const std::array<std::uint8_t, 3> bits_axis{bx, by, bz};
                const std::uint8_t padded_bits = std::max({bx, by, bz});

                std::vector<Row> rows;
                for (std::uint32_t x = 0U; x < (std::uint32_t{1U} << bx); ++x) {
                    for (std::uint32_t y = 0U; y < (std::uint32_t{1U} << by); ++y) {
                        for (std::uint32_t z = 0U; z < (std::uint32_t{1U} << bz); ++z) {
                            const Point3u32 point{x, y, z};
                            const auto padded = Morton3::encode(point, padded_bits);
                            const auto compact = Morton3::encode(point, bits_axis);
                            ASSERT_TRUE(padded.has_value() && compact.has_value());
                            rows.push_back(Row{*padded, *compact});
                        }
                    }
                }

                std::ranges::sort(rows, [](const Row& lhs, const Row& rhs) {
                    return lhs.padded < rhs.padded;
                });
                for (std::size_t rank = 0U; rank < rows.size(); ++rank) {
                    ASSERT_EQ(rows[rank].compact, rank)
                        << "bits_axis=(" << +bx << "," << +by << "," << +bz << ")";
                }
            }
        }
    }
}

} // namespace
