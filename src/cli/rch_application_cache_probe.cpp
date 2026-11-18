// Linux-only, file-specific page-cache intervention on frozen application files.
#include <fcntl.h>
#include <sys/mman.h>
#include <unistd.h>

#include <algorithm>
#include <chrono>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

#include "rch/application/page_directory.hpp"
#include "rch/application/window_query.hpp"

namespace {
using namespace rch::application;

struct Query {
    std::string id;
    QueryWindow window;
    std::uint64_t expected_count{};
    std::string expected_hash;
};

auto hash_ids(const std::vector<std::uint64_t>& ids) -> std::string {
    rch::core::Sha256 hash;
    for (auto id : ids)
        hash.update_u64_le(id);
    std::ostringstream text;
    for (auto byte : hash.finalize()) {
        text << std::hex << std::setfill('0') << std::setw(2) << static_cast<unsigned>(byte);
    }
    return text.str();
}

auto read_bytes() -> std::optional<std::uint64_t> {
    std::ifstream io("/proc/self/io");
    std::string key;
    std::uint64_t value{};
    while (io >> key >> value)
        if (key == "read_bytes:")
            return value;
    return std::nullopt;
}

// Mapping is never touched: mincore observes residency without faulting file data in.
class CacheFile {
public:
    explicit CacheFile(const std::filesystem::path& path) {
        size_ = std::filesystem::file_size(path);
        const auto page_size = ::sysconf(_SC_PAGESIZE);
        if (size_ == 0 || page_size <= 0)
            throw std::runtime_error("invalid mapped file size");
        pages_ =
            (size_ + static_cast<std::size_t>(page_size) - 1) / static_cast<std::size_t>(page_size);
        fd_ = ::open(path.c_str(), O_RDONLY);
        if (fd_ < 0)
            throw std::runtime_error("cannot open cache-control file");
        mapping_ = ::mmap(nullptr, size_, PROT_READ, MAP_SHARED, fd_, 0);
        if (mapping_ == MAP_FAILED) {
            ::close(fd_);
            throw std::runtime_error("cannot map cache-control file");
        }
    }
    CacheFile(const CacheFile&) = delete;
    auto operator=(const CacheFile&) -> CacheFile& = delete;
    ~CacheFile() {
        ::munmap(mapping_, size_);
        ::close(fd_);
    }
    auto pages() const -> std::size_t {
        return pages_;
    }
    auto resident() const -> std::size_t {
        std::vector<unsigned char> states(pages_);
        if (::mincore(mapping_, size_, states.data()) != 0) {
            throw std::runtime_error("mincore failed; cache state is unknown");
        }
        return static_cast<std::size_t>(std::count_if(states.begin(), states.end(), [](auto state) {
            return (state & 1U) != 0;
        }));
    }
    void evict() const {
        // Dirty data must reach the filesystem before DONTNEED can discard it.
        if (::fsync(fd_) != 0)
            throw std::runtime_error("fsync failed before cache eviction");
        const auto error = ::posix_fadvise(fd_, 0, 0, POSIX_FADV_DONTNEED);
        if (error != 0)
            throw std::runtime_error(std::string("fadvise failed: ") + std::strerror(error));
        if (resident() != 0) {
            throw std::runtime_error(
                "eviction not verified: resident pages remain; no cold result"
            );
        }
    }
    void warm() const {
        std::vector<char> buffer(1024 * 1024);
        std::size_t offset{};
        while (offset < size_) {
            const auto n = ::pread(
                fd_,
                buffer.data(),
                std::min(buffer.size(), size_ - offset),
                static_cast<off_t>(offset)
            );
            if (n <= 0)
                throw std::runtime_error("warm-cache pread failed");
            offset += static_cast<std::size_t>(n);
        }
        if (resident() != pages_)
            throw std::runtime_error("full-file warm residency not verified");
    }

private:
    int fd_{-1};
    void* mapping_{MAP_FAILED};
    std::size_t size_{}, pages_{};
};

auto queries(const std::filesystem::path& path) -> std::vector<Query> {
    std::ifstream input(path);
    std::vector<Query> result;
    std::string line;
    while (std::getline(input, line)) {
        std::istringstream row(line);
        Query q;
        if (!(row >> q.id >> q.window.minimum[0] >> q.window.minimum[1] >> q.window.minimum[2] >>
              q.window.maximum[0] >> q.window.maximum[1] >> q.window.maximum[2] >>
              q.expected_count >> q.expected_hash)) {
            throw std::runtime_error("invalid query/oracle row");
        }
        std::string extra;
        if (row >> extra || q.expected_hash.size() != 64 || q.id.find(',') != std::string::npos) {
            throw std::runtime_error("invalid query/oracle fields");
        }
        detail::validate_query_window(q.window);
        if (std::any_of(result.begin(), result.end(), [&](const auto& old) {
                return old.id == q.id;
            })) {
            throw std::runtime_error("duplicate query ID");
        }
        result.push_back(q);
    }
    if (result.empty())
        throw std::runtime_error("no query/oracle rows");
    return result;
}
} // namespace

int main(int argc, char** argv) {
    try {
        if (argc != 8)
            throw std::runtime_error(
                "usage: rch_application_cache_probe PAGE INDEX QUERY_ORACLE_TSV REPEATS OUTPUT "
                "SCAN_ALL SEED"
            );
        std::size_t parsed{};
        const std::string repeat_text = argv[4];
        const auto repeats = std::stoul(repeat_text, &parsed);
        if (parsed != repeat_text.size() || repeats == 0 || repeats > 1000) {
            throw std::runtime_error("repeats must be in 1..1000");
        }
        const std::string scan_text = argv[6];
        if (scan_text != "0" && scan_text != "1")
            throw std::runtime_error("SCAN_ALL must be 0 or 1");
        const auto seed = std::stoull(argv[7]);
        const auto workload = queries(argv[3]);
        const auto directory = PageDirectoryFileReader::read(argv[2]);
        {
            PageFileReader reader(argv[1]);
            if (reader.header().record_count != directory.record_count ||
                !reader.verify_payload_checksum())
                throw std::runtime_error("storage integrity failure");
        } // Close stream and discard its userspace read buffer before any intervention.
        CacheFile cache(argv[1]);
        if (std::filesystem::exists(argv[5]))
            throw std::runtime_error("output already exists");
        std::ofstream output(argv[5]);
        if (!output)
            throw std::runtime_error("cannot create output");
        output << "query_id,repeat,cache_mode,resident_pages_before,total_os_pages,wall_seconds,"
                  "logical_bytes,os_read_bytes,result_count,result_sha256,oracle_match\n";
        for (unsigned long repeat = 1; repeat <= repeats; ++repeat) {
            for (std::size_t i = 0; i < workload.size(); ++i) {
                const auto& q = workload[i];
                for (unsigned arm = 0; arm < 2; ++arm) {
                    // Counterbalance cold/warm order without platform-dependent RNG shuffles.
                    const bool cold = ((seed + repeat + i + arm) % 2) == 0;
                    if (cold)
                        cache.evict();
                    else
                        cache.warm();
                    const auto resident = cache.resident();
                    if ((cold && resident != 0) || (!cold && resident != cache.pages())) {
                        throw std::runtime_error("cache residency changed before measurement");
                    }
                    const auto io_before = read_bytes();
                    const auto start = std::chrono::steady_clock::now();
                    // Opening/header read belongs to both arms. No pre-existing stream buffer.
                    const auto measured = [&] {
                        PageFileReader reader(argv[1]);
                        return execute_page_pruned_query(
                            reader, directory.entries, q.window, scan_text == "1"
                        );
                    }();
                    const auto seconds =
                        std::chrono::duration<double>(std::chrono::steady_clock::now() - start)
                            .count();
                    const auto io_after = read_bytes();
                    const auto hash = hash_ids(measured.point_ids);
                    if (hash != q.expected_hash || measured.point_ids.size() != q.expected_count) {
                        throw std::runtime_error("query differs from frozen full-scan oracle");
                    }
                    output << q.id << ',' << repeat << ','
                           << (cold ? "cold_page_cache" : "warm_page_cache") << ',' << resident
                           << ',' << cache.pages() << ',' << std::setprecision(17) << seconds << ','
                           << measured.pages_read * kPageFilePageBytes << ',';
                    if (io_before && io_after && *io_after >= *io_before)
                        output << *io_after - *io_before;
                    output << ',' << measured.point_ids.size() << ',' << hash << ",true\n";
                    output.flush();
                    if (!output)
                        throw std::runtime_error("cannot write metrics");
                }
            }
        }
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "application cache probe failed: " << error.what() << '\n';
        return 1;
    }
}
