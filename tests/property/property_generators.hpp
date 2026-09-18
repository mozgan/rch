#pragma once

#include <algorithm>
#include <array>
#include <bit>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <span>
#include <vector>

#include "rch/curves/curve_key.hpp"
#include "rch/orderings/orderer.hpp"

namespace rch::tests::property {


class DeterministicGenerator {
public:
    explicit constexpr DeterministicGenerator(const std::uint64_t seed) noexcept
        : state_{seed ^ UINT64_C(0x853c49e6748fea9b)} {}

    [[nodiscard]] constexpr auto next_u64() noexcept -> std::uint64_t {
        state_ = (state_ * UINT64_C(6364136223846793005)) + UINT64_C(1442695040888963407);
        return state_;
    }

    [[nodiscard]] constexpr auto next_index(const std::size_t bound) noexcept -> std::size_t {
        if (bound == 0U) {
            return 0U;
        }
        const std::uint64_t value = next_u64() % static_cast<std::uint64_t>(bound);
        if constexpr (sizeof(std::size_t) >= sizeof(std::uint64_t)) {
            return value;
        } else {
            return static_cast<std::size_t>(value);
        }
    }

    [[nodiscard]] auto unit_double() noexcept -> double {
        const std::uint64_t mantissa = next_u64() >> 11U;
        return std::ldexp(static_cast<double>(mantissa), -53);
    }

    [[nodiscard]] auto finite_double(const double lo, const double hi) noexcept -> double {
        return lo + ((hi - lo) * unit_double());
    }

private:
    std::uint64_t state_{};
};

[[nodiscard]] inline auto generated_cloud(const std::uint64_t seed, const std::size_t n)
    -> std::vector<double> {
    DeterministicGenerator rng{seed};
    std::vector<double> points;
    points.reserve(3U * n);
    for (std::size_t i = 0U; i < n; ++i) {
        const double ix = static_cast<double>(i % 7U);
        const double iy = static_cast<double>((i / 7U) % 7U);
        const double iz = static_cast<double>((i / 49U) % 7U);
        points.push_back((0.25 * ix) + rng.finite_double(-0.01, 0.01));
        points.push_back((0.30 * iy) + rng.finite_double(-0.01, 0.01));
        points.push_back((0.35 * iz) + rng.finite_double(-0.01, 0.01));
    }
    return points;
}

[[nodiscard]] inline auto permuted_cloud(std::span<const double> points, const std::uint64_t seed)
    -> std::vector<double> {
    const std::size_t n = points.size() / 3U;
    std::vector<std::size_t> indices(n);
    for (std::size_t i = 0U; i < n; ++i) {
        indices[i] = i;
    }

    DeterministicGenerator rng{seed};
    for (std::size_t i = n; i > 1U; --i) {
        const std::size_t j = rng.next_index(i);
        std::swap(indices[i - 1U], indices[j]);
    }

    std::vector<double> out;
    out.reserve(points.size());
    for (const std::size_t index : indices) {
        const std::size_t base = 3U * index;
        out.push_back(points[base]);
        out.push_back(points[base + 1U]);
        out.push_back(points[base + 2U]);
    }
    return out;
}

[[nodiscard]] inline auto ordered_coordinate_keys(
    std::span<const double> points, const rch::orderings::OrderingResult& result
) -> std::vector<std::array<std::uint64_t, 3>> {
    std::vector<std::array<std::uint64_t, 3>> keys;
    keys.reserve(result.permutation.size());
    for (const std::uint64_t raw_index_u64 : result.permutation) {
        const auto raw_index = static_cast<std::size_t>(raw_index_u64);
        const std::size_t base = 3U * raw_index;
        keys.push_back({
            rch::curves::double_total_order_key(points[base]),
            rch::curves::double_total_order_key(points[base + 1U]),
            rch::curves::double_total_order_key(points[base + 2U]),
        });
    }
    return keys;
}

[[nodiscard]] inline auto
is_permutation_of_size(const rch::orderings::OrderingResult& result, const std::size_t n) -> bool {
    if (result.permutation.size() != n || result.primary_keys.size() != n) {
        return false;
    }
    std::vector<std::uint8_t> seen(n, 0U);
    for (const std::uint64_t raw_index : result.permutation) {
        if (raw_index >= static_cast<std::uint64_t>(n)) {
            return false;
        }
        auto& slot = seen[static_cast<std::size_t>(raw_index)];
        if (slot != 0U) {
            return false;
        }
        slot = 1U;
    }
    return std::ranges::all_of(seen, [](const std::uint8_t value) noexcept { return value == 1U; });
}

[[nodiscard]] constexpr auto all_ordering_methods() noexcept
    -> std::array<rch::orderings::OrderingMethod, 8> {
    return {
        rch::orderings::OrderingMethod::InputOrder,
        rch::orderings::OrderingMethod::Lexicographic,
        rch::orderings::OrderingMethod::Morton,
        rch::orderings::OrderingMethod::IsotropicHilbert,
        rch::orderings::OrderingMethod::CompactHilbertAABB,
        rch::orderings::OrderingMethod::PcaCompactHilbert,
        rch::orderings::OrderingMethod::RobustFrameMorton,
        rch::orderings::OrderingMethod::RCH,
    };
}

} // namespace rch::tests::property
