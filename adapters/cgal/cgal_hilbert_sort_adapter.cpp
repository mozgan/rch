#include <CGAL/Simple_cartesian.h>
#include <CGAL/hilbert_sort.h>
#include <CGAL/spatial_sort.h>
#include <CGAL/version.h>

// ----------------------------------------------------------------------------
// cgal_hilbert_sort_adapter.cpp - A7 baseline adapter for CGAL spatial_sort.
//
// References:
//   - Christophe Delage, Olivier Devillers, "CGAL Spatial Sorting User Manual",
//     CGAL Spatial Sorting documentation.
//   - CGAL Project, "SpatialSortingTraits_3 Concept Reference", CGAL
//     documentation.
//   - Haverkort, "An inventory of three-dimensional Hilbert space-filling
//     curves", 2011, doi:10.48550/arXiv.1109.2323.
//
// Algorithm:
//   1. Read finite 3D points \(p_i=(x_i,y_i,z_i)\) and attach raw index \(i\).
//   2. Expose a CGAL 3D spatial-sorting traits view over \((p_i,i)\).
//   3. Call `CGAL::spatial_sort` with median or middle Hilbert policy.
//   4. Emit the sorted raw indices as a permutation and write CGAL provenance.
// ----------------------------------------------------------------------------

#include <algorithm>
#include <array>
#include <cctype>
#include <cmath>
#include <cstddef>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <optional>
#include <sstream>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#define RCH_STRINGIFY_DETAIL(value) #value
#define RCH_STRINGIFY(value) RCH_STRINGIFY_DETAIL(value)

namespace {

using Kernel = CGAL::Simple_cartesian<double>;
using Point3 = Kernel::Point_3;
using PointWithIndex = std::pair<Point3, std::size_t>;

inline constexpr std::ptrdiff_t kSpatialSortDimension = 3;
inline constexpr std::ptrdiff_t kThresholdHilbert = 8;
inline constexpr std::ptrdiff_t kThresholdMultiscale = 64;
inline constexpr double kMultiscaleRatio = 0.125;

struct PointWithIndexTraits {
    // CGAL SpatialSortingTraits_3 model for sorting `(Point_3, raw_index)` pairs.
    using Point_3 = PointWithIndex;

    struct Compute_x_3 {
        // Return \(x\)-coordinate for CGAL Hilbert/spatial sorting.
        [[nodiscard]] auto operator()(const PointWithIndex& value) const -> Kernel::FT {
            return value.first.x();
        }
    };

    struct Compute_y_3 {
        // Return \(y\)-coordinate for CGAL Hilbert/spatial sorting.
        [[nodiscard]] auto operator()(const PointWithIndex& value) const -> Kernel::FT {
            return value.first.y();
        }
    };

    struct Compute_z_3 {
        // Return \(z\)-coordinate for CGAL Hilbert/spatial sorting.
        [[nodiscard]] auto operator()(const PointWithIndex& value) const -> Kernel::FT {
            return value.first.z();
        }
    };

    struct Less_x_3 {
        // Strict order by \(x\); input is prefiltered to finite coordinates.
        [[nodiscard]] auto operator()(const PointWithIndex& left, const PointWithIndex& right) const
            -> bool {
            return left.first.x() < right.first.x();
        }
    };

    struct Less_y_3 {
        // Strict order by \(y\); matches the SpatialSortingTraits_3 contract.
        [[nodiscard]] auto operator()(const PointWithIndex& left, const PointWithIndex& right) const
            -> bool {
            return left.first.y() < right.first.y();
        }
    };

    struct Less_z_3 {
        // Strict order by \(z\); matches the SpatialSortingTraits_3 contract.
        [[nodiscard]] auto operator()(const PointWithIndex& left, const PointWithIndex& right) const
            -> bool {
            return left.first.z() < right.first.z();
        }
    };

    [[nodiscard]] auto compute_x_3_object() const -> Compute_x_3 {
        return {};
    }

    [[nodiscard]] auto compute_y_3_object() const -> Compute_y_3 {
        return {};
    }

    [[nodiscard]] auto compute_z_3_object() const -> Compute_z_3 {
        return {};
    }

    [[nodiscard]] auto less_x_3_object() const -> Less_x_3 {
        return {};
    }

    [[nodiscard]] auto less_y_3_object() const -> Less_y_3 {
        return {};
    }

    [[nodiscard]] auto less_z_3_object() const -> Less_z_3 {
        return {};
    }
};

struct Args {
    // CLI paths and Hilbert subdivision policy.
    std::filesystem::path input{};
    std::filesystem::path output{};
    std::filesystem::path metadata_output{};
    std::string policy{"median"};
};

[[nodiscard]] auto usage() -> int {
    std::cerr << "usage: rch_cgal_spatial_sort --input points.csv --output order.csv "
                 "[--policy median|middle] [--metadata-output metadata.json]\n";
    return 2;
}

// Parse the adapter CLI; unknown flags and missing values fail closed.
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
        } else if (flag == "--metadata-output") {
            args.metadata_output = value;
        } else if (flag == "--policy") {
            if (value != "median" && value != "middle") {
                return std::nullopt;
            }
            args.policy = value;
        } else {
            return std::nullopt;
        }
    }
    if (args.input.empty() || args.output.empty()) {
        return std::nullopt;
    }
    return args;
}

// Parse one CSV/whitespace/semicolon row into a finite 3D point.
[[nodiscard]] auto parse_point_line(std::string line) -> std::optional<std::array<double, 3>> {
    std::ranges::replace(line, ',', ' ');
    std::ranges::replace(line, ';', ' ');
    std::istringstream stream{line};
    std::array<double, 3> point{};
    if (!(stream >> point[0] >> point[1] >> point[2])) {
        return std::nullopt;
    }
    if (!std::isfinite(point[0]) || !std::isfinite(point[1]) || !std::isfinite(point[2])) {
        return std::nullopt;
    }
    char extra{};
    if (stream >> extra) {
        return std::nullopt;
    }
    return point;
}

[[nodiscard]] auto is_blank_line(const std::string_view line) -> bool {
    return std::ranges::all_of(line, [](const char value) noexcept {
        return std::isspace(static_cast<unsigned char>(value)) != 0;
    });
}

// Read all point rows; malformed or non-finite rows reject the whole input.
[[nodiscard]] auto read_points(const std::filesystem::path& path)
    -> std::optional<std::vector<Point3>> {
    std::ifstream input{path};
    if (!input.is_open()) {
        return std::nullopt;
    }
    std::vector<Point3> points{};
    std::string line{};
    while (std::getline(input, line)) {
        if (is_blank_line(line)) {
            continue;
        }
        const auto parsed = parse_point_line(line);
        if (!parsed.has_value()) {
            return std::nullopt;
        }
        points.emplace_back((*parsed)[0], (*parsed)[1], (*parsed)[2]);
    }
    return points;
}

// Emit the permutation schema consumed by experiment runners.
[[nodiscard]] auto
write_order(const std::filesystem::path& path, const std::vector<std::size_t>& indices) -> bool {
    std::ofstream output{path};
    if (!output.is_open()) {
        return false;
    }
    output << "rank,raw_index,key\n";
    for (std::size_t rank = 0U; rank < indices.size(); ++rank) {
        output << rank << ',' << indices[rank] << ",0\n";
    }
    return static_cast<bool>(output);
}

// Record CGAL version and spatial-sort parameters for reproducibility.
[[nodiscard]] auto
write_metadata(const std::filesystem::path& path, const std::string_view policy) -> bool {
    std::ofstream output{path};
    if (!output.is_open()) {
        return false;
    }
    output << "{\n";
    output << "  \"schema\": \"rch.cgal_adapter.metadata.v1\",\n";
    output << "  \"cgal_version\": \"" << RCH_STRINGIFY(CGAL_VERSION) << "\",\n";
    output << "  \"cgal_version_nr\": " << CGAL_VERSION_NR << ",\n";
    output << "  \"cgal_git_hash\": \"" << RCH_STRINGIFY(CGAL_GIT_HASH) << "\",\n";
    output << "  \"spatial_sort_dimension\": " << kSpatialSortDimension << ",\n";
    output << "  \"spatial_sort_policy\": \"" << policy << "\",\n";
    output << "  \"threshold_hilbert\": " << kThresholdHilbert << ",\n";
    output << "  \"threshold_multiscale\": " << kThresholdMultiscale << ",\n";
    output << "  \"ratio\": " << kMultiscaleRatio << "\n";
    output << "}\n";
    return static_cast<bool>(output);
}

} // namespace

int main(const int argc, char** argv) {
    const auto args = parse_args(argc, argv);
    if (!args.has_value()) {
        return usage();
    }
    auto points = read_points(args->input);
    if (!points.has_value()) {
        std::cerr << "failed to read input points\n";
        return 1;
    }

    std::vector<PointWithIndex> indexed_points;
    indexed_points.reserve(points->size());
    for (std::size_t index = 0; index < points->size(); ++index) {
        indexed_points.emplace_back((*points)[index], index);
    }

    PointWithIndexTraits traits{};
    if (args->policy == "middle") {
        // Middle policy recursively splits at cell centers.
        CGAL::spatial_sort(
            indexed_points.begin(),
            indexed_points.end(),
            traits,
            CGAL::Hilbert_sort_middle_policy(),
            kThresholdHilbert,
            kThresholdMultiscale,
            kMultiscaleRatio
        );
    } else {
        // Median policy recursively splits at coordinate medians; CGAL defaults to it.
        CGAL::spatial_sort(
            indexed_points.begin(),
            indexed_points.end(),
            traits,
            CGAL::Hilbert_sort_median_policy(),
            kThresholdHilbert,
            kThresholdMultiscale,
            kMultiscaleRatio
        );
    }

    std::vector<std::size_t> indices;
    indices.reserve(indexed_points.size());
    for (const auto& entry : indexed_points) {
        indices.push_back(entry.second);
    }

    if (!write_order(args->output, indices)) {
        std::cerr << "failed to write output order\n";
        return 1;
    }
    if (!args->metadata_output.empty() && !write_metadata(args->metadata_output, args->policy)) {
        std::cerr << "failed to write metadata output\n";
        return 1;
    }
    return 0;
}
