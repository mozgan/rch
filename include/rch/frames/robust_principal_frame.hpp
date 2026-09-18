#pragma once

// ----------------------------------------------------------------------------
// robust_principal_frame.hpp - robust principal-axis frame from a robust scatter
// matrix.
//
// Algorithm:
//   - Treat the input scatter as a symmetric covariance-like matrix
//     \(\Sigma\).
//   - Compute \(\Sigma = Q \Lambda Q^T\) with the deterministic 3x3 Jacobi
//     solver, then reorder eigenpairs so
//     \(\lambda_0 \ge \lambda_1 \ge \lambda_2\).
//   - Compute relative eigengaps
//     \(g_{12}=(\lambda_0-\lambda_1)/\max_j|\lambda_j|\) and
//     \(g_{23}=(\lambda_1-\lambda_2)/\max_j|\lambda_j|\).
//   - Use the principal eigenframe only when the eigensolver converged and both
//     gaps exceed the tolerance; otherwise fall back to canonical axes.
//   - Set half extents as \(a_j=\sqrt{\tau_q^2\,s_j}\), using eigenvalue
//     spreads in principal mode and diagonal scatter spreads in fallback mode.
//   - Project points by \(y = Q^T(x-\mu)\), where the columns of \(Q\) are the
//     selected axes.
//
// References:
//   - Gene H. Golub and Charles F. Van Loan, Matrix Computations,
//     4th ed., 2013, DOI: 10.56021/9781421407944.
//   - I. T. Jolliffe, Principal Component Analysis, 1986,
//     DOI: 10.1007/978-1-4757-1904-8.
//   - Mia Hubert, Peter J. Rousseeuw, and Tim Verdonck, A Deterministic
//     Algorithm for Robust Location and Scatter, 2012,
//     DOI: 10.1080/10618600.2012.672100.
//   - Kris Boudt, Peter J. Rousseeuw, Steven Vanduffel, and Tim Verdonck,
//     The minimum regularized covariance determinant estimator, 2020,
//     DOI: 10.1007/s11222-019-09869-x.
// ----------------------------------------------------------------------------

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <limits>

#include "rch/core/matrix3.hpp"
#include "rch/frames/eigen3x3.hpp"

namespace rch::frames {

// Records whether the frame uses eigenvectors or the deterministic fallback.
enum class RobustFrameMode {
    principal_eigenframe,
    canonical_axes_fallback,
};

// Default relative gap threshold for rejecting unstable eigenspaces.
inline constexpr double kEigengapRelativeTolerance = 256.0 * std::numeric_limits<double>::epsilon();

// Principal-frame axes, spreads, half extents, and fallback diagnostics.
//
// `axes` is orthonormal but not necessarily right-handed: reversing the solver's
// ascending eigenpairs into descending order flips \(\det\), and the per-column sign
// canonicalization flips it again, so \(\det(Q) = \pm 1\) in roughly equal measure.
// The sign is a deterministic function of the input, so projections stay reproducible;
// consumers that need a specific handedness must impose it themselves.
struct RobustPrincipalFrame {
    rch::core::Matrix3<double> axes{rch::core::identity_matrix3<double>()};
    rch::core::Vec3<double> eigenvalues{};
    rch::core::Vec3<double> half_extents{};
    RobustFrameMode mode{RobustFrameMode::canonical_axes_fallback};
    double gap12{};
    double gap23{};
    bool eigensolver_converged{};
};

namespace detail {

// Maps ascending Jacobi output to descending PCA axis order.
inline constexpr std::array<std::size_t, 3> kDescendingEigenOrder{2U, 1U, 0U};

// Converts a spread \(s_j\) to \(a_j=\sqrt{\tau_q^2 s_j}\).
[[nodiscard]] inline auto
scaled_half_extent(const double tau_quant_squared, const double spread) noexcept -> double {
    if (!std::isfinite(tau_quant_squared) || !std::isfinite(spread)) {
        return 0.0;
    }
    if (tau_quant_squared <= 0.0 || spread <= 0.0) {
        return 0.0;
    }
    return std::sqrt(tau_quant_squared) * std::sqrt(spread);
}

// Computes \(Q^T\delta\) for axis columns stored in \(Q\).
[[nodiscard]] inline auto project_delta_to_axes(
    const rch::core::Vec3<double>& delta, const rch::core::Matrix3<double>& axes
) noexcept -> rch::core::Vec3<double> {
    rch::core::Vec3<double> projected{};
    for (std::size_t axis = 0U; axis < 3U; ++axis) {
        projected[axis] =
            (axes(0U, axis) * delta[0]) + (axes(1U, axis) * delta[1]) + (axes(2U, axis) * delta[2]);
    }
    return projected;
}

} // namespace detail

// Builds a stable principal frame, falling back when eigengaps are too small.
[[nodiscard]] inline auto make_robust_principal_frame(
    const rch::core::Matrix3<double>& scatter,
    const double tau_quant_squared,
    double eigengap_relative_tolerance = kEigengapRelativeTolerance
) noexcept -> RobustPrincipalFrame {
    if (!std::isfinite(eigengap_relative_tolerance) || eigengap_relative_tolerance < 0.0) {
        eigengap_relative_tolerance = kEigengapRelativeTolerance;
    }

    const auto eigen = cyclic_jacobi_eigen_symmetric3(scatter);

    RobustPrincipalFrame frame{};
    frame.eigensolver_converged = eigen.converged;
    for (std::size_t out_axis = 0U; out_axis < 3U; ++out_axis) {
        frame.eigenvalues[out_axis] = eigen.eigenvalues[detail::kDescendingEigenOrder[out_axis]];
    }

    double eigen_scale = 0.0;
    bool finite_eigenvalues = true;
    for (const double eigenvalue : frame.eigenvalues) {
        finite_eigenvalues = finite_eigenvalues && std::isfinite(eigenvalue);
        eigen_scale = std::max(eigen_scale, std::abs(eigenvalue));
    }
    const double gap_denominator = eigen_scale;
    const double safe_gap_denominator = (gap_denominator > 0.0) ? gap_denominator : 1.0;
    frame.gap12 = (frame.eigenvalues[0] - frame.eigenvalues[1]) / safe_gap_denominator;
    frame.gap23 = (frame.eigenvalues[1] - frame.eigenvalues[2]) / safe_gap_denominator;

    const bool must_fallback =
        !frame.eigensolver_converged || !finite_eigenvalues || !(gap_denominator > 0.0) ||
        frame.gap12 <= eigengap_relative_tolerance || frame.gap23 <= eigengap_relative_tolerance;
    if (must_fallback) {
        frame.mode = RobustFrameMode::canonical_axes_fallback;
        frame.axes = rch::core::identity_matrix3<double>();
        for (std::size_t axis = 0U; axis < 3U; ++axis) {
            frame.half_extents[axis] =
                detail::scaled_half_extent(tau_quant_squared, scatter(axis, axis));
        }
        return frame;
    }

    frame.mode = RobustFrameMode::principal_eigenframe;
    for (std::size_t out_axis = 0U; out_axis < 3U; ++out_axis) {
        const std::size_t in_axis = detail::kDescendingEigenOrder[out_axis];
        frame.half_extents[out_axis] =
            detail::scaled_half_extent(tau_quant_squared, frame.eigenvalues[out_axis]);
        for (std::size_t row = 0U; row < 3U; ++row) {
            frame.axes(row, out_axis) = eigen.eigenvectors(row, in_axis);
        }
    }
    return frame;
}

// Centers a point and projects it into the selected robust frame.
[[nodiscard]] inline auto project_to_robust_frame(
    const rch::core::Vec3<double>& point,
    const rch::core::Vec3<double>& center,
    const RobustPrincipalFrame& frame
) noexcept -> rch::core::Vec3<double> {
    const rch::core::Vec3<double> delta{
        point[0] - center[0],
        point[1] - center[1],
        point[2] - center[2],
    };
    return detail::project_delta_to_axes(delta, frame.axes);
}

} // namespace rch::frames
