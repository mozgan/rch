// ----------------------------------------------------------------------------
// bench_ordering.cpp - ordering-facade microbenchmarks.
//
// Algorithm:
//   - Generate deterministic row-major Gaussian point clouds.
//   - Measure `order_point_cloud` for Morton, isotropic Hilbert, and RCH.
//   - Treat any failed ordering as a benchmark configuration error.
//
// References:
//   Hilbert, Ueber die stetige Abbildung einer Linie auf ein Flaechenstueck,
//   1891, DOI: 10.1007/BF01199431.
//   Moon, Jagadish, Faloutsos and Saltz, Analysis of the Clustering Properties
//   of the Hilbert Space-Filling Curve, 2001, DOI: 10.1109/69.908985.
//   Hubert, Rousseeuw and Verdonck, A Deterministic Algorithm for Robust
//   Location and Scatter, 2012, DOI: 10.1080/10618600.2012.672100.
// ----------------------------------------------------------------------------

#include <cstdint>
#include <cstdlib>
#include <random>
#include <span>
#include <vector>

#include <benchmark/benchmark.h>

#include "bench_common.hpp"
#include "rch/orderings/orderer.hpp"

namespace {

// Generate row-major \(x,y,z\) samples consumed by the ordering facade.
[[nodiscard]] auto generate_gaussian_cloud(const std::size_t count) -> std::vector<double> {
    std::mt19937_64 rng{0xB16'B005'B16'B005ULL};
    std::normal_distribution<double> dist{0.0, 1.0};
    std::vector<double> out;
    out.reserve(3U * count);
    for (std::size_t i = 0; i < count; ++i) {
        out.push_back(dist(rng));
        out.push_back(dist(rng));
        out.push_back(dist(rng));
    }
    return out;
}

void run_method(benchmark::State& state, const rch::orderings::OrderingMethod method) {
    const auto count = static_cast<std::size_t>(state.range(0));
    const auto points = generate_gaussian_cloud(count);
    rch::orderings::OrderingConfig config{};
    config.method = method;
    for (auto _ : state) {
        const auto result =
            rch::orderings::order_point_cloud(std::span<const double>{points}, config);
        if (!result.has_value()) [[unlikely]] {
            state.SkipWithError("order_point_cloud failed");
            return;
        }
        benchmark::DoNotOptimize(result->permutation.data());
    }
    state.SetItemsProcessed(rch::benchmarks::processed_items(state, count));
}

void BM_OrderMorton(benchmark::State& state) {
    run_method(state, rch::orderings::OrderingMethod::Morton);
}

void BM_OrderIsotropicHilbert(benchmark::State& state) {
    run_method(state, rch::orderings::OrderingMethod::IsotropicHilbert);
}

void BM_OrderRCH(benchmark::State& state) {
    run_method(state, rch::orderings::OrderingMethod::RCH);
}

BENCHMARK(BM_OrderMorton)->Arg(1U << 10U)->Arg(1U << 14U)->Arg(1U << 16U);
BENCHMARK(BM_OrderIsotropicHilbert)->Arg(1U << 10U)->Arg(1U << 14U)->Arg(1U << 16U);
BENCHMARK(BM_OrderRCH)->Arg(1U << 10U)->Arg(1U << 14U)->Arg(1U << 16U);

} // namespace
