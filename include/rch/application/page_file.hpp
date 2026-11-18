#pragma once

#include <algorithm>
#include <array>
#include <bit>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <limits>
#include <span>
#include <stdexcept>
#include <string>
#include <vector>

#include "rch/core/sha256.hpp"

namespace rch::application {

inline constexpr std::size_t kPageFileHeaderBytes = 4096U;
inline constexpr std::size_t kPageFilePageBytes = 4096U;
inline constexpr std::size_t kPointRecordBytes = 32U;
inline constexpr std::size_t kRecordsPerPage = kPageFilePageBytes / kPointRecordBytes;

struct PointRecord final {
    std::uint64_t id{};
    std::array<double, 3> xyz{};

    friend auto operator==(const PointRecord&, const PointRecord&) -> bool = default;
};

struct PageFileMetadata final {
    std::uint64_t layout_id{};
    std::array<std::uint8_t, 32> source_checksum{};
};

struct PageFileHeader final {
    std::uint64_t record_count{};
    std::uint64_t layout_id{};
    std::array<std::uint8_t, 32> source_checksum{};
    std::array<std::uint8_t, 32> payload_checksum{};

    [[nodiscard]] auto page_count() const noexcept -> std::uint64_t {
        return record_count / kRecordsPerPage +
               static_cast<std::uint64_t>(record_count % kRecordsPerPage != 0U);
    }
};

struct PageDirectoryEntry final {
    std::array<double, 3> minimum{};
    std::array<double, 3> maximum{};
    std::uint64_t byte_offset{};
    std::uint32_t valid_record_count{};
};

namespace detail {

inline constexpr std::array<std::uint8_t, 8> kMagic{
    'R',
    'C',
    'H',
    'P',
    'A',
    'G',
    'E',
    '1',
};
inline constexpr std::uint32_t kFormatVersion = 1U;
inline constexpr std::size_t kHeaderChecksumOffset = 72U;
inline constexpr std::size_t kHeaderUsedBytes = 104U;

inline void put_u32_le(std::span<std::uint8_t> out, const std::size_t offset, std::uint32_t value) {
    for (std::size_t i = 0U; i < 4U; ++i) {
        out[offset + i] = static_cast<std::uint8_t>(value & 0xFFU);
        value >>= 8U;
    }
}

inline void put_u64_le(std::span<std::uint8_t> out, const std::size_t offset, std::uint64_t value) {
    for (std::size_t i = 0U; i < 8U; ++i) {
        out[offset + i] = static_cast<std::uint8_t>(value & 0xFFU);
        value >>= 8U;
    }
}

[[nodiscard]] inline auto
get_u32_le(const std::span<const std::uint8_t> in, const std::size_t offset) -> std::uint32_t {
    std::uint32_t value = 0U;
    for (std::size_t i = 0U; i < 4U; ++i) {
        value |= static_cast<std::uint32_t>(in[offset + i]) << (8U * i);
    }
    return value;
}

[[nodiscard]] inline auto
get_u64_le(const std::span<const std::uint8_t> in, const std::size_t offset) -> std::uint64_t {
    std::uint64_t value = 0U;
    for (std::size_t i = 0U; i < 8U; ++i) {
        value |= static_cast<std::uint64_t>(in[offset + i]) << (8U * i);
    }
    return value;
}

inline void encode_record(std::span<std::uint8_t> out, const PointRecord& point) {
    put_u64_le(out, 0U, point.id);
    for (std::size_t axis = 0U; axis < point.xyz.size(); ++axis) {
        put_u64_le(out, 8U + axis * 8U, std::bit_cast<std::uint64_t>(point.xyz[axis]));
    }
}

[[nodiscard]] inline auto decode_record(const std::span<const std::uint8_t> in) -> PointRecord {
    PointRecord point{};
    point.id = get_u64_le(in, 0U);
    for (std::size_t axis = 0U; axis < point.xyz.size(); ++axis) {
        point.xyz[axis] = std::bit_cast<double>(get_u64_le(in, 8U + axis * 8U));
    }
    return point;
}

[[nodiscard]] inline auto make_header_bytes(const PageFileHeader& header)
    -> std::array<std::uint8_t, kPageFileHeaderBytes> {
    std::array<std::uint8_t, kPageFileHeaderBytes> bytes{};
    std::copy(kMagic.begin(), kMagic.end(), bytes.begin());
    const auto view = std::span<std::uint8_t>{bytes};
    put_u32_le(view, 8U, kFormatVersion);
    put_u32_le(view, 12U, static_cast<std::uint32_t>(kPageFileHeaderBytes));
    put_u32_le(view, 16U, static_cast<std::uint32_t>(kPageFilePageBytes));
    put_u32_le(view, 20U, static_cast<std::uint32_t>(kPointRecordBytes));
    put_u64_le(view, 24U, header.record_count);
    put_u64_le(view, 32U, header.layout_id);
    std::copy(header.source_checksum.begin(), header.source_checksum.end(), bytes.begin() + 40);
    std::copy(
        header.payload_checksum.begin(),
        header.payload_checksum.end(),
        bytes.begin() + static_cast<std::ptrdiff_t>(kHeaderChecksumOffset)
    );
    return bytes;
}

[[nodiscard]] inline auto
parse_header(const std::span<const std::uint8_t, kPageFileHeaderBytes> bytes) -> PageFileHeader {
    if (!std::equal(kMagic.begin(), kMagic.end(), bytes.begin())) {
        throw std::runtime_error("invalid page-file magic");
    }
    if (get_u32_le(bytes, 8U) != kFormatVersion || get_u32_le(bytes, 12U) != kPageFileHeaderBytes ||
        get_u32_le(bytes, 16U) != kPageFilePageBytes ||
        get_u32_le(bytes, 20U) != kPointRecordBytes) {
        throw std::runtime_error("unsupported page-file header");
    }
    if (!std::all_of(
            bytes.begin() + static_cast<std::ptrdiff_t>(kHeaderUsedBytes),
            bytes.end(),
            [](const std::uint8_t value) { return value == 0U; }
        )) {
        throw std::runtime_error("nonzero reserved page-file header bytes");
    }

    PageFileHeader header{};
    header.record_count = get_u64_le(bytes, 24U);
    header.layout_id = get_u64_le(bytes, 32U);
    std::copy_n(bytes.begin() + 40, header.source_checksum.size(), header.source_checksum.begin());
    std::copy_n(
        bytes.begin() + static_cast<std::ptrdiff_t>(kHeaderChecksumOffset),
        header.payload_checksum.size(),
        header.payload_checksum.begin()
    );
    return header;
}

} // namespace detail

class PageFileWriter final {
public:
    static void write(
        const std::filesystem::path& path,
        const std::span<const PointRecord> points,
        const PageFileMetadata& metadata
    ) {
        for (const auto& point : points) {
            if (!std::all_of(point.xyz.begin(), point.xyz.end(), [](const double value) {
                    return std::isfinite(value);
                })) {
                throw std::invalid_argument("page-file coordinates must be finite");
            }
        }
        if (points.size() > std::numeric_limits<std::uint64_t>::max()) {
            throw std::length_error("point count does not fit page-file header");
        }

        std::ofstream output(path, std::ios::binary | std::ios::trunc);
        if (!output) {
            throw std::runtime_error("cannot create page file: " + path.string());
        }
        std::array<std::uint8_t, kPageFileHeaderBytes> empty_header{};
        output.write(
            reinterpret_cast<const char*>(empty_header.data()),
            static_cast<std::streamsize>(empty_header.size())
        );
        if (!output) {
            throw std::runtime_error("cannot write page-file header placeholder");
        }

        rch::core::Sha256 payload_hash{};
        std::array<std::uint8_t, kPageFilePageBytes> page{};
        for (std::size_t start = 0U; start < points.size(); start += kRecordsPerPage) {
            page.fill(0U);
            const auto valid_count = std::min(kRecordsPerPage, points.size() - start);
            for (std::size_t i = 0U; i < valid_count; ++i) {
                detail::encode_record(
                    std::span<std::uint8_t>{page}.subspan(i * kPointRecordBytes, kPointRecordBytes),
                    points[start + i]
                );
            }
            payload_hash.update(page);
            output.write(
                reinterpret_cast<const char*>(page.data()),
                static_cast<std::streamsize>(page.size())
            );
            if (!output) {
                throw std::runtime_error("cannot write page-file data page");
            }
        }

        PageFileHeader header{};
        header.record_count = static_cast<std::uint64_t>(points.size());
        header.layout_id = metadata.layout_id;
        header.source_checksum = metadata.source_checksum;
        header.payload_checksum = payload_hash.finalize();
        const auto bytes = detail::make_header_bytes(header);
        output.seekp(0);
        output.write(
            reinterpret_cast<const char*>(bytes.data()), static_cast<std::streamsize>(bytes.size())
        );
        output.flush();
        if (!output) {
            throw std::runtime_error("cannot finalize page-file header");
        }
    }
};

class PageFileReader final {
public:
    explicit PageFileReader(const std::filesystem::path& path) : input_(path, std::ios::binary) {
        if (!input_) {
            throw std::runtime_error("cannot open page file: " + path.string());
        }
        std::array<std::uint8_t, kPageFileHeaderBytes> bytes{};
        input_.read(
            reinterpret_cast<char*>(bytes.data()), static_cast<std::streamsize>(bytes.size())
        );
        if (input_.gcount() != static_cast<std::streamsize>(bytes.size())) {
            throw std::runtime_error("truncated page-file header");
        }
        header_ = detail::parse_header(bytes);
        const auto page_count = static_cast<std::uintmax_t>(header_.page_count());
        constexpr auto max_size = std::numeric_limits<std::uintmax_t>::max();
        if (page_count > (max_size - kPageFileHeaderBytes) / kPageFilePageBytes) {
            throw std::runtime_error("page-file size overflows addressable file size");
        }
        const auto expected_size =
            static_cast<std::uintmax_t>(kPageFileHeaderBytes) + page_count * kPageFilePageBytes;
        if (expected_size >
            static_cast<std::uintmax_t>(std::numeric_limits<std::streamoff>::max())) {
            throw std::runtime_error("page-file size exceeds stream offset range");
        }
        std::error_code error{};
        const auto actual_size = std::filesystem::file_size(path, error);
        if (error || actual_size != expected_size) {
            throw std::runtime_error("page-file size does not match its header");
        }
    }

    [[nodiscard]] auto header() const noexcept -> const PageFileHeader& {
        return header_;
    }

    [[nodiscard]] auto read_page(const std::uint64_t page_index) -> std::vector<PointRecord> {
        if (page_index >= header_.page_count()) {
            throw std::out_of_range("page index is outside page file");
        }
        const auto offset = static_cast<std::streamoff>(kPageFileHeaderBytes) +
                            static_cast<std::streamoff>(page_index * kPageFilePageBytes);
        input_.clear();
        input_.seekg(offset);
        std::array<std::uint8_t, kPageFilePageBytes> bytes{};
        input_.read(
            reinterpret_cast<char*>(bytes.data()), static_cast<std::streamsize>(bytes.size())
        );
        if (input_.gcount() != static_cast<std::streamsize>(bytes.size())) {
            throw std::runtime_error("truncated page-file data page");
        }

        const auto first_record = page_index * kRecordsPerPage;
        const auto valid_count = static_cast<std::size_t>(
            std::min<std::uint64_t>(kRecordsPerPage, header_.record_count - first_record)
        );
        std::vector<PointRecord> result;
        result.reserve(valid_count);
        for (std::size_t i = 0U; i < valid_count; ++i) {
            result.push_back(
                detail::decode_record(
                    std::span<const std::uint8_t>{bytes}.subspan(
                        i * kPointRecordBytes, kPointRecordBytes
                    )
                )
            );
        }
        if (!std::all_of(
                bytes.begin() + static_cast<std::ptrdiff_t>(valid_count * kPointRecordBytes),
                bytes.end(),
                [](const std::uint8_t value) { return value == 0U; }
            )) {
            throw std::runtime_error("nonzero page padding");
        }
        return result;
    }

    [[nodiscard]] auto verify_payload_checksum() -> bool {
        rch::core::Sha256 payload_hash{};
        std::array<std::uint8_t, kPageFilePageBytes> bytes{};
        input_.clear();
        input_.seekg(static_cast<std::streamoff>(kPageFileHeaderBytes));
        for (std::uint64_t page_index = 0U; page_index < header_.page_count(); ++page_index) {
            input_.read(
                reinterpret_cast<char*>(bytes.data()), static_cast<std::streamsize>(bytes.size())
            );
            if (input_.gcount() != static_cast<std::streamsize>(bytes.size())) {
                throw std::runtime_error("truncated page-file while verifying checksum");
            }
            payload_hash.update(bytes);
        }
        return payload_hash.finalize() == header_.payload_checksum;
    }

private:
    std::ifstream input_;
    PageFileHeader header_{};
};

[[nodiscard]] inline auto build_page_directory(const std::span<const PointRecord> points)
    -> std::vector<PageDirectoryEntry> {
    std::vector<PageDirectoryEntry> entries;
    const auto page_count = points.size() / kRecordsPerPage +
                            static_cast<std::size_t>(points.size() % kRecordsPerPage != 0U);
    entries.reserve(page_count);
    for (std::size_t start = 0U; start < points.size(); start += kRecordsPerPage) {
        const auto valid_count = std::min(kRecordsPerPage, points.size() - start);
        PageDirectoryEntry entry{};
        entry.minimum = points[start].xyz;
        entry.maximum = points[start].xyz;
        if (!std::all_of(entry.minimum.begin(), entry.minimum.end(), [](const double value) {
                return std::isfinite(value);
            })) {
            throw std::invalid_argument("page-directory coordinates must be finite");
        }
        entry.byte_offset = kPageFileHeaderBytes + entries.size() * kPageFilePageBytes;
        entry.valid_record_count = static_cast<std::uint32_t>(valid_count);
        for (std::size_t i = 1U; i < valid_count; ++i) {
            if (!std::all_of(
                    points[start + i].xyz.begin(),
                    points[start + i].xyz.end(),
                    [](const double value) { return std::isfinite(value); }
                )) {
                throw std::invalid_argument("page-directory coordinates must be finite");
            }
            for (std::size_t axis = 0U; axis < 3U; ++axis) {
                entry.minimum[axis] = std::min(entry.minimum[axis], points[start + i].xyz[axis]);
                entry.maximum[axis] = std::max(entry.maximum[axis], points[start + i].xyz[axis]);
            }
        }
        entries.push_back(entry);
    }
    return entries;
}

} // namespace rch::application
