#pragma once

// ----------------------------------------------------------------------------
// metrics/memory.hpp - peak resident-set-size helper for Linux `/proc`.
//
// Algorithm:
//   - Open `/proc/self/status`, the current process status record.
//   - Select `VmHWM:` for resident high-water mark or `VmPeak:` for virtual
//     memory peak.
//   - Scan lines until the marker is found, skip non-digits, then parse the
//     numeric kilobyte value with `std::from_chars`.
//   - Return `std::nullopt` when the file, marker, or numeric parse is missing.
//
// References:
//   - Michael Kerrisk and Linux man-pages contributors, proc_pid_status(5) -
//     Linux manual page, `VmHWM` and `VmPeak`,
//     <https://www.man7.org/linux/man-pages/man5/proc_pid_status.5.html>.
//   - ISO/IEC, ISO/IEC 14882:2020 Programming languages - C++, 2020.
// ----------------------------------------------------------------------------

#include <cctype>
#include <charconv>
#include <cstdint>
#include <fstream>
#include <optional>
#include <string>
#include <string_view>
#include <system_error>

namespace rch::metrics {

// Selects the Linux `/proc/self/status` peak memory field to read.
enum class PeakRssField : std::uint8_t {
    VmHighWaterMark, // resident peak (Linux VmHWM)
    VmPeak,          // virtual peak (Linux VmPeak)
};

namespace detail {

[[nodiscard]] inline constexpr auto peak_rss_marker(const PeakRssField field) noexcept
    -> std::string_view {
    return (field == PeakRssField::VmHighWaterMark) ? "VmHWM:" : "VmPeak:";
}

[[nodiscard]] inline auto
parse_peak_rss_kb_line(const std::string_view line, const PeakRssField field)
    -> std::optional<std::uint64_t> {
    const std::string_view marker = peak_rss_marker(field);
    if (line.size() < marker.size() || line.substr(0, marker.size()) != marker) {
        return std::nullopt;
    }
    std::size_t pos = marker.size();
    while (pos < line.size() && std::isspace(static_cast<unsigned char>(line[pos]))) {
        ++pos;
    }
    if (pos == line.size() || !std::isdigit(static_cast<unsigned char>(line[pos]))) {
        return std::nullopt;
    }
    std::uint64_t value = 0;
    const auto* begin = line.data() + pos;
    const auto* end = line.data() + line.size();
    const auto result = std::from_chars(begin, end, value);
    if (result.ec == std::errc{}) {
        return value;
    }
    return std::nullopt;
}

} // namespace detail

// Reads the selected peak memory field as kilobytes.
[[nodiscard]] inline auto read_peak_rss_kb(PeakRssField field = PeakRssField::VmHighWaterMark)
    -> std::optional<std::uint64_t> {
    std::ifstream input{"/proc/self/status"};
    if (!input.is_open()) {
        return std::nullopt;
    }
    const std::string_view marker = detail::peak_rss_marker(field);
    std::string line;
    while (std::getline(input, line)) {
        if (line.size() < marker.size() ||
            std::string_view{line}.substr(0, marker.size()) != marker) {
            continue;
        }
        // Format: "VmHWM:\t   1234 kB"; parse the numeric kilobyte value.
        return detail::parse_peak_rss_kb_line(std::string_view{line}, field);
    }
    return std::nullopt;
}

} // namespace rch::metrics
