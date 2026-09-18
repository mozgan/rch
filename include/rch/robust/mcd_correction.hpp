#pragma once

// ----------------------------------------------------------------------------
// mcd_correction.hpp — MCD scatter correction factors.
//
// The raw MCD scatter estimate is NOT the plain sample covariance of the
// optimal \(h\)-subset. It is that covariance multiplied by
//
//   (a) a consistency factor \(c_\alpha\), which makes the estimate Fisher-consistent
//       at the multivariate normal model, and
//   (b) a finite-sample correction factor, which removes the small-sample bias.
//
// Equations:
//   \(c_\alpha(p,h/n)=(h/n)/F_{\chi^2_{p+2}}(F^{-1}_{\chi^2_p}(h/n))\)
//   \(\Sigma_{\mathrm{raw}} = c_\alpha\,c_{np2}\,S_X(H)\)
//
// Note that \(c_\alpha\) is exactly the reciprocal of `hardin_rocke_casy`, which
// already implements \(F_{\chi^2_{p+2}}(F^{-1}_{\chi^2_p}(h/n))/(h/n)\); it is
// reused here so the two code paths can never drift apart.
//
// `mcd_small_sample_factor` reproduces the *interpolation branch* of robustbase's
// `.MCDcnp2` for \(p>2\) (this project is fixed at \(p=3\)).
//
// One robustbase branch is deliberately not reproduced: for \(\alpha=0.5\) exactly,
// `.MCDcnp2` replaces the interpolated `fp.500.n` with a tabulated simulation value
// `MCDcnp2s$sim.0(p, n)` whenever that table covers \((p,n)\). For \(p=3\) the table
// spans only \(n\in[6,10]\), where the two differ by 19%-239%. That window is
// unreachable through `det_mcd`, whose `min_n` default is \(5p=15\), but callers
// invoking this function directly at \(n \le 10\) will not match robustbase.
//
// Outside that window the two agree exactly: verified against robustbase 0.99.7 at
// \(p=3\) for \(n\in\{20,30,50,100,200,500,1000,5000\}\) with
// \(\alpha\in\{0.5,0.75\}\),
// relative difference 0 in every case.
//
// The 2x2 linear system solved by `solve()` in the
// R source is inlined in closed form:
//     \(A=\begin{bmatrix}1&-\log(2p^2)\\1&-\log(3p^2)\end{bmatrix}\),
//     \(Ak=y\)
//   => \(k_1=(y_2-y_1)/\log(2/3)\), \(k_0=y_1+k_1\log(2p^2)\)
//     \(f_p=1-\exp(k_0)/n^{k_1}\)
// (verified equal to the linear-solve form to < 1e-14 relative over
//  \(p\in\{3,4,5\}\times n\in\{50,100,200,1000\}\times
//  \alpha\in\{0.5,0.7,0.875,0.95\}\)).
//
// References:
//   - Croux, C. & Haesbroeck, G. (1999), "Influence Function and Efficiency of
//     the Minimum Covariance Determinant Scatter Matrix Estimator",
//     J. Multivariate Anal. 71(2):161-190, doi:10.1006/jmva.1999.1839.
//   - Pison, G., Van Aelst, S. & Willems, G. (2002), "Small Sample Corrections
//     for LTS and MCD", Metrika 55:111-123, doi:10.1007/s001840200191.
//   - Boudt, Rousseeuw, Vanduffel & Verdonck (2020), "The Minimum Regularized
//     Covariance Determinant Estimator", 2020, doi:10.1007/s11222-019-09869-x,
//     Eq. (5):
//         S_MCD = c_alpha * S_X(H_MCD)
//     and Eq. (7):
//         K(H) = rho * T + (1 - rho) * c_alpha * S_U(H)
//     ("c_alpha is the same consistency factor as in (5)").
//   - robustbase `covMcd` vignette §2: "the raw MCD estimate of scatter [...] is
//     their covariance matrix, multiplied by a consistency factor
//     .MCDcons(p, h/n) and (by default) a finite sample correction factor
//     .MCDcnp2(p, n, alpha), to make it consistent at the normal model and
//     unbiased at small samples." - Martin Maechler
//   - robustbase R/covMcd.R, `.MCDcons` / `.MCDcnp2`:
//     https://github.com/cran/robustbase/blob/master/R/covMcd.R
// ----------------------------------------------------------------------------

#include <cmath>
#include <cstddef>
#include <optional>

#include "rch/robust/hardin_rocke_cutoff.hpp"

namespace rch::robust {

// MCD normal-consistency factor \(c_\alpha\).
[[nodiscard]] inline auto
mcd_consistency_factor(const std::size_t nobs, const std::size_t nvar, const std::size_t h) noexcept
    -> std::optional<double> {
    const auto casy = hardin_rocke_casy(nobs, nvar, h);
    if (!casy.has_value() || !(*casy > 0.0) || !std::isfinite(*casy)) {
        return std::nullopt;
    }
    return 1.0 / (*casy);
}

namespace detail {

// One interpolation branch from robustbase `.MCDcnp2` for \(p>2\).
[[nodiscard]] inline auto mcd_cnp2_fp(
    const double a_p2,
    const double b_p2,
    const double a_p3,
    const double b_p3,
    const double p,
    const double n
) noexcept -> double {
    const double y1 = std::log(-a_p2 / std::pow(p, b_p2));
    const double y2 = std::log(-a_p3 / std::pow(p, b_p3));
    const double k1 = (y2 - y1) / std::log(2.0 / 3.0);
    const double k0 = y1 + (k1 * std::log(2.0 * p * p));
    return 1.0 - (std::exp(k0) / std::pow(n, k1));
}

} // namespace detail

// robustbase `.MCDcnp2(p,n,alpha)` for \(p>2\); alpha is trimming, not \(h/n\).
[[nodiscard]] inline auto
mcd_small_sample_factor(const std::size_t nobs, const std::size_t nvar, const double alpha) noexcept
    -> std::optional<double> {
    if (nvar <= 2U || nobs == 0U || !(alpha >= 0.0) || !(alpha <= 1.0)) {
        return std::nullopt;
    }
    const double p = static_cast<double>(nvar);
    const double n = static_cast<double>(nobs);

    const double fp_500 = detail::mcd_cnp2_fp(
        -1.42764571687802, 1.26263336932151, -1.06141115981725, 1.28907991440387, p, n
    );
    const double fp_875 = detail::mcd_cnp2_fp(
        -0.455179464070565, 1.11192541278794, -0.294241208320834, 1.09649329149811, p, n
    );

    const double fp_alpha = (alpha <= 0.875)
                                ? (fp_500 + (((fp_875 - fp_500) / 0.375) * (alpha - 0.5)))
                                : (fp_875 + (((1.0 - fp_875) / 0.125) * (alpha - 0.875)));
    if (!std::isfinite(fp_alpha) || fp_alpha <= 0.0) {
        return std::nullopt;
    }
    return 1.0 / fp_alpha;
}

// Combined multiplier for \(\Sigma_{raw}=c_\alpha c_{n,p,\alpha}S_X(H)\).
[[nodiscard]] inline auto mcd_scatter_correction(
    const std::size_t nobs,
    const std::size_t nvar,
    const std::size_t h,
    const double alpha,
    const bool apply_small_sample_correction = true
) noexcept -> std::optional<double> {
    const auto consistency = mcd_consistency_factor(nobs, nvar, h);
    if (!consistency.has_value()) {
        return std::nullopt;
    }
    if (!apply_small_sample_correction) {
        return consistency;
    }
    const auto small_sample = mcd_small_sample_factor(nobs, nvar, alpha);
    if (!small_sample.has_value()) {
        return consistency;
    }
    const double combined = (*consistency) * (*small_sample);
    if (!std::isfinite(combined) || !(combined > 0.0)) {
        return std::nullopt;
    }
    return combined;
}

} // namespace rch::robust
