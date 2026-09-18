#include <algorithm>
#include <array>
#include <cstdint>
#include <fstream>
#include <optional>
#include <sstream>
#include <string>

#include "rch/curves/hilbert3_compact.hpp"
#include "rch/curves/hilbert3_standard.hpp"

#include <gtest/gtest.h>

#include "simdjson_warning_guard.hpp"

namespace {

using rch::curves::BitsAxis3;
using rch::curves::Hilbert3Compact;
using rch::curves::Hilbert3Standard;
using rch::curves::Point3u32;

[[nodiscard]] auto oracle_path(const char* filename) -> std::string {
    return std::string{RCH_TEST_ORACLE_DIR} + "/" + filename;
}

[[nodiscard]] auto rank_by_padded_standard_order(const Point3u32& point, const BitsAxis3& bits_axis)
    -> std::optional<std::uint64_t> {
    const auto max_bits = *std::max_element(bits_axis.begin(), bits_axis.end());
    if (max_bits > Hilbert3Standard::max_bits) {
        return std::nullopt;
    }

    const auto target = Hilbert3Standard::encode(point, max_bits);
    if (!target.has_value()) {
        return std::nullopt;
    }

    std::uint64_t rank = 0U;
    const std::uint64_t nx = UINT64_C(1) << bits_axis[0];
    const std::uint64_t ny = UINT64_C(1) << bits_axis[1];
    const std::uint64_t nz = UINT64_C(1) << bits_axis[2];

    for (std::uint64_t x = 0U; x < nx; ++x) {
        for (std::uint64_t y = 0U; y < ny; ++y) {
            for (std::uint64_t z = 0U; z < nz; ++z) {
                const Point3u32 candidate{
                    static_cast<std::uint32_t>(x),
                    static_cast<std::uint32_t>(y),
                    static_cast<std::uint32_t>(z)
                };
                const auto candidate_key = Hilbert3Standard::encode(candidate, max_bits);
                if (!candidate_key.has_value()) {
                    return std::nullopt;
                }
                if (*candidate_key < *target) {
                    ++rank;
                }
            }
        }
    }

    return rank;
}

TEST(CompactHilbertOracle, PinnedJsonlVectorsMatchBitExactly) {
    std::ifstream input{oracle_path("compact_hilbert_vectors.jsonl")};
    ASSERT_TRUE(input.is_open());

    simdjson::dom::parser parser;
    std::string line;
    std::size_t count = 0U;
    while (std::getline(input, line)) {
        if (line.empty()) {
            continue;
        }

        simdjson::padded_string padded{line};
        simdjson::dom::element doc;
        ASSERT_EQ(parser.parse(padded).get(doc), simdjson::SUCCESS) << "line " << (count + 1U);

        std::uint64_t compact = 0U;
        std::uint64_t rank_by_definition = 0U;
        ASSERT_EQ(doc["compact"].get(compact), simdjson::SUCCESS);
        ASSERT_EQ(doc["rank_by_definition"].get(rank_by_definition), simdjson::SUCCESS);

        simdjson::dom::array bits_json;
        ASSERT_EQ(doc["bits_axis"].get(bits_json), simdjson::SUCCESS);
        BitsAxis3 bits_axis{};
        std::size_t axis = 0U;
        for (simdjson::dom::element bits_value_json : bits_json) {
            ASSERT_LT(axis, bits_axis.size());
            std::uint64_t bits_value = 0U;
            ASSERT_EQ(bits_value_json.get(bits_value), simdjson::SUCCESS);
            ASSERT_LE(bits_value, 32U);
            bits_axis[axis] = static_cast<std::uint8_t>(bits_value);
            ++axis;
        }
        ASSERT_EQ(axis, bits_axis.size());

        simdjson::dom::array point_json;
        ASSERT_EQ(doc["point"].get(point_json), simdjson::SUCCESS);
        Point3u32 point{};
        axis = 0U;
        for (simdjson::dom::element coordinate_json : point_json) {
            ASSERT_LT(axis, point.size());
            std::uint64_t coordinate = 0U;
            ASSERT_EQ(coordinate_json.get(coordinate), simdjson::SUCCESS);
            ASSERT_LE(coordinate, UINT32_MAX);
            point[axis] = static_cast<std::uint32_t>(coordinate);
            ++axis;
        }
        ASSERT_EQ(axis, point.size());

        const auto recomputed_rank = rank_by_padded_standard_order(point, bits_axis);
        ASSERT_TRUE(recomputed_rank.has_value());
        EXPECT_EQ(rank_by_definition, *recomputed_rank);
        EXPECT_EQ(compact, rank_by_definition);
        const auto encoded = Hilbert3Compact::encode(point, bits_axis);
        ASSERT_TRUE(encoded.has_value());
        EXPECT_EQ(*encoded, compact);

        const auto decoded = Hilbert3Compact::decode(compact, bits_axis);
        ASSERT_TRUE(decoded.has_value());
        EXPECT_EQ(*decoded, point);
        ++count;
    }

    EXPECT_GE(count, 24U);
    EXPECT_EQ(count, 40U);
}

TEST(CompactHilbertOracle, ProvenanceNoteIsCheckedIn) {
    std::ifstream input{oracle_path("compact_hilbert_vectors.provenance.md")};
    ASSERT_TRUE(input.is_open());

    std::ostringstream buffer;
    buffer << input.rdbuf();
    const std::string text = buffer.str();

    EXPECT_NE(text.find("definition-pinned in-repository oracle"), std::string::npos);
    EXPECT_NE(text.find("not an external third-party oracle"), std::string::npos);
    EXPECT_NE(text.find("rank_by_definition"), std::string::npos);
    EXPECT_NE(text.find("test_compact_hilbert_oracle"), std::string::npos);
}

} // namespace
