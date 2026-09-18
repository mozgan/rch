// ----------------------------------------------------------------------------
// bench_sfc_keygen.cpp - SFC encoder microbenchmarks.
//
// Algorithm:
//   - Generate deterministic integer grid points.
//   - Measure standard Hilbert, compact Hilbert, and Morton key encoders.
//   - Abort if an encoder rejects the configured bit budget.
//
// References:
//   Hilbert, Ueber die stetige Abbildung einer Linie auf ein Flaechenstueck,
//   1891, DOI: 10.1007/BF01199431.
//   Butz, Alternative Algorithm for Hilbert's Space-Filling Curve, 1971,
//   DOI: 10.1109/T-C.1971.223258.
//   Hamilton and Rau-Chaplin, Compact Hilbert Indices, 2008,
//   DOI: 10.1016/j.ipl.2008.05.017.
// ----------------------------------------------------------------------------

#include <array>
#include <cstdlib>
#include <cstdint>
#include <limits>
#include <optional>
#include <random>
#include <vector>

#include <benchmark/benchmark.h>

#include "bench_common.hpp"
#include "rch/curves/hilbert3_compact.hpp"
#include "rch/curves/hilbert3_standard.hpp"
#include "rch/curves/morton3.hpp"

namespace {

constexpr std::uint8_t kEqualBits = 10U;
constexpr rch::curves::BitsAxis3 kMixedBits{12U, 10U, 8U};

// Treat a rejected key as a benchmark configuration error.
[[nodiscard]] auto require_key(const std::optional<std::uint64_t> key) -> std::uint64_t {
    if (!key.has_value()) {
        std::abort();
    }
    return *key;
}

// Generate points in an equal-depth \(2^m\times2^m\times2^m\) grid.
[[nodiscard]] auto generate_points(std::size_t count, std::uint8_t bits)
    -> std::vector<rch::curves::Point3u32> {
    std::mt19937_64 rng{0xBEEFULL};
    const auto max = (bits == 32U) ? std::numeric_limits<std::uint32_t>::max()
                                    : ((1U << bits) - 1U);
    std::uniform_int_distribution<std::uint32_t> dist{0U, max};
    std::vector<rch::curves::Point3u32> out(count);
    for (auto& p : out) {
        p = {dist(rng), dist(rng), dist(rng)};
    }
    return out;
}

// Generate points in a compact axiswise grid with bit depths \((m_x,m_y,m_z)\).
[[nodiscard]] auto generate_points_axiswise(std::size_t count, rch::curves::BitsAxis3 bits)
    -> std::vector<rch::curves::Point3u32> {
    std::mt19937_64 rng{0xBEEFULL};
    const auto axis_max = [](const std::uint8_t b) noexcept -> std::uint32_t {
        return (b >= 32U) ? std::numeric_limits<std::uint32_t>::max()
                          : ((std::uint32_t{1U} << b) - 1U);
    };
    std::uniform_int_distribution<std::uint32_t> dx{0U, axis_max(bits[0])};
    std::uniform_int_distribution<std::uint32_t> dy{0U, axis_max(bits[1])};
    std::uniform_int_distribution<std::uint32_t> dz{0U, axis_max(bits[2])};
    std::vector<rch::curves::Point3u32> out(count);
    for (auto& p : out) {
        p = {dx(rng), dy(rng), dz(rng)};
    }
    return out;
}

void BM_HilbertStandardEncode(benchmark::State& state) {
    const auto count = static_cast<std::size_t>(state.range(0));
    const auto points = generate_points(count, kEqualBits);
    for (auto _ : state) {
        std::uint64_t accumulator = 0U;
        for (const auto& p : points) {
            accumulator += require_key(rch::curves::hilbert3_standard_encode(p, kEqualBits));
        }
        benchmark::DoNotOptimize(accumulator);
    }
    state.SetItemsProcessed(rch::benchmarks::processed_items(state, count));
}

void BM_HilbertCompactEncode(benchmark::State& state) {
    const auto count = static_cast<std::size_t>(state.range(0));
    const auto points = generate_points_axiswise(count, kMixedBits);
    for (auto _ : state) {
        std::uint64_t accumulator = 0U;
        for (const auto& p : points) {
            accumulator += require_key(rch::curves::hilbert3_compact_encode(p, kMixedBits));
        }
        benchmark::DoNotOptimize(accumulator);
    }
    state.SetItemsProcessed(rch::benchmarks::processed_items(state, count));
}

void BM_MortonEncode(benchmark::State& state) {
    const auto count = static_cast<std::size_t>(state.range(0));
    const auto points = generate_points(count, kEqualBits);
    for (auto _ : state) {
        std::uint64_t accumulator = 0U;
        for (const auto& p : points) {
            accumulator += require_key(rch::curves::morton3_encode(
                std::array<std::uint32_t, 3>{p[0], p[1], p[2]}, kEqualBits));
        }
        benchmark::DoNotOptimize(accumulator);
    }
    state.SetItemsProcessed(rch::benchmarks::processed_items(state, count));
}

BENCHMARK(BM_HilbertStandardEncode)->Arg(1U << 10U)->Arg(1U << 12U);
BENCHMARK(BM_HilbertCompactEncode)->Arg(1U << 10U)->Arg(1U << 12U);
BENCHMARK(BM_MortonEncode)->Arg(1U << 10U)->Arg(1U << 12U);

} // namespace
