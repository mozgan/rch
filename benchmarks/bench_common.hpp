#pragma once

// ----------------------------------------------------------------------------
// bench_common.hpp - shared Google Benchmark accounting helpers.
//
// Algorithm:
//   - Convert `state.iterations()` and a per-iteration item count into
//     `SetItemsProcessed`'s signed counter.
//
// References:
//   - Google, Google Benchmark User Guide.
// ----------------------------------------------------------------------------

#include <benchmark/benchmark.h>

#include <cstddef>
#include <cstdint>
#include <limits>

namespace rch::benchmarks {

// Return a signed Google Benchmark counter value, saturating instead of wrapping.
[[nodiscard]] inline auto
processed_items_total(const std::uint64_t iterations, const std::size_t item_count) noexcept
    -> std::int64_t {
    constexpr auto kMaxCounter = std::numeric_limits<std::int64_t>::max();
    if (iterations == 0U || item_count == 0U) {
        return 0;
    }
    if (item_count > static_cast<std::size_t>(kMaxCounter)) {
        return kMaxCounter;
    }
    const auto items = static_cast<std::uint64_t>(item_count);
    if (iterations > static_cast<std::uint64_t>(kMaxCounter) / items) {
        return kMaxCounter;
    }
    return static_cast<std::int64_t>(iterations * items);
}

[[nodiscard]] inline auto processed_items(
    const benchmark::State& state, const std::size_t item_count
) noexcept -> std::int64_t {
    const auto iterations = state.iterations();
    if (iterations <= 0) {
        return 0;
    }
    return processed_items_total(static_cast<std::uint64_t>(iterations), item_count);
}

} // namespace rch::benchmarks
