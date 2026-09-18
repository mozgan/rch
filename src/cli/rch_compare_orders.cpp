// ----------------------------------------------------------------------------
// rch_compare_orders.cpp - compare two ordering CSV files by raw indices.
//
// Algorithm:
//   - Read optional `rank,raw_index,key` headers.
//   - Extract the second CSV field as a strict base-10 raw index.
//   - Return success iff the raw-index sequences are identical.
//
// References:
//   Shafranovich, Common Format and MIME Type for CSV Files, 2005,
//   DOI: 10.17487/RFC4180.
//   ISO/IEC, Programming Languages - C++, 2020.
// ----------------------------------------------------------------------------

#include <algorithm>
#include <cstdint>
#include <filesystem>
#include <fstream>
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

[[nodiscard]] auto usage() -> int {
    std::cerr << "usage: rch_compare_orders left.csv right.csv\n";
    return 2;
}

// Reject signs and trailing text in raw-index fields.
[[nodiscard]] auto parse_u64_token(const std::string_view token) -> std::optional<std::uint64_t> {
    if (token.empty() || !std::ranges::all_of(token, is_ascii_digit)) {
        return std::nullopt;
    }
    try {
        std::size_t used = 0U;
        const auto parsed = std::stoull(std::string{token}, &used, 10);
        if (used != token.size() ||
            parsed > static_cast<unsigned long long>(std::numeric_limits<std::uint64_t>::max())) {
            return std::nullopt;
        }
        return static_cast<std::uint64_t>(parsed);
    } catch (...) {
        return std::nullopt;
    }
}

[[nodiscard]] auto parse_raw_index_line(const std::string& line) -> std::optional<std::uint64_t> {
    std::istringstream stream{line};
    std::string rank{};
    std::string raw{};
    if (!std::getline(stream, rank, ',') || !std::getline(stream, raw, ',')) {
        return std::nullopt;
    }
    return parse_u64_token(raw);
}

[[nodiscard]] auto read_raw_indices(const std::filesystem::path& path)
    -> std::optional<std::vector<std::uint64_t>> {
    std::ifstream input{path};
    if (!input.is_open()) {
        return std::nullopt;
    }
    std::vector<std::uint64_t> indices{};
    std::string line{};
    bool first = true;
    while (std::getline(input, line)) {
        if (first) {
            first = false;
            if (line == "rank,raw_index,key") {
                continue;
            }
        }
        const auto parsed = parse_raw_index_line(line);
        if (!parsed.has_value()) {
            return std::nullopt;
        }
        indices.push_back(*parsed);
    }
    return indices;
}

} // namespace

int main(const int argc, char** argv) {
    if (argc != 3) {
        return usage();
    }
    const auto left = read_raw_indices(argv[1]);
    const auto right = read_raw_indices(argv[2]);
    if (!left.has_value() || !right.has_value()) {
        std::cerr << "failed to parse one or both CSV files\n";
        return 2;
    }
    if (*left != *right) {
        std::cerr << "orders differ\n";
        return 1;
    }
    std::cout << "orders match\n";
    return 0;
}
