#pragma once

// ----------------------------------------------------------------------------
// orderer.hpp - ordering strategy hub.
//
// Algorithm:
//   - Validate row-major point input \(P=\{p_i\}_{i=0}^{n-1}\subset \mathbb{R}^3\) and
//     reject NaN/Inf coordinates.
//   - Choose one ordering model: identity, lexicographic, Morton, isotropic
//     Hilbert, compact Hilbert over the raw AABB, PCA compact Hilbert, robust
//     frame Morton, or RCH.
//   - Quantize coordinates to integer cells. Raw methods use AABB coordinates;
//     frame methods use \(y=Q^T(x-\mu)\).
//   - Encode each quantized point as a curve key \(k_i\), then sort by
//     \((k_i,x_i,y_i,z_i,i)\) for deterministic tie-breaking.
//   - RCH obtains \((\mu,Q)\) from DetMCD/MRCD/OGK when possible, otherwise
//     falls back to sample covariance.
//   - Optional MIAD refinement accepts only moves with negative exact change
//     in adjacent path length \(\sum_i \|p_{o_i}-p_{o_{i-1}}\|_2\).
//   - Hash method metadata, bit depths, fallback flag, permutation, and primary
//     keys with SHA-256 for reproducibility checks.
//
// References:
//   - David Hilbert, Ueber die stetige Abbildung einer Linie auf ein
//     Flaechenstueck, 1891, DOI: 10.1007/BF01199431.
//   - Arthur R. Butz, Alternative Algorithm for Hilbert's Space-Filling Curve,
//     1971, DOI: 10.1109/T-C.1971.223258.
//   - Bongki Moon, H. V. Jagadish, Christos Faloutsos, and Joel H. Saltz,
//     Analysis of the clustering properties of the Hilbert space-filling curve,
//     2001, DOI: 10.1109/69.908985.
//   - Chris H. Hamilton and Andrew Rau-Chaplin, Compact Hilbert indices:
//     Space-filling curves for domains with unequal side lengths, 2008,
//     DOI: 10.1016/j.ipl.2007.08.034.
//   - Mia Hubert, Peter J. Rousseeuw, and Tim Verdonck, A Deterministic
//     Algorithm for Robust Location and Scatter, 2012,
//     DOI: 10.1080/10618600.2012.672100.
//   - Kris Boudt, Peter J. Rousseeuw, Steven Vanduffel, and Tim Verdonck,
//     The minimum regularized covariance determinant estimator, 2020,
//     DOI: 10.1007/s11222-019-09869-x.
//   - Ricardo A. Maronna and Ruben H. Zamar, Robust Estimates of Location and
//     Dispersion for High-Dimensional Datasets, 2002,
//     DOI: 10.1198/004017002188618509.
//   - G. A. Croes, A Method for Solving Traveling-Salesman Problems, 1958,
//     DOI: 10.1287/opre.6.6.791.
//   - National Institute of Standards and Technology, Secure Hash Standard
//     (SHS), FIPS PUB 180-4, 2015, DOI: 10.6028/NIST.FIPS.180-4.
//   - Michael J. Wichura, Algorithm AS 241: The Percentage Points of the
//     Normal Distribution, 1988, DOI: 10.2307/2347330.
// ----------------------------------------------------------------------------

#include <algorithm>
#include <array>
#include <bit>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <expected>
#include <limits>
#include <numeric>
#include <optional>
#include <span>
#include <string_view>
#include <tuple>
#include <vector>

#include "rch/core/matrix3.hpp"
#include "rch/core/sha256.hpp"
#include "rch/curves/bit_allocation_monotone.hpp"
#include "rch/curves/bit_allocation_occupancy.hpp"
#include "rch/curves/curve_key.hpp"
#include "rch/curves/hilbert3_compact.hpp"
#include "rch/curves/hilbert3_standard.hpp"
#include "rch/curves/morton3.hpp"
#include "rch/curves/quantization.hpp"
#include "rch/frames/robust_principal_frame.hpp"
#include "rch/robust/det_mcd.hpp"
#include "rch/robust/mrcd.hpp"
#include "rch/robust/ogk.hpp"

namespace rch::orderings {

// Public ordering strategies exposed by the library and CLI.
enum class OrderingMethod {
    InputOrder,
    Lexicographic,
    Morton,
    IsotropicHilbert,
    CompactHilbertAABB,
    PcaCompactHilbert,
    RobustFrameMorton,
    RCH,
};

// Frame estimator used by PCA/RCH frame-based orderings.
enum class FrameEstimator {
    SampleCovariance,
    DetMCD,
    MRCD,
    OGK,
};

// Bit-depth allocator for compact curve domains.
enum class BitAllocator {
    Uniform,
    MonotoneHalf,
    OccupancyFloor1,
    OccupancyFloor10,
    FrameCoreOccupancy,
    HybridOccupancy,
    SampleCountUniform,
};

// Controls which methods receive the post-sort local MIAD-refinement pass.
// `Off` disables refinement for every method; `All` applies it to every
// ordering except the input-order baseline, which is held as a fixed identity
// reference.
enum class RefinementMode {
    Off,
    All,
};

// Stable error categories returned by `order_point_cloud`.
enum class OrderingErrorCode {
    invalid_shape,
    invalid_input,
    unsupported_method,
    key_encoding_failed,
};

// Error code and short diagnostic for failed ordering requests.
struct OrderingError {
    OrderingErrorCode code{OrderingErrorCode::invalid_input};
    std::string_view message{};
};

// User-facing controls for method, frame estimator, bit allocation, and refinement.
struct OrderingConfig {
    OrderingMethod method{OrderingMethod::RCH};
    FrameEstimator frame{FrameEstimator::DetMCD};
    BitAllocator bit_alloc{BitAllocator::FrameCoreOccupancy};
    std::uint8_t bit_sum_max{rch::curves::kMaxCurveTotalBits};
    std::uint8_t uniform_bits{10U};
    std::uint8_t min_axis_bits{1U};
    RefinementMode refinement{RefinementMode::Off};
    double tau_quant_squared{4.0};
};

// Ordering output plus diagnostics needed by experiments and manifests.
struct OrderingResult {
    OrderingMethod method{OrderingMethod::RCH};
    std::vector<std::uint64_t> permutation{};
    std::vector<std::uint64_t> primary_keys{};
    rch::curves::BitsAxis3 bits_axis{};
    rch::core::Vec3<double> center{};
    rch::core::Vec3<double> half_extent{};
    rch::core::Matrix3<double> frame_axes{rch::core::identity_matrix3<double>()};
    bool scatter_regularized{};
    bool robust_fallback_used{};
    bool finite_only_passed{};
    std::array<std::uint8_t, 32> output_hash{};
};

using OrderingExpected = std::expected<OrderingResult, OrderingError>;

// Runtime-polymorphic ordering strategy interface.
class OrderingStrategy {
public:
    virtual ~OrderingStrategy() = default;
    [[nodiscard]] virtual auto method() const noexcept -> OrderingMethod = 0;
    [[nodiscard]] virtual auto
    order(std::span<const double> points_xyz, const OrderingConfig& config) const
        -> OrderingExpected = 0;
};

// Converts an ordering method enum to the manifest/CLI token.
[[nodiscard]] constexpr auto to_string(const OrderingMethod method) noexcept -> std::string_view {
    switch (method) {
    case OrderingMethod::InputOrder:
        return "input";
    case OrderingMethod::Lexicographic:
        return "lexicographic";
    case OrderingMethod::Morton:
        return "morton";
    case OrderingMethod::IsotropicHilbert:
        return "isotropic_hilbert";
    case OrderingMethod::CompactHilbertAABB:
        return "compact_hilbert_aabb";
    case OrderingMethod::PcaCompactHilbert:
        return "pca_compact_hilbert";
    case OrderingMethod::RobustFrameMorton:
        return "robust_frame_morton";
    case OrderingMethod::RCH:
        return "rch";
    default:
        break;
    }
    return "unknown";
}

// Converts a frame estimator enum to the manifest/CLI token.
[[nodiscard]] constexpr auto to_string(const FrameEstimator estimator) noexcept
    -> std::string_view {
    switch (estimator) {
    case FrameEstimator::SampleCovariance:
        return "sample_covariance";
    case FrameEstimator::DetMCD:
        return "det_mcd";
    case FrameEstimator::MRCD:
        return "mrcd";
    case FrameEstimator::OGK:
        return "ogk";
    default:
        break;
    }
    return "unknown";
}

// Converts a refinement enum to the manifest/CLI token.
[[nodiscard]] constexpr auto to_string(const RefinementMode mode) noexcept -> std::string_view {
    switch (mode) {
    case RefinementMode::Off:
        return "off";
    case RefinementMode::All:
        return "all";
    default:
        break;
    }
    return "unknown";
}

// Parses a refinement token accepted by the CLI/config layer.
[[nodiscard]] constexpr auto refinement_from_string(const std::string_view name) noexcept
    -> std::optional<RefinementMode> {
    if (name == "off" || name == "none" || name == "default") {
        return RefinementMode::Off;
    }
    if (name == "all") {
        return RefinementMode::All;
    }
    return std::nullopt;
}

// Parses a robust/PCA frame-estimator token accepted by the CLI/config layer.
[[nodiscard]] constexpr auto frame_estimator_from_string(const std::string_view name) noexcept
    -> std::optional<FrameEstimator> {
    if (name == "sample" || name == "sample_covariance" || name == "b0_sample_covariance") {
        return FrameEstimator::SampleCovariance;
    }
    if (name == "det_mcd" || name == "detmcd" || name == "mcd" || name == "b1_det_mcd") {
        return FrameEstimator::DetMCD;
    }
    if (name == "mrcd" || name == "b2_mrcd") {
        return FrameEstimator::MRCD;
    }
    if (name == "ogk" || name == "b3_ogk") {
        return FrameEstimator::OGK;
    }
    return std::nullopt;
}

// Parses an ordering-method token accepted by the CLI/config layer.
[[nodiscard]] constexpr auto method_from_string(const std::string_view name) noexcept
    -> std::optional<OrderingMethod> {
    if (name == "input" || name == "input_order") {
        return OrderingMethod::InputOrder;
    }
    if (name == "lexicographic" || name == "lex") {
        return OrderingMethod::Lexicographic;
    }
    if (name == "morton" || name == "zorder" || name == "z_order") {
        return OrderingMethod::Morton;
    }
    if (name == "isotropic_hilbert" || name == "hilbert") {
        return OrderingMethod::IsotropicHilbert;
    }
    if (name == "compact_hilbert_aabb" || name == "compact") {
        return OrderingMethod::CompactHilbertAABB;
    }
    if (name == "pca_compact_hilbert" || name == "pca_compact") {
        return OrderingMethod::PcaCompactHilbert;
    }
    if (name == "robust_frame_morton" || name == "robust_morton") {
        return OrderingMethod::RobustFrameMorton;
    }
    if (name == "rch" || name == "robust_compact_hilbert") {
        return OrderingMethod::RCH;
    }
    return std::nullopt;
}

// Formats a SHA-256 digest as lower-case hexadecimal plus a trailing NUL.
[[nodiscard]] inline auto hash_hex(const std::array<std::uint8_t, 32>& hash)
    -> std::array<char, 65> {
    constexpr std::array<char, 16> digits{
        '0', '1', '2', '3', '4', '5', '6', '7', '8', '9', 'a', 'b', 'c', 'd', 'e', 'f'
    };
    std::array<char, 65> out{};
    for (std::size_t i = 0U; i < hash.size(); ++i) {
        out[2U * i] = digits[hash[i] >> 4U];
        out[(2U * i) + 1U] = digits[hash[i] & 0x0FU];
    }
    out[64U] = '\0';
    return out;
}

namespace detail {

// Axis-aligned bounds in raw or frame coordinates.
struct Bounds3 {
    rch::core::Vec3<double> lo{};
    rch::core::Vec3<double> hi{};
};

// Prepared center/frame state used by frame-based orderings.
struct FramePreparation {
    rch::core::Vec3<double> center{};
    rch::frames::RobustPrincipalFrame frame{};
    bool scatter_regularized{};
    bool robust_fallback_used{};
};

// Canonicalizes \(-0\) to \(+0\) for stable ordering and hashing.
[[nodiscard]] constexpr auto normalize_signed_zero(const double value) noexcept -> double {
    return std::fpclassify(value) == FP_ZERO ? 0.0 : value;
}

// Returns \(n\) for row-major \(n\times3\) input, or empty on malformed shape.
[[nodiscard]] constexpr auto point_count(const std::span<const double> points_xyz) noexcept
    -> std::optional<std::size_t> {
    if (points_xyz.size() % 3U != 0U) {
        return std::nullopt;
    }
    return points_xyz.size() / 3U;
}

// Loads point \(p_i=(x_i,y_i,z_i)\) from row-major coordinates.
[[nodiscard]] inline auto
point_at(const std::span<const double> points_xyz, const std::size_t index) noexcept
    -> rch::core::Vec3<double> {
    const std::size_t base = 3U * index;
    return {
        normalize_signed_zero(points_xyz[base]),
        normalize_signed_zero(points_xyz[base + 1U]),
        normalize_signed_zero(points_xyz[base + 2U]),
    };
}

// Verifies that every raw coordinate is finite.
[[nodiscard]] inline auto validate_finite(const std::span<const double> points_xyz) noexcept
    -> bool {
    return std::ranges::all_of(points_xyz, [](const double value) noexcept {
        return std::isfinite(value);
    });
}

// Copies row-major input into `Vec3` storage for statistical routines.
[[nodiscard]] inline auto materialize_points(const std::span<const double> points_xyz)
    -> std::vector<rch::core::Vec3<double>> {
    const std::size_t n = points_xyz.size() / 3U;
    std::vector<rch::core::Vec3<double>> points;
    points.reserve(n);
    for (std::size_t i = 0U; i < n; ++i) {
        points.push_back(point_at(points_xyz, i));
    }
    return points;
}

// Builds the identity permutation \(o_i=i\).
[[nodiscard]] inline auto make_identity_permutation(const std::size_t n)
    -> std::vector<std::uint64_t> {
    std::vector<std::uint64_t> permutation(n);
    std::iota(permutation.begin(), permutation.end(), std::uint64_t{0U});
    return permutation;
}

// Computes \(\|p_l-p_r\|_2\) in raw coordinates.
[[nodiscard]] inline auto raw_point_distance(
    const std::span<const double> points_xyz, const std::uint64_t left, const std::uint64_t right
) noexcept -> double {
    const auto a = point_at(points_xyz, static_cast<std::size_t>(left));
    const auto b = point_at(points_xyz, static_cast<std::size_t>(right));
    const double dx = a[0] - b[0];
    const double dy = a[1] - b[1];
    const double dz = a[2] - b[2];
    return std::hypot(dx, dy, dz);
}

// Adjacent-swap local search; accepts only strict MIAD-decreasing swaps.
inline auto refine_adjacent_miad(
    const std::span<const double> points_xyz,
    std::vector<std::uint64_t>& permutation,
    const std::size_t passes = 16U
) noexcept -> bool {
    if (permutation.size() < 3U) {
        return false;
    }
    bool changed_any = false;
    for (std::size_t pass = 0U; pass < passes; ++pass) {
        bool changed_pass = false;
        for (std::size_t pos = 0U; pos + 1U < permutation.size(); ++pos) {
            const std::uint64_t left = permutation[pos];
            const std::uint64_t right = permutation[pos + 1U];
            double before = 0.0;
            double after = 0.0;
            if (pos > 0U) {
                const std::uint64_t previous = permutation[pos - 1U];
                before += raw_point_distance(points_xyz, previous, left);
                after += raw_point_distance(points_xyz, previous, right);
            }
            if (pos + 2U < permutation.size()) {
                const std::uint64_t next = permutation[pos + 2U];
                before += raw_point_distance(points_xyz, right, next);
                after += raw_point_distance(points_xyz, left, next);
            }
            if (after < before) {
                std::swap(permutation[pos], permutation[pos + 1U]);
                changed_pass = true;
                changed_any = true;
            }
        }
        if (!changed_pass) {
            break;
        }
    }
    return changed_any;
}

inline auto refine_windowed_miad(
    const std::span<const double> points_xyz,
    std::vector<std::uint64_t>& permutation,
    const std::size_t window = 16U,
    const std::size_t passes = 8U
) noexcept -> bool {
    if (permutation.size() < 3U || window < 2U) {
        return false;
    }
    bool changed_any = false;
    for (std::size_t pass = 0U; pass < passes; ++pass) {
        bool changed = false;
        for (std::size_t pos = 0U; pos + 1U < permutation.size(); ++pos) {
            const std::size_t end = std::min(permutation.size(), pos + 1U + window);
            const std::uint64_t current = permutation[pos];
            std::size_t best = pos + 1U;
            // Accept a move only if it strictly decreases the total adjacent-distance
            // sum, i.e. MIAD itself because \(n\) is fixed and
            // \(\operatorname{MIAD}=\mathrm{sum}/(n-1)\).
            // Picking the nearest candidate unconditionally -- as this pass used to --
            // is a greedy nearest-neighbour chain, which is not monotone in path
            // length: measured over 300 randomized clouds it *increased* MIAD in 8 of
            // them, by up to 10.5%.
            double best_delta = 0.0;
            for (std::size_t candidate = pos + 2U; candidate < end; ++candidate) {
                // Or-opt node insertion: move permutation[candidate] to pos+1.
                //   removed edges: (pos, pos+1), (candidate-1, candidate),
                //                  (candidate, candidate+1)
                //   added edges:   (pos, candidate), (candidate, pos+1),
                //                  (candidate-1, candidate+1)
                // Every edge strictly between pos+1 and candidate-1 is untouched, so
                // this difference is exactly the change in the total.
                double removed = raw_point_distance(points_xyz, current, permutation[pos + 1U]) +
                                 raw_point_distance(
                                     points_xyz, permutation[candidate - 1U], permutation[candidate]
                                 );
                double added =
                    raw_point_distance(points_xyz, current, permutation[candidate]) +
                    raw_point_distance(points_xyz, permutation[candidate], permutation[pos + 1U]);
                if (candidate + 1U < permutation.size()) {
                    removed += raw_point_distance(
                        points_xyz, permutation[candidate], permutation[candidate + 1U]
                    );
                    added += raw_point_distance(
                        points_xyz, permutation[candidate - 1U], permutation[candidate + 1U]
                    );
                }
                const double delta = added - removed;
                if (delta < best_delta) {
                    best = candidate;
                    best_delta = delta;
                }
            }
            if (best != pos + 1U) {
                const std::uint64_t selected = permutation[best];
                for (std::size_t shift = best; shift > pos + 1U; --shift) {
                    permutation[shift] = permutation[shift - 1U];
                }
                permutation[pos + 1U] = selected;
                changed = true;
                changed_any = true;
            }
        }
        if (!changed) {
            break;
        }
    }
    return changed_any;
}

// 2-opt on a path: reverse the segment \([pos+1,best]\).
//   removed edges: \((pos,pos+1)\) and \((best,best+1)\)
//   added edges:   \((pos,best)\) and \((pos+1,best+1)\)
// Every edge strictly inside the reversed segment keeps both endpoints, and the
// segment is undirected for a symmetric metric, so this difference is exactly
// the change in the total adjacent-distance sum. When `best` is the last index
// there is no (best, best+1) edge and the move simply reverses the tail.
//
// Or-opt alone relocates single points but can never undo a crossing, which is
// what leaves long edges in the order; 2-opt removes exactly those. Guarding on
// the exact delta keeps the pass monotone, as with `refine_windowed_miad`.
//
// `window` here bounds the length of the reversed segment, which is a different
// quantity from `refine_windowed_miad`'s `window` (how far a single point may be
// relocated). The two happen to share the value 16; they are independent choices,
// and neither is reachable from OrderingConfig.
//
// Reference: Croes, G.A. (1958), "A Method for Solving Traveling-Salesman
// Problems", Operations Research 6(6):791-812, DOI: 10.1287/opre.6.6.791.
inline auto refine_two_opt_miad(
    const std::span<const double> points_xyz,
    std::vector<std::uint64_t>& permutation,
    const std::size_t window = 16U
) noexcept -> bool {
    const std::size_t n = permutation.size();
    if (n < 3U || window < 2U) {
        return false;
    }
    bool changed = false;
    for (std::size_t pos = 0U; pos + 2U < n; ++pos) {
        std::size_t best = 0U;
        double best_delta = 0.0;
        const std::size_t limit = std::min(n - 1U, pos + window);
        for (std::size_t candidate = pos + 2U; candidate <= limit; ++candidate) {
            double removed =
                raw_point_distance(points_xyz, permutation[pos], permutation[pos + 1U]);
            double added = raw_point_distance(points_xyz, permutation[pos], permutation[candidate]);
            if (candidate + 1U < n) {
                removed += raw_point_distance(
                    points_xyz, permutation[candidate], permutation[candidate + 1U]
                );
                added += raw_point_distance(
                    points_xyz, permutation[pos + 1U], permutation[candidate + 1U]
                );
            }
            const double delta = added - removed;
            if (delta < best_delta) {
                best_delta = delta;
                best = candidate;
            }
        }
        if (best != 0U) {
            std::reverse(
                permutation.begin() + static_cast<std::ptrdiff_t>(pos + 1U),
                permutation.begin() + static_cast<std::ptrdiff_t>(best + 1U)
            );
            changed = true;
        }
    }
    return changed;
}

[[nodiscard]] inline auto make_output_hash(const OrderingResult& result) noexcept
    -> std::array<std::uint8_t, 32> {
    rch::core::Sha256 sha{};
    sha.update_u64_le(static_cast<std::uint64_t>(result.method));
    sha.update_u64_le(result.bits_axis[0]);
    sha.update_u64_le(result.bits_axis[1]);
    sha.update_u64_le(result.bits_axis[2]);
    sha.update_u64_le(result.robust_fallback_used ? 1ULL : 0ULL);
    sha.update_u64_le(result.permutation.size());
    for (const std::uint64_t raw_index : result.permutation) {
        sha.update_u64_le(raw_index);
    }
    sha.update_u64_le(result.primary_keys.size());
    for (const std::uint64_t key : result.primary_keys) {
        sha.update_u64_le(key);
    }
    return sha.finalize();
}

// Returns whether the selected method participates in MIAD refinement.
[[nodiscard]] constexpr auto
should_refine(const OrderingMethod method, const RefinementMode mode) noexcept -> bool {
    // The input-order baseline is a fixed identity reference. It is never
    // refined, so it stays invariant across every refinement mode and does
    // not silently turn into a "local-refinement-from-input" heuristic.
    if (method == OrderingMethod::InputOrder) {
        return false;
    }
    switch (mode) {
    case RefinementMode::Off:
        return false;
    case RefinementMode::All:
        return true;
    default:
        return false;
    }
}

inline auto
apply_miad_refinement(const std::span<const double> points_xyz, OrderingResult& result) noexcept
    -> void {
    // Alternate the two guarded neighbourhoods to a joint local optimum, then
    // finish with the adjacent-swap pass. Or-opt relocates single points; 2-opt
    // removes crossings that relocation alone cannot. Both are guarded on their
    // exact objective delta, so every accepted move strictly lowers the total
    // adjacent-distance sum and the whole procedure is monotone.
    constexpr std::size_t kJointPasses = 8U;
    bool changed_any = false;
    for (std::size_t pass = 0U; pass < kJointPasses; ++pass) {
        const bool or_opt_changed = refine_windowed_miad(points_xyz, result.permutation, 16U, 1U);
        const bool two_opt_changed = refine_two_opt_miad(points_xyz, result.permutation);
        changed_any = changed_any || or_opt_changed || two_opt_changed;
        if (!or_opt_changed && !two_opt_changed) {
            break;
        }
    }
    const bool adjacent_changed = refine_adjacent_miad(points_xyz, result.permutation);
    if (changed_any || adjacent_changed) {
        result.output_hash = make_output_hash(result);
    }
}

// Computes the raw coordinate AABB over all input points.
[[nodiscard]] inline auto raw_bounds(const std::span<const double> points_xyz) noexcept -> Bounds3 {
    const std::size_t n = points_xyz.size() / 3U;
    Bounds3 bounds{};
    if (n == 0U) {
        return bounds;
    }
    bounds.lo = point_at(points_xyz, 0U);
    bounds.hi = bounds.lo;
    for (std::size_t i = 1U; i < n; ++i) {
        const auto point = point_at(points_xyz, i);
        for (std::size_t axis = 0U; axis < 3U; ++axis) {
            bounds.lo[axis] = std::min(bounds.lo[axis], point[axis]);
            bounds.hi[axis] = std::max(bounds.hi[axis], point[axis]);
        }
    }
    return bounds;
}

// Computes half of a finite interval width while avoiding `hi - lo` overflow.
[[nodiscard]] inline auto stable_half_width(const double lo, const double hi) noexcept -> double {
    if (!std::isfinite(lo) || !std::isfinite(hi) || hi < lo) {
        return 0.0;
    }
    if (lo <= 0.0 && hi >= 0.0) {
        return (std::abs(lo) * 0.5) + (std::abs(hi) * 0.5);
    }
    return std::abs(hi - lo) * 0.5;
}

// Converts AABB width to half extents \(a=(h-l)/2\).
[[nodiscard]] inline auto half_extent_from_bounds(const Bounds3& bounds) noexcept
    -> rch::core::Vec3<double> {
    return {
        stable_half_width(bounds.lo[0], bounds.hi[0]),
        stable_half_width(bounds.lo[1], bounds.hi[1]),
        stable_half_width(bounds.lo[2], bounds.hi[2]),
    };
}

// Converts AABB bounds to center \(c=(h+l)/2\).
[[nodiscard]] inline auto center_from_bounds(const Bounds3& bounds) noexcept
    -> rch::core::Vec3<double> {
    return {
        std::midpoint(bounds.lo[0], bounds.hi[0]),
        std::midpoint(bounds.lo[1], bounds.hi[1]),
        std::midpoint(bounds.lo[2], bounds.hi[2]),
    };
}

// Chooses the fixed equal per-axis Hilbert depth within total and implementation caps.
[[nodiscard]] inline auto equal_bits(const OrderingConfig& config) noexcept -> std::uint8_t {
    const std::uint8_t budget_cap = static_cast<std::uint8_t>(config.bit_sum_max / 3U);
    return std::min({config.uniform_bits, budget_cap, rch::curves::Hilbert3Standard::max_bits});
}

// Computes \(\lceil \log_2 n\rceil\) for integer point-count sizing.
[[nodiscard]] constexpr auto ceil_log2_size(std::size_t value) noexcept -> std::uint8_t {
    if (value <= 1U) {
        return 0U;
    }
    --value;
    std::uint8_t bits = 0U;
    while (value > 0U) {
        ++bits;
        value >>= 1U;
    }
    return bits;
}

// Equal-depth grid sized so \(2^{3m}\ge n\), while preserving the configured
// fixed-resolution floor and the 63-bit key budget.
[[nodiscard]] inline auto
sample_count_uniform_bits(const std::size_t n, const OrderingConfig& config) noexcept
    -> std::uint8_t {
    const std::uint8_t budget_cap = std::min<std::uint8_t>(
        static_cast<std::uint8_t>(config.bit_sum_max / 3U), rch::curves::Hilbert3Standard::max_bits
    );
    const std::uint8_t count_bits =
        static_cast<std::uint8_t>((static_cast<unsigned>(ceil_log2_size(n)) + 2U) / 3U);
    return std::min<std::uint8_t>(std::max(config.uniform_bits, count_bits), budget_cap);
}

// Replicates one bit depth across \((x,y,z)\).
[[nodiscard]] inline auto uniform_bits_axis(const std::uint8_t bits) noexcept
    -> rch::curves::BitsAxis3 {
    return {bits, bits, bits};
}

// Quantizes one raw/frame point into its integer curve cell.
[[nodiscard]] inline auto quantized_point(
    const rch::core::Vec3<double>& point,
    const Bounds3& bounds,
    const rch::curves::BitsAxis3& bits_axis
) noexcept -> rch::curves::Point3u32 {
    return {
        rch::curves::quantize_axis(point[0], bounds.lo[0], bounds.hi[0], bits_axis[0]),
        rch::curves::quantize_axis(point[1], bounds.lo[1], bounds.hi[1], bits_axis[1]),
        rch::curves::quantize_axis(point[2], bounds.lo[2], bounds.hi[2], bits_axis[2]),
    };
}

// Creates symmetric frame-coordinate bounds \([-a_j,a_j]\).
[[nodiscard]] inline auto
bounds_from_half_extents(const rch::core::Vec3<double>& half_extents) noexcept -> Bounds3 {
    Bounds3 bounds{};
    for (std::size_t axis = 0U; axis < 3U; ++axis) {
        const double extent = half_extents[axis];
        const double finite_extent = (std::isfinite(extent) && extent > 0.0) ? extent : 0.0;
        bounds.lo[axis] = -finite_extent;
        bounds.hi[axis] = finite_extent;
    }
    return bounds;
}

struct FrameDomain {
    // Smallest box, in frame coordinates, that contains the core box AND every
    // projected point. Used as the quantization domain by every rule except
    // FrameCoreOccupancy.
    rch::core::Vec3<double> covering_half_extents{};
    // Number of points whose projection lies inside the core box. This is
    // \(N_{\mathrm{core}}\) in \(\delta=(V_{\mathrm{core}}/N_{\mathrm{core}})^{1/3}\).
    std::size_t core_occupancy{};
};

// One pass over the cloud producing both quantities.
//
// Boundary points (|y_j| exactly equal to the half extent) count as inside,
// matching `quantize_axis`, which maps `value >= hi` to the last code rather
// than out of range.
[[nodiscard]] inline auto frame_domain(
    const std::span<const double> points_xyz,
    const rch::core::Vec3<double>& center,
    const rch::frames::RobustPrincipalFrame& frame
) noexcept -> FrameDomain {
    FrameDomain domain{};
    domain.covering_half_extents = frame.half_extents;
    const std::size_t n = points_xyz.size() / 3U;
    for (std::size_t i = 0U; i < n; ++i) {
        const auto raw = point_at(points_xyz, i);
        const auto y = rch::frames::project_to_robust_frame(raw, center, frame);
        bool inside = true;
        for (std::size_t axis = 0U; axis < 3U; ++axis) {
            const double extent = std::abs(y[axis]);
            if (!std::isfinite(extent)) {
                inside = false;
                continue;
            }
            domain.covering_half_extents[axis] =
                std::max(domain.covering_half_extents[axis], extent);
            if (extent > frame.half_extents[axis]) {
                inside = false;
            }
        }
        if (inside) {
            ++domain.core_occupancy;
        }
    }
    return domain;
}

// FrameCoreOccupancy is the only mode whose quantization bounds come from the
// statistical \(3\sigma\) core box; out-of-core points then clamp to the box faces.
// HybridOccupancy keeps the covering bounds (no clamp) but still lets robust
// statistics drive the bit budget via allocate_hybrid_occupancy_bits.
[[nodiscard]] constexpr auto uses_statistical_frame_domain(const BitAllocator bit_alloc) noexcept
    -> bool {
    return bit_alloc == BitAllocator::FrameCoreOccupancy;
}

// Allocates occupancy-driven bit depths for a target half-extent box.
[[nodiscard]] inline auto occupancy_bits_for(
    const rch::core::Vec3<double>& half_extent,
    const std::size_t n,
    const OrderingConfig& config,
    const std::uint8_t minimum_axis_bits
) noexcept -> rch::curves::BitsAxis3 {
    const rch::curves::OccupancyBitAllocationOptions options{
        minimum_axis_bits,
        config.bit_sum_max,
        rch::curves::kMaxCurveAxisBits,
    };
    return rch::curves::allocate_occupancy_bits(half_extent, n, options).budget.bits;
}

// HybridOccupancy: robust core plus inlier support sets the target cell size
// \(\delta\); the per-axis bit budget is then sized so the covering box is quantized at \(\delta\),
// so every point stays in range and inliers keep robust-core resolution.
[[nodiscard]] inline auto hybrid_occupancy_bits_for(
    const rch::core::Vec3<double>& core_half_extent,
    const rch::core::Vec3<double>& covering_half_extent,
    const std::size_t n,
    const OrderingConfig& config
) noexcept -> rch::curves::BitsAxis3 {
    const rch::curves::OccupancyBitAllocationOptions options{
        config.min_axis_bits,
        config.bit_sum_max,
        rch::curves::kMaxCurveAxisBits,
    };
    return rch::curves::allocate_hybrid_occupancy_bits(
               core_half_extent, covering_half_extent, n, options
    )
        .budget.bits;
}

// Selects compact curve bit depths for raw or covering half extents.
[[nodiscard]] inline auto compact_bits_for(
    const rch::core::Vec3<double>& half_extent, const std::size_t n, const OrderingConfig& config
) noexcept -> rch::curves::BitsAxis3 {
    if (config.bit_alloc == BitAllocator::Uniform) {
        return uniform_bits_axis(equal_bits(config));
    }
    if (config.bit_alloc == BitAllocator::SampleCountUniform) {
        return uniform_bits_axis(sample_count_uniform_bits(n, config));
    }
    if (config.bit_alloc == BitAllocator::MonotoneHalf) {
        const rch::curves::MonotoneHalfBitAllocationOptions options{
            config.min_axis_bits,
            config.bit_sum_max,
            rch::curves::kMaxCurveAxisBits,
        };
        return rch::curves::allocate_monotone_half_bits(half_extent, equal_bits(config), options)
            .budget.bits;
    }
    if (config.bit_alloc == BitAllocator::OccupancyFloor1 ||
        config.bit_alloc == BitAllocator::FrameCoreOccupancy ||
        config.bit_alloc == BitAllocator::HybridOccupancy) {
        return occupancy_bits_for(half_extent, n, config, config.min_axis_bits);
    }
    return occupancy_bits_for(
        half_extent, n, config, std::max(config.min_axis_bits, equal_bits(config))
    );
}

// Builds a sample-covariance PCA frame.
[[nodiscard]] inline auto
sample_frame(const std::span<const double> points_xyz, const double tau_quant_squared = 4.0)
    -> FramePreparation {
    const auto points = materialize_points(points_xyz);
    FramePreparation prepared{};
    prepared.center = rch::core::mean3<double>(points);
    const auto scatter = rch::core::covariance3<double>(points, prepared.center);
    prepared.frame = rch::frames::make_robust_principal_frame(scatter, tau_quant_squared);
    return prepared;
}

// Builds an OGK robust frame, falling back to sample covariance when disabled.
[[nodiscard]] inline auto
ogk_or_sample_frame(const std::span<const double> points_xyz, const double tau_quant_squared = 4.0)
    -> FramePreparation {
    const auto points = materialize_points(points_xyz);
    FramePreparation prepared{};
    const auto robust = rch::robust::ogk(points);
    const bool robust_ok = robust.policy == rch::robust::FallbackPolicy::none ||
                           robust.policy == rch::robust::FallbackPolicy::chi2_regularized;
    if (robust_ok && rch::core::is_finite(robust.scatter)) {
        prepared.center = robust.center;
        prepared.frame =
            rch::frames::make_robust_principal_frame(robust.scatter, tau_quant_squared);
        prepared.scatter_regularized = robust.used_regularization;
        return prepared;
    }

    prepared.robust_fallback_used = true;
    prepared.center = rch::core::mean3<double>(points);
    const auto scatter = rch::core::covariance3<double>(points, prepared.center);
    prepared.frame = rch::frames::make_robust_principal_frame(scatter, tau_quant_squared);
    return prepared;
}

// Builds an MRCD robust frame, falling back to sample covariance when disabled.
[[nodiscard]] inline auto
mrcd_or_sample_frame(const std::span<const double> points_xyz, const double tau_quant_squared = 4.0)
    -> FramePreparation {
    const auto points = materialize_points(points_xyz);
    FramePreparation prepared{};
    // Use the same adaptive trimming fraction as the DetMCD arm. MRCD's alpha has
    // the same meaning as MCD's -- Boudt et al. (2020) define the h-subset and the
    // consistency factor \(c_\alpha\) from the identical trimming proportion
    // \(\alpha=(n-h)/n\).
    rch::robust::MrcdOptions options{};
    options.alpha = rch::robust::adaptive_mcd_pilot(points).alpha;
    const auto robust = rch::robust::mrcd(points, options);
    const bool robust_ok = robust.policy == rch::robust::FallbackPolicy::none ||
                           robust.policy == rch::robust::FallbackPolicy::chi2_regularized;
    if (robust_ok && rch::core::is_finite(robust.scatter)) {
        prepared.center = robust.center;
        prepared.frame =
            rch::frames::make_robust_principal_frame(robust.scatter, tau_quant_squared);
        prepared.scatter_regularized = robust.used_regularization;
        return prepared;
    }

    prepared.robust_fallback_used = true;
    prepared.center = rch::core::mean3<double>(points);
    const auto scatter = rch::core::covariance3<double>(points, prepared.center);
    prepared.frame = rch::frames::make_robust_principal_frame(scatter, tau_quant_squared);
    return prepared;
}

// Builds a DetMCD robust frame, falling back to sample covariance when disabled.
[[nodiscard]] inline auto det_mcd_or_sample_frame(
    const std::span<const double> points_xyz, const double tau_quant_squared = 4.0
) -> FramePreparation {
    const auto points = materialize_points(points_xyz);
    FramePreparation prepared{};
    rch::robust::DetMcdOptions options{};
    options.alpha = rch::robust::adaptive_mcd_pilot(points).alpha;
    const auto robust = rch::robust::det_mcd(points, options);
    const bool robust_ok = robust.policy == rch::robust::FallbackPolicy::hr_adjusted_f ||
                           robust.policy == rch::robust::FallbackPolicy::chi2_regularized ||
                           robust.policy == rch::robust::FallbackPolicy::none;
    if (robust_ok && rch::core::is_finite(robust.scatter)) {
        prepared.center = robust.center;
        prepared.frame =
            rch::frames::make_robust_principal_frame(robust.scatter, tau_quant_squared);
        prepared.scatter_regularized = robust.used_regularization;
        return prepared;
    }

    prepared.robust_fallback_used = true;
    prepared.center = rch::core::mean3<double>(points);
    const auto scatter = rch::core::covariance3<double>(points, prepared.center);
    prepared.frame = rch::frames::make_robust_principal_frame(scatter, tau_quant_squared);
    return prepared;
}

// Dispatches frame preparation by estimator kind.
[[nodiscard]] inline auto prepare_frame(
    const std::span<const double> points_xyz,
    const FrameEstimator estimator,
    const double tau_quant_squared = 4.0
) -> FramePreparation {
    switch (estimator) {
    case FrameEstimator::SampleCovariance:
        return sample_frame(points_xyz, tau_quant_squared);
    case FrameEstimator::OGK:
        return ogk_or_sample_frame(points_xyz, tau_quant_squared);
    case FrameEstimator::MRCD:
        return mrcd_or_sample_frame(points_xyz, tau_quant_squared);
    case FrameEstimator::DetMCD:
    default:
        return det_mcd_or_sample_frame(points_xyz, tau_quant_squared);
    }
}

// Encodes keys for all points, sorts by key tuple, and fills diagnostics.
template <typename KeyFactory>
[[nodiscard]] inline auto sort_with_keys(
    const std::span<const double> points_xyz,
    const OrderingMethod method,
    const rch::curves::BitsAxis3& bits_axis,
    const rch::core::Vec3<double>& center,
    const rch::core::Vec3<double>& half_extent,
    const rch::core::Matrix3<double>& frame_axes,
    const bool scatter_regularized,
    const bool robust_fallback_used,
    KeyFactory&& make_key
) -> OrderingExpected {
    const std::size_t n = points_xyz.size() / 3U;
    OrderingResult result{};
    result.method = method;
    result.permutation = make_identity_permutation(n);
    result.primary_keys.assign(n, 0U);
    result.bits_axis = bits_axis;
    result.center = center;
    result.half_extent = half_extent;
    result.frame_axes = frame_axes;
    result.scatter_regularized = scatter_regularized;
    result.robust_fallback_used = robust_fallback_used;
    result.finite_only_passed = true;

    std::vector<rch::curves::CurveKey> keys(n);
    for (std::size_t i = 0U; i < n; ++i) {
        const auto key = make_key(i);
        if (!key.has_value()) {
            return std::unexpected(
                OrderingError{
                    OrderingErrorCode::key_encoding_failed,
                    "curve key encoding failed",
                }
            );
        }
        keys[i] = *key;
        result.primary_keys[i] = key->hilbert;
    }

    std::ranges::sort(
        result.permutation, [&keys](const std::uint64_t lhs, const std::uint64_t rhs) noexcept {
            return keys[static_cast<std::size_t>(lhs)] < keys[static_cast<std::size_t>(rhs)];
        }
    );
    result.output_hash = make_output_hash(result);
    return result;
}

// Returns the identity-order baseline result.
[[nodiscard]] inline auto order_input(const std::span<const double> points_xyz)
    -> OrderingExpected {
    const std::size_t n = points_xyz.size() / 3U;
    OrderingResult result{};
    result.method = OrderingMethod::InputOrder;
    result.permutation = make_identity_permutation(n);
    result.primary_keys = result.permutation;
    result.bits_axis = {0U, 0U, 0U};
    result.finite_only_passed = true;
    result.output_hash = make_output_hash(result);
    return result;
}

// Returns the coordinate lexicographic baseline result.
[[nodiscard]] inline auto order_lexicographic(const std::span<const double> points_xyz)
    -> OrderingExpected {
    return sort_with_keys(
        points_xyz,
        OrderingMethod::Lexicographic,
        rch::curves::BitsAxis3{0U, 0U, 0U},
        rch::core::Vec3<double>{},
        rch::core::Vec3<double>{},
        rch::core::identity_matrix3<double>(),
        false,
        false,
        [points_xyz](const std::size_t i) -> std::optional<rch::curves::CurveKey> {
            const auto p = point_at(points_xyz, i);
            return rch::curves::CurveKey{0U, p[0], p[1], p[2], i};
        }
    );
}

// Orders raw AABB coordinates by Morton or compact Hilbert keys.
[[nodiscard]] inline auto order_raw_curve(
    const std::span<const double> points_xyz,
    const OrderingConfig& config,
    const OrderingMethod method
) -> OrderingExpected {
    const Bounds3 bounds = raw_bounds(points_xyz);
    const auto half_extent = half_extent_from_bounds(bounds);
    const auto center = center_from_bounds(bounds);
    const auto bits_axis = compact_bits_for(half_extent, points_xyz.size() / 3U, config);

    return sort_with_keys(
        points_xyz,
        method,
        bits_axis,
        center,
        half_extent,
        rch::core::identity_matrix3<double>(),
        false,
        false,
        [points_xyz, bounds, bits_axis, method](const std::size_t i)
            -> std::optional<rch::curves::CurveKey> {
            const auto p = point_at(points_xyz, i);
            const auto q = quantized_point(p, bounds, bits_axis);
            std::optional<std::uint64_t> curve_key{};
            if (method == OrderingMethod::Morton) {
                curve_key = rch::curves::Morton3::encode(q, bits_axis);
            } else {
                curve_key = rch::curves::Hilbert3Compact::encode(q, bits_axis);
            }
            if (!curve_key.has_value()) {
                return std::nullopt;
            }
            return rch::curves::CurveKey{*curve_key, p[0], p[1], p[2], i};
        }
    );
}

// Orders raw AABB coordinates by equal-depth standard Hilbert keys.
[[nodiscard]] inline auto
order_isotropic_hilbert(const std::span<const double> points_xyz, const OrderingConfig& config)
    -> OrderingExpected {
    const Bounds3 bounds = raw_bounds(points_xyz);
    const auto half_extent = half_extent_from_bounds(bounds);
    const auto center = center_from_bounds(bounds);
    const std::uint8_t bits = (config.bit_alloc == BitAllocator::SampleCountUniform)
                                  ? sample_count_uniform_bits(points_xyz.size() / 3U, config)
                                  : equal_bits(config);
    const auto bits_axis = uniform_bits_axis(bits);

    return sort_with_keys(
        points_xyz,
        OrderingMethod::IsotropicHilbert,
        bits_axis,
        center,
        half_extent,
        rch::core::identity_matrix3<double>(),
        false,
        false,
        [points_xyz, bounds, bits, bits_axis](const std::size_t i)
            -> std::optional<rch::curves::CurveKey> {
            const auto p = point_at(points_xyz, i);
            const auto q = quantized_point(p, bounds, bits_axis);
            const auto curve_key = rch::curves::Hilbert3Standard::encode(q, bits);
            if (!curve_key.has_value()) {
                return std::nullopt;
            }
            return rch::curves::CurveKey{*curve_key, p[0], p[1], p[2], i};
        }
    );
}

// Orders raw AABB coordinates by compact Hilbert keys.
[[nodiscard]] inline auto
order_compact_aabb(const std::span<const double> points_xyz, const OrderingConfig& config)
    -> OrderingExpected {
    const Bounds3 bounds = raw_bounds(points_xyz);
    const auto half_extent = half_extent_from_bounds(bounds);
    const auto center = center_from_bounds(bounds);
    const auto bits_axis = compact_bits_for(half_extent, points_xyz.size() / 3U, config);

    return sort_with_keys(
        points_xyz,
        OrderingMethod::CompactHilbertAABB,
        bits_axis,
        center,
        half_extent,
        rch::core::identity_matrix3<double>(),
        false,
        false,
        [points_xyz,
         bounds,
         bits_axis](const std::size_t i) -> std::optional<rch::curves::CurveKey> {
            const auto p = point_at(points_xyz, i);
            const auto q = quantized_point(p, bounds, bits_axis);
            const auto curve_key = rch::curves::Hilbert3Compact::encode(q, bits_axis);
            if (!curve_key.has_value()) {
                return std::nullopt;
            }
            return rch::curves::CurveKey{*curve_key, p[0], p[1], p[2], i};
        }
    );
}

// Orders projected frame coordinates by compact Hilbert or Morton keys.
[[nodiscard]] inline auto order_frame_curve(
    const std::span<const double> points_xyz,
    const OrderingConfig& config,
    const OrderingMethod method,
    const FramePreparation& prepared
) -> OrderingExpected {
    const auto domain = frame_domain(points_xyz, prepared.center, prepared.frame);
    const auto& covering_half_extents = domain.covering_half_extents;
    const auto bounds_half_extents = uses_statistical_frame_domain(config.bit_alloc)
                                         ? prepared.frame.half_extents
                                         : covering_half_extents;
    // \(N_{\mathrm{core}}\): points occupying the core box. Falls back to the full count only
    // for a degenerate frame that contains nothing.
    const std::size_t support_count =
        domain.core_occupancy > 0U ? domain.core_occupancy : points_xyz.size() / 3U;

    rch::curves::BitsAxis3 bits_axis{};
    if (config.bit_alloc == BitAllocator::HybridOccupancy) {
        bits_axis = hybrid_occupancy_bits_for(
            prepared.frame.half_extents, covering_half_extents, support_count, config
        );
    } else if (config.bit_alloc == BitAllocator::FrameCoreOccupancy) {
        bits_axis = occupancy_bits_for(
            prepared.frame.half_extents, support_count, config, config.min_axis_bits
        );
    } else {
        bits_axis = compact_bits_for(covering_half_extents, points_xyz.size() / 3U, config);
    }
    const Bounds3 bounds = bounds_from_half_extents(bounds_half_extents);
    const bool morton = method == OrderingMethod::RobustFrameMorton;

    auto ordered = sort_with_keys(
        points_xyz,
        method,
        bits_axis,
        prepared.center,
        bounds_half_extents,
        prepared.frame.axes,
        prepared.scatter_regularized,
        prepared.robust_fallback_used,
        [points_xyz, bounds, prepared, bits_axis, morton](const std::size_t i)
            -> std::optional<rch::curves::CurveKey> {
            const auto raw = point_at(points_xyz, i);
            const auto y =
                rch::frames::project_to_robust_frame(raw, prepared.center, prepared.frame);
            const auto q = quantized_point(y, bounds, bits_axis);
            std::optional<std::uint64_t> curve_key{};
            if (morton) {
                curve_key = rch::curves::Morton3::encode(q, bits_axis);
            } else {
                curve_key = rch::curves::Hilbert3Compact::encode(q, bits_axis);
            }
            if (!curve_key.has_value()) {
                return std::nullopt;
            }
            return rch::curves::CurveKey{*curve_key, raw[0], raw[1], raw[2], i};
        }
    );
    return ordered;
}

} // namespace detail

// Validates input and dispatches the selected ordering strategy.
[[nodiscard]] inline auto
order_point_cloud(const std::span<const double> points_xyz, const OrderingConfig& config = {})
    -> OrderingExpected {
    const auto count = detail::point_count(points_xyz);
    if (!count.has_value()) {
        return std::unexpected(
            OrderingError{
                OrderingErrorCode::invalid_shape,
                "points_xyz must be N*3 row-major doubles",
            }
        );
    }
    if (!detail::validate_finite(points_xyz)) {
        return std::unexpected(
            OrderingError{
                OrderingErrorCode::invalid_input,
                "points_xyz contains NaN or infinity",
            }
        );
    }

    OrderingExpected result = std::unexpected(
        OrderingError{
            OrderingErrorCode::unsupported_method,
            "unsupported ordering method",
        }
    );
    switch (config.method) {
    case OrderingMethod::InputOrder:
        result = detail::order_input(points_xyz);
        break;
    case OrderingMethod::Lexicographic:
        result = detail::order_lexicographic(points_xyz);
        break;
    case OrderingMethod::Morton:
        result = detail::order_raw_curve(points_xyz, config, config.method);
        break;
    case OrderingMethod::IsotropicHilbert:
        result = detail::order_isotropic_hilbert(points_xyz, config);
        break;
    case OrderingMethod::CompactHilbertAABB:
        result = detail::order_compact_aabb(points_xyz, config);
        break;
    case OrderingMethod::PcaCompactHilbert:
        result = detail::order_frame_curve(
            points_xyz,
            config,
            config.method,
            detail::sample_frame(points_xyz, config.tau_quant_squared)
        );
        break;
    case OrderingMethod::RobustFrameMorton:
    case OrderingMethod::RCH:
        result = detail::order_frame_curve(
            points_xyz,
            config,
            config.method,
            detail::prepare_frame(points_xyz, config.frame, config.tau_quant_squared)
        );
        break;
    default:
        break;
    }

    // Post-sort local MIAD refinement is applied here, uniformly across methods,
    // so the off/all refinement axis can be ablated cleanly.
    if (result.has_value() && detail::should_refine(config.method, config.refinement)) {
        detail::apply_miad_refinement(points_xyz, *result);
    }
    return result;
}

template <OrderingMethod Method>
// Compile-time strategy wrapper that pins `OrderingMethod`.
class StaticOrderingStrategy final : public OrderingStrategy {
public:
    [[nodiscard]] auto method() const noexcept -> OrderingMethod override {
        return Method;
    }

    [[nodiscard]] auto
    order(const std::span<const double> points_xyz, const OrderingConfig& config) const
        -> OrderingExpected override {
        OrderingConfig local = config;
        local.method = Method;
        return order_point_cloud(points_xyz, local);
    }
};

} // namespace rch::orderings
