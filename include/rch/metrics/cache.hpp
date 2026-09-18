#pragma once

// ----------------------------------------------------------------------------
// metrics/cache.hpp - cache-counter metric C++ reference.
//
// Algorithm:
//   - Read cache reference and cache miss counters from the caller-provided
//     measurement record.
//   - Return no metric when either counter is unavailable or references are zero.
//   - Otherwise compute \(m = \mathrm{misses}/\mathrm{references}\).
//
// References:
//   - Michael Kerrisk and Linux man-pages contributors, perf_event_open(2),
//     `PERF_COUNT_HW_CACHE_REFERENCES` and `PERF_COUNT_HW_CACHE_MISSES`,
//     <https://man7.org/linux/man-pages/man2/perf_event_open.2.html>.
//   - Linux perf maintainers, perf-stat(1), CSV output and hardware counter
//     examples, <https://manpages.debian.org/perf-stat.1>.
// ----------------------------------------------------------------------------

#include <cstdint>
#include <optional>

namespace rch::metrics {

// Optional hardware cache counters collected by the caller.
struct CacheCounters {
    std::optional<std::uint64_t> cache_references{};
    std::optional<std::uint64_t> cache_misses{};
};

// Computes cache miss ratio when both counters are present and valid.
[[nodiscard]] inline auto cache_miss_rate(const CacheCounters& counters) noexcept
    -> std::optional<double> {
    if (!counters.cache_references.has_value() || !counters.cache_misses.has_value()) {
        return std::nullopt;
    }
    const std::uint64_t refs = *counters.cache_references;
    if (refs == 0U) {
        return std::nullopt;
    }
    return static_cast<double>(*counters.cache_misses) / static_cast<double>(refs);
}

} // namespace rch::metrics
