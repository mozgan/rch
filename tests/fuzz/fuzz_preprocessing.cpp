// ----------------------------------------------------------------------------
// fuzz_preprocessing.cpp — libFuzzer harness
// ----------------------------------------------------------------------------

#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <limits>
#include <vector>

#include "rch/orderings/orderer.hpp"

#include "tests/property/property_generators.hpp"

namespace {

[[nodiscard]] auto finite_coordinate(const std::uint8_t lo, const std::uint8_t hi) noexcept
    -> double {
    const auto word = static_cast<std::uint16_t>(
        static_cast<std::uint16_t>(lo) | static_cast<std::uint16_t>(hi) << 8U
    );
    return (static_cast<double>(word) / 4096.0) - 8.0;
}

[[nodiscard]] auto make_points(const std::uint8_t* data, const std::size_t size)
    -> std::vector<double> {
    if (size == 0U) {
        return {};
    }
    const std::size_t n = static_cast<std::size_t>((data[0] % 24U) + 1U);
    std::vector<double> points;
    points.reserve(3U * n);
    for (std::size_t i = 0U; i < 3U * n; ++i) {
        const std::size_t off = 1U + (2U * i);
        const std::uint8_t lo = off < size ? data[off] : 0U;
        const std::uint8_t hi = (off + 1U) < size ? data[off + 1U] : 0U;
        points.push_back(finite_coordinate(lo, hi));
    }
    if (size > 2U && (data[1] & 0x80U) != 0U) {
        points[static_cast<std::size_t>(data[2]) % points.size()] =
            (data[1] & 0x40U) != 0U ? std::numeric_limits<double>::infinity()
                                    : std::numeric_limits<double>::quiet_NaN();
    }
    return points;
}

} // namespace

extern "C" int LLVMFuzzerTestOneInput(const std::uint8_t* data, const std::size_t size) {
    const auto points = make_points(data, size);
    if (points.empty()) {
        return 0;
    }

    constexpr auto methods = rch::tests::property::all_ordering_methods();
    rch::orderings::OrderingConfig config{};
    config.method = methods[size == 0U ? 0U : static_cast<std::size_t>(data[0] % methods.size())];

    const auto result = rch::orderings::order_point_cloud(points, config);
    if (result.has_value()) {
        if (!rch::tests::property::is_permutation_of_size(*result, points.size() / 3U)) {
            std::abort();
        }
        return 0;
    }

    if (result.error().code != rch::orderings::OrderingErrorCode::invalid_input &&
        result.error().code != rch::orderings::OrderingErrorCode::unsupported_method) {
        std::abort();
    }
    return 0;
}
