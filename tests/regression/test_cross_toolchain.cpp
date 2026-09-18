#include <algorithm>
#include <array>
#include <bit>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <filesystem>
#include <iostream>
#include <limits>
#include <span>
#include <string>
#include <string_view>
#include <vector>

#include "rch/core/sha256.hpp"
#include "rch/orderings/orderer.hpp"

#include <gtest/gtest.h>

#include "simdjson_warning_guard.hpp"

namespace {

constexpr std::size_t kFixtureCount = 100U;
constexpr std::size_t kPointCount = 48U;

constexpr std::array<rch::orderings::OrderingMethod, 8> kMethods{
    rch::orderings::OrderingMethod::InputOrder,
    rch::orderings::OrderingMethod::Lexicographic,
    rch::orderings::OrderingMethod::Morton,
    rch::orderings::OrderingMethod::IsotropicHilbert,
    rch::orderings::OrderingMethod::CompactHilbertAABB,
    rch::orderings::OrderingMethod::PcaCompactHilbert,
    rch::orderings::OrderingMethod::RobustFrameMorton,
    rch::orderings::OrderingMethod::RCH,
};

[[nodiscard]] constexpr auto running_on_x86_64() noexcept -> bool {
#if defined(__x86_64__) || defined(_M_X64)
    return true;
#else
    return false;
#endif
}

[[nodiscard]] constexpr auto compiler_family() noexcept -> std::string_view {
#if defined(__clang__)
    return "clang";
#elif defined(__GNUC__)
    return "gcc";
#else
    return "unknown";
#endif
}

[[nodiscard]] auto expected_outputs_path() -> std::filesystem::path {
    return std::filesystem::path{RCH_EXPECTED_OUTPUTS_DIR} / "portability_diff.json";
}

inline void mix_u64(rch::core::Sha256& sha, const std::uint64_t value) noexcept {
    sha.update_u64_le(value);
}

inline void mix_bytes(rch::core::Sha256& sha, const std::span<const std::uint8_t> bytes) noexcept {
    sha.update(bytes);
}

[[nodiscard]] auto digest_hex(rch::core::Sha256& sha) -> std::array<char, 65> {
    const auto bytes = sha.finalize();
    return rch::orderings::hash_hex(bytes);
}

[[nodiscard]] auto make_fixture(const std::size_t fixture_index) -> std::vector<double> {
    std::vector<double> points;
    points.reserve(3U * kPointCount);
    const std::size_t seed = fixture_index + 1U;
    for (std::size_t i = 0U; i < kPointCount; ++i) {
        const std::size_t t = i + 1U;
        const auto x = static_cast<std::int64_t>(((17U * t) + (29U * seed)) % 257U) - 128;
        const auto y =
            static_cast<std::int64_t>(((31U * t * t) + (7U * seed) + (i % 5U)) % 263U) - 131;
        const auto z =
            static_cast<std::int64_t>(((43U * t) + (11U * seed * seed) + (3U * (i % 7U))) % 269U) -
            134;
        points.push_back(static_cast<double>(x));
        points.push_back(static_cast<double>(y));
        points.push_back(static_cast<double>(z));
    }
    return points;
}

[[nodiscard]] auto
is_permutation_of_size(const rch::orderings::OrderingResult& result, const std::size_t point_count)
    -> bool {
    if (result.permutation.size() != point_count || result.primary_keys.size() != point_count) {
        return false;
    }
    std::vector<std::uint8_t> seen(point_count, 0U);
    for (const std::uint64_t raw_index : result.permutation) {
        if (raw_index >= static_cast<std::uint64_t>(point_count)) {
            return false;
        }
        auto& slot = seen[static_cast<std::size_t>(raw_index)];
        if (slot != 0U) {
            return false;
        }
        slot = 1U;
    }
    return std::ranges::all_of(seen, [](const std::uint8_t value) noexcept { return value == 1U; });
}

[[nodiscard]] auto compute_cross_toolchain_digest() -> std::array<char, 65> {
    rch::core::Sha256 sha{};
    mix_u64(sha, kFixtureCount);
    mix_u64(sha, kPointCount);
    mix_u64(sha, kMethods.size());

    for (std::size_t fixture_index = 0U; fixture_index < kFixtureCount; ++fixture_index) {
        const auto points = make_fixture(fixture_index);
        for (const auto method : kMethods) {
            rch::orderings::OrderingConfig config{};
            config.method = method;

            const auto result = rch::orderings::order_point_cloud(points, config);
            EXPECT_TRUE(result.has_value())
                << "fixture=" << fixture_index << " method=" << rch::orderings::to_string(method);
            if (!result.has_value()) {
                mix_u64(sha, fixture_index);
                mix_u64(sha, static_cast<std::uint64_t>(method));
                mix_u64(sha, 0U);
                continue;
            }

            EXPECT_TRUE(is_permutation_of_size(*result, kPointCount))
                << "fixture=" << fixture_index << " method=" << rch::orderings::to_string(method);
            mix_u64(sha, fixture_index);
            mix_u64(sha, static_cast<std::uint64_t>(method));
            mix_u64(sha, result->robust_fallback_used ? 1U : 0U);
            mix_u64(sha, result->bits_axis[0]);
            mix_u64(sha, result->bits_axis[1]);
            mix_u64(sha, result->bits_axis[2]);
            mix_bytes(sha, result->output_hash);
        }
    }

    return digest_hex(sha);
}

[[nodiscard]] auto get_string(simdjson::dom::element object, const char* field) -> std::string {
    std::string_view value{};
    EXPECT_EQ(object[field].get(value), simdjson::SUCCESS);
    return std::string{value};
}

[[nodiscard]] auto get_uint64(simdjson::dom::element object, const char* field) -> std::uint64_t {
    std::uint64_t value{};
    EXPECT_EQ(object[field].get(value), simdjson::SUCCESS);
    return value;
}

[[nodiscard]] auto get_bool(simdjson::dom::element object, const char* field) -> bool {
    bool value{};
    EXPECT_EQ(object[field].get(value), simdjson::SUCCESS);
    return value;
}

[[nodiscard]] auto load_portability_manifest() -> simdjson::dom::element {
    static simdjson::dom::parser parser;
    simdjson::dom::element doc;
    EXPECT_EQ(parser.load(expected_outputs_path().string()).get(doc), simdjson::SUCCESS);
    return doc;
}

TEST(CrossToolchainManifest, SchemaStatesNoFloatBitExactClaim) {
    const auto doc = load_portability_manifest();
    simdjson::dom::element float_diagnostics;
    ASSERT_EQ(doc["float_diagnostics"].get(float_diagnostics), simdjson::SUCCESS);
    EXPECT_FALSE(get_bool(float_diagnostics, "bit_exact_claim"));
    EXPECT_EQ(get_string(float_diagnostics, "accepted_equivalence"), "semantic_tolerance");
    EXPECT_EQ(get_string(float_diagnostics, "status"), "reported_not_hash_locked");
}

TEST(CrossToolchainManifest, ReferencesUseRequiredBibliographicShape) {
    const auto doc = load_portability_manifest();
    simdjson::dom::array references;
    ASSERT_EQ(doc["references"].get(references), simdjson::SUCCESS);

    std::size_t count = 0U;
    for (simdjson::dom::element reference : references) {
        EXPECT_FALSE(get_string(reference, "author").empty());
        EXPECT_FALSE(get_string(reference, "work").empty());
        EXPECT_FALSE(get_string(reference, "date").empty());
        ++count;
    }
    EXPECT_GE(count, 3U);
}

TEST(CrossToolchainManifest, CoversX86ClangAndGccRuns) {
    const auto doc = load_portability_manifest();
    simdjson::dom::element integer_domain;
    ASSERT_EQ(doc["integer_domain"].get(integer_domain), simdjson::SUCCESS);
    EXPECT_EQ(get_uint64(integer_domain, "fixture_count"), kFixtureCount);
    EXPECT_EQ(get_uint64(integer_domain, "point_count_per_fixture"), kPointCount);
    EXPECT_EQ(get_uint64(integer_domain, "method_count"), kMethods.size());
    EXPECT_EQ(get_uint64(integer_domain, "integer_domain_mismatches"), 0U);

    simdjson::dom::array compiler_runs;
    EXPECT_EQ(integer_domain["compiler_runs"].get(compiler_runs), simdjson::SUCCESS);

    bool saw_clang = false;
    bool saw_gcc = false;
    for (simdjson::dom::element run : compiler_runs) {
        const std::string compiler = get_string(run, "compiler");
        EXPECT_EQ(get_string(run, "arch"), "x86_64");
        EXPECT_EQ(get_uint64(run, "fixture_count"), kFixtureCount);
        EXPECT_EQ(get_uint64(run, "method_count"), kMethods.size());
        EXPECT_EQ(get_uint64(run, "mismatches"), 0U);
        saw_clang = saw_clang || compiler == "clang";
        saw_gcc = saw_gcc || compiler == "gcc";
    }
    EXPECT_TRUE(saw_clang);
    EXPECT_TRUE(saw_gcc);
}

TEST(CrossToolchainIntegerDomain, CurrentCompilerMatchesPinnedDigest) {
    if (!running_on_x86_64()) {
        GTEST_SKIP() << "F8 canonical portability manifest is scoped to x86-64.";
    }
    if (compiler_family() == "unknown") {
        GTEST_SKIP() << "F8 canonical portability manifest is scoped to Clang/GCC.";
    }

    const auto actual = compute_cross_toolchain_digest();
    if (std::getenv("RCH_PRINT_CROSS_TOOLCHAIN_DIGEST") != nullptr) {
        std::cout << "RCH_CROSS_TOOLCHAIN_DIGEST=" << actual.data() << '\n';
    }

    const auto doc = load_portability_manifest();
    simdjson::dom::element integer_domain;
    ASSERT_EQ(doc["integer_domain"].get(integer_domain), simdjson::SUCCESS);
    const std::string expected = get_string(integer_domain, "canonical_digest");
    EXPECT_EQ(std::string{actual.data()}, expected);
}

TEST(CrossToolchainFixture, AllCoordinatesAreFiniteIntegersInBinary64ExactRange) {
    for (std::size_t fixture_index = 0U; fixture_index < kFixtureCount; ++fixture_index) {
        const auto points = make_fixture(fixture_index);
        ASSERT_EQ(points.size(), 3U * kPointCount);
        for (const double coord : points) {
            EXPECT_TRUE(std::isfinite(coord)) << "fixture=" << fixture_index;
            EXPECT_EQ(std::trunc(coord), coord)
                << "fixture=" << fixture_index << " coord=" << coord;
            EXPECT_LE(std::abs(coord), 200.0) << "fixture=" << fixture_index;
        }
    }
}

TEST(CrossToolchainFixture, IsDeterministicAcrossInvocations) {
    const auto a = make_fixture(0U);
    const auto b = make_fixture(0U);
    const auto c = make_fixture(99U);
    const auto d = make_fixture(99U);
    EXPECT_EQ(a, b);
    EXPECT_EQ(c, d);
    EXPECT_NE(a, c);
}

TEST(CrossToolchainManifest, TolerancePolicyIsPositiveAndBoundedBelowOne) {
    const auto doc = load_portability_manifest();
    simdjson::dom::element tolerance_policy;
    ASSERT_EQ(
        doc["float_diagnostics"]["tolerance_policy"].get(tolerance_policy), simdjson::SUCCESS
    );

    double absolute = 0.0;
    double relative = 0.0;
    ASSERT_EQ(tolerance_policy["absolute"].get(absolute), simdjson::SUCCESS);
    ASSERT_EQ(tolerance_policy["relative"].get(relative), simdjson::SUCCESS);

    EXPECT_GT(absolute, 0.0);
    EXPECT_LT(absolute, 1.0);
    EXPECT_TRUE(std::isfinite(absolute));

    EXPECT_GT(relative, 0.0);
    EXPECT_LT(relative, 1.0);
    EXPECT_TRUE(std::isfinite(relative));
}

TEST(CrossToolchainHelper, IsPermutationOfSizeRejectsMalformedResults) {
    rch::orderings::OrderingResult valid{};
    valid.permutation = {0U, 1U, 2U};
    valid.primary_keys = {0U, 1U, 2U};
    EXPECT_TRUE(is_permutation_of_size(valid, 3U));

    rch::orderings::OrderingResult wrong_size{};
    wrong_size.permutation = {0U, 1U, 2U};
    wrong_size.primary_keys = {0U, 1U};
    EXPECT_FALSE(is_permutation_of_size(wrong_size, 3U));

    rch::orderings::OrderingResult duplicate{};
    duplicate.permutation = {0U, 1U, 1U};
    duplicate.primary_keys = {0U, 1U, 2U};
    EXPECT_FALSE(is_permutation_of_size(duplicate, 3U));

    rch::orderings::OrderingResult out_of_range{};
    out_of_range.permutation = {0U, 1U, 5U};
    out_of_range.primary_keys = {0U, 1U, 2U};
    EXPECT_FALSE(is_permutation_of_size(out_of_range, 3U));
}

} // namespace
