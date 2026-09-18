// ----------------------------------------------------------------------------
// rch_block_read_probe.cpp - deterministic block-read checksum probe.
//
// Algorithm:
//   - Read raw points \(p_i=(x_i,y_i,z_i)\) and an order CSV.
//   - Traverse ordered raw indices in blocks of size \(B\).
//   - Accumulate \(0.25x_i+0.5y_i+z_i\) to force ordered coordinate reads.
//
// References:
//   Shafranovich, Common Format and MIME Type for CSV Files, 2005,
//   DOI: 10.17487/RFC4180.
//   ISO/IEC, Programming Languages - C++, 2020.
// ----------------------------------------------------------------------------

#include <algorithm>
#include <array>
#include <cctype>
#include <cmath>
#include <cstddef>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <optional>
#include <sstream>
#include <string>
#include <string_view>
#include <vector>

namespace {

[[nodiscard]] constexpr auto is_ascii_digit(const char c) noexcept -> bool {
    return c >= '0' && c <= '9';
}

struct Args {
    std::filesystem::path points{};
    std::filesystem::path order{};
    std::size_t block_size{32U};
};

[[nodiscard]] auto usage() -> int {
    std::cerr << "usage: rch_block_read_probe --points points.csv --order order.csv "
                 "[--block-size N]\n";
    return 2;
}

[[nodiscard]] auto parse_size(const std::string_view value) -> std::optional<std::size_t> {
    if (value.empty() || !std::ranges::all_of(value, is_ascii_digit)) {
        return std::nullopt;
    }
    try {
        std::size_t used = 0U;
        const auto parsed = std::stoull(std::string{value}, &used, 10);
        if (used != value.size() ||
            parsed > static_cast<unsigned long long>(std::numeric_limits<std::size_t>::max())) {
            return std::nullopt;
        }
        return static_cast<std::size_t>(parsed);
    } catch (...) {
        return std::nullopt;
    }
}

[[nodiscard]] auto parse_args(const int argc, char** argv) -> std::optional<Args> {
    Args args{};
    for (int i = 1; i < argc; ++i) {
        const std::string_view flag{argv[i]};
        if (i + 1 >= argc) {
            return std::nullopt;
        }
        const std::string_view value{argv[++i]};
        if (flag == "--points") {
            args.points = value;
        } else if (flag == "--order") {
            args.order = value;
        } else if (flag == "--block-size") {
            const auto block_size = parse_size(value);
            if (!block_size.has_value() || *block_size < 2U) {
                return std::nullopt;
            }
            args.block_size = *block_size;
        } else {
            return std::nullopt;
        }
    }
    if (args.points.empty() || args.order.empty()) {
        return std::nullopt;
    }
    return args;
}

[[nodiscard]] auto is_blank_line(const std::string_view line) -> bool {
    return std::ranges::all_of(line, [](const char value) noexcept {
        return std::isspace(static_cast<unsigned char>(value)) != 0;
    });
}

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

[[nodiscard]] auto read_points(const std::filesystem::path& path)
    -> std::optional<std::vector<double>> {
    std::ifstream input{path};
    if (!input.is_open()) {
        return std::nullopt;
    }
    std::vector<double> points{};
    std::string line{};
    while (std::getline(input, line)) {
        if (is_blank_line(line)) {
            continue;
        }
        const auto parsed = parse_point_line(line);
        if (!parsed.has_value()) {
            return std::nullopt;
        }
        points.push_back((*parsed)[0]);
        points.push_back((*parsed)[1]);
        points.push_back((*parsed)[2]);
    }
    return points;
}

// Read the `rank,raw_index,key` order file emitted by `rch_order`.
[[nodiscard]] auto read_order(const std::filesystem::path& path)
    -> std::optional<std::vector<std::size_t>> {
    std::ifstream input{path};
    if (!input.is_open()) {
        return std::nullopt;
    }
    std::vector<std::size_t> order{};
    std::string line{};
    if (!std::getline(input, line)) {
        return std::nullopt;
    }
    if (line != "rank,raw_index,key") {
        return std::nullopt;
    }
    while (std::getline(input, line)) {
        std::istringstream stream{line};
        std::string rank{};
        std::string raw{};
        if (!std::getline(stream, rank, ',') || !std::getline(stream, raw, ',')) {
            return std::nullopt;
        }
        const auto parsed = parse_size(raw);
        if (!parsed.has_value()) {
            return std::nullopt;
        }
        order.push_back(*parsed);
    }
    return order;
}

// Simulate block-ordered coordinate reads with a deterministic linear checksum.
[[nodiscard]] auto block_read_checksum(
    const std::vector<double>& points,
    const std::vector<std::size_t>& order,
    const std::size_t block_size
) -> std::optional<double> {
    const std::size_t point_count = points.size() / 3U;
    double checksum = 0.0;
    for (std::size_t start = 0U; start < order.size(); start += block_size) {
        const std::size_t stop = std::min(order.size(), start + block_size);
        for (std::size_t rank = start; rank < stop; ++rank) {
            const std::size_t raw = order[rank];
            if (raw >= point_count) {
                return std::nullopt;
            }
            const std::size_t base = raw * 3U;
            checksum += points[base] * 0.25 + points[base + 1U] * 0.5 + points[base + 2U];
        }
    }
    return checksum;
}

} // namespace

int main(const int argc, char** argv) {
    const auto args = parse_args(argc, argv);
    if (!args.has_value()) {
        return usage();
    }
    const auto points = read_points(args->points);
    if (!points.has_value() || (points->size() % 3U) != 0U) {
        std::cerr << "failed to read points\n";
        return 1;
    }
    const auto order = read_order(args->order);
    if (!order.has_value()) {
        std::cerr << "failed to read order\n";
        return 1;
    }
    const auto checksum = block_read_checksum(*points, *order, args->block_size);
    if (!checksum.has_value()) {
        std::cerr << "order index out of range\n";
        return 1;
    }
    std::cout << std::setprecision(17) << *checksum << '\n';
    return 0;
}
