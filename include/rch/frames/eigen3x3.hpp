#pragma once

// ----------------------------------------------------------------------------
// eigen3x3.hpp - symmetric 3x3 eigendecomposition via deterministic cyclic
// Jacobi sweeps.
//
// Algorithm:
//   - Start with a symmetric matrix \(A \in R^{3 \times 3}\) and
//     eigenvector accumulator \(V=I\).
//   - Run cyclic Jacobi sweeps with fixed pivot order \((0,1),(0,2),(1,2)\)
//     for deterministic output.
//   - For pivot \((p,q)\), compute
//     \(\tau=(a_{qq}-a_{pp})/(2a_{pq})\),
//     \(t=\operatorname{sign}(\tau)/(|\tau|+\sqrt{1+\tau^2})\),
//     \(c=1/\sqrt{1+t^2}\), and \(s=tc\).
//   - Apply the plane rotation \(G\) as \(A \leftarrow G^T A G\) and
//     \(V \leftarrow V G\), explicitly zeroing \(a_{pq}\).
//   - Normalize by the largest absolute entry before iteration so convergence
//     and pivot decisions are scale-independent, then scale eigenvalues back.
//   - Stop when \(\|\operatorname{off}(A)\|_F\) is small relative to the
//     normalized matrix, then sort eigenpairs by ascending eigenvalue and
//     canonicalize vector signs.
//   - Use `std::hypot`-based norms and rotation parameters to avoid avoidable
//     overflow for large finite scatter matrices.
//
// References:
//   - Gene H. Golub and Charles F. Van Loan, Matrix Computations,
//     4th ed., 2013, DOI: 10.56021/9781421407944.
//   - Roger A. Horn and Charles R. Johnson, Matrix Analysis,
//     2nd ed., 2012, DOI: 10.1017/CBO9781139020411.
//   - ISO/IEC, ISO/IEC 14882:2020 Programming languages - C++, `std::hypot`.
// ----------------------------------------------------------------------------

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <limits>

#include "rch/core/matrix3.hpp"

namespace rch::frames {

// Relative stopping tolerance for the normalized off-diagonal norm.
inline constexpr double kDefaultJacobiTolerance = 1.0e-15;

// Eigenpairs and convergence metadata for a 3x3 symmetric eigensolve.
struct Eigen3x3 {
    rch::core::Vec3<double> eigenvalues{};
    rch::core::Matrix3<double> eigenvectors{};
    std::size_t sweeps{};
    bool converged{};
};

namespace detail {

// Computes \(\|\operatorname{off}(A)\|_F\) over the strict upper triangle.
[[nodiscard]] inline auto off_diagonal_norm(const rch::core::Matrix3<double>& matrix) noexcept
    -> double {
    return std::hypot(matrix(0U, 1U), matrix(0U, 2U), matrix(1U, 2U));
}

// Computes \(\|A\|_F\) without avoidable overflow for large finite entries.
[[nodiscard]] inline auto stable_frobenius_norm(const rch::core::Matrix3<double>& matrix) noexcept
    -> double {
    double norm = 0.0;
    for (std::size_t row = 0U; row < 3U; ++row) {
        for (std::size_t col = 0U; col < 3U; ++col) {
            norm = std::hypot(norm, matrix(row, col));
        }
    }
    return norm;
}

[[nodiscard]] inline auto max_abs_entry(const rch::core::Matrix3<double>& matrix) noexcept
    -> double {
    double max_abs = 0.0;
    for (std::size_t row = 0U; row < 3U; ++row) {
        for (std::size_t col = 0U; col < 3U; ++col) {
            const double entry_abs = std::abs(matrix(row, col));
            if (entry_abs > max_abs) {
                max_abs = entry_abs;
            }
        }
    }
    return max_abs;
}

// Applies one Jacobi rotation to annihilate the \((p,q)\) entry.
inline void rotate_pair(
    rch::core::Matrix3<double>& matrix,
    rch::core::Matrix3<double>& eigenvectors,
    const std::size_t p,
    const std::size_t q
) noexcept {
    const double apq = matrix(p, q);
    if (!(std::abs(apq) > 0.0)) {
        return;
    }

    const double app = matrix(p, p);
    const double aqq = matrix(q, q);
    const double tau = (aqq - app) / (2.0 * apq);
    const double sign = tau < 0.0 ? -1.0 : 1.0;
    const double t = sign / (std::abs(tau) + std::hypot(1.0, tau));
    const double c = 1.0 / std::sqrt(1.0 + (t * t));
    const double s = t * c;

    matrix(p, p) = app - (t * apq);
    matrix(q, q) = aqq + (t * apq);
    matrix(p, q) = 0.0;
    matrix(q, p) = 0.0;

    for (std::size_t r = 0U; r < 3U; ++r) {
        if (r == p || r == q) {
            continue;
        }
        const double arp = matrix(r, p);
        const double arq = matrix(r, q);
        matrix(r, p) = (c * arp) - (s * arq);
        matrix(p, r) = matrix(r, p);
        matrix(r, q) = (s * arp) + (c * arq);
        matrix(q, r) = matrix(r, q);
    }

    for (std::size_t r = 0U; r < 3U; ++r) {
        const double vrp = eigenvectors(r, p);
        const double vrq = eigenvectors(r, q);
        eigenvectors(r, p) = (c * vrp) - (s * vrq);
        eigenvectors(r, q) = (s * vrp) + (c * vrq);
    }
}

// Flips an eigenvector column so its largest-magnitude entry is non-negative.
inline void
canonicalize_column(rch::core::Matrix3<double>& matrix, const std::size_t col) noexcept {
    std::size_t pivot = 0U;
    double pivot_abs = std::abs(matrix(0U, col));
    for (std::size_t row = 1U; row < 3U; ++row) {
        const double candidate_abs = std::abs(matrix(row, col));
        if (candidate_abs > pivot_abs) {
            pivot = row;
            pivot_abs = candidate_abs;
        }
    }
    if (matrix(pivot, col) < 0.0) {
        for (std::size_t row = 0U; row < 3U; ++row) {
            matrix(row, col) = -matrix(row, col);
        }
    }
}

} // namespace detail

// Solves the symmetric 3x3 eigenproblem with fixed-order cyclic Jacobi sweeps.
//
// Only the upper triangle of `input` is read as independent data: `rotate_pair` mirrors
// its updates across the diagonal, so a non-symmetric argument is decomposed as if its
// lower triangle equalled its upper one, rather than being rejected or symmetrized.
// Every in-repo caller passes a bit-level symmetric matrix.
[[nodiscard]] inline auto cyclic_jacobi_eigen_symmetric3(
    const rch::core::Matrix3<double>& input,
    const std::size_t max_sweeps = 32U,
    const double tolerance = kDefaultJacobiTolerance
) noexcept -> Eigen3x3 {
    Eigen3x3 result{};
    if (!rch::core::is_finite(input)) {
        result.eigenvectors = rch::core::identity_matrix3<double>();
        return result;
    }

    // A zero tolerance is rejected alongside negative and non-finite ones: exact zero
    // asks for exact diagonalization in floating-point arithmetic and can stall on
    // residual roundoff.
    const double effective_tolerance =
        (std::isfinite(tolerance) && tolerance > 0.0) ? tolerance : kDefaultJacobiTolerance;

    const double input_scale = detail::max_abs_entry(input);
    if (!(input_scale > 0.0)) {
        result.eigenvectors = rch::core::identity_matrix3<double>();
        result.converged = true;
        return result;
    }

    rch::core::Matrix3<double> matrix{};
    for (std::size_t row = 0U; row < 3U; ++row) {
        for (std::size_t col = 0U; col < 3U; ++col) {
            matrix(row, col) = input(row, col) / input_scale;
        }
    }
    auto eigenvectors = rch::core::identity_matrix3<double>();
    const double scale = std::max(1.0, detail::stable_frobenius_norm(matrix));

    for (std::size_t sweep = 0U; sweep < max_sweeps; ++sweep) {
        if (detail::off_diagonal_norm(matrix) <= effective_tolerance * scale) {
            result.converged = true;
            result.sweeps = sweep;
            break;
        }
        detail::rotate_pair(matrix, eigenvectors, 0U, 1U);
        detail::rotate_pair(matrix, eigenvectors, 0U, 2U);
        detail::rotate_pair(matrix, eigenvectors, 1U, 2U);
        result.sweeps = sweep + 1U;
    }
    if (!result.converged) {
        result.converged = detail::off_diagonal_norm(matrix) <= effective_tolerance * scale;
    }

    std::array<std::size_t, 3> order{0U, 1U, 2U};
    std::ranges::sort(order, [&matrix](const std::size_t lhs, const std::size_t rhs) noexcept {
        if (rch::core::exactly_equal_for_tie_break(matrix(lhs, lhs), matrix(rhs, rhs))) {
            return lhs < rhs;
        }
        return matrix(lhs, lhs) < matrix(rhs, rhs);
    });

    rch::core::Matrix3<double> sorted_vectors{};
    for (std::size_t out = 0U; out < 3U; ++out) {
        const std::size_t in = order[out];
        result.eigenvalues[out] = matrix(in, in) * input_scale;
        for (std::size_t row = 0U; row < 3U; ++row) {
            sorted_vectors(row, out) = eigenvectors(row, in);
        }
        detail::canonicalize_column(sorted_vectors, out);
    }
    result.eigenvectors = sorted_vectors;
    return result;
}

} // namespace rch::frames
