#pragma once

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <span>
#include <stdexcept>
#include <vector>

#include "rch/application/page_file.hpp"

namespace rch::application {

struct QueryWindow final {
    std::array<double, 3> minimum{};
    std::array<double, 3> maximum{};
};

struct PageQueryResult final {
    std::vector<std::uint64_t> point_ids;
    std::uint64_t candidate_pages{};
    std::uint64_t pages_read{};
    std::uint64_t records_examined{};
};

namespace detail {

inline void validate_query_window(const QueryWindow& window) {
    for (std::size_t axis = 0U; axis < 3U; ++axis) {
        if (!std::isfinite(window.minimum[axis]) || !std::isfinite(window.maximum[axis]) ||
            window.minimum[axis] > window.maximum[axis]) {
            throw std::invalid_argument("query window bounds must be finite and ordered");
        }
    }
}

[[nodiscard]] inline auto query_contains(const QueryWindow& window, const PointRecord& point)
    -> bool {
    for (std::size_t axis = 0U; axis < 3U; ++axis) {
        if (point.xyz[axis] < window.minimum[axis] || point.xyz[axis] > window.maximum[axis]) {
            return false;
        }
    }
    return true;
}

[[nodiscard]] inline auto
query_intersects(const QueryWindow& window, const PageDirectoryEntry& page) -> bool {
    for (std::size_t axis = 0U; axis < 3U; ++axis) {
        if (window.maximum[axis] < page.minimum[axis] ||
            window.minimum[axis] > page.maximum[axis]) {
            return false;
        }
    }
    return true;
}

inline void validate_page_directory_entry(
    const PageFileHeader& header, const PageDirectoryEntry& page, const std::size_t page_index
) {
    const auto first_record = static_cast<std::uint64_t>(page_index) * kRecordsPerPage;
    const auto expected_count = static_cast<std::uint32_t>(
        std::min<std::uint64_t>(kRecordsPerPage, header.record_count - first_record)
    );
    const auto expected_offset = kPageFileHeaderBytes + page_index * kPageFilePageBytes;
    if (page.byte_offset != expected_offset || page.valid_record_count != expected_count) {
        throw std::invalid_argument("page directory entry does not match page file layout");
    }
    for (std::size_t axis = 0U; axis < 3U; ++axis) {
        if (!std::isfinite(page.minimum[axis]) || !std::isfinite(page.maximum[axis]) ||
            page.minimum[axis] > page.maximum[axis]) {
            throw std::invalid_argument("page directory has invalid bounds");
        }
    }
}

} // namespace detail

[[nodiscard]] inline auto execute_page_pruned_query(
    PageFileReader& page_file,
    const std::span<const PageDirectoryEntry> directory,
    const QueryWindow& window,
    const bool scan_all_pages = false
) -> PageQueryResult {
    detail::validate_query_window(window);
    if (directory.size() != page_file.header().page_count()) {
        throw std::invalid_argument("page directory size does not match page file");
    }

    PageQueryResult result{};
    for (std::size_t page_index = 0U; page_index < directory.size(); ++page_index) {
        const auto& page = directory[page_index];
        detail::validate_page_directory_entry(page_file.header(), page, page_index);
        if (!scan_all_pages && !detail::query_intersects(window, page)) {
            continue;
        }
        ++result.candidate_pages;
        const auto records = page_file.read_page(static_cast<std::uint64_t>(page_index));
        ++result.pages_read;
        if (records.size() != page.valid_record_count) {
            throw std::runtime_error("page record count does not match page directory");
        }
        result.records_examined += records.size();
        for (const auto& point : records) {
            if (detail::query_contains(window, point)) {
                result.point_ids.push_back(point.id);
            }
        }
    }
    std::sort(result.point_ids.begin(), result.point_ids.end());
    return result;
}

// This deliberately scans the original records and does not consult the page directory.
[[nodiscard]] inline auto
full_scan_query_oracle(const std::span<const PointRecord> points, const QueryWindow& window)
    -> std::vector<std::uint64_t> {
    detail::validate_query_window(window);
    std::vector<std::uint64_t> result;
    for (const auto& point : points) {
        if (point.xyz[0] >= window.minimum[0] && point.xyz[0] <= window.maximum[0] &&
            point.xyz[1] >= window.minimum[1] && point.xyz[1] <= window.maximum[1] &&
            point.xyz[2] >= window.minimum[2] && point.xyz[2] <= window.maximum[2]) {
            result.push_back(point.id);
        }
    }
    std::sort(result.begin(), result.end());
    return result;
}

} // namespace rch::application
