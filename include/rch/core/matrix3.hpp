#pragma once

// ----------------------------------------------------------------------------
// matrix3.hpp - fixed-size 3D vector and matrix primitives for the robust
// statistics, frame, ordering, and metric code paths.
//
// Algorithm:
//   - Store vectors as \(x \in \mathbb{R}^3\) and matrices as row-major
//     \(A \in \mathbb{R}^{3 \times 3}\).
//   - Implement small fixed-size operations directly: \(x \cdot y\),
//     \(Ax\), \(A^T\), \(\operatorname{tr}(A)\), \(\det(A)\), and
//     \(\|A\|_F = \sqrt{\sum_{i,j} a_{ij}^2}\).
//   - Invert a matrix as \(A^{-1} = \operatorname{adj}(A) / \det(A)\);
//     reject non-finite or near-singular cases before returning a result.
//   - Compute sample covariance as
//     \(\Sigma = (n-1)^{-1}\sum_i (x_i-\mu)(x_i-\mu)^T\).
//   - Convert IEEE-754 doubles to integer ordering keys for deterministic
//     tie-breaks without relying on platform-specific NaN comparisons.
//
// References:
//   - Gene H. Golub and Charles F. Van Loan, Matrix Computations,
//     4th ed., 2013, DOI: 10.56021/9781421407944.
//   - Roger A. Horn and Charles R. Johnson, Matrix Analysis,
//     2nd ed., 2012, DOI: 10.1017/CBO9781139020411.
//   - IEEE, IEEE Standard for Floating-Point Arithmetic, 2019,
//     DOI: 10.1109/IEEESTD.2019.8766229.
// ----------------------------------------------------------------------------

#include <array>
#include <bit>
#include <cmath>
#include <concepts>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <optional>
#include <span>

namespace rch::core {

// Three-component point/vector storage shared by 3D geometry code.
template <typename T>
using Vec3 = std::array<T, 3>;

// Row-major 3x3 matrix with unchecked element access for small hot paths.
template <typename T>
struct Matrix3 {
    std::array<std::array<T, 3>, 3> rows{};

    [[nodiscard]] constexpr auto operator()(const std::size_t row, const std::size_t col) noexcept
        -> T& {
        return rows[row][col];
    }

    [[nodiscard]] constexpr auto
    operator()(const std::size_t row, const std::size_t col) const noexcept -> const T& {
        return rows[row][col];
    }
};

template <typename T>
[[nodiscard]] constexpr auto zero_matrix3() noexcept -> Matrix3<T> {
    return Matrix3<T>{};
}

template <typename T>
[[nodiscard]] constexpr auto identity_matrix3() noexcept -> Matrix3<T> {
    Matrix3<T> matrix{};
    matrix(0U, 0U) = T{1};
    matrix(1U, 1U) = T{1};
    matrix(2U, 2U) = T{1};
    return matrix;
}

template <typename T>
[[nodiscard]] constexpr auto operator+(const Vec3<T>& lhs, const Vec3<T>& rhs) noexcept -> Vec3<T> {
    return {lhs[0] + rhs[0], lhs[1] + rhs[1], lhs[2] + rhs[2]};
}

template <typename T>
[[nodiscard]] constexpr auto operator-(const Vec3<T>& lhs, const Vec3<T>& rhs) noexcept -> Vec3<T> {
    return {lhs[0] - rhs[0], lhs[1] - rhs[1], lhs[2] - rhs[2]};
}

template <typename T>
[[nodiscard]] constexpr auto operator*(const Vec3<T>& vector, const T scalar) noexcept -> Vec3<T> {
    return {vector[0] * scalar, vector[1] * scalar, vector[2] * scalar};
}

template <typename T>
[[nodiscard]] constexpr auto operator/(const Vec3<T>& vector, const T scalar) noexcept -> Vec3<T> {
    return {vector[0] / scalar, vector[1] / scalar, vector[2] / scalar};
}

template <typename T>
[[nodiscard]] constexpr auto dot(const Vec3<T>& lhs, const Vec3<T>& rhs) noexcept -> T {
    return (lhs[0] * rhs[0]) + (lhs[1] * rhs[1]) + (lhs[2] * rhs[2]);
}

template <typename T>
[[nodiscard]] auto squared_norm(const Vec3<T>& vector) noexcept -> T {
    return dot(vector, vector);
}

template <typename T>
[[nodiscard]] constexpr auto operator+(const Matrix3<T>& lhs, const Matrix3<T>& rhs) noexcept
    -> Matrix3<T> {
    Matrix3<T> result{};
    for (std::size_t row = 0U; row < 3U; ++row) {
        for (std::size_t col = 0U; col < 3U; ++col) {
            result(row, col) = lhs(row, col) + rhs(row, col);
        }
    }
    return result;
}

template <typename T>
[[nodiscard]] constexpr auto operator-(const Matrix3<T>& lhs, const Matrix3<T>& rhs) noexcept
    -> Matrix3<T> {
    Matrix3<T> result{};
    for (std::size_t row = 0U; row < 3U; ++row) {
        for (std::size_t col = 0U; col < 3U; ++col) {
            result(row, col) = lhs(row, col) - rhs(row, col);
        }
    }
    return result;
}

// Scales every matrix entry by a scalar.
template <typename T>
[[nodiscard]] constexpr auto operator*(const Matrix3<T>& matrix, const T scalar) noexcept
    -> Matrix3<T> {
    Matrix3<T> result{};
    for (std::size_t row = 0U; row < 3U; ++row) {
        for (std::size_t col = 0U; col < 3U; ++col) {
            result(row, col) = matrix(row, col) * scalar;
        }
    }
    return result;
}

// Divides every matrix entry by a scalar.
template <typename T>
[[nodiscard]] constexpr auto operator/(const Matrix3<T>& matrix, const T scalar) noexcept
    -> Matrix3<T> {
    Matrix3<T> result{};
    for (std::size_t row = 0U; row < 3U; ++row) {
        for (std::size_t col = 0U; col < 3U; ++col) {
            result(row, col) = matrix(row, col) / scalar;
        }
    }
    return result;
}

// Applies a matrix to a 3D vector.
template <typename T>
[[nodiscard]] constexpr auto multiply(const Matrix3<T>& matrix, const Vec3<T>& vector) noexcept
    -> Vec3<T> {
    return {
        (matrix(0U, 0U) * vector[0]) + (matrix(0U, 1U) * vector[1]) + (matrix(0U, 2U) * vector[2]),
        (matrix(1U, 0U) * vector[0]) + (matrix(1U, 1U) * vector[1]) + (matrix(1U, 2U) * vector[2]),
        (matrix(2U, 0U) * vector[0]) + (matrix(2U, 1U) * vector[1]) + (matrix(2U, 2U) * vector[2])
    };
}

// Swaps rows and columns.
template <typename T>
[[nodiscard]] constexpr auto transpose(const Matrix3<T>& matrix) noexcept -> Matrix3<T> {
    Matrix3<T> result{};
    for (std::size_t row = 0U; row < 3U; ++row) {
        for (std::size_t col = 0U; col < 3U; ++col) {
            result(row, col) = matrix(col, row);
        }
    }
    return result;
}

template <typename T>
[[nodiscard]] constexpr auto trace(const Matrix3<T>& matrix) noexcept -> T {
    return matrix(0U, 0U) + matrix(1U, 1U) + matrix(2U, 2U);
}

// Computes the 3x3 determinant by cofactor expansion along the first row.
template <typename T>
[[nodiscard]] constexpr auto determinant(const Matrix3<T>& matrix) noexcept -> T {
    return (matrix(0U, 0U) *
            ((matrix(1U, 1U) * matrix(2U, 2U)) - (matrix(1U, 2U) * matrix(2U, 1U)))) -
           (matrix(0U, 1U) *
            ((matrix(1U, 0U) * matrix(2U, 2U)) - (matrix(1U, 2U) * matrix(2U, 0U)))) +
           (matrix(0U, 2U) *
            ((matrix(1U, 0U) * matrix(2U, 1U)) - (matrix(1U, 1U) * matrix(2U, 0U))));
}

namespace detail {

template <std::floating_point T>
[[nodiscard]] auto matrix_max_abs_entry(const Matrix3<T>& matrix) noexcept -> T {
    T max_abs{};
    for (std::size_t row = 0U; row < 3U; ++row) {
        for (std::size_t col = 0U; col < 3U; ++col) {
            const T entry_abs = std::abs(matrix(row, col));
            if (!std::isfinite(entry_abs)) {
                return entry_abs;
            }
            if (entry_abs > max_abs) {
                max_abs = entry_abs;
            }
        }
    }
    return max_abs;
}

} // namespace detail

// Computes \(\|A\|_F\) after scaling by the largest absolute entry.
template <std::floating_point T>
[[nodiscard]] auto frobenius_norm(const Matrix3<T>& matrix) noexcept -> T {
    const T max_abs = detail::matrix_max_abs_entry(matrix);
    if (!(max_abs > T{0}) || !std::isfinite(max_abs)) {
        return max_abs;
    }

    T sum{};
    for (std::size_t row = 0U; row < 3U; ++row) {
        for (std::size_t col = 0U; col < 3U; ++col) {
            const T scaled = matrix(row, col) / max_abs;
            sum += scaled * scaled;
        }
    }
    return max_abs * std::sqrt(sum);
}

// Treats +0 and -0 as equal, otherwise compares exact IEEE-754 bit patterns.
[[nodiscard]] inline auto exactly_equal_for_tie_break(const double lhs, const double rhs) noexcept
    -> bool {
    constexpr std::uint64_t sign_mask = UINT64_C(0x8000000000000000);
    constexpr std::uint64_t magnitude_mask = ~sign_mask;
    const std::uint64_t lhs_bits = std::bit_cast<std::uint64_t>(lhs);
    const std::uint64_t rhs_bits = std::bit_cast<std::uint64_t>(rhs);
    if ((lhs_bits & magnitude_mask) == 0U && (rhs_bits & magnitude_mask) == 0U) {
        return true;
    }
    return lhs_bits == rhs_bits;
}

// Maps IEEE-754 double bits to unsigned keys matching the required totalOrder
// clauses for signed zeros, finite values, infinities, and signed quiet/signaling
// NaNs. Where IEEE leaves same-class NaN ordering implementation-defined, this
// deliberately orders the canonical binary64 bit patterns by payload bits.
//
// Negative encodings occupy [2^63, 2^64) and are sign-magnitude, so a larger encoding
// means a more negative value; ~bits maps them decreasingly onto [0, 2^63). Non-negative
// encodings occupy [0, 2^63) increasingly and are shifted onto [2^63, 2^64) by the
// sign-bit set. The two images are disjoint and correctly ordered relative to each other,
// so the map is a strictly increasing bijection onto uint64_t.
[[nodiscard]] constexpr auto double_total_order_key(const double value) noexcept -> std::uint64_t {
    constexpr std::uint64_t sign_mask = UINT64_C(0x8000000000000000);
    const std::uint64_t bits = std::bit_cast<std::uint64_t>(value);
    if ((bits & sign_mask) != 0U) {
        return ~bits;
    }
    return bits | sign_mask;
}

[[nodiscard]] constexpr auto
lexicographic_point_less_for_tie_break(const Vec3<double>& lhs, const Vec3<double>& rhs) noexcept
    -> bool {
    for (std::size_t axis = 0U; axis < 3U; ++axis) {
        const std::uint64_t lhs_key = double_total_order_key(lhs[axis]);
        const std::uint64_t rhs_key = double_total_order_key(rhs[axis]);
        if (lhs_key != rhs_key) {
            return lhs_key < rhs_key;
        }
    }
    return false;
}

template <std::floating_point T>
[[nodiscard]] auto is_finite(const Vec3<T>& vector) noexcept -> bool {
    return std::isfinite(vector[0]) && std::isfinite(vector[1]) && std::isfinite(vector[2]);
}

template <std::floating_point T>
[[nodiscard]] auto is_finite(const Matrix3<T>& matrix) noexcept -> bool {
    for (std::size_t row = 0U; row < 3U; ++row) {
        for (std::size_t col = 0U; col < 3U; ++col) {
            if (!std::isfinite(matrix(row, col))) {
                return false;
            }
        }
    }
    return true;
}

// Returns the inverse via adjugate/determinant, or nullopt when singular/invalid.
template <std::floating_point T>
[[nodiscard]] auto inverse(
    const Matrix3<T>& matrix, const T determinant_floor = std::numeric_limits<T>::epsilon()
) noexcept -> std::optional<Matrix3<T>> {
    if (!is_finite(matrix)) {
        return std::nullopt;
    }

    const T max_abs = detail::matrix_max_abs_entry(matrix);
    if (!(max_abs > T{0}) || !std::isfinite(max_abs)) {
        return std::nullopt;
    }

    Matrix3<T> normalized{};
    for (std::size_t row = 0U; row < 3U; ++row) {
        for (std::size_t col = 0U; col < 3U; ++col) {
            normalized(row, col) = matrix(row, col) / max_abs;
        }
    }

    const T det = determinant(normalized);
    const T scale = frobenius_norm(normalized);
    const T scaled_floor = std::abs(determinant_floor) * scale * scale * scale;
    if (!std::isfinite(det) || !std::isfinite(scaled_floor) || std::abs(det) <= scaled_floor) {
        return std::nullopt;
    }

    Matrix3<T> result{};
    const T inverse_scale = T{1} / max_abs;
    result(0U, 0U) =
        (((normalized(1U, 1U) * normalized(2U, 2U)) - (normalized(1U, 2U) * normalized(2U, 1U))) /
         det) *
        inverse_scale;
    result(0U, 1U) =
        (((normalized(0U, 2U) * normalized(2U, 1U)) - (normalized(0U, 1U) * normalized(2U, 2U))) /
         det) *
        inverse_scale;
    result(0U, 2U) =
        (((normalized(0U, 1U) * normalized(1U, 2U)) - (normalized(0U, 2U) * normalized(1U, 1U))) /
         det) *
        inverse_scale;
    result(1U, 0U) =
        (((normalized(1U, 2U) * normalized(2U, 0U)) - (normalized(1U, 0U) * normalized(2U, 2U))) /
         det) *
        inverse_scale;
    result(1U, 1U) =
        (((normalized(0U, 0U) * normalized(2U, 2U)) - (normalized(0U, 2U) * normalized(2U, 0U))) /
         det) *
        inverse_scale;
    result(1U, 2U) =
        (((normalized(0U, 2U) * normalized(1U, 0U)) - (normalized(0U, 0U) * normalized(1U, 2U))) /
         det) *
        inverse_scale;
    result(2U, 0U) =
        (((normalized(1U, 0U) * normalized(2U, 1U)) - (normalized(1U, 1U) * normalized(2U, 0U))) /
         det) *
        inverse_scale;
    result(2U, 1U) =
        (((normalized(0U, 1U) * normalized(2U, 0U)) - (normalized(0U, 0U) * normalized(2U, 1U))) /
         det) *
        inverse_scale;
    result(2U, 2U) =
        (((normalized(0U, 0U) * normalized(1U, 1U)) - (normalized(0U, 1U) * normalized(1U, 0U))) /
         det) *
        inverse_scale;

    if (!is_finite(result)) {
        return std::nullopt;
    }
    return result;
}

// Computes the arithmetic mean of 3D points; empty input returns zero.
template <std::floating_point T>
[[nodiscard]] auto mean3(const std::span<const Vec3<T>> points) noexcept -> Vec3<T> {
    Vec3<T> center{};
    if (points.empty()) {
        return center;
    }
    for (const auto& point : points) {
        center = center + point;
    }
    return center / static_cast<T>(points.size());
}

// Computes the unbiased sample covariance matrix around a supplied center.
template <std::floating_point T>
[[nodiscard]] auto
covariance3(const std::span<const Vec3<T>> points, const Vec3<T>& center) noexcept -> Matrix3<T> {
    Matrix3<T> scatter{};
    if (points.size() < 2U) {
        return scatter;
    }
    for (const auto& point : points) {
        const auto delta = point - center;
        for (std::size_t row = 0U; row < 3U; ++row) {
            for (std::size_t col = row; col < 3U; ++col) {
                scatter(row, col) += delta[row] * delta[col];
            }
        }
    }
    const T scale = T{1} / static_cast<T>(points.size() - 1U);
    for (std::size_t row = 0U; row < 3U; ++row) {
        for (std::size_t col = row; col < 3U; ++col) {
            scatter(row, col) *= scale;
            scatter(col, row) = scatter(row, col);
        }
    }
    return scatter;
}

} // namespace rch::core
