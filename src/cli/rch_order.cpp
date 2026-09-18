// ----------------------------------------------------------------------------
// rch_order.cpp - CLI entry point for deterministic point-cloud ordering.
//
// Algorithm:
//   - Parse CLI options and read \(P=\{p_i\}_{i=0}^{n-1}\subset \mathbb{R}^3\) from
//     XYZ/CSV or ASCII PLY.
//   - Call `order_point_cloud`, which applies the selected SFC/frame algorithm.
//   - Write `rank,raw_index,key` CSV and a JSON manifest with timing,
//     bit-allocation provenance, bit-depths, frame axes, fallback flag, and
//     SHA-256 digest.
//
// References:
//   Shafranovich, Common Format and MIME Type for CSV Files, 2005,
//   DOI: 10.17487/RFC4180.
//   Bray, The JavaScript Object Notation (JSON) Data Interchange Format, 2017,
//   DOI: 10.17487/RFC8259.
//   Hilbert, Ueber die stetige Abbildung einer Linie auf ein Flaechenstueck,
//   1891, DOI: 10.1007/BF01199431.
//   Hamilton and Rau-Chaplin, Compact Hilbert Indices, 2008,
//   DOI: 10.1016/j.ipl.2007.08.034.
// ----------------------------------------------------------------------------

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <optional>
#include <span>
#include <sstream>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#if defined(__unix__) || defined(__APPLE__)
#include <sys/resource.h>
#endif

#include "rch/io/xyz_parse.hpp"
#include "rch/orderings/orderer.hpp"

namespace {

struct Args {
    std::filesystem::path input{};
    std::filesystem::path output{};
    std::filesystem::path manifest{};
    rch::orderings::OrderingMethod method{rch::orderings::OrderingMethod::RCH};
    rch::orderings::FrameEstimator frame_estimator{rch::orderings::FrameEstimator::DetMCD};
    rch::orderings::BitAllocator bit_allocator{rch::orderings::BitAllocator::FrameCoreOccupancy};
    rch::orderings::RefinementMode refinement{rch::orderings::RefinementMode::Off};
    std::uint8_t uniform_bits{10U};
    std::uint8_t min_axis_bits{1U};
    std::size_t timing_repeats{1U};
};

[[nodiscard]] constexpr auto is_ascii_digit(const char c) noexcept -> bool {
    return c >= '0' && c <= '9';
}

[[nodiscard]] auto usage() -> int {
    std::cerr << "usage: rch_order --input file.{xyz,csv,ply} --method METHOD "
                 "--output order.csv --manifest manifest.json "
                 "[--frame-estimator sample|det_mcd|mrcd|ogk] "
                 "[--bit-allocator uniform|sample_count_uniform|monotone_half|"
                 "occupancy_floor1|occupancy_floor10|frame_core_occupancy|hybrid_occupancy] "
                 "[--refinement off|all] [--uniform-bits N] "
                 "[--min-axis-bits N] [--timing-repeats N]\n";
    return 2;
}

// Map experiment/runlist bit allocator tokens to library enums.
[[nodiscard]] auto bit_allocator_from_string(const std::string_view value)
    -> std::optional<rch::orderings::BitAllocator> {
    if (value == "uniform" || value == "c0_uniform") {
        return rch::orderings::BitAllocator::Uniform;
    }
    if (value == "sample_count_uniform" || value == "sample-count-uniform" ||
        value == "count_adaptive_uniform" || value == "count-adaptive-uniform" ||
        value == "c5_sample_count_uniform") {
        return rch::orderings::BitAllocator::SampleCountUniform;
    }
    if (value == "monotone_half" || value == "monotone-half" || value == "c1_monotone_half") {
        return rch::orderings::BitAllocator::MonotoneHalf;
    }
    if (value == "occupancy_floor10" || value == "occupancy-floor10" ||
        value == "c2_occupancy_floor10") {
        return rch::orderings::BitAllocator::OccupancyFloor10;
    }
    if (value == "occupancy_floor1" || value == "occupancy-floor1" ||
        value == "c2_occupancy_floor1") {
        return rch::orderings::BitAllocator::OccupancyFloor1;
    }
    if (value == "frame_core_occupancy" || value == "frame-core-occupancy" ||
        value == "c3_frame_core_occupancy") {
        return rch::orderings::BitAllocator::FrameCoreOccupancy;
    }
    if (value == "hybrid_occupancy" || value == "hybrid-occupancy" || value == "hybrid" ||
        value == "c4_hybrid") {
        return rch::orderings::BitAllocator::HybridOccupancy;
    }
    return std::nullopt;
}

// Render the selected bit allocator into the manifest token set.
[[nodiscard]] constexpr auto
bit_allocator_to_string(const rch::orderings::BitAllocator value) noexcept -> std::string_view {
    switch (value) {
    case rch::orderings::BitAllocator::Uniform:
        return "uniform";
    case rch::orderings::BitAllocator::SampleCountUniform:
        return "sample_count_uniform";
    case rch::orderings::BitAllocator::MonotoneHalf:
        return "monotone_half";
    case rch::orderings::BitAllocator::OccupancyFloor1:
        return "occupancy_floor1";
    case rch::orderings::BitAllocator::OccupancyFloor10:
        return "occupancy_floor10";
    case rch::orderings::BitAllocator::FrameCoreOccupancy:
        return "frame_core_occupancy";
    case rch::orderings::BitAllocator::HybridOccupancy:
        return "hybrid_occupancy";
    default:
        break;
    }
    return "unknown";
}

[[nodiscard]] constexpr auto
bit_allocation_model_to_string(const rch::orderings::BitAllocator value) noexcept
    -> std::string_view {
    switch (value) {
    case rch::orderings::BitAllocator::Uniform:
        return "fixed_equal_depth";
    case rch::orderings::BitAllocator::SampleCountUniform:
        return "sample_count_equal_depth";
    case rch::orderings::BitAllocator::MonotoneHalf:
        return "extent_ranked_monotone_half";
    case rch::orderings::BitAllocator::OccupancyFloor1:
        return "covering_occupancy_floor1";
    case rch::orderings::BitAllocator::OccupancyFloor10:
        return "covering_occupancy_floor10";
    case rch::orderings::BitAllocator::FrameCoreOccupancy:
        return "robust_core_occupancy";
    case rch::orderings::BitAllocator::HybridOccupancy:
        return "robust_core_delta_covering_occupancy";
    default:
        break;
    }
    return "unknown";
}

[[nodiscard]] constexpr auto
bit_budget_projection_to_string(const rch::orderings::BitAllocator value) noexcept
    -> std::string_view {
    switch (value) {
    case rch::orderings::BitAllocator::OccupancyFloor1:
    case rch::orderings::BitAllocator::OccupancyFloor10:
    case rch::orderings::BitAllocator::FrameCoreOccupancy:
    case rch::orderings::BitAllocator::HybridOccupancy:
        return "minimax_worst_cell_edge";
    case rch::orderings::BitAllocator::MonotoneHalf:
        return "extent_ranked_half_budget";
    case rch::orderings::BitAllocator::Uniform:
    case rch::orderings::BitAllocator::SampleCountUniform:
        return "equal_depth_axis_cap";
    default:
        break;
    }
    return "unknown";
}

[[nodiscard]] auto parse_u8_token(const std::string_view value) -> std::optional<std::uint8_t> {
    if (value.empty() || !std::ranges::all_of(value, is_ascii_digit)) {
        return std::nullopt;
    }
    unsigned long parsed = 0UL;
    try {
        std::size_t used = 0U;
        parsed = std::stoul(std::string{value}, &used, 10);
        if (used != value.size() || parsed > 255UL) {
            return std::nullopt;
        }
    } catch (...) {
        return std::nullopt;
    }
    return static_cast<std::uint8_t>(parsed);
}

[[nodiscard]] auto parse_size_token(const std::string_view value) -> std::optional<std::size_t> {
    if (value.empty() || !std::ranges::all_of(value, is_ascii_digit)) {
        return std::nullopt;
    }
    unsigned long long parsed = 0ULL;
    try {
        std::size_t used = 0U;
        parsed = std::stoull(std::string{value}, &used, 10);
        if (used != value.size() || parsed == 0ULL ||
            parsed > static_cast<unsigned long long>(std::numeric_limits<std::size_t>::max())) {
            return std::nullopt;
        }
    } catch (...) {
        return std::nullopt;
    }
    return static_cast<std::size_t>(parsed);
}

[[nodiscard]] auto parse_count_token(const std::string_view value) -> std::optional<std::size_t> {
    if (value.empty() || !std::ranges::all_of(value, is_ascii_digit)) {
        return std::nullopt;
    }
    unsigned long long parsed = 0ULL;
    try {
        std::size_t used = 0U;
        parsed = std::stoull(std::string{value}, &used, 10);
        if (used != value.size() ||
            parsed > static_cast<unsigned long long>(std::numeric_limits<std::size_t>::max())) {
            return std::nullopt;
        }
    } catch (...) {
        return std::nullopt;
    }
    return static_cast<std::size_t>(parsed);
}

[[nodiscard]] auto parse_args(const int argc, char** argv) -> std::optional<Args> {
    Args args{};
    for (int i = 1; i < argc; ++i) {
        const std::string_view flag{argv[i]};
        if (i + 1 >= argc) {
            return std::nullopt;
        }
        const std::string_view value{argv[++i]};
        if (flag == "--input") {
            args.input = value;
        } else if (flag == "--output") {
            args.output = value;
        } else if (flag == "--manifest") {
            args.manifest = value;
        } else if (flag == "--method") {
            const auto method = rch::orderings::method_from_string(value);
            if (!method.has_value()) {
                return std::nullopt;
            }
            args.method = *method;
        } else if (flag == "--bit-allocator") {
            const auto bit_allocator = bit_allocator_from_string(value);
            if (!bit_allocator.has_value()) {
                return std::nullopt;
            }
            args.bit_allocator = *bit_allocator;
        } else if (flag == "--frame-estimator") {
            const auto frame_estimator = rch::orderings::frame_estimator_from_string(value);
            if (!frame_estimator.has_value()) {
                return std::nullopt;
            }
            args.frame_estimator = *frame_estimator;
        } else if (flag == "--refinement") {
            const auto refinement = rch::orderings::refinement_from_string(value);
            if (!refinement.has_value()) {
                return std::nullopt;
            }
            args.refinement = *refinement;
        } else if (flag == "--uniform-bits") {
            const auto uniform_bits = parse_u8_token(value);
            if (!uniform_bits.has_value()) {
                return std::nullopt;
            }
            args.uniform_bits = *uniform_bits;
        } else if (flag == "--min-axis-bits") {
            const auto min_axis_bits = parse_u8_token(value);
            if (!min_axis_bits.has_value()) {
                return std::nullopt;
            }
            args.min_axis_bits = *min_axis_bits;
        } else if (flag == "--timing-repeats") {
            const auto timing_repeats = parse_size_token(value);
            if (!timing_repeats.has_value()) {
                return std::nullopt;
            }
            args.timing_repeats = *timing_repeats;
        } else {
            return std::nullopt;
        }
    }
    if (args.input.empty() || args.output.empty() || args.manifest.empty()) {
        return std::nullopt;
    }
    return args;
}

[[nodiscard]] auto extension_of(const std::filesystem::path& path) -> std::string {
    std::string ext = path.extension().string();
    std::ranges::transform(ext, ext.begin(), [](const char c) noexcept {
        if (c >= 'A' && c <= 'Z') {
            return static_cast<char>(c - 'A' + 'a');
        }
        return c;
    });
    return ext;
}

[[nodiscard]] auto read_xyz_or_csv(const std::filesystem::path& path)
    -> std::optional<std::vector<double>> {
    std::ifstream input{path};
    if (!input.is_open()) {
        return std::nullopt;
    }
    std::vector<double> points{};
    std::string line{};
    while (std::getline(input, line)) {
        const auto parsed = rch::io::parse_three_doubles(line);
        if (!parsed.has_value() && line.empty()) {
            continue;
        }
        if (!parsed.has_value()) {
            return std::nullopt;
        }
        points.push_back((*parsed)[0]);
        points.push_back((*parsed)[1]);
        points.push_back((*parsed)[2]);
    }
    return points;
}

[[nodiscard]] auto read_ascii_ply(const std::filesystem::path& path)
    -> std::optional<std::vector<double>> {
    std::ifstream input{path};
    if (!input.is_open()) {
        return std::nullopt;
    }

    std::size_t vertex_count = 0U;
    bool saw_vertex_count = false;
    bool ascii = false;
    bool end_header = false;
    std::string line{};
    if (!std::getline(input, line) || line != "ply") {
        return std::nullopt;
    }
    while (std::getline(input, line)) {
        if (line == "format ascii 1.0") {
            ascii = true;
        }
        if (line.rfind("element vertex ", 0U) == 0U) {
            if (saw_vertex_count) {
                return std::nullopt;
            }
            const auto parsed_count =
                parse_count_token(line.substr(std::string_view{"element vertex "}.size()));
            if (!parsed_count.has_value()) {
                return std::nullopt;
            }
            vertex_count = *parsed_count;
            saw_vertex_count = true;
        }
        if (line == "end_header") {
            end_header = true;
            break;
        }
    }
    if (!ascii || !saw_vertex_count || !end_header) {
        return std::nullopt;
    }

    std::vector<double> points{};
    points.reserve(vertex_count * 3U);
    for (std::size_t i = 0U; i < vertex_count && std::getline(input, line); ++i) {
        const auto parsed = rch::io::parse_three_doubles(line);
        if (!parsed.has_value()) {
            return std::nullopt;
        }
        points.push_back((*parsed)[0]);
        points.push_back((*parsed)[1]);
        points.push_back((*parsed)[2]);
    }
    if (points.size() != vertex_count * 3U) {
        return std::nullopt;
    }
    return points;
}

[[nodiscard]] auto read_points(const std::filesystem::path& path)
    -> std::optional<std::vector<double>> {
    const std::string ext = extension_of(path);
    if (ext == ".xyz" || ext == ".csv") {
        return read_xyz_or_csv(path);
    }
    if (ext == ".ply") {
        return read_ascii_ply(path);
    }
    return std::nullopt;
}

// Persist the final permutation as RFC-4180-style comma-separated rows.
[[nodiscard]] auto
write_order_csv(const std::filesystem::path& path, const rch::orderings::OrderingResult& result)
    -> bool {
    std::ofstream output{path};
    if (!output.is_open()) {
        return false;
    }
    output << "rank,raw_index,key\n";
    for (std::size_t rank = 0U; rank < result.permutation.size(); ++rank) {
        const auto raw = static_cast<std::size_t>(result.permutation[rank]);
        output << rank << ',' << raw << ',' << result.primary_keys[raw] << '\n';
    }
    return static_cast<bool>(output);
}

[[nodiscard]] constexpr auto hex_digit(const unsigned int nibble) noexcept -> char {
    return static_cast<char>(nibble < 10U ? ('0' + nibble) : ('A' + (nibble - 10U)));
}

[[nodiscard]] auto json_escape(const std::string_view value) -> std::string {
    std::string out;
    out.reserve(value.size());
    for (const char raw : value) {
        const auto c = static_cast<unsigned char>(raw);
        switch (c) {
        case '"':
        case '\\':
            out.push_back('\\');
            out.push_back(static_cast<char>(c));
            break;
        case '\b':
            out += "\\b";
            break;
        case '\f':
            out += "\\f";
            break;
        case '\n':
            out += "\\n";
            break;
        case '\r':
            out += "\\r";
            break;
        case '\t':
            out += "\\t";
            break;
        default:
            if (c < 0x20U) {
                out += "\\u00";
                out.push_back(hex_digit(c >> 4U));
                out.push_back(hex_digit(c & 0x0FU));
            } else {
                out.push_back(static_cast<char>(c));
            }
            break;
        }
    }
    return out;
}

// Write the \(3\times3\) frame-axis matrix in row-major JSON form.
void write_frame_axes_json(std::ostream& output, const rch::core::Matrix3<double>& axes) {
    output << std::setprecision(std::numeric_limits<double>::max_digits10);
    output << "  \"frame_axes\": [\n";
    for (std::size_t row = 0U; row < 3U; ++row) {
        output << "    [" << axes(row, 0U) << ", " << axes(row, 1U) << ", " << axes(row, 2U) << "]";
        output << (row + 1U == 3U ? "\n" : ",\n");
    }
    output << "  ],\n";
}

[[nodiscard]] auto median_seconds(std::vector<double> values) -> double {
    if (values.empty()) {
        return 0.0;
    }
    std::ranges::sort(values);
    const std::size_t middle = values.size() / 2U;
    if ((values.size() % 2U) == 1U) {
        return values[middle];
    }
    return 0.5 * (values[middle - 1U] + values[middle]);
}

[[nodiscard]] auto
effective_frame_estimator(const Args& args, const rch::orderings::OrderingMethod method)
    -> std::string_view {
    switch (method) {
    case rch::orderings::OrderingMethod::PcaCompactHilbert:
        return rch::orderings::to_string(rch::orderings::FrameEstimator::SampleCovariance);
    case rch::orderings::OrderingMethod::RobustFrameMorton:
    case rch::orderings::OrderingMethod::RCH:
        return rch::orderings::to_string(args.frame_estimator);
    case rch::orderings::OrderingMethod::InputOrder:
    case rch::orderings::OrderingMethod::Lexicographic:
    case rch::orderings::OrderingMethod::Morton:
    case rch::orderings::OrderingMethod::IsotropicHilbert:
    case rch::orderings::OrderingMethod::CompactHilbertAABB:
        return "none";
    default:
        return "none";
    }
}

[[nodiscard]] auto peak_rss_kb() -> std::optional<std::uint64_t> {
#if defined(__unix__) || defined(__APPLE__)
    rusage usage{};
    if (getrusage(RUSAGE_SELF, &usage) != 0) {
        return std::nullopt;
    }
#if defined(__APPLE__)
    return static_cast<std::uint64_t>(usage.ru_maxrss / 1024L);
#else
    return static_cast<std::uint64_t>(usage.ru_maxrss);
#endif
#else
    return std::nullopt;
#endif
}

// Write a deterministic JSON manifest for experiment/reproducibility scripts.
[[nodiscard]] auto write_manifest(
    const std::filesystem::path& path,
    const Args& args,
    const rch::orderings::OrderingResult& result,
    const std::size_t point_count,
    const double sort_seconds
) -> bool {
    const auto hash = rch::orderings::hash_hex(result.output_hash);
    std::ofstream output{path};
    if (!output.is_open()) {
        return false;
    }
    output << "{\n";
    output << "  \"status\": \"ok\",\n";
    output << "  \"input\": \"" << json_escape(args.input.string()) << "\",\n";
    output << "  \"method\": \"" << rch::orderings::to_string(result.method) << "\",\n";
    output << "  \"frame_estimator\": \"" << effective_frame_estimator(args, result.method)
           << "\",\n";
    output << "  \"bit_allocator\": \"" << bit_allocator_to_string(args.bit_allocator) << "\",\n";
    output << "  \"bit_allocation_model\": \"" << bit_allocation_model_to_string(args.bit_allocator)
           << "\",\n";
    output << "  \"bit_budget_projection\": \""
           << bit_budget_projection_to_string(args.bit_allocator) << "\",\n";
    output << "  \"refinement\": \"" << rch::orderings::to_string(args.refinement) << "\",\n";
    output << "  \"uniform_bits\": " << static_cast<unsigned int>(args.uniform_bits) << ",\n";
    output << "  \"min_axis_bits\": " << static_cast<unsigned int>(args.min_axis_bits) << ",\n";
    output << "  \"timing_repeats\": " << args.timing_repeats << ",\n";
    output << std::setprecision(std::numeric_limits<double>::max_digits10);
    output << "  \"sort_seconds\": " << sort_seconds << ",\n";
    const auto rss = peak_rss_kb();
    if (rss.has_value()) {
        output << "  \"peak_rss_kb\": " << *rss << ",\n";
    } else {
        output << "  \"peak_rss_kb\": null,\n";
    }
    output << "  \"point_count\": " << point_count << ",\n";
    output << "  \"hash\": \"" << hash.data() << "\",\n";
    output << "  \"bits_axis\": [" << static_cast<unsigned int>(result.bits_axis[0]) << ", "
           << static_cast<unsigned int>(result.bits_axis[1]) << ", "
           << static_cast<unsigned int>(result.bits_axis[2]) << "],\n";
    write_frame_axes_json(output, result.frame_axes);
    output << "  \"robust_fallback_used\": " << (result.robust_fallback_used ? "true" : "false")
           << "\n";
    output << "}\n";
    return static_cast<bool>(output);
}

} // namespace

int main(const int argc, char** argv) {
    const auto args = parse_args(argc, argv);
    if (!args.has_value()) {
        return usage();
    }

    const auto points = read_points(args->input);
    if (!points.has_value()) {
        std::cerr << "failed to read input points\n";
        return 1;
    }

    rch::orderings::OrderingConfig config{};
    config.method = args->method;
    config.frame = args->frame_estimator;
    config.bit_alloc = args->bit_allocator;
    config.refinement = args->refinement;
    config.uniform_bits = args->uniform_bits;
    config.min_axis_bits = args->min_axis_bits;
    std::optional<rch::orderings::OrderingResult> final_result{};
    std::vector<double> elapsed_seconds;
    elapsed_seconds.reserve(args->timing_repeats);
    for (std::size_t repeat = 0U; repeat < args->timing_repeats; ++repeat) {
        const auto start = std::chrono::steady_clock::now();
        auto result = rch::orderings::order_point_cloud(std::span<const double>{*points}, config);
        const auto stop = std::chrono::steady_clock::now();
        if (!result.has_value()) {
            std::cerr << "ordering failed: " << result.error().message << '\n';
            return 1;
        }
        elapsed_seconds.push_back(std::chrono::duration<double>{stop - start}.count());
        final_result = std::move(*result);
    }
    const double sort_seconds = median_seconds(std::move(elapsed_seconds));

    if (!write_order_csv(args->output, *final_result)) {
        std::cerr << "failed to write output csv\n";
        return 1;
    }
    if (!write_manifest(args->manifest, *args, *final_result, points->size() / 3U, sort_seconds)) {
        std::cerr << "failed to write manifest\n";
        return 1;
    }
    return 0;
}
