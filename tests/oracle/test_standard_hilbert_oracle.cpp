#include <array>
#include <cstdint>
#include <fstream>
#include <string>

#include "rch/curves/hilbert3_standard.hpp"

#include <gtest/gtest.h>

#include "simdjson_warning_guard.hpp"

namespace {

using rch::curves::Hilbert3Standard;
using rch::curves::Point3u32;

[[nodiscard]] auto oracle_path(const char* filename) -> std::string {
    return std::string{RCH_TEST_ORACLE_DIR} + "/" + filename;
}

TEST(StandardHilbertOracle, PinnedJsonlVectorsMatchBitExactly) {
    std::ifstream input{oracle_path("standard_hilbert_vectors.jsonl")};
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

        std::uint64_t bits_raw = 0U;
        std::uint64_t hilbert = 0U;
        ASSERT_EQ(doc["bits"].get(bits_raw), simdjson::SUCCESS);
        ASSERT_EQ(doc["hilbert"].get(hilbert), simdjson::SUCCESS);
        ASSERT_LE(bits_raw, Hilbert3Standard::max_bits);

        simdjson::dom::array point_json;
        ASSERT_EQ(doc["point"].get(point_json), simdjson::SUCCESS);
        Point3u32 point{};
        std::size_t axis = 0U;
        for (simdjson::dom::element coordinate_json : point_json) {
            ASSERT_LT(axis, point.size());
            std::uint64_t coordinate = 0U;
            ASSERT_EQ(coordinate_json.get(coordinate), simdjson::SUCCESS);
            ASSERT_LE(coordinate, UINT32_MAX);
            point[axis] = static_cast<std::uint32_t>(coordinate);
            ++axis;
        }
        ASSERT_EQ(axis, point.size());

        const auto encoded = Hilbert3Standard::encode(point, static_cast<std::uint8_t>(bits_raw));
        ASSERT_TRUE(encoded.has_value());
        EXPECT_EQ(*encoded, hilbert);

        const auto decoded = Hilbert3Standard::decode(hilbert, static_cast<std::uint8_t>(bits_raw));
        ASSERT_TRUE(decoded.has_value());
        EXPECT_EQ(*decoded, point);
        ++count;
    }

    EXPECT_EQ(count, 32U);
}

TEST(StandardHilbertOracle, ConsecutiveDecodedCellsAreFaceAdjacent) {
    constexpr std::uint8_t bits = 2U;
    constexpr std::uint64_t cell_count = UINT64_C(1) << (3U * bits);

    auto previous = Hilbert3Standard::decode(0U, bits);
    ASSERT_TRUE(previous.has_value());
    for (std::uint64_t h = 1U; h < cell_count; ++h) {
        const auto current = Hilbert3Standard::decode(h, bits);
        ASSERT_TRUE(current.has_value());

        const std::uint32_t dx = previous->at(0) > current->at(0)
                                     ? previous->at(0) - current->at(0)
                                     : current->at(0) - previous->at(0);
        const std::uint32_t dy = previous->at(1) > current->at(1)
                                     ? previous->at(1) - current->at(1)
                                     : current->at(1) - previous->at(1);
        const std::uint32_t dz = previous->at(2) > current->at(2)
                                     ? previous->at(2) - current->at(2)
                                     : current->at(2) - previous->at(2);
        EXPECT_EQ(dx + dy + dz, 1U) << "h=" << h;
        previous = current;
    }
}

} // namespace
