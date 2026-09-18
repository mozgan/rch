// ----------------------------------------------------------------------------
// test_refinement_modes.cpp — refinement-axis ablation hook.
//
// Validates the RefinementMode axis added to the ordering facade:
//   * Off refines no method;
//   * All refines every method, using the exact same post-sort passes.
// The cross-mode equalities are expressed against the internal
// detail::apply_miad_refinement helper so they hold whether or not the
// refinement actually moves a given cloud, while a hand-built zig-zag cloud
// guarantees the pass fires at least once.
// ----------------------------------------------------------------------------

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <numeric>
#include <span>
#include <vector>

#include "rch/orderings/orderer.hpp"

#include <gtest/gtest.h>

namespace {

using rch::orderings::OrderingConfig;
using rch::orderings::OrderingMethod;
using rch::orderings::OrderingResult;
using rch::orderings::RefinementMode;

// A 1-D zig-zag along x: input order 0,1,2,... is intentionally not
// MIAD-optimal (point i's nearest neighbour is i+2, not i+1), so the local
// refinement provably changes any identity-like permutation.
[[nodiscard]] auto zigzag_cloud() -> std::vector<double> {
    std::vector<double> points;
    constexpr std::array<double, 12> xs{0.0, 5.0, 1.0, 6.0, 2.0, 7.0,
                                        3.0, 8.0, 4.0, 9.0, 4.5, 9.5};
    for (const double x : xs) {
        points.push_back(x);
        points.push_back(0.0);
        points.push_back(0.0);
    }
    return points;
}

// Monotonic in x but alternating in y, so the lexicographic order (sorted by
// x) is the identity yet not MIAD-optimal: point i's nearest neighbour is i+2.
// Used to show the refinement pass still fires for a refined baseline now that
// the input-order control is excluded from refinement.
[[nodiscard]] auto lex_suboptimal_cloud() -> std::vector<double> {
    std::vector<double> points;
    for (std::size_t i = 0U; i < 8U; ++i) {
        points.push_back(static_cast<double>(i));      // x strictly increasing
        points.push_back((i % 2U == 0U) ? 0.0 : 10.0); // y alternates
        points.push_back(0.0);
    }
    return points;
}

[[nodiscard]] auto order(
    const std::vector<double>& points,
    const OrderingMethod method,
    const RefinementMode refinement
) -> OrderingResult {
    OrderingConfig config{};
    config.method = method;
    config.refinement = refinement;
    auto result = rch::orderings::order_point_cloud(std::span<const double>{points}, config);
    EXPECT_TRUE(result.has_value()) << static_cast<int>(method);
    return *result;
}

// Reference: the Off result with the same two refinement passes applied by hand.
[[nodiscard]] auto manually_refined(
    const std::vector<double>& points, const OrderingMethod method
) -> OrderingResult {
    OrderingResult reference = order(points, method, RefinementMode::Off);
    rch::orderings::detail::apply_miad_refinement(std::span<const double>{points}, reference);
    return reference;
}

[[nodiscard]] auto identity(const std::size_t n) -> std::vector<std::uint64_t> {
    std::vector<std::uint64_t> values(n);
    std::iota(values.begin(), values.end(), std::uint64_t{0U});
    return values;
}

TEST(RefinementModes, DefaultConfigIsOff) {
    EXPECT_EQ(OrderingConfig{}.refinement, RefinementMode::Off);
}

TEST(RefinementModes, DefaultMatchesExplicitOffForRch) {
    const auto points = zigzag_cloud();
    OrderingConfig default_config{};
    default_config.method = OrderingMethod::RCH;
    const auto from_default =
        rch::orderings::order_point_cloud(std::span<const double>{points}, default_config);
    ASSERT_TRUE(from_default.has_value());
    const auto explicit_off = order(points, OrderingMethod::RCH, RefinementMode::Off);
    EXPECT_EQ(from_default->output_hash, explicit_off.output_hash);
    EXPECT_EQ(from_default->permutation, explicit_off.permutation);
}

// Under All every method EXCEPT the input-order control gets exactly the
// shared post-sort refinement.
TEST(RefinementModes, AllModeRefinesEveryMethodExceptInput) {
    const auto points = zigzag_cloud();
    constexpr std::array refined_methods{
        OrderingMethod::Lexicographic,
        OrderingMethod::Morton,
        OrderingMethod::IsotropicHilbert,
        OrderingMethod::CompactHilbertAABB,
        OrderingMethod::PcaCompactHilbert,
        OrderingMethod::RobustFrameMorton,
        OrderingMethod::RCH,
    };
    for (const OrderingMethod method : refined_methods) {
        const auto all = order(points, method, RefinementMode::All);
        const auto reference = manually_refined(points, method);
        EXPECT_EQ(all.permutation, reference.permutation) << static_cast<int>(method);
        EXPECT_EQ(all.output_hash, reference.output_hash) << static_cast<int>(method);
    }
}

// The input-order baseline is a fixed identity reference in every mode: it is
// never refined, so off and all both return the identity permutation.
TEST(RefinementModes, InputOrderIsIdentityInEveryMode) {
    const auto points = zigzag_cloud();
    const auto n = points.size() / 3U;
    for (const RefinementMode mode : {RefinementMode::Off, RefinementMode::All}) {
        const auto result = order(points, OrderingMethod::InputOrder, mode);
        EXPECT_EQ(result.permutation, identity(n)) << static_cast<int>(mode);
    }
}

// All applies the same shared post-sort refinement to RCH as to every other
// non-input method.
TEST(RefinementModes, RchPathRefinedUnderAll) {
    const auto points = zigzag_cloud();
    const auto all = order(points, OrderingMethod::RCH, RefinementMode::All);
    const auto reference = manually_refined(points, OrderingMethod::RCH);
    EXPECT_EQ(all.permutation, reference.permutation);
    EXPECT_EQ(all.output_hash, reference.output_hash);
}

// The pass is not a no-op: on a lexicographically-suboptimal cloud, All
// actually reorders a refined baseline (lexicographic) while staying a valid
// permutation. Uses lexicographic (not input order) because the input-order
// control is now held fixed.
TEST(RefinementModes, RefinementActuallyFiresForRefinedBaseline) {
    const auto points = lex_suboptimal_cloud();
    const auto n = points.size() / 3U;
    const auto lex_off = order(points, OrderingMethod::Lexicographic, RefinementMode::Off);
    EXPECT_EQ(lex_off.permutation, identity(n)); // strictly increasing x => identity

    const auto lex_all = order(points, OrderingMethod::Lexicographic, RefinementMode::All);
    EXPECT_NE(lex_all.permutation, identity(n));
    EXPECT_NE(lex_all.output_hash, lex_off.output_hash);

    // Still a valid permutation of the same index set.
    auto sorted = lex_all.permutation;
    std::ranges::sort(sorted);
    EXPECT_EQ(sorted, identity(n));
}

} // namespace
