#include <array>
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <limits>
#include <string>
#include <vector>

#include "rch/application/page_directory.hpp"

#include <gtest/gtest.h>

namespace {

class TemporaryDirectory final {
public:
    TemporaryDirectory() {
        const auto nonce = std::chrono::steady_clock::now().time_since_epoch().count();
        path_ = std::filesystem::temp_directory_path() /
                ("rch_page_directory_test_" + std::to_string(nonce));
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

[[nodiscard]] auto fixture_entries() -> std::vector<rch::application::PageDirectoryEntry> {
    std::vector<rch::application::PageDirectoryEntry> entries(2U);
    entries[0] = {{-1.0, -2.0, -3.0}, {4.0, 5.0, 6.0}, 4096U, 128U};
    entries[1] = {{0.0, 1.0, 2.0}, {7.0, 8.0, 9.0}, 8192U, 2U};
    return entries;
}

TEST(ApplicationPageDirectory, RoundTripsBoundsOffsetsAndValidCounts) {
    TemporaryDirectory temporary{};
    const auto path = temporary.file("directory.index");
    const auto entries = fixture_entries();
    rch::application::PageDirectoryFileWriter::write(path, 130U, entries);

    const auto loaded = rch::application::PageDirectoryFileReader::read(path);
    ASSERT_EQ(loaded.record_count, 130U);
    ASSERT_EQ(loaded.entries.size(), entries.size());
    for (std::size_t i = 0U; i < entries.size(); ++i) {
        EXPECT_EQ(loaded.entries[i].minimum, entries[i].minimum);
        EXPECT_EQ(loaded.entries[i].maximum, entries[i].maximum);
        EXPECT_EQ(loaded.entries[i].byte_offset, entries[i].byte_offset);
        EXPECT_EQ(loaded.entries[i].valid_record_count, entries[i].valid_record_count);
    }
    EXPECT_EQ(
        std::filesystem::file_size(path),
        rch::application::kPageDirectoryHeaderBytes +
            entries.size() * rch::application::kPageDirectoryEntryBytes
    );
}

TEST(ApplicationPageDirectory, RejectsEntryCountThatDoesNotMatchRecordCount) {
    TemporaryDirectory temporary{};
    const auto path = temporary.file("wrong-count.index");
    const auto entries = fixture_entries();
    EXPECT_THROW(
        rch::application::PageDirectoryFileWriter::write(path, 128U, entries), std::invalid_argument
    );
    EXPECT_FALSE(std::filesystem::exists(path));
}

TEST(ApplicationPageDirectory, DetectsChecksumMismatchAndTruncation) {
    TemporaryDirectory temporary{};
    const auto entries = fixture_entries();
    const auto corrupt_path = temporary.file("corrupt.index");
    rch::application::PageDirectoryFileWriter::write(corrupt_path, 130U, entries);
    {
        std::fstream file(corrupt_path, std::ios::binary | std::ios::in | std::ios::out);
        ASSERT_TRUE(file);
        file.seekp(static_cast<std::streamoff>(rch::application::kPageDirectoryHeaderBytes + 7U));
        const char changed = '\x55';
        file.write(&changed, 1);
    }
    EXPECT_THROW(
        static_cast<void>(rch::application::PageDirectoryFileReader::read(corrupt_path)),
        std::runtime_error
    );

    const auto truncated_path = temporary.file("truncated.index");
    rch::application::PageDirectoryFileWriter::write(truncated_path, 130U, entries);
    std::filesystem::resize_file(truncated_path, std::filesystem::file_size(truncated_path) - 1U);
    EXPECT_THROW(
        static_cast<void>(rch::application::PageDirectoryFileReader::read(truncated_path)),
        std::runtime_error
    );
}

} // namespace
