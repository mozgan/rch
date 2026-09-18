#pragma once

// ----------------------------------------------------------------------------
// regularization.hpp
//
// References:
//   - Kris Boudt, Peter J. Rousseeuw, Steven Vanduffel, Tim Verdonck,
//     "The Minimum Regularized Covariance Determinant Estimator", 2020,
//     doi:10.1007/s11222-019-09869-x.
//   - Gene H. Golub, Charles F. Van Loan, "Matrix Computations", 2013,
//     doi:10.56021/9781421407944.
//   - Roger A. Horn, Charles R. Johnson, "Matrix Analysis", 2013,
//     doi:10.1017/CBO9781139020411.
//
// Algorithm:
//   1. Compute eigenvalues of symmetric scatter \(S\).
//   2. Accept \(S\) when \(\lambda_{\min}\) and \(\det(S)\) exceed the floor.
//   3. Otherwise add a ridge \(\delta I\) so the matrix is positive definite.
// ----------------------------------------------------------------------------

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>

#include "rch/core/matrix3.hpp"
#include "rch/frames/eigen3x3.hpp"

namespace rch::robust {

struct RegularizationResult {
    // Possibly ridged scatter matrix.
    rch::core::Matrix3<double> scatter{};
    double ridge{};
    bool applied{};
    bool rank_deficient{};
};

namespace detail {

[[nodiscard]] inline auto max_abs_entry(const rch::core::Matrix3<double>& matrix) noexcept
    -> double {
    double max_abs = 0.0;
    for (std::size_t row = 0U; row < 3U; ++row) {
        for (std::size_t col = 0U; col < 3U; ++col) {
            max_abs = std::max(max_abs, std::abs(matrix(row, col)));
        }
    }
    return max_abs;
}

} // namespace detail

[[nodiscard]] inline auto regularize_spd(
    const rch::core::Matrix3<double>& scatter, const double relative_floor = 1.0e-10
) noexcept -> RegularizationResult {
    // Ensure robust scatter is usable for inversion and determinant tests.
    RegularizationResult result{scatter, 0.0, false, false};
    if (!rch::core::is_finite(scatter)) {
        result.rank_deficient = true;
        return result;
    }

    // A non-finite or negative relative floor is meaningless; fall back to the default
    // instead of poisoning every comparison below with NaN.
    const double floor_ratio =
        (std::isfinite(relative_floor) && relative_floor >= 0.0) ? relative_floor : 1.0e-10;

    const double scatter_scale = detail::max_abs_entry(scatter);
    if (!(scatter_scale > 0.0)) {
        result.rank_deficient = true;
        return result;
    }

    rch::core::Matrix3<double> normalized{};
    for (std::size_t row = 0U; row < 3U; ++row) {
        for (std::size_t col = 0U; col < 3U; ++col) {
            normalized(row, col) = scatter(row, col) / scatter_scale;
        }
    }

    const auto eigen = rch::frames::cyclic_jacobi_eigen_symmetric3(normalized);
    if (!eigen.converged) {
        result.applied = true;
        result.rank_deficient = true;
        const double ridge = floor_ratio * scatter_scale;
        result.ridge = ridge;
        for (std::size_t axis = 0U; axis < 3U; ++axis) {
            result.scatter(axis, axis) += ridge;
        }
        return result;
    }
    const double min_eigenvalue = *std::ranges::min_element(eigen.eigenvalues);

    // Compare determinants in the trace-normalized domain: det(S) and floor^3 both
    // overflow/underflow for large or tiny well-conditioned scatters, whereas
    // det(S / scatter_scale) > relative_floor^3 is the same scale-relative test.
    const double normalized_determinant = rch::core::determinant(normalized);

    if (min_eigenvalue >= floor_ratio &&
        normalized_determinant > floor_ratio * floor_ratio * floor_ratio) {
        return result;
    }

    result.applied = true;
    result.rank_deficient = min_eigenvalue <= 0.0;
    const double floor = floor_ratio * scatter_scale;
    result.ridge = (floor_ratio - min_eigenvalue) * scatter_scale;
    if (result.ridge < floor) {
        result.ridge = floor;
    }
    for (std::size_t axis = 0U; axis < 3U; ++axis) {
        result.scatter(axis, axis) += result.ridge;
    }
    return result;
}

} // namespace rch::robust
