#include <algorithm>
#include <cmath>
#include <cstddef>
#include <fstream>
#include <span>
#include <string>
#include <vector>

#include "rch/core/matrix3.hpp"
#include "rch/robust/fallback_policy.hpp"
#include "rch/robust/mrcd.hpp"

#include <gtest/gtest.h>

#include "simdjson_warning_guard.hpp"

namespace {

using rch::core::Matrix3;
using rch::core::Vec3;
using rch::robust::FallbackPolicy;
using rch::robust::mrcd;

[[nodiscard]] auto oracle_path(const char* filename) -> std::string {
    return std::string{RCH_TEST_ORACLE_DIR} + "/" + filename;
}

[[nodiscard]] auto parse_points(simdjson::dom::array rows) -> std::vector<Vec3<double>> {
    std::vector<Vec3<double>> points;
    for (simdjson::dom::element row_json : rows) {
        simdjson::dom::array row;
        EXPECT_EQ(row_json.get(row), simdjson::SUCCESS);
        Vec3<double> point{};
        std::size_t axis = 0U;
        for (simdjson::dom::element value_json : row) {
            EXPECT_LT(axis, point.size());
            EXPECT_EQ(value_json.get(point[axis]), simdjson::SUCCESS);
            ++axis;
        }
        EXPECT_EQ(axis, point.size());
        points.push_back(point);
    }
    return points;
}

[[nodiscard]] auto parse_vec3(simdjson::dom::array values) -> Vec3<double> {
    Vec3<double> result{};
    std::size_t axis = 0U;
    for (simdjson::dom::element value_json : values) {
        EXPECT_LT(axis, result.size());
        EXPECT_EQ(value_json.get(result[axis]), simdjson::SUCCESS);
        ++axis;
    }
    EXPECT_EQ(axis, result.size());
    return result;
}

[[nodiscard]] auto parse_matrix3(simdjson::dom::array rows) -> Matrix3<double> {
    Matrix3<double> result{};
    std::size_t row_index = 0U;
    for (simdjson::dom::element row_json : rows) {
        EXPECT_LT(row_index, 3U);
        simdjson::dom::array row;
        EXPECT_EQ(row_json.get(row), simdjson::SUCCESS);
        std::size_t col_index = 0U;
        for (simdjson::dom::element value_json : row) {
            EXPECT_LT(col_index, 3U);
            EXPECT_EQ(value_json.get(result(row_index, col_index)), simdjson::SUCCESS);
            ++col_index;
        }
        EXPECT_EQ(col_index, 3U);
        ++row_index;
    }
    EXPECT_EQ(row_index, 3U);
    return result;
}

[[nodiscard]] auto linf_distance(const Vec3<double>& lhs, const Vec3<double>& rhs)
    -> double {
    double value = 0.0;
    for (std::size_t axis = 0U; axis < 3U; ++axis) {
        value = std::max(value, std::abs(lhs[axis] - rhs[axis]));
    }
    return value;
}

TEST(MrcdOracle, RrcovJsonlFixturesMatchWithinPinnedTolerances) {
    simdjson::padded_string tolerance_json;
    ASSERT_EQ(simdjson::padded_string::load(oracle_path("mrcd_tolerances.json"))
                  .get(tolerance_json),
              simdjson::SUCCESS);

    simdjson::dom::parser parser;
    simdjson::dom::element tolerance_doc;
    ASSERT_EQ(parser.parse(tolerance_json).get(tolerance_doc), simdjson::SUCCESS);
    double tol_loc = 0.0;
    double tol_scatter_rel = 0.0;
    ASSERT_EQ(tolerance_doc["tol_loc"].get(tol_loc), simdjson::SUCCESS);
    ASSERT_EQ(tolerance_doc["tol_scatter_rel"].get(tol_scatter_rel),
              simdjson::SUCCESS);

    std::ifstream input{oracle_path("mrcd_oracles.jsonl")};
    ASSERT_TRUE(input.is_open());

    std::string line;
    std::size_t count = 0U;
    while (std::getline(input, line)) {
        if (line.empty()) {
            continue;
        }

        simdjson::padded_string padded{line};
        simdjson::dom::element doc;
        ASSERT_EQ(parser.parse(padded).get(doc), simdjson::SUCCESS)
            << "line " << (count + 1U);

        simdjson::dom::array points_json;
        simdjson::dom::array center_json;
        simdjson::dom::array scatter_json;
        ASSERT_EQ(doc["points"].get(points_json), simdjson::SUCCESS);
        ASSERT_EQ(doc["center"].get(center_json), simdjson::SUCCESS);
        ASSERT_EQ(doc["scatter"].get(scatter_json), simdjson::SUCCESS);

        const auto points = parse_points(points_json);
        const auto expected_center = parse_vec3(center_json);
        const auto expected_scatter = parse_matrix3(scatter_json);
        const auto actual = mrcd(std::span<const Vec3<double>>{points});

        ASSERT_NE(actual.policy, FallbackPolicy::disabled_small_n);
        ASSERT_NE(actual.policy, FallbackPolicy::disabled_rank_deficient);
        EXPECT_LE(linf_distance(actual.center, expected_center), tol_loc)
            << "case " << (count + 1U);

        // Normalize by ||expected||, not max(1, ||expected||): clamping to 1
        // turns this into an absolute test for these small-magnitude fixtures.
        const double expected_norm = rch::core::frobenius_norm(expected_scatter);
        ASSERT_GT(expected_norm, 0.0) << "case " << (count + 1U);
        const double scatter_error =
            rch::core::frobenius_norm(actual.scatter - expected_scatter) / expected_norm;
        EXPECT_LE(scatter_error, tol_scatter_rel) << "case " << (count + 1U);
        ++count;
    }

    EXPECT_EQ(count, 3U);
}

} // namespace
