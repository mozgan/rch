// ----------------------------------------------------------------------------
// bench_quantization.cpp - quantization-layer microbenchmark.
//
// Algorithm:
//   - Generate deterministic \(x_i\in[0,1]\).
//   - Measure `quantize_axis` on \(x_i\in[0,1]\) with fixed \(m=12\).
//   - Accumulate codes so the compiler cannot remove the encode loop.
//
// References:
//   Goldberg, What Every Computer Scientist Should Know About Floating-Point
//   Arithmetic, 1991, DOI: 10.1145/103162.103163.
//   IEEE, IEEE Standard for Floating-Point Arithmetic, 2019,
//   DOI: 10.1109/IEEESTD.2019.8766229.
// ----------------------------------------------------------------------------

#include <cstdint>
#include <random>
#include <vector>

#include <benchmark/benchmark.h>

#include "bench_common.hpp"
#include "rch/curves/quantization.hpp"

namespace {

void BM_QuantizeAxis(benchmark::State& state) {
    const auto count = static_cast<std::size_t>(state.range(0));
    std::mt19937_64 rng{0xC0FFEEULL};
    std::uniform_real_distribution<double> dist{0.0, 1.0};
    std::vector<double> samples(count);
    for (auto& v : samples) {
        v = dist(rng);
    }
    constexpr std::uint8_t kBits = 12U;
    for (auto _ : state) {
        std::uint64_t accumulator = 0U;
        for (const double s : samples) {
            accumulator += rch::curves::quantize_axis(s, 0.0, 1.0, kBits);
        }
        benchmark::DoNotOptimize(accumulator);
    }
    state.SetItemsProcessed(rch::benchmarks::processed_items(state, count));
}

BENCHMARK(BM_QuantizeAxis)->Arg(1U << 10U)->Arg(1U << 12U)->Arg(1U << 14U);

} // namespace
