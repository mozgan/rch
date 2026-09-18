#pragma once

// ----------------------------------------------------------------------------
// median_mad.hpp
//
// References:
//   - Peter J. Rousseeuw, Christophe Croux, "Alternatives to the Median Absolute
//     Deviation", 1993, doi:10.1080/01621459.1993.10476408.
//   - Peter J. Huber, "Robust Statistics", 1981, doi:10.1002/0471725250.
//   - Rob J. Hyndman, Yanan Fan, "Sample Quantiles in Statistical Packages",
//     1996, doi:10.1080/00031305.1996.10473566.
//
// Algorithm:
//   - Median: sort values and return the middle value, or average the two middle values.
//   - MAD: compute \(\operatorname{median}(|x_i-m|)\) and scale by \(1/\Phi^{-1}(0.75)\).
//   - Even-sample medians use `lo + (hi-lo)/2` to avoid intermediate overflow
//     while preserving the same real-valued average for finite inputs.
// ----------------------------------------------------------------------------

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <optional>
#include <span>
#include <vector>

#include "rch/core/matrix3.hpp"

namespace rch::robust {

inline constexpr double kMadNormalConsistency = 1.482602218505602;

// Lower median used where deterministic rank definitions require a lower tie.
[[nodiscard]] inline auto lower_median(std::vector<double> values) -> std::optional<double> {
    if (values.empty()) {
        return std::nullopt;
    }
    std::ranges::sort(values);
    return values[(values.size() - 1U) / 2U];
}

// Usual sample median; even samples return the average of the two central values.
[[nodiscard]] inline auto median(std::vector<double> values) -> std::optional<double> {
    if (values.empty()) {
        return std::nullopt;
    }
    std::ranges::sort(values);
    const std::size_t hi = values.size() / 2U;
    if ((values.size() % 2U) == 1U) {
        return values[hi];
    }
    const std::size_t lo = hi - 1U;
    return values[lo] + ((values[hi] - values[lo]) * 0.5);
}

// Span overload that leaves caller-owned data unchanged.
[[nodiscard]] inline auto lower_median(const std::span<const double> values)
    -> std::optional<double> {
    std::vector<double> copy(values.size());
    std::ranges::copy(values, copy.begin());
    return lower_median(std::move(copy));
}

// Span overload that leaves caller-owned data unchanged.
[[nodiscard]] inline auto median(const std::span<const double> values) -> std::optional<double> {
    std::vector<double> copy(values.size());
    std::ranges::copy(values, copy.begin());
    return median(std::move(copy));
}

[[nodiscard]] inline auto
mad(const std::span<const double> values,
    const double center,
    const double consistency = kMadNormalConsistency) -> double {
    // \(MAD=c\,\operatorname{median}_i |x_i-center|\).
    std::vector<double> deviations;
    deviations.reserve(values.size());
    for (const double value : values) {
        deviations.push_back(std::abs(value - center));
    }
    const auto raw = median(std::move(deviations));
    if (!raw.has_value()) {
        return 0.0;
    }
    return consistency * (*raw);
}

[[nodiscard]] inline auto
component_values(const std::span<const rch::core::Vec3<double>> points, const std::size_t axis)
    -> std::vector<double> {
    // Extract one coordinate axis for univariate robust summaries.
    std::vector<double> values;
    values.reserve(points.size());
    for (const auto& point : points) {
        values.push_back(point[axis]);
    }
    return values;
}

[[nodiscard]] inline auto
componentwise_median(const std::span<const rch::core::Vec3<double>> points)
    -> rch::core::Vec3<double> {
    // Coordinatewise median center \((med(x),med(y),med(z))\).
    rch::core::Vec3<double> center{};
    for (std::size_t axis = 0U; axis < 3U; ++axis) {
        auto values = component_values(points, axis);
        center[axis] = median(std::move(values)).value_or(0.0);
    }
    return center;
}

[[nodiscard]] inline auto componentwise_mad_scale(
    const std::span<const rch::core::Vec3<double>> points,
    const rch::core::Vec3<double>& center,
    const double scale_floor = 1.0e-12
) -> rch::core::Vec3<double> {
    // Coordinatewise MAD scale with a floor to avoid division by zero.
    rch::core::Vec3<double> scale{};
    for (std::size_t axis = 0U; axis < 3U; ++axis) {
        auto values = component_values(points, axis);
        scale[axis] = std::max(mad(std::span<const double>{values}, center[axis]), scale_floor);
    }
    return scale;
}

} // namespace rch::robust
