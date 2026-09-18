#include "bench_common.hpp"

#include <cstddef>
#include <cstdint>
#include <limits>

namespace {

[[nodiscard]] auto check(const bool condition) noexcept -> int {
    return condition ? 0 : 1;
}

} // namespace

int main() {
    constexpr auto max_counter = std::numeric_limits<std::int64_t>::max();
    int failures = 0;

    failures += check(rch::benchmarks::processed_items_total(0U, 1024U) == 0);
    failures += check(rch::benchmarks::processed_items_total(7U, 0U) == 0);
    failures += check(rch::benchmarks::processed_items_total(7U, 11U) == 77);
    failures += check(
        rch::benchmarks::processed_items_total(
            static_cast<std::uint64_t>(max_counter) / 3U,
            3U
        ) == max_counter - (max_counter % 3)
    );
    failures += check(
        rch::benchmarks::processed_items_total(
            (static_cast<std::uint64_t>(max_counter) / 3U) + 1U,
            3U
        ) == max_counter
    );
    failures += check(
        rch::benchmarks::processed_items_total(
            1U,
            static_cast<std::size_t>(max_counter)
        ) == max_counter
    );

    return failures == 0 ? 0 : 1;
}
