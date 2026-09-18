#pragma once

// ----------------------------------------------------------------------------
// metrics/timing.hpp - wall-clock sort-time helpers.
//
// Algorithm:
//   - Run the callable \(n\) times with `std::chrono::steady_clock`.
//   - Store elapsed wall-clock samples in seconds.
//   - Select the median sample with `nth_element`, avoiding a full sort.
//   - Return zero for an empty sample set or zero requested repeats.
//
// References:
//   - ISO/IEC, ISO/IEC 14882:2020 Programming languages - C++, 2020.
//   - Google Benchmark project, User Guide: Statistics - Reporting the Mean,
//     Median and Standard Deviation, 2026.
// ----------------------------------------------------------------------------

#include <algorithm>
#include <chrono>
#include <concepts>
#include <cstddef>
#include <ranges>
#include <vector>

namespace rch::metrics {

// Floating-point seconds duration used by timing samples.
using Seconds = std::chrono::duration<double>;

// Restricts timed work to callable objects.
template <typename F>
concept Measurable = std::invocable<F&>;

// Selects the median value from a copy of the input range.
template <std::ranges::random_access_range R>
[[nodiscard]] inline auto sample_median(R range) -> double {
    std::vector<double> values(std::ranges::begin(range), std::ranges::end(range));
    if (values.empty()) {
        return 0.0;
    }
    const std::size_t upper_mid = values.size() / 2U;
    std::ranges::nth_element(values, values.begin() + static_cast<std::ptrdiff_t>(upper_mid));
    const double upper = values[upper_mid];
    if ((values.size() % 2U) == 1U) {
        return upper;
    }
    const auto lower_it = std::ranges::max_element(
        values.begin(), values.begin() + static_cast<std::ptrdiff_t>(upper_mid)
    );
    const double lower = *lower_it;
    return lower + ((upper - lower) / 2.0);
}

// Measures repeated wall-clock samples and returns their median.
template <Measurable F>
[[nodiscard]] inline auto measure_median_seconds(F&& callable, std::size_t repeats = 11U)
    -> double {
    if (repeats == 0U) [[unlikely]] {
        return 0.0;
    }
    std::vector<double> samples;
    samples.reserve(repeats);
    for (std::size_t i = 0U; i < repeats; ++i) {
        const auto start = std::chrono::steady_clock::now();
        callable();
        const auto end = std::chrono::steady_clock::now();
        samples.push_back(Seconds{end - start}.count());
    }
    return sample_median(samples);
}

} // namespace rch::metrics
