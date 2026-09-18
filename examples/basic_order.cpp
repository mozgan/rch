// -----------------------------------------------------------------------------
// basic_order.cpp - header-only RCH ordering demo.
//
// What this example demonstrates:
//   1. RCH is consumed as a header-only C++23 library: include one public header,
//      link no RCH object library, and call rch::orderings::order_point_cloud().
//   2. Input points are row-major doubles: [x0,y0,z0, x1,y1,z1, ...], i.e. an
//      N x 3 matrix flattened into a single std::vector<double>.
//   3. OrderingConfig selects the algorithm variant:
//        method      : input, lexicographic, morton, isotropic_hilbert,
//                      compact_hilbert_aabb, pca_compact_hilbert,
//                      robust_frame_morton, rch
//        frame       : sample_covariance, det_mcd, mrcd, ogk
//        bit_alloc   : uniform, monotone_half, occupancy_floor1,
//                      occupancy_floor10, frame_core_occupancy,
//                      hybrid_occupancy
//        refinement  : off, all
//   4. The result is a permutation plus primary integer keys. Reorder your own
//      point/attribute arrays with result.permutation; keys are diagnostic and
//      useful when debugging ties or determinism.
//
// Build from the repository root after enabling examples:
//   cmake -S . -B build/examples -DRCH_BUILD_TESTS=OFF -DRCH_BUILD_EXAMPLES=ON
//   cmake --build build/examples --target rch_basic_order
//
// Run with embedded points:
//   build/examples/examples/rch_basic_order
//
// Run with the fixture and a different variant:
//   build/examples/examples/rch_basic_order examples/tiny_point_cloud.xyz
//       --method pca_compact_hilbert --frame sample_covariance
//       --bit-allocator uniform --refinement all
// -----------------------------------------------------------------------------

#include <array>
#include <cstdint>
#include <cstdlib>
#include <expected>
#include <fstream>
#include <iostream>
#include <optional>
#include <span>
#include <sstream>
#include <string>
#include <string_view>
#include <vector>

#include "rch/orderings/orderer.hpp"

namespace {

using rch::orderings::BitAllocator;
using rch::orderings::FrameEstimator;
using rch::orderings::OrderingConfig;
using rch::orderings::OrderingMethod;
using rch::orderings::RefinementMode;

struct DemoOptions {
    std::optional<std::string> input_path{};
    OrderingConfig config{};
};

// A tiny non-degenerate cloud is enough to show the API shape. Real applications
// should usually read their own point buffer and keep any attributes in a
// separate array indexed by the same raw point index.
[[nodiscard]] auto embedded_points_xyz() -> std::vector<double> {
    return {
        0.0, 0.0, 0.0,
        1.0, 0.0, 0.0,
        0.0, 1.0, 0.0,
        0.0, 0.0, 1.0,
        0.5, 0.5, 0.2,
        0.2, 0.4, 0.8,
    };
}

// Parse whitespace-separated XYZ rows. The library itself only needs the
// flattened vector; this helper is here so the demo can be run on an external
// file without pulling in the project's CLI parser.
[[nodiscard]] auto read_xyz_file(const std::string& path) -> std::expected<std::vector<double>, std::string> {
    std::ifstream input{path};
    if (!input.is_open()) {
        return std::unexpected("failed to open input file: " + path);
    }

    std::vector<double> points;
    std::string line;
    std::size_t line_number = 0U;
    while (std::getline(input, line)) {
        ++line_number;
        if (line.empty() || line[0] == '#') {
            continue;
        }
        std::istringstream row{line};
        std::array<double, 3> point{};
        if (!(row >> point[0] >> point[1] >> point[2])) {
            return std::unexpected(
                "expected three numeric columns at line " + std::to_string(line_number)
            );
        }
        std::string extra;
        if (row >> extra) {
            return std::unexpected(
                "expected exactly three columns at line " + std::to_string(line_number)
            );
        }
        points.insert(points.end(), point.begin(), point.end());
    }
    return points;
}

[[nodiscard]] constexpr auto to_string(const BitAllocator allocator) noexcept -> std::string_view {
    switch (allocator) {
    case BitAllocator::Uniform:
        return "uniform";
    case BitAllocator::SampleCountUniform:
        return "sample_count_uniform";
    case BitAllocator::MonotoneHalf:
        return "monotone_half";
    case BitAllocator::OccupancyFloor1:
        return "occupancy_floor1";
    case BitAllocator::OccupancyFloor10:
        return "occupancy_floor10";
    case BitAllocator::FrameCoreOccupancy:
        return "frame_core_occupancy";
    case BitAllocator::HybridOccupancy:
        return "hybrid_occupancy";
    default:
        break;
    }
    return "unknown";
}

[[nodiscard]] constexpr auto bit_allocator_from_string(const std::string_view name)
    -> std::optional<BitAllocator> {
    if (name == "uniform") {
        return BitAllocator::Uniform;
    }
    if (name == "sample_count_uniform") {
        return BitAllocator::SampleCountUniform;
    }
    if (name == "monotone_half") {
        return BitAllocator::MonotoneHalf;
    }
    if (name == "occupancy_floor1") {
        return BitAllocator::OccupancyFloor1;
    }
    if (name == "occupancy_floor10") {
        return BitAllocator::OccupancyFloor10;
    }
    if (name == "frame_core_occupancy") {
        return BitAllocator::FrameCoreOccupancy;
    }
    if (name == "hybrid_occupancy" || name == "hybrid") {
        return BitAllocator::HybridOccupancy;
    }
    return std::nullopt;
}

auto print_usage(const char* program) -> void {
    std::cerr
        << "usage: " << program << " [points.xyz] [options]\n"
        << "\n"
        << "options:\n"
        << "  --method NAME          input|lexicographic|morton|isotropic_hilbert|\n"
        << "                         compact_hilbert_aabb|pca_compact_hilbert|\n"
        << "                         robust_frame_morton|rch\n"
        << "  --frame NAME           sample_covariance|det_mcd|mrcd|ogk\n"
        << "  --bit-allocator NAME   uniform|sample_count_uniform|monotone_half|\n"
        << "                         occupancy_floor1|occupancy_floor10|\n"
        << "                         frame_core_occupancy|hybrid_occupancy\n"
        << "  --refinement NAME      off|all\n"
        << "\n"
        << "default: --method rch --frame det_mcd "
        << "--bit-allocator frame_core_occupancy --refinement off\n";
}

[[nodiscard]] auto parse_args(const int argc, char** argv) -> std::expected<DemoOptions, std::string> {
    DemoOptions options{};
    for (int i = 1; i < argc; ++i) {
        const std::string_view token{argv[i]};
        if (token == "--help" || token == "-h") {
            print_usage(argv[0]);
            std::exit(0);
        }

        auto require_value = [&](const std::string_view flag) -> std::expected<std::string_view, std::string> {
            if (i + 1 >= argc) {
                return std::unexpected("missing value after " + std::string{flag});
            }
            return std::string_view{argv[++i]};
        };

        if (token == "--method") {
            auto value = require_value(token);
            if (!value.has_value()) {
                return std::unexpected(value.error());
            }
            auto method = rch::orderings::method_from_string(*value);
            if (!method.has_value()) {
                return std::unexpected("unknown --method: " + std::string{*value});
            }
            options.config.method = *method;
        } else if (token == "--frame") {
            auto value = require_value(token);
            if (!value.has_value()) {
                return std::unexpected(value.error());
            }
            auto frame = rch::orderings::frame_estimator_from_string(*value);
            if (!frame.has_value()) {
                return std::unexpected("unknown --frame: " + std::string{*value});
            }
            options.config.frame = *frame;
        } else if (token == "--bit-allocator") {
            auto value = require_value(token);
            if (!value.has_value()) {
                return std::unexpected(value.error());
            }
            auto allocator = bit_allocator_from_string(*value);
            if (!allocator.has_value()) {
                return std::unexpected(
                    "unknown --bit-allocator: " + std::string{*value}
                );
            }
            options.config.bit_alloc = *allocator;
        } else if (token == "--refinement") {
            auto value = require_value(token);
            if (!value.has_value()) {
                return std::unexpected(value.error());
            }
            auto refinement = rch::orderings::refinement_from_string(*value);
            if (!refinement.has_value()) {
                return std::unexpected("unknown --refinement: " + std::string{*value});
            }
            options.config.refinement = *refinement;
        } else if (!token.empty() && token[0] == '-') {
            return std::unexpected("unknown option: " + std::string{token});
        } else if (!options.input_path.has_value()) {
            options.input_path = std::string{token};
        } else {
            return std::unexpected("only one input file may be provided");
        }
    }
    return options;
}

} // namespace

int main(const int argc, char** argv) {
    const auto options = parse_args(argc, argv);
    if (!options.has_value()) {
        std::cerr << "error: " << options.error() << "\n\n";
        print_usage(argv[0]);
        return 2;
    }

    const auto points = options->input_path.has_value()
        ? read_xyz_file(*options->input_path)
        : std::expected<std::vector<double>, std::string>{embedded_points_xyz()};
    if (!points.has_value()) {
        std::cerr << "error: " << points.error() << '\n';
        return 1;
    }

    // The public facade validates shape and finite values. Bad input returns
    // std::unexpected instead of throwing, so examples and production callers can
    // handle errors without exceptions crossing API boundaries.
    const auto result = rch::orderings::order_point_cloud(
        std::span<const double>{*points}, options->config
    );
    if (!result.has_value()) {
        std::cerr << "ordering failed: " << result.error().message << '\n';
        return 1;
    }

    const auto hash = rch::orderings::hash_hex(result->output_hash);
    std::cerr << "method=" << rch::orderings::to_string(result->method)
              << " frame=" << rch::orderings::to_string(options->config.frame)
              << " bit_allocator=" << to_string(options->config.bit_alloc)
              << " refinement=" << rch::orderings::to_string(options->config.refinement)
              << " points=" << (points->size() / 3U)
              << " bits_axis=" << static_cast<unsigned int>(result->bits_axis[0])
              << ' ' << static_cast<unsigned int>(result->bits_axis[1])
              << ' ' << static_cast<unsigned int>(result->bits_axis[2])
              << " robust_fallback_used=" << (result->robust_fallback_used ? "true" : "false")
              << " hash=" << hash.data() << '\n';

    // CSV on stdout mirrors the developer CLI: rank is the new sorted position,
    // raw_index points back to the caller's original point/attribute arrays, and
    // key is the primary SFC key used by curve-based methods.
    std::cout << "rank,raw_index,key\n";
    for (std::size_t rank = 0; rank < result->permutation.size(); ++rank) {
        const std::uint64_t raw_index = result->permutation[rank];
        std::cout << rank << ',' << raw_index << ',' << result->primary_keys[raw_index]
                  << '\n';
    }
    return 0;
}
