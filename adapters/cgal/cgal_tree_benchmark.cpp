// Native CGAL k-d-tree and DFS layout benchmark. XYZ remains float64; IDs preserve duplicates.
// Range search: CGAL Fuzzy_iso_box epsilon=0; inclusive bounds; no approximate matches.
#include <CGAL/Fuzzy_iso_box.h>
#include <CGAL/Kd_tree.h>
#include <CGAL/Search_traits_3.h>
#include <CGAL/Search_traits_adapter.h>
#include <CGAL/Simple_cartesian.h>
#include <CGAL/Splitters.h>
#include <CGAL/property_map.h>
#include <CGAL/version.h>
#include <sys/resource.h>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <ctime>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <iterator>
#include <memory>
#include <numeric>
#include <random>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

#include "rch/application/page_directory.hpp"
#include "rch/application/window_query.hpp"
#include "rch/core/sha256.hpp"
#include "rch/io/xyz_parse.hpp"

namespace {
namespace app = rch::application;
using Clock = std::chrono::steady_clock;
using Kernel = CGAL::Simple_cartesian<double>;
using Item = std::pair<Kernel::Point_3, std::uint64_t>;
using Traits = CGAL::Search_traits_adapter<
    Item,
    CGAL::First_of_pair_property_map<Item>,
    CGAL::Search_traits_3<Kernel>>;
using Splitter = CGAL::Sliding_midpoint<Traits>;
using Tree = CGAL::Kd_tree<Traits, Splitter, CGAL::Tag_false, CGAL::Tag_false>;

struct Query {
    std::string id;
    app::QueryWindow box;
};

struct Args {
    std::filesystem::path points, queries, order, output;
    std::string backend;
    unsigned repeats{5}, bucket{128};
    std::uint64_t seed{2026};
};

auto number(const std::string& s) -> std::uint64_t {
    if (s.empty() || s.front() == '-')
        throw std::invalid_argument("invalid unsigned integer");
    std::size_t pos{};
    const auto n = std::stoull(s, &pos);
    if (pos != s.size())
        throw std::invalid_argument("invalid unsigned integer");
    return n;
}

auto args_from(int argc, char* argv[]) -> Args {
    Args a;
    for (int i = 1; i < argc; i += 2) {
        if (i + 1 >= argc)
            throw std::invalid_argument("flags require values");
        const std::string key = argv[i], value = argv[i + 1];
        if (key == "--points")
            a.points = value;
        else if (key == "--queries")
            a.queries = value;
        else if (key == "--order")
            a.order = value;
        else if (key == "--output")
            a.output = value;
        else if (key == "--backend")
            a.backend = value;
        else if (key == "--repeats" || key == "--bucket") {
            auto n = number(value);
            if (!n || n > 10000)
                throw std::invalid_argument("repeats/bucket outside 1..10000");
            if (key == "--repeats")
                a.repeats = static_cast<unsigned>(n);
            else
                a.bucket = static_cast<unsigned>(n);
        } else if (key == "--seed")
            a.seed = number(value);
        else
            throw std::invalid_argument("unknown flag: " + key);
    }
    const std::vector<std::string> allowed{
        "cgal_kdtree",
        "kdtree_dfs_pages",
        "input_pages",
        "hilbert_pages",
        "rch_pages",
        "ram_full_scan",
        "hilbert_ram_pages",
        "rch_ram_pages"
    };
    if (a.points.empty() || a.queries.empty() || a.output.empty() ||
        std::find(allowed.begin(), allowed.end(), a.backend) == allowed.end())
        throw std::invalid_argument("invalid/missing inputs/backend");
    if ((a.backend.starts_with("hilbert") || a.backend.starts_with("rch")) && a.order.empty())
        throw std::invalid_argument("SFC backend needs --order");
    return a;
}

auto fields(const std::string& line) -> std::vector<std::string> {
    std::istringstream in(line);
    std::vector<std::string> out;
    std::string s;
    while (std::getline(in, s, ','))
        out.push_back(s);
    return out;
}

auto load_points(const std::filesystem::path& path) -> std::vector<app::PointRecord> {
    std::ifstream in(path);
    if (!in)
        throw std::runtime_error("cannot open points");
    std::vector<app::PointRecord> out;
    std::string line;
    while (std::getline(in, line)) {
        if (line.empty())
            continue;
        auto xyz = rch::io::parse_three_doubles(line);
        if (!xyz || !std::ranges::all_of(*xyz, [](double x) { return std::isfinite(x); }))
            throw std::runtime_error("invalid/nonfinite xyz");
        out.push_back({static_cast<std::uint64_t>(out.size()), *xyz});
    }
    if (out.empty())
        throw std::runtime_error("empty points");
    return out;
}

auto load_queries(const std::filesystem::path& path) -> std::vector<Query> {
    std::ifstream in(path);
    std::string line;
    if (!std::getline(in, line) || line != "query_id,min_x,min_y,min_z,max_x,max_y,max_z")
        throw std::runtime_error("invalid query header");
    std::vector<Query> out;
    while (std::getline(in, line)) {
        auto f = fields(line);
        if (f.size() != 7 || f[0].empty())
            throw std::runtime_error("invalid query row");
        if (std::ranges::any_of(out, [&](const auto& q) { return q.id == f[0]; }))
            throw std::runtime_error("duplicate query ID");
        Query q{f[0], {}};
        for (std::size_t j = 0; j < 3; ++j) {
            std::size_t used{};
            q.box.minimum[j] = std::stod(f[j + 1], &used);
            if (used != f[j + 1].size())
                throw std::runtime_error("invalid query number");
            q.box.maximum[j] = std::stod(f[j + 4], &used);
            if (used != f[j + 4].size())
                throw std::runtime_error("invalid query number");
        }
        app::detail::validate_query_window(q.box);
        out.push_back(q);
    }
    if (out.empty())
        throw std::runtime_error("empty queries");
    return out;
}

auto load_order(const std::filesystem::path& path, std::size_t n) -> std::vector<std::uint64_t> {
    std::ifstream in(path);
    std::string line;
    if (!std::getline(in, line) || line != "rank,raw_index,key")
        throw std::runtime_error("invalid order header");
    std::vector<std::uint64_t> ids;
    std::vector<bool> seen(n);
    while (std::getline(in, line)) {
        auto f = fields(line);
        if (f.size() != 3)
            throw std::runtime_error("invalid order row");
        auto rank = number(f[0]), id = number(f[1]);
        if (rank != ids.size() || id >= n || seen[id])
            throw std::runtime_error("order is not a permutation");
        seen[id] = true;
        ids.push_back(id);
    }
    if (ids.size() != n)
        throw std::runtime_error("incomplete order");
    return ids;
}

auto digest_ids(const std::vector<std::uint64_t>& ids) -> std::string {
    rch::core::Sha256 hash;
    for (auto id : ids)
        hash.update_u64_le(id);
    std::ostringstream out;
    out << std::hex << std::setfill('0');
    for (auto b : hash.finalize())
        out << std::setw(2) << static_cast<unsigned>(b);
    return out.str();
}

auto seconds(Clock::time_point t) -> double {
    return std::chrono::duration<double>(Clock::now() - t).count();
}

auto peak_rss_kib() -> long {
    rusage usage{};
    if (getrusage(RUSAGE_SELF, &usage) != 0)
        return -1;
#if defined(__APPLE__)
    return usage.ru_maxrss / 1024;
#else
    return usage.ru_maxrss;
#endif
}

void run(const Args& a) {
    if (std::filesystem::exists(a.output))
        throw std::runtime_error("output already exists");
    std::filesystem::create_directories(a.output);
    auto original = load_points(a.points);
    auto queries = load_queries(a.queries);
    const bool native = a.backend == "cgal_kdtree";
    const bool dfs = a.backend == "kdtree_dfs_pages";
    const bool scan = a.backend == "ram_full_scan";
    const bool disk = !native && !scan && a.backend.find("ram") == std::string::npos;
    const auto start = Clock::now();
    std::unique_ptr<Tree> tree;
    std::vector<Item> items;
    double tree_build_seconds = 0;
    if (native || dfs) {
        for (const auto& p : original)
            items.emplace_back(Kernel::Point_3(p.xyz[0], p.xyz[1], p.xyz[2]), p.id);
        tree = std::make_unique<Tree>(items.begin(), items.end(), Splitter(a.bucket));
        tree->build<CGAL::Sequential_tag>();
        tree_build_seconds = seconds(start);
    }
    std::vector<app::PointRecord> ordered;
    std::vector<app::PageDirectoryEntry> directory;
    std::unique_ptr<app::PageFileReader> page_file;
    if (!native && !scan) {
        std::vector<std::uint64_t> ids;
        if (dfs) {
            std::vector<Item> traversal;
            tree->root()->tree_items(std::back_inserter(traversal));
            for (const auto& p : traversal)
                ids.push_back(p.second);
            auto check = ids;
            std::sort(check.begin(), check.end());
            for (std::size_t i = 0; i < original.size(); ++i)
                if (check.size() != original.size() || check[i] != i)
                    throw std::runtime_error("invalid tree DFS permutation");
            tree.reset();
            items.clear();
            items.shrink_to_fit();
        } else if (a.order.empty()) {
            ids.resize(original.size());
            std::iota(ids.begin(), ids.end(), std::uint64_t{0});
        } else
            ids = load_order(a.order, original.size());
        for (auto id : ids)
            ordered.push_back(original[id]);
        directory = app::build_page_directory(ordered);
        std::ofstream order(a.output / "order.csv");
        order << "rank,raw_index,key\n";
        for (std::size_t i = 0; i < ids.size(); ++i)
            order << i << ',' << ids[i] << ",0\n";
        if (!order)
            throw std::runtime_error("cannot write order");
        if (disk) {
            app::PageFileWriter::write(a.output / "points.page", ordered, {});
            app::PageDirectoryFileWriter::write(
                a.output / "points.index", original.size(), directory
            );
            page_file = std::make_unique<app::PageFileReader>(a.output / "points.page");
            if (!page_file->verify_payload_checksum())
                throw std::runtime_error("page checksum mismatch");
        }
    }
    const double prepare_seconds = seconds(start);
    std::ofstream meta(a.output / "preparation.csv");
    meta << "backend,point_count,bucket,tree_build_seconds,prepare_seconds,cgal_version,scope\n"
         << a.backend << ',' << original.size() << ',' << a.bucket << ',' << std::setprecision(17)
         << tree_build_seconds << ',' << prepare_seconds << ',' << CGAL_VERSION_STR << ','
         << (disk ? "warm_page_file" : "resident_memory") << '\n';
    if (!meta)
        throw std::runtime_error("cannot write preparation");
    auto execute = [&](const Query& q) {
        app::PageQueryResult result;
        if (native) {
            std::vector<Item> found;
            // Degenerate boxes (including a single point) are supported by the closed-box
            // predicates.
            const auto& lo = q.box.minimum;
            const auto& hi = q.box.maximum;
            const CGAL::Fuzzy_iso_box<Traits> box(
                Kernel::Point_3(lo[0], lo[1], lo[2]), Kernel::Point_3(hi[0], hi[1], hi[2]), 0.0
            );
            tree->search(std::back_inserter(found), box);
            for (const auto& p : found)
                result.point_ids.push_back(p.second);
            std::sort(result.point_ids.begin(), result.point_ids.end());
        } else if (scan)
            result.point_ids = app::full_scan_query_oracle(original, q.box);
        else if (disk)
            result = app::execute_page_pruned_query(*page_file, directory, q.box);
        else {
            for (std::size_t i = 0; i < directory.size(); ++i) {
                if (!app::detail::query_intersects(q.box, directory[i]))
                    continue;
                ++result.candidate_pages;
                const auto count = directory[i].valid_record_count;
                result.records_examined += count;
                for (std::size_t j = 0; j < count; ++j) {
                    const auto& p = ordered[i * app::kRecordsPerPage + j];
                    if (app::detail::query_contains(q.box, p))
                        result.point_ids.push_back(p.id);
                }
            }
            std::sort(result.point_ids.begin(), result.point_ids.end());
        }
        return result;
    };
    std::ofstream metrics(a.output / "query_metrics.csv");
    metrics << "backend,scope,query_id,repeat,wall_seconds,cpu_seconds,result_count,result_hash,"
               "oracle_match,candidate_pages,pages_read,records_examined,peak_rss_kib\n"
            << std::setprecision(17);
    std::vector<std::size_t> sequence(queries.size());
    std::iota(sequence.begin(), sequence.end(), std::size_t{0});
    std::mt19937_64 rng(a.seed);
    // One complete untimed warmup, then seeded query order per repeat.
    for (unsigned repeat = 0; repeat <= a.repeats; ++repeat) {
        std::shuffle(sequence.begin(), sequence.end(), rng);
        for (auto i : sequence) {
            const auto cpu_start = std::clock();
            const auto t = Clock::now();
            auto result = execute(queries[i]);
            const auto elapsed = seconds(t);
            const auto cpu_end = std::clock();
            const auto cpu = static_cast<double>(cpu_end - cpu_start) / CLOCKS_PER_SEC;
            const auto oracle = app::full_scan_query_oracle(original, queries[i].box);
            if (result.point_ids != oracle)
                throw std::runtime_error("oracle mismatch: " + queries[i].id);
            if (repeat == 0)
                continue;
            metrics << a.backend << ',' << (disk ? "warm_page_file" : "resident_memory") << ','
                    << queries[i].id << ',' << repeat << ',' << elapsed << ',' << cpu << ','
                    << result.point_ids.size() << ',' << digest_ids(result.point_ids) << ",true,";
            if (!native && !scan)
                metrics << result.candidate_pages;
            metrics << ',';
            if (disk)
                metrics << result.pages_read;
            metrics << ',';
            if (!native)
                metrics << (scan ? original.size() : result.records_examined);
            metrics << ',' << peak_rss_kib() << '\n';
        }
    }
    if (!metrics)
        throw std::runtime_error("cannot write metrics");
}
} // namespace

int main(int argc, char* argv[]) {
    try {
        run(args_from(argc, argv));
        return 0;
    } catch (const std::exception& e) {
        std::cerr << "tree benchmark: " << e.what() << '\n';
        return 1;
    }
}
