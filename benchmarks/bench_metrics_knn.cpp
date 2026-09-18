// ----------------------------------------------------------------------------
// bench_metrics_knn.cpp - locality-metric microbenchmarks.
//
// Algorithm:
//   - Generate deterministic Gaussian points and identity order \(o_i=i\).
//   - Measure sort-window recall@\(k\) with window radius \(w\).
//   - Measure pairwise \(L_1\) worst-case and \(L_2\) best-case locality over
//     the same identity order.
//
// References:
//   Gotsman and Lindenbaum, On the metric properties of discrete
//   space-filling curves, 1996, DOI: 10.1109/83.499920.
//   Friedman, Bentley and Finkel, An Algorithm for Finding Best Matches in
//   Logarithmic Expected Time, 1977, DOI: 10.1145/361002.361007.
// ----------------------------------------------------------------------------

#include <cstddef>
#include <cstdint>
#include <numeric>
#include <random>
#include <span>
#include <vector>

#include <benchmark/benchmark.h>

#include "bench_common.hpp"
#include "rch/core/matrix3.hpp"
#include "rch/metrics/summary.hpp"

namespace {

// Generate deterministic 3D Gaussian points for metric workloads.
[[nodiscard]] auto generate_points(const std::size_t count)
    -> std::vector<rch::core::Vec3<double>> {
    std::mt19937_64 rng{0xC0DEC0DEC0DEULL};
    std::normal_distribution<double> dist{0.0, 1.0};
    std::vector<rch::core::Vec3<double>> out(count);
    for (auto& p : out) {
        p = {dist(rng), dist(rng), dist(rng)};
    }
    return out;
}

[[nodiscard]] auto identity_order(const std::size_t count) -> std::vector<std::size_t> {
    std::vector<std::size_t> order(count);
    std::iota(order.begin(), order.end(), std::size_t{0U});
    return order;
}

void BM_RecallAtKWindow(benchmark::State& state) {
    const auto count = static_cast<std::size_t>(state.range(0));
    const auto k = static_cast<std::size_t>(state.range(1));
    const auto window = static_cast<std::size_t>(state.range(2));
    const auto points = generate_points(count);
    const auto order = identity_order(count);
    for (auto _ : state) {
        double recall = rch::metrics::recall_at_k_window<std::size_t>(
            std::span<const rch::core::Vec3<double>>{points},
            std::span<const std::size_t>{order},
            k,
            window
        );
        benchmark::DoNotOptimize(recall);
    }
    state.SetItemsProcessed(rch::benchmarks::processed_items(state, count));
}

BENCHMARK(BM_RecallAtKWindow)
    ->Args({1U << 9U, 8U, 64U})
    ->Args({1U << 10U, 8U, 64U})
    ->Args({1U << 10U, 16U, 128U})
    ->Args({1U << 11U, 16U, 128U})
    ->Args({1U << 11U, 32U, 256U});

void BM_L1Locality(benchmark::State& state) {
    const auto count = static_cast<std::size_t>(state.range(0));
    const auto points = generate_points(count);
    const auto order = identity_order(count);
    for (auto _ : state) {
        auto value = rch::metrics::l1_locality<std::size_t>(
            std::span<const rch::core::Vec3<double>>{points},
            std::span<const std::size_t>{order}
        );
        benchmark::DoNotOptimize(value);
    }
    state.SetItemsProcessed(rch::benchmarks::processed_items(state, count));
}

void BM_L2Locality(benchmark::State& state) {
    const auto count = static_cast<std::size_t>(state.range(0));
    const auto points = generate_points(count);
    const auto order = identity_order(count);
    for (auto _ : state) {
        auto value = rch::metrics::l2_locality<std::size_t>(
            std::span<const rch::core::Vec3<double>>{points},
            std::span<const std::size_t>{order}
        );
        benchmark::DoNotOptimize(value);
    }
    state.SetItemsProcessed(rch::benchmarks::processed_items(state, count));
}

BENCHMARK(BM_L1Locality)->Arg(1U << 10U)->Arg(1U << 12U)->Arg(1U << 14U);
BENCHMARK(BM_L2Locality)->Arg(1U << 10U)->Arg(1U << 12U)->Arg(1U << 14U);

} // namespace
