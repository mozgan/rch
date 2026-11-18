#include <array>
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <limits>
#include <span>
#include <string>
#include <vector>

#include "rch/application/page_file.hpp"

#include <gtest/gtest.h>

namespace {

class TemporaryDirectory final {
public:
    TemporaryDirectory() {
        const auto nonce = std::chrono::steady_clock::now().time_since_epoch().count();
        path_ = std::filesystem::temp_directory_path() /
                ("rch_page_file_test_" + std::to_string(nonce));
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

[[nodiscard]] auto fixture_points(const std::size_t count)
    -> std::vector<rch::application::PointRecord> {
    std::vector<rch::application::PointRecord> points;
    points.reserve(count);
    for (std::size_t i = 0U; i < count; ++i) {
        points.push_back({
            UINT64_C(0x0102030405060000) + static_cast<std::uint64_t>(i),
            {static_cast<double>(i) - 2.25,
             7.5 - static_cast<double>(i),
             static_cast<double>(i * 3U) + 0.125},
        });
    }
    return points;
}

[[nodiscard]] auto fixture_metadata() -> rch::application::PageFileMetadata {
    rch::application::PageFileMetadata metadata{};
    metadata.layout_id = 6U;
    metadata.source_checksum[0] = 0xA5U;
    metadata.source_checksum[31] = 0x5AU;
    return metadata;
}

TEST(ApplicationPageFile, RoundTripsIdsAndCoordinatesAcrossFullAndPartialPages) {
    TemporaryDirectory temporary{};
    const auto points = fixture_points(rch::application::kRecordsPerPage + 3U);
    const auto path = temporary.file("roundtrip.page");
    rch::application::PageFileWriter::write(path, points, fixture_metadata());

    rch::application::PageFileReader reader{path};
    ASSERT_EQ(reader.header().record_count, points.size());
    ASSERT_EQ(reader.header().layout_id, 6U);
    EXPECT_EQ(reader.header().source_checksum, fixture_metadata().source_checksum);
    EXPECT_EQ(
        reader.read_page(0U),
        std::vector<rch::application::PointRecord>(
            points.begin(),
            points.begin() + static_cast<std::ptrdiff_t>(rch::application::kRecordsPerPage)
        )
    );
    EXPECT_EQ(
        reader.read_page(1U),
        std::vector<rch::application::PointRecord>(
            points.begin() + static_cast<std::ptrdiff_t>(rch::application::kRecordsPerPage),
            points.end()
        )
    );
    EXPECT_TRUE(reader.verify_payload_checksum());
}

TEST(ApplicationPageFile, EncodesIntegerAndFloatBitsAsLittleEndian) {
    TemporaryDirectory temporary{};
    constexpr rch::application::PointRecord point{
        UINT64_C(0x0123456789ABCDEF),
        {1.0, -2.0, 0.5},
    };
    const auto path = temporary.file("endian.page");
    rch::application::PageFileWriter::write(
        path, std::span<const rch::application::PointRecord>{&point, 1U}, fixture_metadata()
    );

    std::ifstream input(path, std::ios::binary);
    ASSERT_TRUE(input);
    input.seekg(static_cast<std::streamoff>(rch::application::kPageFileHeaderBytes));
    std::array<std::uint8_t, 32> bytes{};
    input.read(reinterpret_cast<char*>(bytes.data()), static_cast<std::streamsize>(bytes.size()));
    ASSERT_EQ(input.gcount(), static_cast<std::streamsize>(bytes.size()));
    constexpr std::array<std::uint8_t, 8> expected_id{
        0xEFU,
        0xCDU,
        0xABU,
        0x89U,
        0x67U,
        0x45U,
        0x23U,
        0x01U,
    };
    EXPECT_TRUE(std::equal(expected_id.begin(), expected_id.end(), bytes.begin()));
    EXPECT_EQ(bytes[14], 0xF0U); // IEEE-754 1.0 has byte 0xF0 before its exponent byte.
    EXPECT_EQ(bytes[15], 0x3FU);
    EXPECT_EQ(bytes[23], 0xC0U); // IEEE-754 -2.0 ends with little-endian byte 0xC0.
    EXPECT_EQ(bytes[31], 0x3FU); // IEEE-754 0.5 ends with little-endian byte 0x3F.
}

TEST(ApplicationPageFile, ZeroPadsUnusedBytesInFinalPage) {
    TemporaryDirectory temporary{};
    const auto points = fixture_points(2U);
    const auto path = temporary.file("padding.page");
    rch::application::PageFileWriter::write(path, points, fixture_metadata());

    std::ifstream input(path, std::ios::binary);
    ASSERT_TRUE(input);
    input.seekg(
        static_cast<std::streamoff>(
            rch::application::kPageFileHeaderBytes +
            points.size() * rch::application::kPointRecordBytes
        )
    );
    std::array<
        std::uint8_t,
        rch::application::kPageFilePageBytes - 2U * rch::application::kPointRecordBytes>
        padding{};
    input.read(
        reinterpret_cast<char*>(padding.data()), static_cast<std::streamsize>(padding.size())
    );
    ASSERT_EQ(input.gcount(), static_cast<std::streamsize>(padding.size()));
    EXPECT_TRUE(std::all_of(padding.begin(), padding.end(), [](const auto value) {
        return value == 0U;
    }));
}

TEST(ApplicationPageFile, DetectsPayloadChecksumMismatch) {
    TemporaryDirectory temporary{};
    const auto points = fixture_points(2U);
    const auto path = temporary.file("checksum.page");
    rch::application::PageFileWriter::write(path, points, fixture_metadata());
    {
        std::fstream file(path, std::ios::binary | std::ios::in | std::ios::out);
        ASSERT_TRUE(file);
        file.seekp(static_cast<std::streamoff>(rch::application::kPageFileHeaderBytes + 3U));
        const char changed = '\x7f';
        file.write(&changed, 1);
    }
    rch::application::PageFileReader reader{path};
    EXPECT_FALSE(reader.verify_payload_checksum());
}

TEST(ApplicationPageFile, RejectsMalformedHeaderAndTruncatedFile) {
    TemporaryDirectory temporary{};
    const auto points = fixture_points(2U);
    const auto bad_header_path = temporary.file("bad-header.page");
    rch::application::PageFileWriter::write(bad_header_path, points, fixture_metadata());
    {
        std::fstream file(bad_header_path, std::ios::binary | std::ios::in | std::ios::out);
        ASSERT_TRUE(file);
        file.seekp(0);
        const char invalid = 'X';
        file.write(&invalid, 1);
    }
    EXPECT_THROW(rch::application::PageFileReader{bad_header_path}, std::runtime_error);

    const auto truncated_path = temporary.file("truncated.page");
    rch::application::PageFileWriter::write(truncated_path, points, fixture_metadata());
    std::filesystem::resize_file(truncated_path, std::filesystem::file_size(truncated_path) - 1U);
    EXPECT_THROW(rch::application::PageFileReader{truncated_path}, std::runtime_error);
}

TEST(ApplicationPageFile, RejectsNonFiniteCoordinatesBeforeCreatingFile) {
    TemporaryDirectory temporary{};
    const auto path = temporary.file("non-finite.page");
    const std::array<rch::application::PointRecord, 1> points{{
        {1U, {0.0, 1.0, std::numeric_limits<double>::infinity()}},
    }};
    EXPECT_THROW(
        rch::application::PageFileWriter::write(path, points, fixture_metadata()),
        std::invalid_argument
    );
    EXPECT_FALSE(std::filesystem::exists(path));
}

TEST(ApplicationPageFile, DirectoryBoundsCoverEveryRecordAndUsePageOffsets) {
    const auto points = fixture_points(rch::application::kRecordsPerPage + 2U);
    const auto directory = rch::application::build_page_directory(points);
    ASSERT_EQ(directory.size(), 2U);
    EXPECT_EQ(directory[0].valid_record_count, rch::application::kRecordsPerPage);
    EXPECT_EQ(directory[1].valid_record_count, 2U);
    EXPECT_EQ(directory[0].byte_offset, rch::application::kPageFileHeaderBytes);
    EXPECT_EQ(
        directory[1].byte_offset,
        rch::application::kPageFileHeaderBytes + rch::application::kPageFilePageBytes
    );

    for (std::size_t page_index = 0U; page_index < directory.size(); ++page_index) {
        const auto& bounds = directory[page_index];
        const auto start = page_index * rch::application::kRecordsPerPage;
        for (std::size_t i = 0U; i < bounds.valid_record_count; ++i) {
            for (std::size_t axis = 0U; axis < 3U; ++axis) {
                EXPECT_LE(bounds.minimum[axis], points[start + i].xyz[axis]);
                EXPECT_GE(bounds.maximum[axis], points[start + i].xyz[axis]);
            }
        }
    }
}

} // namespace
