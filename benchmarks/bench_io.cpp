// ----------------------------------------------------------------------------
// bench_io.cpp - ASCII XYZ/CSV coordinate parsing microbenchmark.
//
// Algorithm:
//   - Generate deterministic 17-digit decimal point rows.
//   - Measure `parse_three_doubles` over every row.
//   - Report processed rows and source bytes per iteration.
//
// References:
//   ISO/IEC, ISO/IEC 9899:2018 Information technology - Programming
//   languages - C, 2018.
//   Rusu and Cousins, 3D is here: Point Cloud Library (PCL), 2011,
//   DOI: 10.1109/ICRA.2011.5980567.
// ----------------------------------------------------------------------------

#include <cstddef>
#include <cstdint>
#include <numeric>
#include <random>
#include <sstream>
#include <string>
#include <vector>

#include <benchmark/benchmark.h>

#include "bench_common.hpp"
#include "rch/io/xyz_parse.hpp"

namespace {

// Generate reproducible ASCII coordinate rows with high precision.
[[nodiscard]] auto generate_xyz_lines(const std::size_t count) -> std::vector<std::string> {
    std::mt19937_64 rng{0x0FFE'C001'C001'0FFEULL};
    std::uniform_real_distribution<double> dist{-100.0, 100.0};
    std::vector<std::string> lines;
    lines.reserve(count);
    for (std::size_t i = 0U; i < count; ++i) {
        std::ostringstream out;
        out.precision(17);
        out << dist(rng) << ' ' << dist(rng) << ' ' << dist(rng);
        lines.push_back(out.str());
    }
    return lines;
}

void BM_ParseThreeDoubles(benchmark::State& state) {
    const auto count = static_cast<std::size_t>(state.range(0));
    const auto lines = generate_xyz_lines(count);
    for (auto _ : state) {
        std::uint64_t accumulator = 0U;
        for (const auto& line : lines) {
            const auto parsed = rch::io::parse_three_doubles(line);
            accumulator += parsed.has_value() ? 1U : 0U;
        }
        benchmark::DoNotOptimize(accumulator);
    }
    state.SetItemsProcessed(rch::benchmarks::processed_items(state, count));
    const auto bytes_per_iteration = std::accumulate(
        lines.begin(),
        lines.end(),
        std::size_t{0U},
        [](std::size_t acc, const std::string& s) noexcept { return acc + s.size(); }
    );
    state.SetBytesProcessed(rch::benchmarks::processed_items(state, bytes_per_iteration));
}

BENCHMARK(BM_ParseThreeDoubles)->Arg(1U << 10U)->Arg(1U << 14U)->Arg(1U << 16U);

} // namespace
