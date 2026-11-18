// One fresh-process storage/query workflow. Oracle generation and verification are
// outside the continuous timer; actual result IDs and file fsync are inside it.
#include <fcntl.h>
#include <sys/mman.h>
#include <sys/resource.h>
#include <unistd.h>

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <optional>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

#include "rch/application/page_directory.hpp"
#include "rch/application/window_query.hpp"
#include "rch/core/sha256.hpp"
#include "rch/io/xyz_parse.hpp"
#include "rch/orderings/orderer.hpp"

namespace {
namespace app = rch::application;
using Clock = std::chrono::steady_clock;
struct Query {
    std::string id;
    app::QueryWindow window;
    std::uint64_t count;
    std::string hash;
};
struct IO {
    std::optional<std::uint64_t> read, write;
};
auto io() -> IO {
    std::ifstream input("/proc/self/io");
    IO result;
    std::string key;
    std::uint64_t value{};
    while (input >> key >> value) {
        if (key == "read_bytes:")
            result.read = value;
        if (key == "write_bytes:")
            result.write = value;
    }
    return result;
}
auto delta(std::optional<std::uint64_t> a, std::optional<std::uint64_t> b) -> std::string {
    return a && b && *b >= *a ? std::to_string(*b - *a) : "null";
}
auto hex(const std::array<std::uint8_t, 32>& value) -> std::string {
    std::ostringstream out;
    out << std::hex << std::setfill('0');
    for (auto byte : value)
        out << std::setw(2) << unsigned(byte);
    return out.str();
}
void put(std::ostream& out, std::uint64_t value) {
    std::array<char, 8> bytes{};
    for (auto& byte : bytes) {
        byte = static_cast<char>(value & 255U);
        value >>= 8U;
    }
    out.write(bytes.data(), 8);
}
auto get(std::istream& input) -> std::uint64_t {
    std::array<unsigned char, 8> bytes{};
    if (!input.read(reinterpret_cast<char*>(bytes.data()), 8))
        throw std::runtime_error("truncated results");
    std::uint64_t value{};
    for (unsigned i = 0; i < 8; ++i)
        value |= std::uint64_t(bytes[i]) << (8U * i);
    return value;
}
auto queries(const std::filesystem::path& path) -> std::vector<Query> {
    std::ifstream input(path);
    if (!input)
        throw std::runtime_error("cannot open frozen workload");
    std::vector<Query> result;
    std::set<std::string> ids;
    std::string line;
    while (std::getline(input, line)) {
        Query q{};
        std::istringstream row(line);
        if (!(row >> q.id >> q.window.minimum[0] >> q.window.minimum[1] >> q.window.minimum[2] >>
              q.window.maximum[0] >> q.window.maximum[1] >> q.window.maximum[2] >> q.count >>
              q.hash))
            throw std::runtime_error("invalid frozen workload");
        std::string extra;
        if (row >> extra || !ids.insert(q.id).second ||
            q.id.find_first_not_of(
                "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
            ) != std::string::npos ||
            q.hash.size() != 64 ||
            q.hash.find_first_not_of("0123456789abcdef") != std::string::npos)
            throw std::runtime_error("invalid query ID/hash or duplicate query");
        app::detail::validate_query_window(q.window);
        result.push_back(q);
    }
    if (result.empty() || result.size() > 1024)
        throw std::runtime_error("query count must be 1..1024");
    return result;
}
// Reproducible warm input only. Newly written page files retain their natural
// page-cache state; this is not a cold-device experiment.
void warm_input(const std::filesystem::path& path) {
    const int fd = ::open(path.c_str(), O_RDONLY | O_CLOEXEC);
    if (fd < 0)
        throw std::runtime_error("cannot open input for cache setup");
    const auto size = std::filesystem::file_size(path);
    if (size == 0) {
        ::close(fd);
        throw std::runtime_error("empty input file");
    }
    std::array<char, 65536> buffer{};
    ssize_t n;
    do {
        n = ::read(fd, buffer.data(), buffer.size());
    } while (n > 0);
    if (n < 0) {
        ::close(fd);
        throw std::runtime_error("input cache setup failed");
    }
    void* mapping = ::mmap(nullptr, size, PROT_READ, MAP_SHARED, fd, 0);
    if (mapping == MAP_FAILED) {
        ::close(fd);
        throw std::runtime_error("input mmap failed");
    }
    const auto page_size = ::sysconf(_SC_PAGESIZE);
    if (page_size <= 0) {
        ::munmap(mapping, size);
        ::close(fd);
        throw std::runtime_error("cannot determine page size");
    }
    const auto page = static_cast<std::size_t>(page_size);
    std::vector<unsigned char> states((size + page - 1) / page);
    const bool resident =
        ::mincore(mapping, size, states.data()) == 0 &&
        std::all_of(states.begin(), states.end(), [](auto s) { return (s & 1U) != 0; });
    ::munmap(mapping, size);
    ::close(fd);
    if (!resident)
        throw std::runtime_error("warm input residency not verified");
}
void sync_file(const std::filesystem::path& path) {
    const int fd = ::open(path.c_str(), O_RDONLY | O_CLOEXEC);
    if (fd < 0)
        throw std::runtime_error("cannot open output for fsync");
    const int status = ::fsync(fd);
    const int closed = ::close(fd);
    if (status != 0 || closed != 0)
        throw std::runtime_error("output fsync/close failed");
}
auto seconds(Clock::time_point a, Clock::time_point b) -> double {
    return std::chrono::duration<double>(b - a).count();
}
auto cpu(const rusage& r) -> double {
    return double(r.ru_utime.tv_sec + r.ru_stime.tv_sec) +
           double(r.ru_utime.tv_usec + r.ru_stime.tv_usec) / 1e6;
}
void run(
    const std::filesystem::path& input_path,
    const std::filesystem::path& workload,
    const std::string& layout,
    const std::filesystem::path& output
) {
    rch::orderings::OrderingConfig config;
    config.refinement = rch::orderings::RefinementMode::Off;
    if (layout == "A0_input")
        config.method = rch::orderings::OrderingMethod::InputOrder;
    else if (layout == "A3_isotropic_hilbert") {
        config.method = rch::orderings::OrderingMethod::IsotropicHilbert;
        config.bit_alloc = rch::orderings::BitAllocator::Uniform;
    } else if (layout != "A6_rch_C3")
        throw std::runtime_error("unsupported workflow layout");
    const auto windows = queries(workload); // Frozen oracle; no point scan here.
    if (std::filesystem::exists(output))
        throw std::runtime_error("output already exists");
    std::filesystem::create_directories(output);
    warm_input(input_path);
    rusage before{}, after{};
    if (::getrusage(RUSAGE_SELF, &before) != 0)
        throw std::runtime_error("getrusage failed");
    const auto io_before = io();
    const auto start = Clock::now();
    std::vector<double> xyz;
    {
        std::ifstream input(input_path);
        if (!input)
            throw std::runtime_error("cannot read input");
        std::string line;
        while (std::getline(input, line)) {
            auto p = rch::io::parse_three_doubles(line);
            if (!p || !std::all_of(p->begin(), p->end(), [](double v) { return std::isfinite(v); }))
                throw std::runtime_error("invalid or non-finite input record");
            xyz.insert(xyz.end(), p->begin(), p->end());
        }
        if (input.bad() || xyz.empty())
            throw std::runtime_error("input read failed");
    }
    const auto read_end = Clock::now();
    const auto order = rch::orderings::order_point_cloud(xyz, config); // Exactly one call.
    if (!order)
        throw std::runtime_error("ordering failed: " + std::string(order.error().message));
    const auto order_end = Clock::now();
    if (!rch::core::is_finite(order->center) || !rch::core::is_finite(order->half_extent) ||
        !rch::core::is_finite(order->frame_axes))
        throw std::runtime_error("non-finite ordering frame geometry");
    std::vector<app::PointRecord> ordered;
    ordered.reserve(order->permutation.size());
    {
        std::ofstream out(output / "order.csv");
        out << "rank,raw_index,key\n";
        for (std::size_t i = 0; i < order->permutation.size(); ++i) {
            const auto id = order->permutation[i];
            if (id >= xyz.size() / 3)
                throw std::runtime_error("invalid permutation index");
            ordered.push_back({id, {xyz[3 * id], xyz[3 * id + 1], xyz[3 * id + 2]}});
            out << i << ',' << id << ',' << order->primary_keys[id] << '\n';
        }
        out.close();
        if (!out)
            throw std::runtime_error("order output failed");
    }
    const auto directory = app::build_page_directory(ordered);
    app::PageFileMetadata metadata{};
    metadata.layout_id = layout == "A0_input" ? 0U : (layout == "A3_isotropic_hilbert" ? 3U : 63U);
    app::PageFileWriter::write(output / "points.page", ordered, metadata);
    app::PageDirectoryFileWriter::write(output / "points.index", ordered.size(), directory);
    const auto prep_end = Clock::now();
    std::uint64_t logical_bytes{}, result_ids{};
    {
        const auto loaded = app::PageDirectoryFileReader::read(output / "points.index");
        app::PageFileReader reader(output / "points.page");
        std::ofstream results(output / "results.bin", std::ios::binary);
        results.write("RCHWF001", 8);
        put(results, windows.size());
        for (const auto& q : windows) {
            const auto found = app::execute_page_pruned_query(reader, loaded.entries, q.window);
            logical_bytes += found.pages_read * app::kPageFilePageBytes;
            result_ids += found.point_ids.size();
            put(results, found.point_ids.size());
            for (auto id : found.point_ids)
                put(results, id);
        }
        results.close();
        if (!results)
            throw std::runtime_error("result output failed");
    }
    const auto query_end = Clock::now();
    for (const auto* name : {"order.csv", "points.page", "points.index", "results.bin"})
        sync_file(output / name);
    sync_file(output);
    const auto finish = Clock::now();
    const auto io_after = io();
    if (::getrusage(RUSAGE_SELF, &after) != 0)
        throw std::runtime_error("getrusage failed");
    // Full verification is deliberately after BOTH timing and I/O snapshots.
    app::PageFileReader page_check(output / "points.page");
    if (!page_check.verify_payload_checksum())
        throw std::runtime_error("page checksum failed");
    for (std::size_t p = 0; p < directory.size(); ++p) {
        const auto records = page_check.read_page(p);
        if (!std::equal(
                records.begin(),
                records.end(),
                ordered.begin() + static_cast<std::ptrdiff_t>(p * app::kRecordsPerPage)
            ))
            throw std::runtime_error("stored points differ from ordered input");
    }
    auto permutation = order->permutation;
    std::sort(permutation.begin(), permutation.end());
    if (permutation.size() != xyz.size() / 3)
        throw std::runtime_error("invalid permutation size");
    for (std::size_t i = 0; i < permutation.size(); ++i)
        if (permutation[i] != i)
            throw std::runtime_error("non-bijective permutation");
    std::ifstream results(output / "results.bin", std::ios::binary);
    std::array<char, 8> magic{};
    results.read(magic.data(), 8);
    if (std::string(magic.data(), 8) != "RCHWF001" || get(results) != windows.size())
        throw std::runtime_error("invalid results header");
    for (const auto& q : windows) {
        const auto count = get(results);
        if (count != q.count || count > ordered.size())
            throw std::runtime_error("oracle count mismatch");
        rch::core::Sha256 sha;
        std::optional<std::uint64_t> previous;
        for (std::uint64_t i = 0; i < count; ++i) {
            const auto id = get(results);
            if (id >= ordered.size() || (previous && *previous >= id))
                throw std::runtime_error("invalid result ID");
            sha.update_u64_le(id);
            previous = id;
        }
        if (hex(sha.finalize()) != q.hash)
            throw std::runtime_error("oracle hash mismatch");
    }
    if (results.peek() != std::char_traits<char>::eof())
        throw std::runtime_error("trailing results");
    std::ofstream metrics(output / "metrics.json");
    metrics << std::setprecision(17)
            << "{\"schema\":\"rch.application_workflow.metrics.v1\",\"layout\":\"" << layout
            << "\",\"point_count\":" << ordered.size() << ",\"query_count\":" << windows.size()
            << ",\"ordering_calls\":1,\"oracle_match\":true,\"input_warm_verified\":true"
            << ",\"order_sha256\":\"" << hex(order->output_hash) << "\""
            << ",\"total_seconds\":" << seconds(start, finish)
            << ",\"read_seconds\":" << seconds(start, read_end)
            << ",\"order_seconds\":" << seconds(read_end, order_end)
            << ",\"prepare_seconds\":" << seconds(order_end, prep_end)
            << ",\"query_write_seconds\":" << seconds(prep_end, query_end)
            << ",\"sync_seconds\":" << seconds(query_end, finish)
            << ",\"cpu_seconds\":" << cpu(after) - cpu(before)
            << ",\"peak_rss_kib\":" << after.ru_maxrss
            << ",\"logical_query_bytes\":" << logical_bytes << ",\"result_ids\":" << result_ids
            << ",\"storage_read_bytes\":" << delta(io_before.read, io_after.read)
            << ",\"storage_write_bytes\":" << delta(io_before.write, io_after.write) << "}\n";
    metrics.close();
    if (!metrics)
        throw std::runtime_error("metrics output failed");
}
} // namespace

int main(int argc, char** argv) {
    try {
        if (argc != 5)
            throw std::runtime_error(
                "usage: rch_application_workflow POINTS_CSV ORACLE_TSV LAYOUT NEW_OUTPUT_DIR"
            );
        run(argv[1], argv[2], argv[3], argv[4]);
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "application workflow failed: " << error.what() << '\n';
        return 1;
    }
}
