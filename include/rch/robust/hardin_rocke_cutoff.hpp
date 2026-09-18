#pragma once

// ----------------------------------------------------------------------------
// hardin_rocke_cutoff.hpp - Hardin-Rocke (2005) finite-sample adjusted F
// cutoff
//
// Equation (qHardRoqF):
//     \(\operatorname{cutoff}(q,n,v,h,adj)
//       = \frac{vm}{c(m-v+1)} F^{-1}_{v,m-v+1}(q)\)
//   where:
//     \(v\) = `nvar` (dimension),
//     \(n\) = `nobs` (sample size),
//     \(h\) = MCD subset size,
//     \(c=c_a\) = asymptotic consistency factor (`hardin_rocke_casy`),
//     \(m=m_a\) = asymptotic DoF (`hardin_rocke_chmasy`),
//     `adj = TRUE` -> \(\hat m=m\exp(0.725-0.00663v-0.078\log n)\)
//
// `c_a` (asymptotic consistency factor):
//     \(c_a=F_{\chi^2_{v+2}}(F^{-1}_{\chi^2_v}(h/n))/(h/n)\)
//
// References:
//   - Johanna Hardin, David M. Rocke, "The Distribution of Robust Distances",
//     2005, doi:10.1198/106186005X77685.
//   - NIST/SEMATECH, "F Distribution", Engineering Statistics Handbook, 2012.
//   - CRAN MAINT.Data `qHardRoqF`,
//     <https://search.r-project.org/CRAN/refmans/MAINT.Data/html/qHardRoqF.html>
//   - CRAN CerioliOutlierDetection, `hr05AdjustedDF` / `hr05CutoffMvnormal`
//   - NIST/SEMATECH F distribution notes:
//     <https://www.itl.nist.gov/div898/handbook/eda/section3/eda3665.htm>
// ----------------------------------------------------------------------------

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <limits>
#include <optional>

namespace rch::robust {

namespace detail {

[[nodiscard]] inline auto
beta_continued_fraction(const double a, const double b, const double x) noexcept -> double {
    // Lentz-style continued fraction for the incomplete beta function.
    constexpr std::size_t max_iterations = 200U;
    constexpr double epsilon = 3.0e-14;
    constexpr double tiny = 1.0e-300;

    const double qab = a + b;
    const double qap = a + 1.0;
    const double qam = a - 1.0;
    double c = 1.0;
    double d = 1.0 - (qab * x / qap);
    if (std::abs(d) < tiny) {
        d = tiny;
    }
    d = 1.0 / d;
    double h = d;

    for (std::size_t m = 1U; m <= max_iterations; ++m) {
        const double m_as_double = static_cast<double>(m);
        const double m2 = 2.0 * m_as_double;

        double aa = (m_as_double * (b - m_as_double) * x) / ((qam + m2) * (a + m2));
        d = 1.0 + (aa * d);
        if (std::abs(d) < tiny) {
            d = tiny;
        }
        c = 1.0 + (aa / c);
        if (std::abs(c) < tiny) {
            c = tiny;
        }
        d = 1.0 / d;
        h *= d * c;

        aa = -((a + m_as_double) * (qab + m_as_double) * x) / ((a + m2) * (qap + m2));
        d = 1.0 + (aa * d);
        if (std::abs(d) < tiny) {
            d = tiny;
        }
        c = 1.0 + (aa / c);
        if (std::abs(c) < tiny) {
            c = tiny;
        }
        d = 1.0 / d;
        const double delta = d * c;
        h *= delta;
        if (std::abs(delta - 1.0) <= epsilon) {
            break;
        }
    }
    return h;
}

[[nodiscard]] inline auto regularized_beta(const double x, const double a, const double b) noexcept
    -> double {
    // Regularized incomplete beta \(I_x(a,b)\), used by the F CDF.
    if (x <= 0.0) {
        return 0.0;
    }
    if (x >= 1.0) {
        return 1.0;
    }
    const double log_front = std::lgamma(a + b) - std::lgamma(a) - std::lgamma(b) +
                             (a * std::log(x)) + (b * std::log1p(-x));
    const double front = std::exp(log_front);
    if (x < (a + 1.0) / (a + b + 2.0)) {
        return front * beta_continued_fraction(a, b, x) / a;
    }
    return 1.0 - (front * beta_continued_fraction(b, a, 1.0 - x) / b);
}

[[nodiscard]] inline auto regularized_gamma_p(const double a, const double x) noexcept -> double {
    // Lower regularized gamma \(P(a,x)\), used by the chi-square CDF.
    constexpr std::size_t max_iterations = 200U;
    constexpr double epsilon = 3.0e-14;
    constexpr double tiny = 1.0e-300;

    if (!(a > 0.0) || !(x > 0.0)) {
        return 0.0;
    }
    const double log_front = (a * std::log(x)) - x - std::lgamma(a);
    if (x < a + 1.0) {
        double term = 1.0 / a;
        double sum = term;
        for (std::size_t n = 1U; n <= max_iterations; ++n) {
            term *= x / (a + static_cast<double>(n));
            sum += term;
            if (std::abs(term) <= std::abs(sum) * epsilon) {
                break;
            }
        }
        return std::clamp(sum * std::exp(log_front), 0.0, 1.0);
    }

    double b = x + 1.0 - a;
    double c = 1.0 / tiny;
    double d = 1.0 / b;
    double h = d;
    for (std::size_t i = 1U; i <= max_iterations; ++i) {
        const double i_as_double = static_cast<double>(i);
        const double an = -i_as_double * (i_as_double - a);
        b += 2.0;
        d = (an * d) + b;
        if (std::abs(d) < tiny) {
            d = tiny;
        }
        c = b + (an / c);
        if (std::abs(c) < tiny) {
            c = tiny;
        }
        d = 1.0 / d;
        const double delta = d * c;
        h *= delta;
        if (std::abs(delta - 1.0) <= epsilon) {
            break;
        }
    }
    return std::clamp(1.0 - (std::exp(log_front) * h), 0.0, 1.0);
}

} // namespace detail

[[nodiscard]] inline auto
f_cdf(const double x, const double numerator_df, const double denominator_df) noexcept -> double {
    // \(F_{\nu_1,\nu_2}(x)=I_z(\nu_1/2,\nu_2/2)\).
    if (!(x > 0.0) || !(numerator_df > 0.0) || !(denominator_df > 0.0) ||
        !std::isfinite(numerator_df) || !std::isfinite(denominator_df)) {
        return 0.0;
    }
    if (!std::isfinite(x)) {
        return 1.0;
    }
    const double z = x / (x + (denominator_df / numerator_df));
    return detail::regularized_beta(z, numerator_df / 2.0, denominator_df / 2.0);
}

[[nodiscard]] inline auto f_quantile(
    const double probability, const double numerator_df, const double denominator_df
) noexcept -> std::optional<double> {
    // Monotone bisection inverse for the F CDF.
    if (!(probability > 0.0 && probability < 1.0) || !(numerator_df > 0.0) ||
        !(denominator_df > 0.0)) {
        return std::nullopt;
    }

    double lo = 0.0;
    double hi = 1.0;
    while (f_cdf(hi, numerator_df, denominator_df) < probability &&
           hi < std::numeric_limits<double>::max() / 2.0) {
        hi *= 2.0;
    }
    for (std::size_t iter = 0U; iter < 128U; ++iter) {
        const double mid = 0.5 * (lo + hi);
        if (f_cdf(mid, numerator_df, denominator_df) < probability) {
            lo = mid;
        } else {
            hi = mid;
        }
    }
    return 0.5 * (lo + hi);
}

[[nodiscard]] inline auto chi_square_cdf(const double x, const double degrees_of_freedom) noexcept
    -> double {
    // \(\chi^2_\nu\) CDF as \(P(\nu/2,x/2)\).
    if (!(x > 0.0) || !(degrees_of_freedom > 0.0) || !std::isfinite(degrees_of_freedom)) {
        return 0.0;
    }
    if (!std::isfinite(x)) {
        return 1.0;
    }
    return detail::regularized_gamma_p(degrees_of_freedom / 2.0, x / 2.0);
}

[[nodiscard]] inline auto
chi_square_quantile(const double probability, const double degrees_of_freedom) noexcept
    -> std::optional<double> {
    // Monotone bisection inverse for the chi-square CDF.
    if (!(probability > 0.0 && probability < 1.0) || !(degrees_of_freedom > 0.0)) {
        return std::nullopt;
    }
    double lo = 0.0;
    double hi = degrees_of_freedom;
    while (chi_square_cdf(hi, degrees_of_freedom) < probability &&
           hi < std::numeric_limits<double>::max() / 2.0) {
        hi *= 2.0;
    }
    for (std::size_t iter = 0U; iter < 128U; ++iter) {
        const double mid = 0.5 * (lo + hi);
        if (chi_square_cdf(mid, degrees_of_freedom) < probability) {
            lo = mid;
        } else {
            hi = mid;
        }
    }
    return 0.5 * (lo + hi);
}

[[nodiscard]] inline auto
hardin_rocke_casy(const std::size_t nobs, const std::size_t nvar, const std::size_t h) noexcept
    -> std::optional<double> {
    // Hardin-Rocke \(c_a\), the reciprocal of the MCD consistency factor.
    if (nobs == 0U || nvar == 0U || h == 0U || h > nobs) {
        return std::nullopt;
    }
    if (h == nobs) {
        return 1.0;
    }
    const double h_over_n = static_cast<double>(h) / static_cast<double>(nobs);
    const auto q = chi_square_quantile(h_over_n, static_cast<double>(nvar));
    if (!q.has_value()) {
        return std::nullopt;
    }
    return chi_square_cdf(*q, static_cast<double>(nvar + 2U)) / h_over_n;
}

[[nodiscard]] inline auto
hardin_rocke_chmasy(const std::size_t nobs, const std::size_t nvar, const std::size_t h) noexcept
    -> std::optional<double> {
    // Asymptotic denominator degrees of freedom \(m_a\).
    if (nobs == 0U || nvar == 0U || h == 0U || h > nobs) {
        return std::nullopt;
    }
    const double alpha = static_cast<double>(nobs - h) / static_cast<double>(nobs);
    const double one_minus_alpha = 1.0 - alpha;
    const auto q_alpha = chi_square_quantile(one_minus_alpha, static_cast<double>(nvar));
    if (!q_alpha.has_value()) {
        return std::nullopt;
    }

    const double c0 = chi_square_cdf(*q_alpha, static_cast<double>(nvar + 2U));
    const double c_alpha = one_minus_alpha / c0;
    const double c2 = -c0 / 2.0;
    const double c3 = -chi_square_cdf(*q_alpha, static_cast<double>(nvar + 4U)) / 2.0;
    const double c4 = 3.0 * c3;
    const double b1 = c_alpha * (c3 - c4) / one_minus_alpha;
    const double b2 =
        0.5 + (c_alpha / one_minus_alpha) *
                  (c3 - ((*q_alpha / static_cast<double>(nvar)) * (c2 + (one_minus_alpha / 2.0))));
    const double nvar_as_double = static_cast<double>(nvar);
    const double v1 =
        (one_minus_alpha * b1 * b1 *
         ((alpha * std::pow((c_alpha * (*q_alpha) / nvar_as_double) - 1.0, 2.0)) - 1.0)) -
        (2.0 * c3 * c_alpha * c_alpha *
         ((3.0 * std::pow(b1 - (nvar_as_double * b2), 2.0)) +
          ((nvar_as_double + 2.0) * b2 * ((2.0 * b1) - (nvar_as_double * b2)))));
    const double v2 = static_cast<double>(nobs) *
                      std::pow(b1 * (b1 - (nvar_as_double * b2)) * one_minus_alpha, 2.0) * c_alpha *
                      c_alpha;
    const double v = v1 / v2;
    if (!(v > 0.0) || !(c_alpha > 0.0)) {
        return std::nullopt;
    }
    return 2.0 / (v * c_alpha * c_alpha);
}

[[nodiscard]] inline auto
hardin_rocke_hdmpred(const std::size_t nobs, const std::size_t nvar, const std::size_t h) noexcept
    -> std::optional<double> {
    // Finite-sample prediction \(\hat m\) for adjusted F cutoffs.
    const auto masy = hardin_rocke_chmasy(nobs, nvar, h);
    if (!masy.has_value()) {
        return std::nullopt;
    }
    return (*masy) * std::exp(
                         0.725 - (0.00663 * static_cast<double>(nvar)) -
                         (0.078 * std::log(static_cast<double>(nobs)))
                     );
}

[[nodiscard]] inline auto hardin_rocke_f_cutoff(
    const std::size_t nobs,
    const std::size_t nvar,
    const std::size_t h,
    const double probability = 0.975,
    const bool adjusted = true
) noexcept -> std::optional<double> {
    // Adjusted F cutoff for robust squared distances from raw MCD scatter.
    if (nvar == 0U || h <= nvar || nobs <= nvar) {
        return std::nullopt;
    }
    const auto c = hardin_rocke_casy(nobs, nvar, h);
    const auto m =
        adjusted ? hardin_rocke_hdmpred(nobs, nvar, h) : hardin_rocke_chmasy(nobs, nvar, h);
    if (!c.has_value() || !m.has_value()) {
        return std::nullopt;
    }
    const double df2 = (*m) - static_cast<double>(nvar) + 1.0;
    if (!(df2 > 0.0) || !std::isfinite(df2)) {
        return std::nullopt;
    }
    const auto quantile = f_quantile(probability, static_cast<double>(nvar), df2);
    if (!quantile.has_value()) {
        return std::nullopt;
    }
    return (static_cast<double>(nvar) * (*m) / ((*c) * df2)) * (*quantile);
}

} // namespace rch::robust
