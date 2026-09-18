// ----------------------------------------------------------------------------
// bench_detmcd.cpp - deterministic MCD microbenchmarks.
//
// Algorithm:
//   - Generate deterministic Gaussian inliers plus separated uniform outliers.
//   - Measure `det_mcd` with \(\alpha=0.5\) and \(\alpha=0.75\).
//   - Consume determinant/iteration diagnostics to retain the robust fit.
//
// References:
//   Rousseeuw and Van Driessen, A Fast Algorithm for the Minimum Covariance
//   Determinant Estimator, 1999, DOI: 10.1080/00401706.1999.10485670.
//   Hubert, Rousseeuw and Verdonck, A Deterministic Algorithm for Robust
//   Location and Scatter, 2012, DOI: 10.1080/10618600.2012.672100.
// ----------------------------------------------------------------------------

#include <cstddef>
#include <cstdint>
#include <random>
#include <span>
#include <vector>

#include <benchmark/benchmark.h>

#include "bench_common.hpp"
#include "rch/core/matrix3.hpp"
#include "rch/robust/det_mcd.hpp"

namespace {

// Generate a fixed mixture used to exercise robust outlier handling.
[[nodiscard]] auto generate_contaminated_cloud(
    const std::size_t count, const double outlier_fraction
) -> std::vector<rch::core::Vec3<double>> {
    std::mt19937_64 rng{0xDE7'C0DE'BABEULL};
    std::normal_distribution<double> inlier{0.0, 1.0};
    std::uniform_real_distribution<double> outlier{8.0, 12.0};
    std::uniform_real_distribution<double> coin{0.0, 1.0};
    std::vector<rch::core::Vec3<double>> out(count);
    for (auto& p : out) {
        if (coin(rng) < outlier_fraction) {
            p = {outlier(rng), outlier(rng), outlier(rng)};
        } else {
            p = {inlier(rng), inlier(rng), inlier(rng)};
        }
    }
    return out;
}

void BM_DetMcd(benchmark::State& state) {
    const auto count = static_cast<std::size_t>(state.range(0));
    const auto points = generate_contaminated_cloud(count, 0.10);
    const rch::robust::DetMcdOptions options{};
    for (auto _ : state) {
        const auto result =
            rch::robust::det_mcd(std::span<const rch::core::Vec3<double>>{points}, options);
        auto determinant = result.determinant;
        auto cstep_iterations = result.cstep_iterations;
        benchmark::DoNotOptimize(determinant);
        benchmark::DoNotOptimize(cstep_iterations);
    }
    state.SetItemsProcessed(rch::benchmarks::processed_items(state, count));
}

void BM_DetMcdAlphaHigh(benchmark::State& state) {
    const auto count = static_cast<std::size_t>(state.range(0));
    const auto points = generate_contaminated_cloud(count, 0.05);
    rch::robust::DetMcdOptions options{};
    options.alpha = 0.75;
    for (auto _ : state) {
        const auto result =
            rch::robust::det_mcd(std::span<const rch::core::Vec3<double>>{points}, options);
        auto determinant = result.determinant;
        benchmark::DoNotOptimize(determinant);
    }
    state.SetItemsProcessed(rch::benchmarks::processed_items(state, count));
}

BENCHMARK(BM_DetMcd)->Arg(64U)->Arg(256U)->Arg(1024U)->Arg(4096U);
BENCHMARK(BM_DetMcdAlphaHigh)->Arg(64U)->Arg(256U)->Arg(1024U);

} // namespace
