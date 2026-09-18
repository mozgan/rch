// ----------------------------------------------------------------------------
// bench_sort.cpp - key/index sort microbenchmarks.
//
// Algorithm:
//   - Generate deterministic \((key,index)\) pairs.
//   - Restore the unsorted input outside the timed region.
//   - Measure `std::ranges::sort` and `std::stable_sort` over the same pairs.
//
// References:
//   ISO/IEC, Programming Languages - C++, 2020.
//   Musser, Introspective Sorting and Selection Algorithms, 1997,
//   DOI: 10.1002/(SICI)1097-024X(199708)27:8<983::AID-SPE117>3.0.CO;2-%23.
// ----------------------------------------------------------------------------

#include <algorithm>
#include <cstdint>
#include <random>
#include <utility>
#include <vector>

#include <benchmark/benchmark.h>

#include "bench_common.hpp"

namespace {

using KeyIndexPair = std::pair<std::uint64_t, std::uint64_t>;

// Generate reproducible \((key,index)\) pairs with independent random keys.
[[nodiscard]] auto generate_pairs(const std::size_t count) -> std::vector<KeyIndexPair> {
    std::mt19937_64 rng{0xA5A5'5A5A'A5A5'5A5AULL};
    std::vector<KeyIndexPair> out(count);
    for (std::size_t i = 0; i < count; ++i) {
        out[i] = {rng(), static_cast<std::uint64_t>(i)};
    }
    return out;
}

void BM_RangesSortKeyIndex(benchmark::State& state) {
    const auto count = static_cast<std::size_t>(state.range(0));
    const auto original = generate_pairs(count);
    std::vector<KeyIndexPair> working;
    working.reserve(count);
    for (auto _ : state) {
        state.PauseTiming();
        working = original;
        state.ResumeTiming();
        std::ranges::sort(working);
        benchmark::DoNotOptimize(working.data());
    }
    state.SetItemsProcessed(rch::benchmarks::processed_items(state, count));
}

void BM_StableSortKeyIndex(benchmark::State& state) {
    const auto count = static_cast<std::size_t>(state.range(0));
    const auto original = generate_pairs(count);
    std::vector<KeyIndexPair> working;
    working.reserve(count);
    for (auto _ : state) {
        state.PauseTiming();
        working = original;
        state.ResumeTiming();
        std::stable_sort(working.begin(), working.end());
        benchmark::DoNotOptimize(working.data());
    }
    state.SetItemsProcessed(rch::benchmarks::processed_items(state, count));
}

BENCHMARK(BM_RangesSortKeyIndex)->Arg(1U << 10U)->Arg(1U << 14U)->Arg(1U << 18U);
BENCHMARK(BM_StableSortKeyIndex)->Arg(1U << 10U)->Arg(1U << 14U)->Arg(1U << 18U);

} // namespace
