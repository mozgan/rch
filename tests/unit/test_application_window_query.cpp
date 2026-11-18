#include <algorithm>
#include <array>
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <string>
#include <vector>

#include "rch/application/window_query.hpp"
#include "rch/core/sha256.hpp"

#include <gtest/gtest.h>

namespace {

class TemporaryDirectory final {
public:
    TemporaryDirectory() {
        const auto nonce = std::chrono::steady_clock::now().time_since_epoch().count();
        path_ = std::filesystem::temp_directory_path() /
                ("rch_window_query_test_" + std::to_string(nonce));
        std::filesystem::create_directories(path_);
    }

    ~TemporaryDirectory() {
        std::error_code error{};
        std::filesystem::remove_all(path_, error);
    }

    [[nodiscard]] auto file(const std::string& name) const -> std::filesystem::path {
        return path_ / name;
    }

private:
    std::filesystem::path path_;
};

[[nodiscard]] auto make_original_fixture() -> std::vector<rch::application::PointRecord> {
    std::vector<rch::application::PointRecord> points;
    points.reserve(130U);
    points.push_back({1000U, {0.0, 0.0, 0.0}});
    points.push_back({1001U, {1.0, 1.0, 1.0}});
    points.push_back({1002U, {1.0, 1.0, 1.0}}); // Distinct IDs at duplicate coordinates.
    for (std::uint64_t id = 3U; id < 130U; ++id) {
        const auto coordinate = static_cast<double>(id);
        points.push_back({1000U + id, {coordinate, static_cast<double>(id % 7U), -coordinate}});
    }
    return points;
}

[[nodiscard]] auto ordered_fixture(
    const std::vector<rch::application::PointRecord>& source, const std::uint64_t layout_id
) -> std::vector<rch::application::PointRecord> {
    auto points = source;
    if (layout_id == 3U) {
        std::reverse(points.begin(), points.end());
    } else if (layout_id == 6U) {
        std::rotate(points.begin(), points.begin() + 43, points.end());
    }
    return points;
}

[[nodiscard]] auto fixture_metadata(const std::uint64_t layout_id)
    -> rch::application::PageFileMetadata {
    rch::application::PageFileMetadata metadata{};
    metadata.layout_id = layout_id;
    metadata.source_checksum[0] = 0x42U;
    return metadata;
}

[[nodiscard]] auto id_hash(const std::vector<std::uint64_t>& ids) -> std::array<std::uint8_t, 32> {
    rch::core::Sha256 hash{};
    for (const auto id : ids) {
        hash.update_u64_le(id);
    }
    return hash.finalize();
}

TEST(ApplicationWindowQuery, MatchesIndependentOracleForA0A3A6FixturePermutations) {
    const auto original = make_original_fixture();
    constexpr std::array<std::uint64_t, 3> layout_ids{0U, 3U, 6U};
    const std::array<rch::application::QueryWindow, 4> windows{{
        {{1.0, 1.0, 1.0}, {1.0, 1.0, 1.0}},
        {{500.0, 500.0, 500.0}, {501.0, 501.0, 501.0}},
        {{-10.0, -10.0, -200.0}, {200.0, 10.0, 10.0}},
        {{129.0, 3.0, -129.0}, {129.0, 3.0, -129.0}},
    }};

    TemporaryDirectory temporary{};
    for (const auto layout_id : layout_ids) {
        const auto ordered = ordered_fixture(original, layout_id);
        const auto directory = rch::application::build_page_directory(ordered);
        const auto path = temporary.file("layout_" + std::to_string(layout_id) + ".page");
        rch::application::PageFileWriter::write(path, ordered, fixture_metadata(layout_id));
        rch::application::PageFileReader page_file{path};

        for (const auto& window : windows) {
            const auto expected = rch::application::full_scan_query_oracle(original, window);
            const auto actual =
                rch::application::execute_page_pruned_query(page_file, directory, window);
            EXPECT_EQ(actual.point_ids, expected) << "layout=" << layout_id;
            EXPECT_EQ(id_hash(actual.point_ids), id_hash(expected)) << "layout=" << layout_id;
            EXPECT_EQ(actual.candidate_pages, actual.pages_read) << "layout=" << layout_id;
        }
    }
}

TEST(ApplicationWindowQuery, ReadsOnlyTheMatchingPartialFinalPage) {
    const auto original = make_original_fixture();
    const auto directory = rch::application::build_page_directory(original);
    TemporaryDirectory temporary{};
    const auto path = temporary.file("partial.page");
    rch::application::PageFileWriter::write(path, original, fixture_metadata(0U));
    rch::application::PageFileReader page_file{path};

    const rch::application::QueryWindow final_record{{129.0, 3.0, -129.0}, {129.0, 3.0, -129.0}};
    const auto actual =
        rch::application::execute_page_pruned_query(page_file, directory, final_record);
    EXPECT_EQ(actual.point_ids, (std::vector<std::uint64_t>{1129U}));
    EXPECT_EQ(actual.pages_read, 1U);
    EXPECT_EQ(actual.candidate_pages, 1U);
}

TEST(ApplicationWindowQuery, DiskFullScanReadsAllRecordsEvenForEmptyWindow) {
    const auto points = make_original_fixture();
    const auto directory = rch::application::build_page_directory(points);
    TemporaryDirectory temporary{};
    const auto path = temporary.file("full_scan.page");
    rch::application::PageFileWriter::write(path, points, fixture_metadata(0U));
    rch::application::PageFileReader reader{path};
    const rch::application::QueryWindow outside{{500.0, 500.0, 500.0}, {501.0, 501.0, 501.0}};
    const auto pruned = rch::application::execute_page_pruned_query(reader, directory, outside);
    const auto full = rch::application::execute_page_pruned_query(reader, directory, outside, true);
    EXPECT_EQ(pruned.pages_read, 0U);
    EXPECT_EQ(full.pages_read, directory.size());
    EXPECT_EQ(full.records_examined, points.size());
    EXPECT_EQ(full.point_ids, pruned.point_ids);
    EXPECT_EQ(full.point_ids, rch::application::full_scan_query_oracle(points, outside));
}

TEST(ApplicationWindowQuery, RejectsInvalidWindowAndMismatchedDirectory) {
    const auto points = make_original_fixture();
    auto directory = rch::application::build_page_directory(points);
    TemporaryDirectory temporary{};
    const auto path = temporary.file("validation.page");
    rch::application::PageFileWriter::write(path, points, fixture_metadata(0U));
    rch::application::PageFileReader page_file{path};

    const rch::application::QueryWindow reversed{{2.0, 0.0, 0.0}, {1.0, 1.0, 1.0}};
    EXPECT_THROW(
        static_cast<void>(
            rch::application::execute_page_pruned_query(page_file, directory, reversed)
        ),
        std::invalid_argument
    );

    directory.pop_back();
    const rch::application::QueryWindow valid{{0.0, 0.0, 0.0}, {1.0, 1.0, 1.0}};
    EXPECT_THROW(
        static_cast<void>(rch::application::execute_page_pruned_query(page_file, directory, valid)),
        std::invalid_argument
    );
}

} // namespace
