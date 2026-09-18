#pragma once

// ----------------------------------------------------------------------------
// io/xyz_parse.hpp - ASCII XYZ/CSV coordinate parsing helpers.
//
// Algorithm:
//   - Normalize common coordinate separators by mapping `,` and `;` to spaces.
//   - Extract the first three fields as candidate coordinates
//     \(p=(x,y,z)\).
//   - Parse each field with C's `strtod` conversion and accept it only when the
//     whole token is consumed.
//   - Return `std::nullopt` for missing or malformed coordinates.
//
// Accepted and rejected values (these follow from `strtod` and are deliberate):
//   - Numeric *overflow* is rejected: "1e309" yields ERANGE with a non-finite
//     result and returns nullopt.
//   - An *explicit* non-finite literal is accepted: "inf", "-inf", "infinity",
//     "nan", "nan(0x7)" and their case variants parse to the corresponding
//     value with errno untouched. The two cases are distinguished precisely by
//     the `errno == ERANGE && !isfinite` guard below. This is intentional --
//     `tests/regression/tiny_clouds/nan_inf_mixed.xyz` depends on it, and every
//     downstream consumer (robust estimators, metrics, frames) re-checks
//     finiteness and fails closed.
//   - *Underflow* is accepted, not rejected: "1e-400" sets ERANGE but yields a
//     finite 0, so the guard lets it through; subnormals such as "5e-324" round
//     trip exactly.
//   - Hexadecimal floating literals are accepted, since C99 `strtod` parses
//     them: "0x1p3" yields 8.0.
//   - Signed zero is preserved bit-exactly; "-0.0" keeps its sign bit, which
//     the ordering layer relies on via `double_total_order_key`.
//
// Locale precondition:
//   `strtod` takes its decimal separator from LC_NUMERIC. This code is correct
//   only while the C locale is in effect, which the C standard guarantees at
//   program startup ("the equivalent of setlocale(LC_ALL, \"C\") is executed"),
//   and no translation unit in this repository calls `setlocale`. Introducing a
//   `setlocale(LC_ALL, "")` anywhere would make coordinate parsing depend on the
//   user's environment -- under a comma-decimal locale such as tr_TR or de_DE,
//   "1.5" stops converting at the '.' and the token is rejected. The failure is
//   fail-closed (the whole file is refused) rather than a silent misparse, but
//   it is still a hard failure; keep LC_NUMERIC at "C" if a locale is ever set.
//
// References:
//   - ISO/IEC, ISO/IEC 9899:2018 Information technology - Programming
//     languages - C, 2018.
//   - ISO/IEC, ISO/IEC 14882:2020 Programming languages - C++, 2020.
//   - Radu Bogdan Rusu and Steve Cousins, 3D is here: Point Cloud Library
//     (PCL), 2011, DOI: 10.1109/ICRA.2011.5980567.
// ----------------------------------------------------------------------------

#include <algorithm>
#include <array>
#include <cctype>
#include <cerrno>
#include <cmath>
#include <cstdlib>
#include <optional>
#include <sstream>
#include <string>

namespace rch::io {

// Parses a single floating-point token and rejects partial conversions and overflow.
[[nodiscard]] inline auto parse_double_token(const std::string& token) -> std::optional<double> {
    if (token.empty() || std::isspace(static_cast<unsigned char>(token.front())) != 0) {
        return std::nullopt;
    }

    char* end = nullptr;
    errno = 0;
    const double value = std::strtod(token.c_str(), &end);
    if (end == token.c_str() || *end != '\0') {
        return std::nullopt;
    }
    if (errno == ERANGE && !std::isfinite(value)) {
        return std::nullopt;
    }
    return value;
}

// Parses the first three numeric fields of an ASCII XYZ/CSV line.
[[nodiscard]] inline auto parse_three_doubles(std::string line)
    -> std::optional<std::array<double, 3>> {
    std::ranges::replace(line, ',', ' ');
    std::ranges::replace(line, ';', ' ');
    std::istringstream stream{line};
    std::array<std::string, 3> tokens{};
    if (!(stream >> tokens[0] >> tokens[1] >> tokens[2])) {
        return std::nullopt;
    }
    const auto x = parse_double_token(tokens[0]);
    const auto y = parse_double_token(tokens[1]);
    const auto z = parse_double_token(tokens[2]);
    if (x.has_value() && y.has_value() && z.has_value()) {
        return std::array<double, 3>{*x, *y, *z};
    }
    return std::nullopt;
}

} // namespace rch::io
