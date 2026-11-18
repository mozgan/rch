#include <algorithm>
#include <array>
#include <charconv>
#include <chrono>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <ctime>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <optional>
#include <span>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <system_error>
#include <vector>

#include "rch/application/page_directory.hpp"
#include "rch/application/window_query.hpp"
#include "rch/core/sha256.hpp"
#include "rch/io/xyz_parse.hpp"

namespace {

struct Args final {
    std::filesystem::path points{};
    std::filesystem::path a0_order{};
    std::filesystem::path a3_order{};
    std::filesystem::path a6_order{};
    std::array<std::filesystem::path, 3> native_orders{};
    std::string layout_order{};
    std::filesystem::path output_dir{};
    std::filesystem::path query_windows{};
    std::string dataset_id{};
    std::string source_sha256{};
    std::size_t warm_cache_repeats{};
};

struct LayoutInput final {
    std::uint64_t layout_id{};
    std::string_view name{};
    std::filesystem::path order_path{};
};

struct QueryInput final {
    std::string id{};
    rch::application::QueryWindow window{};
};

[[nodiscard]] auto parse_u64(std::string_view token, std::string_view field) -> std::uint64_t;

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
        } else if (flag == "--a0-order") {
            args.a0_order = value;
        } else if (flag == "--a3-order") {
            args.a3_order = value;
        } else if (flag == "--a6-order") {
            args.a6_order = value;
        } else if (flag == "--a6-c2-order") {
            args.native_orders[0] = value;
        } else if (flag == "--a6-c3-order") {
            args.native_orders[1] = value;
        } else if (flag == "--a6-c4-order") {
            args.native_orders[2] = value;
        } else if (flag == "--layout-order") {
            args.layout_order = value;
        } else if (flag == "--output-dir") {
            args.output_dir = value;
        } else if (flag == "--query-windows") {
            args.query_windows = value;
        } else if (flag == "--dataset-id") {
            args.dataset_id = value;
        } else if (flag == "--source-sha256") {
            args.source_sha256 = value;
        } else if (flag == "--warm-cache-repeats") {
            const auto repeats = parse_u64(value, "warm-cache-repeats");
            if (repeats > std::numeric_limits<std::size_t>::max() || repeats > 10'000U) {
                return std::nullopt;
            }
            args.warm_cache_repeats = static_cast<std::size_t>(repeats);
        } else {
            return std::nullopt;
        }
    }
    if (args.points.empty() || args.a0_order.empty() || args.a3_order.empty() ||
        args.a6_order.empty() || args.output_dir.empty() || args.dataset_id.empty() ||
        args.source_sha256.size() != 64U) {
        return std::nullopt;
    }
    const auto native_count =
        std::ranges::count_if(args.native_orders, [](const auto& path) { return !path.empty(); });
    if (native_count != 0 && native_count != 3)
        return std::nullopt;
    return args;
}

[[nodiscard]] auto process_read_bytes() -> std::optional<std::uint64_t> {
#if defined(__linux__)
    std::ifstream input("/proc/self/io");
    std::string name;
    std::uint64_t value{};
    while (input >> name >> value) {
        if (name == "read_bytes:") {
            return value;
        }
    }
#endif
    return std::nullopt;
}

[[nodiscard]] auto peak_rss_kib() -> std::optional<std::uint64_t> {
#if defined(__linux__)
    std::ifstream status("/proc/self/status");
    std::string key;
    while (status >> key) {
        if (key == "VmHWM:") {
            std::uint64_t value{};
            std::string unit;
            if (status >> value >> unit && unit == "kB") {
                return value;
            }
            return std::nullopt;
        }
        std::string rest;
        std::getline(status, rest);
    }
#endif
    return std::nullopt;
}

[[nodiscard]] auto parse_sha256(const std::string_view text) -> std::array<std::uint8_t, 32> {
    const auto nibble = [](const char c) -> std::optional<std::uint8_t> {
        if (c >= '0' && c <= '9') {
            return static_cast<std::uint8_t>(c - '0');
        }
        if (c >= 'a' && c <= 'f') {
            return static_cast<std::uint8_t>(c - 'a' + 10);
        }
        if (c >= 'A' && c <= 'F') {
            return static_cast<std::uint8_t>(c - 'A' + 10);
        }
        return std::nullopt;
    };
    std::array<std::uint8_t, 32> digest{};
    for (std::size_t i = 0U; i < digest.size(); ++i) {
        const auto high = nibble(text[2U * i]);
        const auto low = nibble(text[2U * i + 1U]);
        if (!high.has_value() || !low.has_value()) {
            throw std::invalid_argument("source SHA-256 must contain 64 hexadecimal digits");
        }
        digest[i] = static_cast<std::uint8_t>((*high << 4U) | *low);
    }
    return digest;
}

[[nodiscard]] auto parse_u64(const std::string_view token, const std::string_view field)
    -> std::uint64_t {
    std::uint64_t value{};
    const auto [end, error] = std::from_chars(token.data(), token.data() + token.size(), value);
    if (error != std::errc{} || end != token.data() + token.size()) {
        throw std::runtime_error("invalid " + std::string{field} + " in ordering file");
    }
    return value;
}

[[nodiscard]] auto read_points(const std::filesystem::path& path)
    -> std::vector<rch::application::PointRecord> {
    std::ifstream input(path);
    if (!input) {
        throw std::runtime_error("cannot open points CSV: " + path.string());
    }
    std::vector<rch::application::PointRecord> points;
    std::string line;
    while (std::getline(input, line)) {
        if (line.empty()) {
            continue;
        }
        const auto coordinates = rch::io::parse_three_doubles(line);
        if (!coordinates.has_value()) {
            throw std::runtime_error("invalid xyz row in points CSV");
        }
        points.push_back({static_cast<std::uint64_t>(points.size()), *coordinates});
    }
    if (points.empty()) {
        throw std::runtime_error("points CSV contains no records");
    }
    return points;
}

[[nodiscard]] auto read_order(const std::filesystem::path& path, const std::size_t point_count)
    -> std::vector<std::size_t> {
    std::ifstream input(path);
    if (!input) {
        throw std::runtime_error("cannot open ordering CSV: " + path.string());
    }
    std::string line;
    if (!std::getline(input, line) || line != "rank,raw_index,key") {
        throw std::runtime_error("ordering CSV has an unexpected header");
    }

    std::vector<std::size_t> order;
    order.reserve(point_count);
    std::vector<bool> seen(point_count, false);
    while (std::getline(input, line)) {
        std::array<std::string_view, 3> fields{};
        std::size_t field_index = 0U;
        std::size_t start = 0U;
        for (std::size_t i = 0U; i <= line.size(); ++i) {
            if (i == line.size() || line[i] == ',') {
                if (field_index >= fields.size()) {
                    throw std::runtime_error("ordering CSV row has extra columns");
                }
                fields[field_index++] = std::string_view{line}.substr(start, i - start);
                start = i + 1U;
            }
        }
        if (field_index != fields.size()) {
            throw std::runtime_error("ordering CSV row must have three columns");
        }
        const auto rank = parse_u64(fields[0], "rank");
        const auto raw_index = parse_u64(fields[1], "raw index");
        if (rank != order.size() || raw_index >= point_count || seen[raw_index]) {
            throw std::runtime_error("ordering CSV is not a complete point permutation");
        }
        seen[raw_index] = true;
        order.push_back(static_cast<std::size_t>(raw_index));
    }
    if (order.size() != point_count) {
        throw std::runtime_error("ordering CSV does not contain every point");
    }
    return order;
}

[[nodiscard]] auto build_queries(const std::span<const rch::application::PointRecord> points)
    -> std::array<QueryInput, 4> {
    auto minimum = points.front().xyz;
    auto maximum = points.front().xyz;
    for (const auto& point : points) {
        for (std::size_t axis = 0U; axis < 3U; ++axis) {
            minimum[axis] = std::min(minimum[axis], point.xyz[axis]);
            maximum[axis] = std::max(maximum[axis], point.xyz[axis]);
        }
    }
    std::array<double, 3> center{};
    double diagonal_squared = 0.0;
    for (std::size_t axis = 0U; axis < 3U; ++axis) {
        const auto extent = maximum[axis] - minimum[axis];
        center[axis] = minimum[axis] + extent * 0.5;
        diagonal_squared += extent * extent;
    }
    const auto diagonal = std::sqrt(diagonal_squared);
    const auto margin = std::max(1.0, diagonal * 0.1);
    std::array<double, 3> local_minimum{};
    std::array<double, 3> local_maximum{};
    std::array<double, 3> empty_minimum{};
    std::array<double, 3> empty_maximum{};
    for (std::size_t axis = 0U; axis < 3U; ++axis) {
        const auto half_width = (maximum[axis] - minimum[axis]) * 0.05;
        local_minimum[axis] = std::max(minimum[axis], center[axis] - half_width);
        local_maximum[axis] = std::min(maximum[axis], center[axis] + half_width);
        empty_minimum[axis] = maximum[axis] + margin;
        empty_maximum[axis] = maximum[axis] + 2.0 * margin;
        if (!std::isfinite(empty_maximum[axis])) {
            throw std::runtime_error("cannot construct finite outside-bounds smoke query");
        }
    }
    const auto& selected = points[points.size() / 2U].xyz;
    return {{
        {"bbox_all", {minimum, maximum}},
        {"center_local", {local_minimum, local_maximum}},
        {"point_exact", {selected, selected}},
        {"outside_empty", {empty_minimum, empty_maximum}},
    }};
}

[[nodiscard]] auto parse_double(const std::string_view token) -> double {
    double value{};
    const auto [end, error] = std::from_chars(
        token.data(), token.data() + token.size(), value, std::chars_format::general
    );
    if (error != std::errc{} || end != token.data() + token.size() || !std::isfinite(value)) {
        throw std::runtime_error("query window contains an invalid finite coordinate");
    }
    return value;
}

[[nodiscard]] auto read_query_windows(const std::filesystem::path& path)
    -> std::vector<QueryInput> {
    std::ifstream input(path);
    if (!input) {
        throw std::runtime_error("cannot open query windows CSV: " + path.string());
    }
    std::string line;
    constexpr std::string_view header{"query_id,min_x,min_y,min_z,max_x,max_y,max_z"};
    if (!std::getline(input, line) || line != header) {
        throw std::runtime_error("query windows CSV has an unexpected header");
    }
    std::vector<QueryInput> queries;
    std::vector<std::string> query_ids;
    while (std::getline(input, line)) {
        std::array<std::string_view, 7> fields{};
        std::size_t field_index = 0U;
        std::size_t start = 0U;
        for (std::size_t i = 0U; i <= line.size(); ++i) {
            if (i == line.size() || line[i] == ',') {
                if (field_index >= fields.size()) {
                    throw std::runtime_error("query window row has extra fields");
                }
                fields[field_index++] = std::string_view{line}.substr(start, i - start);
                start = i + 1U;
            }
        }
        if (field_index != fields.size() || fields[0].empty()) {
            throw std::runtime_error("query window row must contain an ID and six coordinates");
        }
        if (std::find(query_ids.begin(), query_ids.end(), fields[0]) != query_ids.end()) {
            throw std::runtime_error("query windows CSV contains a duplicate query ID");
        }
        rch::application::QueryWindow window{};
        for (std::size_t axis = 0U; axis < 3U; ++axis) {
            window.minimum[axis] = parse_double(fields[axis + 1U]);
            window.maximum[axis] = parse_double(fields[axis + 4U]);
        }
        rch::application::detail::validate_query_window(window);
        query_ids.emplace_back(fields[0]);
        queries.push_back({query_ids.back(), window});
    }
    if (queries.empty()) {
        throw std::runtime_error("query windows CSV contains no queries");
    }
    return queries;
}

[[nodiscard]] auto hash_ids(const std::span<const std::uint64_t> ids)
    -> std::array<std::uint8_t, 32> {
    rch::core::Sha256 hash{};
    for (const auto id : ids) {
        hash.update_u64_le(id);
    }
    return hash.finalize();
}

[[nodiscard]] auto hash_hex(const std::array<std::uint8_t, 32>& digest) -> std::string {
    constexpr std::string_view hex{"0123456789abcdef"};
    std::string result;
    result.reserve(64U);
    for (const auto byte : digest) {
        result.push_back(hex[byte >> 4U]);
        result.push_back(hex[byte & 0x0FU]);
    }
    return result;
}

void write_query_windows(
    const std::filesystem::path& path, const std::span<const QueryInput> queries
) {
    std::ofstream output(path);
    if (!output) {
        throw std::runtime_error("cannot create query window CSV");
    }
    output << std::setprecision(std::numeric_limits<double>::max_digits10);
    output << "query_id,min_x,min_y,min_z,max_x,max_y,max_z\n";
    for (const auto& query : queries) {
        output << query.id;
        for (const auto value : query.window.minimum) {
            output << ',' << value;
        }
        for (const auto value : query.window.maximum) {
            output << ',' << value;
        }
        output << '\n';
    }
}

void run_dataset(const Args& args, const std::span<const rch::application::PointRecord> original) {
    std::vector<LayoutInput> layouts{
        {0U, "A0_input", args.a0_order},
        {0U, "A0_full_scan", args.a0_order},
        {3U, "A3_isotropic_hilbert", args.a3_order},
        {6U, "A6_rch", args.a6_order},
    };
    if (!args.native_orders[0].empty()) {
        layouts.push_back({62U, "A6_rch_C2", args.native_orders[0]});
        layouts.push_back({63U, "A6_rch_C3", args.native_orders[1]});
        layouts.push_back({64U, "A6_rch_C4", args.native_orders[2]});
    }
    if (!args.layout_order.empty()) {
        if (args.layout_order.back() == ',')
            throw std::runtime_error("invalid layout schedule");
        std::istringstream stream(args.layout_order);
        std::vector<LayoutInput> scheduled;
        std::string name;
        while (std::getline(stream, name, ',')) {
            const auto found = std::ranges::find_if(layouts, [&name](const auto& layout) {
                return layout.name == name;
            });
            if (found == layouts.end() ||
                std::ranges::any_of(scheduled, [&name](const auto& layout) {
                    return layout.name == name;
                }))
                throw std::runtime_error("unknown or duplicate layout in schedule");
            scheduled.push_back(*found);
        }
        if (scheduled.size() != layouts.size())
            throw std::runtime_error("incomplete layout schedule");
        layouts = std::move(scheduled);
    }
    const auto active_queries = args.query_windows.empty() ? [&original] {
        const auto defaults = build_queries(original);
        return std::vector<QueryInput>{defaults.begin(), defaults.end()};
    }()
                                                           : read_query_windows(args.query_windows);
    std::filesystem::create_directories(args.output_dir);
    const auto windows_path = args.output_dir / "query_windows.csv";
    write_query_windows(windows_path, active_queries);
    const auto results_path = args.output_dir / "query_results.csv";
    std::ofstream results(results_path);
    if (!results) {
        throw std::runtime_error("cannot create query result CSV");
    }
    results << "dataset_id,layout_id,query_id,result_count,result_ids_sha256,candidate_pages,pages_"
               "read,oracle_match\n";
    std::ofstream query_metrics{};
    if (args.warm_cache_repeats > 0U) {
        query_metrics.open(args.output_dir / "query_metrics.csv");
        if (!query_metrics) {
            throw std::runtime_error("cannot create warm-cache query metrics CSV");
        }
        query_metrics
            << "dataset_id,layout_id,query_id,repeat,wall_seconds,cpu_seconds,logical_bytes_read,"
               "candidate_pages,pages_read,records_examined,selectivity,process_read_bytes_delta,"
               "result_count,result_ids_sha256,"
               "oracle_match\n";
    }

    const auto metadata_checksum = parse_sha256(args.source_sha256);
    for (const auto& layout : layouts) {
        const auto order = read_order(layout.order_path, original.size());
        std::vector<rch::application::PointRecord> ordered;
        ordered.reserve(order.size());
        for (const auto raw_index : order) {
            auto point = original[raw_index];
            point.id = static_cast<std::uint64_t>(raw_index);
            ordered.push_back(point);
        }

        const auto page_path = args.output_dir / (std::string{layout.name} + ".page");
        const auto index_path = args.output_dir / (std::string{layout.name} + ".index");
        const auto page_write_start = std::chrono::steady_clock::now();
        rch::application::PageFileWriter::write(
            page_path, ordered, {layout.layout_id, metadata_checksum}
        );
        const auto page_write_seconds =
            std::chrono::duration<double>(std::chrono::steady_clock::now() - page_write_start)
                .count();

        const auto index_build_start = std::chrono::steady_clock::now();
        const auto built_directory = rch::application::build_page_directory(ordered);
        const auto index_build_seconds =
            std::chrono::duration<double>(std::chrono::steady_clock::now() - index_build_start)
                .count();
        const auto index_write_start = std::chrono::steady_clock::now();
        rch::application::PageDirectoryFileWriter::write(
            index_path, static_cast<std::uint64_t>(ordered.size()), built_directory
        );
        const auto index_write_seconds =
            std::chrono::duration<double>(std::chrono::steady_clock::now() - index_write_start)
                .count();
        const auto loaded_directory = rch::application::PageDirectoryFileReader::read(index_path);
        if (loaded_directory.record_count != ordered.size()) {
            throw std::runtime_error("page-directory record count does not match page file");
        }

        rch::application::PageFileReader page_file{page_path};
        const auto checksum_start = std::chrono::steady_clock::now();
        if (!page_file.verify_payload_checksum()) {
            throw std::runtime_error("page-file payload checksum mismatch");
        }
        const auto checksum_verify_seconds =
            std::chrono::duration<double>(std::chrono::steady_clock::now() - checksum_start)
                .count();

        const auto readback_start = std::chrono::steady_clock::now();
        for (std::size_t page_index = 0U; page_index < loaded_directory.entries.size();
             ++page_index) {
            const auto page_records = page_file.read_page(static_cast<std::uint64_t>(page_index));
            const auto first_record = page_index * rch::application::kRecordsPerPage;
            if (!std::equal(
                    page_records.begin(),
                    page_records.end(),
                    ordered.begin() + static_cast<std::ptrdiff_t>(first_record)
                )) {
                throw std::runtime_error("page-file records differ from ordered input");
            }
            const auto& bounds = loaded_directory.entries[page_index];
            for (const auto& point : page_records) {
                for (std::size_t axis = 0U; axis < 3U; ++axis) {
                    if (point.xyz[axis] < bounds.minimum[axis] ||
                        point.xyz[axis] > bounds.maximum[axis]) {
                        throw std::runtime_error("page AABB does not cover a stored record");
                    }
                }
            }
        }
        const auto readback_verify_seconds =
            std::chrono::duration<double>(std::chrono::steady_clock::now() - readback_start)
                .count();

        const auto integrity_path =
            args.output_dir / (std::string{layout.name} + ".integrity.json");
        std::ofstream integrity(integrity_path);
        if (!integrity) {
            throw std::runtime_error("cannot write storage integrity manifest");
        }
        integrity << std::setprecision(std::numeric_limits<double>::max_digits10)
                  << "{\n  \"schema\": \"rch.application_storage_integrity.v1\",\n"
                  << "  \"dataset_id\": \"" << args.dataset_id << "\",\n"
                  << "  \"layout_id\": \"" << layout.name << "\",\n"
                  << "  \"record_count\": " << ordered.size() << ",\n"
                  << "  \"page_count\": " << loaded_directory.entries.size() << ",\n"
                  << "  \"page_file_bytes\": " << std::filesystem::file_size(page_path) << ",\n"
                  << "  \"index_file_bytes\": " << std::filesystem::file_size(index_path) << ",\n"
                  << "  \"page_payload_checksum_verified\": true,\n"
                  << "  \"page_directory_checksum_verified\": true,\n"
                  << "  \"page_readback_verified\": true,\n"
                  << "  \"page_aabb_coverage_verified\": true,\n"
                  << "  \"peak_rss_kib\": ";
        if (const auto rss = peak_rss_kib(); rss.has_value()) {
            integrity << *rss;
        } else {
            integrity << "null";
        }
        integrity << ",\n"
                  << "  \"flush_called\": true,\n"
                  << "  \"fsync_performed\": false,\n"
                  << "  \"page_file_write_seconds\": " << page_write_seconds << ",\n"
                  << "  \"index_build_seconds\": " << index_build_seconds << ",\n"
                  << "  \"index_write_seconds\": " << index_write_seconds << ",\n"
                  << "  \"page_checksum_verify_seconds\": " << checksum_verify_seconds << ",\n"
                  << "  \"page_readback_verify_seconds\": " << readback_verify_seconds << "\n}\n";
        integrity.flush();
        if (!integrity) {
            throw std::runtime_error("cannot finalize storage integrity manifest");
        }

        std::vector<std::vector<std::uint64_t>> expected_results;
        expected_results.reserve(active_queries.size());
        for (const auto& query : active_queries) {
            const auto expected = rch::application::full_scan_query_oracle(original, query.window);
            expected_results.push_back(expected);
            const auto actual = rch::application::execute_page_pruned_query(
                page_file, loaded_directory.entries, query.window, layout.name == "A0_full_scan"
            );
            const auto matches = actual.point_ids == expected;
            results << args.dataset_id << ',' << layout.name << ',' << query.id << ','
                    << actual.point_ids.size() << ',' << hash_hex(hash_ids(actual.point_ids)) << ','
                    << actual.candidate_pages << ',' << actual.pages_read << ','
                    << (matches ? "true" : "false") << '\n';
            results.flush();
            if (!matches) {
                throw std::runtime_error("page query result does not match full-scan oracle");
            }
        }
        if (args.warm_cache_repeats > 0U) {
            // Warm the complete workload once before taking any timed sample.
            for (std::size_t query_index = 0U; query_index < active_queries.size(); ++query_index) {
                const auto warmup = rch::application::execute_page_pruned_query(
                    page_file,
                    loaded_directory.entries,
                    active_queries[query_index].window,
                    layout.name == "A0_full_scan"
                );
                if (warmup.point_ids != expected_results[query_index]) {
                    throw std::runtime_error("warm-up query differs from full-scan oracle");
                }
            }
            for (std::size_t repeat = 1U; repeat <= args.warm_cache_repeats; ++repeat) {
                for (std::size_t query_index = 0U; query_index < active_queries.size();
                     ++query_index) {
                    const auto& query = active_queries[query_index];
                    const auto& expected = expected_results[query_index];
                    const auto io_before = process_read_bytes();
                    const auto cpu_before = std::clock();
                    const auto query_start = std::chrono::steady_clock::now();
                    const auto measured = rch::application::execute_page_pruned_query(
                        page_file,
                        loaded_directory.entries,
                        query.window,
                        layout.name == "A0_full_scan"
                    );
                    const auto wall_seconds = std::chrono::duration<double>(
                                                  std::chrono::steady_clock::now() - query_start
                    )
                                                  .count();
                    const auto cpu_after = std::clock();
                    const auto cpu_seconds = cpu_after >= cpu_before
                                                 ? static_cast<double>(cpu_after - cpu_before) /
                                                       static_cast<double>(CLOCKS_PER_SEC)
                                                 : 0.0;
                    const auto io_after = process_read_bytes();
                    const auto io_available =
                        io_before.has_value() && io_after.has_value() && *io_after >= *io_before;
                    const auto io_delta = io_available ? *io_after - *io_before : 0U;
                    const auto measured_matches = measured.point_ids == expected;
                    const auto logical_bytes =
                        measured.pages_read * rch::application::kPageFilePageBytes;
                    query_metrics << args.dataset_id << ',' << layout.name << ',' << query.id << ','
                                  << repeat << ',' << std::setprecision(17) << wall_seconds << ','
                                  << cpu_seconds << ',' << logical_bytes << ','
                                  << measured.candidate_pages << ',' << measured.pages_read << ','
                                  << measured.records_examined << ','
                                  << static_cast<double>(measured.point_ids.size()) /
                                         static_cast<double>(original.size())
                                  << ',';
                    if (io_available) {
                        query_metrics << io_delta;
                    }
                    query_metrics << ',' << measured.point_ids.size() << ','
                                  << hash_hex(hash_ids(measured.point_ids)) << ','
                                  << (measured_matches ? "true" : "false") << '\n';
                    query_metrics.flush();
                    if (!measured_matches) {
                        throw std::runtime_error("measured query differs from full-scan oracle");
                    }
                }
            }
        }
        std::ofstream memory(args.output_dir / (std::string{layout.name} + ".query_memory.json"));
        memory << "{\n  \"scope\": \"process cumulative high-water mark after this layout; "
                  "includes previous layouts and oracle\",\n  \"peak_rss_kib\": ";
        if (const auto rss = peak_rss_kib(); rss.has_value()) {
            memory << *rss;
        } else {
            memory << "null";
        }
        memory << "\n}\n";
        memory.flush();
        if (!memory) {
            throw std::runtime_error("cannot finalize query memory record");
        }
        std::cout << args.dataset_id << ' ' << layout.name << ": " << active_queries.size()
                  << " query windows matched oracle\n";
    }
}

} // namespace

int main(const int argc, char** argv) {
    const auto args = parse_args(argc, argv);
    if (!args.has_value()) {
        std::cerr << "usage: rch_application_query_smoke --dataset-id ID --points xyz.csv "
                     "--a0-order order.csv --a3-order order.csv --a6-order order.csv "
                     "--source-sha256 HEX --output-dir DIR [--warm-cache-repeats N] "
                     "[--query-windows CSV] [--a6-c2-order CSV --a6-c3-order CSV --a6-c4-order "
                     "CSV] [--layout-order IDs]\n";
        return 2;
    }
    try {
        const auto points = read_points(args->points);
        run_dataset(*args, points);
    } catch (const std::exception& error) {
        std::cerr << "application query smoke failed: " << error.what() << '\n';
        return 1;
    }
    return 0;
}
