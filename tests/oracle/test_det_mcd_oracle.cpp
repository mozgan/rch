#include <cmath>
#include <cstddef>
#include <fstream>
#include <string>
#include <vector>

#include "rch/core/matrix3.hpp"
#include "rch/robust/det_mcd.hpp"
#include "rch/robust/fallback_policy.hpp"
#include "rch/robust/hardin_rocke_cutoff.hpp"

#include <gtest/gtest.h>

#include "simdjson_warning_guard.hpp"

namespace {

using rch::core::Matrix3;
using rch::core::Vec3;
using rch::robust::det_mcd;
using rch::robust::FallbackPolicy;

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

[[nodiscard]] auto linf_distance(const Vec3<double>& lhs, const Vec3<double>& rhs) -> double {
    double value = 0.0;
    for (std::size_t axis = 0U; axis < 3U; ++axis) {
        value = std::max(value, std::abs(lhs[axis] - rhs[axis]));
    }
    return value;
}

TEST(DetMcdOracle, RobustbaseJsonlFixturesMatchWithinPinnedTolerances) {
    simdjson::padded_string tolerance_json;
    ASSERT_EQ(simdjson::padded_string::load(oracle_path("det_mcd_tolerances.json")).get(tolerance_json),
              simdjson::SUCCESS);

    simdjson::dom::parser parser;
    simdjson::dom::element tolerance_doc;
    ASSERT_EQ(parser.parse(tolerance_json).get(tolerance_doc), simdjson::SUCCESS);
    double tol_loc = 0.0;
    double tol_scatter_rel = 0.0;
    ASSERT_EQ(tolerance_doc["tol_loc"].get(tol_loc), simdjson::SUCCESS);
    ASSERT_EQ(tolerance_doc["tol_scatter_rel"].get(tol_scatter_rel), simdjson::SUCCESS);

    std::ifstream input{oracle_path("det_mcd_oracles.jsonl")};
    ASSERT_TRUE(input.is_open());

    std::string line;
    std::size_t count = 0U;
    while (std::getline(input, line)) {
        if (line.empty()) {
            continue;
        }

        simdjson::padded_string padded{line};
        simdjson::dom::element doc;
        ASSERT_EQ(parser.parse(padded).get(doc), simdjson::SUCCESS) << "line " << (count + 1U);

        std::uint64_t h = 0U;
        ASSERT_EQ(doc["h"].get(h), simdjson::SUCCESS);

        simdjson::dom::array points_json;
        simdjson::dom::array center_json;
        simdjson::dom::array scatter_json;
        ASSERT_EQ(doc["points"].get(points_json), simdjson::SUCCESS);
        ASSERT_EQ(doc["center"].get(center_json), simdjson::SUCCESS);
        ASSERT_EQ(doc["scatter"].get(scatter_json), simdjson::SUCCESS);

        const auto points = parse_points(points_json);
        const auto expected_center = parse_vec3(center_json);
        const auto expected_scatter = parse_matrix3(scatter_json);
        const auto actual = det_mcd(std::span<const Vec3<double>>{points});

        ASSERT_NE(actual.policy, FallbackPolicy::disabled_small_n);
        ASSERT_NE(actual.policy, FallbackPolicy::disabled_rank_deficient);
        ASSERT_EQ(actual.h, static_cast<std::size_t>(h));
        EXPECT_LE(linf_distance(actual.center, expected_center), tol_loc);

        // Normalize by ||expected||, not by max(1, ||expected||): these fixtures
        // have ||expected||_F ~ 0.13, so clamping to 1 silently turned this into
        // an absolute test and let a 2.5-2.7x scale error pass under a nominal
        // 12% "relative" tolerance.
        const double expected_norm = rch::core::frobenius_norm(expected_scatter);
        ASSERT_GT(expected_norm, 0.0) << "case " << (count + 1U);
        const double scatter_error =
            rch::core::frobenius_norm(actual.scatter - expected_scatter) / expected_norm;
        EXPECT_LE(scatter_error, tol_scatter_rel);
        ++count;
    }

    EXPECT_EQ(count, 3U);
}

TEST(HardinRockeOracle, MaintDataFixturesMatchCutoffHelper) {
    std::ifstream input{oracle_path("hardin_rocke_cutoffs.jsonl")};
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

        double probability = 0.0;
        double expected = 0.0;
        std::uint64_t nobs = 0U;
        std::uint64_t nvar = 0U;
        std::uint64_t h = 0U;
        ASSERT_EQ(doc["p"].get(probability), simdjson::SUCCESS);
        ASSERT_EQ(doc["nobs"].get(nobs), simdjson::SUCCESS);
        ASSERT_EQ(doc["nvar"].get(nvar), simdjson::SUCCESS);
        ASSERT_EQ(doc["h"].get(h), simdjson::SUCCESS);
        ASSERT_EQ(doc["cutoff"].get(expected), simdjson::SUCCESS);

        const auto actual = rch::robust::hardin_rocke_f_cutoff(
            static_cast<std::size_t>(nobs),
            static_cast<std::size_t>(nvar),
            static_cast<std::size_t>(h),
            probability
        );
        ASSERT_TRUE(actual.has_value());
        EXPECT_NEAR(*actual, expected, 1.0e-8);
        ++count;
    }

    EXPECT_EQ(count, 3U);
}

} // namespace
