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
#include <vector>

#include "rch/application/page_file.hpp"

namespace rch::application {

inline constexpr std::size_t kPageDirectoryHeaderBytes = 4096U;
inline constexpr std::size_t kPageDirectoryEntryBytes = 64U;

struct PageDirectoryFile final {
    std::uint64_t record_count{};
    std::vector<PageDirectoryEntry> entries;
};

namespace detail {

inline constexpr std::array<std::uint8_t, 8> kDirectoryMagic{
    'R',
    'C',
    'H',
    'I',
    'D',
    'X',
    '0',
    '1',
};
inline constexpr std::uint32_t kDirectoryVersion = 1U;
inline constexpr std::size_t kDirectoryChecksumOffset = 40U;
inline constexpr std::size_t kDirectoryHeaderUsedBytes = 72U;

[[nodiscard]] inline auto encode_directory_entry(const PageDirectoryEntry& entry)
    -> std::array<std::uint8_t, kPageDirectoryEntryBytes> {
    std::array<std::uint8_t, kPageDirectoryEntryBytes> bytes{};
    const auto output = std::span<std::uint8_t>{bytes};
    for (std::size_t axis = 0U; axis < 3U; ++axis) {
        put_u64_le(output, axis * 8U, std::bit_cast<std::uint64_t>(entry.minimum[axis]));
        put_u64_le(output, 24U + axis * 8U, std::bit_cast<std::uint64_t>(entry.maximum[axis]));
    }
    put_u64_le(output, 48U, entry.byte_offset);
    put_u32_le(output, 56U, entry.valid_record_count);
    return bytes;
}

[[nodiscard]] inline auto
decode_directory_entry(const std::span<const std::uint8_t, kPageDirectoryEntryBytes> bytes)
    -> PageDirectoryEntry {
    PageDirectoryEntry entry{};
    for (std::size_t axis = 0U; axis < 3U; ++axis) {
        entry.minimum[axis] = std::bit_cast<double>(get_u64_le(bytes, axis * 8U));
        entry.maximum[axis] = std::bit_cast<double>(get_u64_le(bytes, 24U + axis * 8U));
    }
    entry.byte_offset = get_u64_le(bytes, 48U);
    entry.valid_record_count = get_u32_le(bytes, 56U);
    if (get_u32_le(bytes, 60U) != 0U) {
        throw std::runtime_error("nonzero reserved page-directory entry bytes");
    }
    return entry;
}

[[nodiscard]] inline auto make_directory_header(
    const std::uint64_t record_count,
    const std::uint64_t page_count,
    const std::array<std::uint8_t, 32>& entries_checksum
) -> std::array<std::uint8_t, kPageDirectoryHeaderBytes> {
    std::array<std::uint8_t, kPageDirectoryHeaderBytes> bytes{};
    std::copy(kDirectoryMagic.begin(), kDirectoryMagic.end(), bytes.begin());
    const auto output = std::span<std::uint8_t>{bytes};
    put_u32_le(output, 8U, kDirectoryVersion);
    put_u32_le(output, 12U, static_cast<std::uint32_t>(kPageDirectoryHeaderBytes));
    put_u32_le(output, 16U, static_cast<std::uint32_t>(kPageDirectoryEntryBytes));
    put_u64_le(output, 24U, record_count);
    put_u64_le(output, 32U, page_count);
    std::copy(
        entries_checksum.begin(),
        entries_checksum.end(),
        bytes.begin() + static_cast<std::ptrdiff_t>(kDirectoryChecksumOffset)
    );
    return bytes;
}

} // namespace detail

class PageDirectoryFileWriter final {
public:
    static void write(
        const std::filesystem::path& path,
        const std::uint64_t record_count,
        const std::span<const PageDirectoryEntry> entries
    ) {
        const auto expected_pages =
            record_count / kRecordsPerPage +
            static_cast<std::uint64_t>(record_count % kRecordsPerPage != 0U);
        if (entries.size() != expected_pages) {
            throw std::invalid_argument("page-directory entry count does not match record count");
        }
        std::ofstream output(path, std::ios::binary | std::ios::trunc);
        if (!output) {
            throw std::runtime_error("cannot create page-directory file: " + path.string());
        }
        std::array<std::uint8_t, kPageDirectoryHeaderBytes> placeholder{};
        output.write(
            reinterpret_cast<const char*>(placeholder.data()),
            static_cast<std::streamsize>(placeholder.size())
        );
        if (!output) {
            throw std::runtime_error("cannot write page-directory header placeholder");
        }

        rch::core::Sha256 entries_hash{};
        for (const auto& entry : entries) {
            const auto bytes = detail::encode_directory_entry(entry);
            output.write(
                reinterpret_cast<const char*>(bytes.data()),
                static_cast<std::streamsize>(bytes.size())
            );
            if (!output) {
                throw std::runtime_error("cannot write page-directory entry");
            }
            entries_hash.update(bytes);
        }
        const auto checksum = entries_hash.finalize();
        const auto header = detail::make_directory_header(
            record_count, static_cast<std::uint64_t>(entries.size()), checksum
        );
        output.seekp(0);
        output.write(
            reinterpret_cast<const char*>(header.data()),
            static_cast<std::streamsize>(header.size())
        );
        output.flush();
        if (!output) {
            throw std::runtime_error("cannot finalize page-directory file");
        }
    }
};

class PageDirectoryFileReader final {
public:
    [[nodiscard]] static auto read(const std::filesystem::path& path) -> PageDirectoryFile {
        std::ifstream input(path, std::ios::binary);
        if (!input) {
            throw std::runtime_error("cannot open page-directory file: " + path.string());
        }
        std::array<std::uint8_t, kPageDirectoryHeaderBytes> header_bytes{};
        input.read(
            reinterpret_cast<char*>(header_bytes.data()),
            static_cast<std::streamsize>(header_bytes.size())
        );
        if (input.gcount() != static_cast<std::streamsize>(header_bytes.size())) {
            throw std::runtime_error("truncated page-directory header");
        }
        const auto header = std::span<const std::uint8_t>{header_bytes};
        if (!std::equal(
                detail::kDirectoryMagic.begin(), detail::kDirectoryMagic.end(), header.begin()
            ) ||
            detail::get_u32_le(header, 8U) != detail::kDirectoryVersion ||
            detail::get_u32_le(header, 12U) != kPageDirectoryHeaderBytes ||
            detail::get_u32_le(header, 16U) != kPageDirectoryEntryBytes ||
            detail::get_u32_le(header, 20U) != 0U ||
            !std::all_of(
                header_bytes.begin() +
                    static_cast<std::ptrdiff_t>(detail::kDirectoryHeaderUsedBytes),
                header_bytes.end(),
                [](const std::uint8_t value) { return value == 0U; }
            )) {
            throw std::runtime_error("invalid page-directory header");
        }

        PageDirectoryFile directory{};
        directory.record_count = detail::get_u64_le(header, 24U);
        const auto page_count = detail::get_u64_le(header, 32U);
        const auto expected_pages =
            directory.record_count / kRecordsPerPage +
            static_cast<std::uint64_t>(directory.record_count % kRecordsPerPage != 0U);
        if (page_count != expected_pages || page_count > std::numeric_limits<std::size_t>::max()) {
            throw std::runtime_error("page-directory page count is invalid");
        }
        const auto max_file_size = std::numeric_limits<std::uintmax_t>::max();
        if (page_count > (max_file_size - kPageDirectoryHeaderBytes) / kPageDirectoryEntryBytes) {
            throw std::runtime_error("page-directory file size overflows addressable file size");
        }
        const auto expected_size =
            static_cast<std::uintmax_t>(kPageDirectoryHeaderBytes) +
            static_cast<std::uintmax_t>(page_count) * kPageDirectoryEntryBytes;
        if (expected_size >
            static_cast<std::uintmax_t>(std::numeric_limits<std::streamoff>::max())) {
            throw std::runtime_error("page-directory size exceeds stream offset range");
        }
        std::error_code error{};
        const auto actual_size = std::filesystem::file_size(path, error);
        if (error || actual_size != expected_size) {
            throw std::runtime_error("page-directory size does not match its header");
        }

        std::array<std::uint8_t, 32> expected_checksum{};
        std::copy_n(
            header_bytes.begin() + static_cast<std::ptrdiff_t>(detail::kDirectoryChecksumOffset),
            expected_checksum.size(),
            expected_checksum.begin()
        );
        rch::core::Sha256 entries_hash{};
        directory.entries.reserve(static_cast<std::size_t>(page_count));
        std::array<std::uint8_t, kPageDirectoryEntryBytes> entry_bytes{};
        for (std::uint64_t page_index = 0U; page_index < page_count; ++page_index) {
            input.read(
                reinterpret_cast<char*>(entry_bytes.data()),
                static_cast<std::streamsize>(entry_bytes.size())
            );
            if (input.gcount() != static_cast<std::streamsize>(entry_bytes.size())) {
                throw std::runtime_error("truncated page-directory entries");
            }
            entries_hash.update(entry_bytes);
            auto entry = detail::decode_directory_entry(entry_bytes);
            const auto first_record = page_index * kRecordsPerPage;
            const auto expected_count = static_cast<std::uint32_t>(
                std::min<std::uint64_t>(kRecordsPerPage, directory.record_count - first_record)
            );
            const auto expected_offset = kPageFileHeaderBytes + page_index * kPageFilePageBytes;
            if (entry.byte_offset != expected_offset ||
                entry.valid_record_count != expected_count) {
                throw std::runtime_error("page-directory entry disagrees with page layout");
            }
            for (std::size_t axis = 0U; axis < 3U; ++axis) {
                if (!std::isfinite(entry.minimum[axis]) || !std::isfinite(entry.maximum[axis]) ||
                    entry.minimum[axis] > entry.maximum[axis]) {
                    throw std::runtime_error("page-directory entry has invalid bounds");
                }
            }
            directory.entries.push_back(entry);
        }
        if (entries_hash.finalize() != expected_checksum) {
            throw std::runtime_error("page-directory checksum mismatch");
        }
        return directory;
    }
};

} // namespace rch::application
