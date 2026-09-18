#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <optional>
#include <sstream>
#include <string>
#include <span>
#include <string_view>
#include <vector>

#include "rch/core/sha256.hpp"
#include "rch/io/xyz_parse.hpp"
#include "rch/orderings/orderer.hpp"

#include <gtest/gtest.h>

#include "simdjson_warning_guard.hpp"

namespace {

struct ExpectedCase {
    std::string fixture{};
    std::string method{};
    std::string status{};
    std::string hash{};
};

[[nodiscard]] auto regression_path(const std::string_view relative) -> std::filesystem::path {
    return std::filesystem::path{RCH_REGRESSION_DIR} / relative;
}

[[nodiscard]] auto load_xyz(const std::string& fixture) -> std::vector<double> {
    std::ifstream input{regression_path(std::string{"tiny_clouds/"} + fixture)};
    EXPECT_TRUE(input.is_open()) << fixture;
    std::vector<double> points{};
    std::string line{};
    while (std::getline(input, line)) {
        const auto parsed = rch::io::parse_three_doubles(line);
        if (!parsed.has_value() && line.empty()) {
            continue;
        }
        EXPECT_TRUE(parsed.has_value()) << fixture << ": " << line;
        if (!parsed.has_value()) {
            continue;
        }
        points.push_back((*parsed)[0]);
        points.push_back((*parsed)[1]);
        points.push_back((*parsed)[2]);
    }
    return points;
}

[[nodiscard]] auto get_string(simdjson::dom::element object, const char* field) -> std::string {
    std::string_view value{};
    EXPECT_EQ(object[field].get(value), simdjson::SUCCESS);
    return std::string{value};
}

[[nodiscard]] auto load_expected_cases() -> std::vector<ExpectedCase> {
    const auto path = regression_path("expected_hashes.json");
    simdjson::dom::parser parser;
    simdjson::dom::element doc;
    EXPECT_EQ(parser.load(path.string()).get(doc), simdjson::SUCCESS);

    simdjson::dom::array cases_json;
    EXPECT_EQ(doc["cases"].get(cases_json), simdjson::SUCCESS);

    std::vector<ExpectedCase> cases{};
    for (simdjson::dom::element item : cases_json) {
        cases.push_back(
            ExpectedCase{
                get_string(item, "fixture"),
                get_string(item, "method"),
                get_string(item, "status"),
                get_string(item, "hash"),
            }
        );
    }
    return cases;
}

[[nodiscard]] auto invalid_hash(const std::string& fixture, const std::string& method)
    -> std::string {
    rch::core::Sha256 sha{};
    sha.update(std::span<const std::uint8_t>{
        reinterpret_cast<const std::uint8_t*>(fixture.data()), fixture.size()
    });
    sha.update_u8(0x1FU); // ASCII unit separator: fixture/method boundary marker.
    sha.update(std::span<const std::uint8_t>{
        reinterpret_cast<const std::uint8_t*>(method.data()), method.size()
    });
    const auto hex = rch::orderings::hash_hex(sha.finalize());
    return std::string{hex.data()};
}

TEST(Reproducibility, ExpectedHashesCoverSevenFixturesAndEightMethods) {
    const auto cases = load_expected_cases();
    EXPECT_EQ(cases.size(), 56U);
}

TEST(Reproducibility, TinyCloudHashesMatchPinnedManifest) {
    const auto cases = load_expected_cases();
    ASSERT_FALSE(cases.empty());

    for (const ExpectedCase& expected : cases) {
        const auto method = rch::orderings::method_from_string(expected.method);
        ASSERT_TRUE(method.has_value()) << expected.method;

        const auto points = load_xyz(expected.fixture);
        rch::orderings::OrderingConfig config{};
        config.method = *method;
        const auto actual = rch::orderings::order_point_cloud(points, config);

        if (expected.status == "invalid_input") {
            ASSERT_FALSE(actual.has_value()) << expected.fixture << " " << expected.method;
            EXPECT_EQ(actual.error().code, rch::orderings::OrderingErrorCode::invalid_input);
            EXPECT_EQ(invalid_hash(expected.fixture, expected.method), expected.hash);
            continue;
        }

        ASSERT_EQ(expected.status, "ok");
        ASSERT_TRUE(actual.has_value()) << expected.fixture << " " << expected.method;
        const auto hex = rch::orderings::hash_hex(actual->output_hash);
        EXPECT_EQ(std::string{hex.data()}, expected.hash)
            << expected.fixture << " " << expected.method;
    }
}

} // namespace
