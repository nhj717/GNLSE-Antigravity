"""Compiled C-accelerated stepping routines for GNLSE solver engine.

Leverages compiled gnlse_c_kernel (AVX2 SIMD fused operations) and scipy.fft
to accelerate the inner RK4IP, S-SSFM, and SSFM numerical loops.
"""

from __future__ import annotations

from typing import Optional, Tuple
import numpy as np
import scipy.fft as sf

from . import gnlse_c_kernel


def c_nonlinear_operator(
    a_t: np.ndarray,
    gamma: float,
    shock_factor: Optional[np.ndarray],
    raman_fft: Optional[np.ndarray],
    raman_fr: float,
    dt: float = 1.0,
) -> np.ndarray:
    """Evaluate nonlinear operator N(A) using C fused envelope arithmetic."""
    n = len(a_t)
    b_t = np.empty(n, dtype=np.complex128)
    intensity = np.empty(n, dtype=np.float64)
    conv = None

    if raman_fr > 0.0 and raman_fft is not None:
        int_t = np.abs(a_t) ** 2
        conv = np.real(dt * sf.fft(sf.ifft(int_t) * raman_fft))

    gnlse_c_kernel.fused_nonlinear_bt(a_t, conv, raman_fr, b_t, intensity)
    b_w = sf.ifft(b_t)
    m_w = np.empty(n, dtype=np.complex128)
    gnlse_c_kernel.fused_apply_shock_gamma(b_w, shock_factor, gamma, m_w)
    return m_w


def step_rk4ip_c(
    a_t: np.ndarray,
    a_w: np.ndarray,
    h: float,
    d_omega: np.ndarray,
    gamma: float,
    shock_factor: Optional[np.ndarray],
    raman_fft: Optional[np.ndarray],
    raman_fr: float,
    filter_window: Optional[np.ndarray] = None,
    dt: float = 1.0,
) -> Tuple[np.ndarray, np.ndarray]:
    """Execute a single step h using C-accelerated RK4IP (Hult 2007)."""
    n = len(a_t)
    exp_half_d = np.exp(0.5 * h * d_omega)

    # 1. Interaction picture midpoint A_I
    a_i_w = np.empty(n, dtype=np.complex128)
    gnlse_c_kernel.fused_linear_step(a_w, exp_half_d, a_i_w)
    a_i = sf.fft(a_i_w)

    # 2. Stage k1 = exp(h/2 * D) * [h * N(A)]
    m1_w = c_nonlinear_operator(a_t, gamma, shock_factor, raman_fft, raman_fr, dt)
    k1_w = np.empty(n, dtype=np.complex128)
    gnlse_c_kernel.fused_linear_step(m1_w, h * exp_half_d, k1_w)
    k1 = sf.fft(k1_w)

    # 3. Stage k2 = h * N(A_I + k1 / 2)
    u2 = np.empty(n, dtype=np.complex128)
    gnlse_c_kernel.fused_rk_stage_prep(a_i, k1, 0.5, u2)
    m2_w = c_nonlinear_operator(u2, gamma, shock_factor, raman_fft, raman_fr, dt)
    k2_w = h * m2_w
    k2 = sf.fft(k2_w)

    # 4. Stage k3 = h * N(A_I + k2 / 2)
    u3 = np.empty(n, dtype=np.complex128)
    gnlse_c_kernel.fused_rk_stage_prep(a_i, k2, 0.5, u3)
    m3_w = c_nonlinear_operator(u3, gamma, shock_factor, raman_fft, raman_fr, dt)
    k3_w = h * m3_w

    # 5. Stage k4 = h * N(exp(h/2 * D) * [A_I + k3])
    u4_prop_w = np.empty(n, dtype=np.complex128)
    gnlse_c_kernel.fused_rk_prop_stage4(a_i_w, k3_w, exp_half_d, u4_prop_w)
    u4_prop = sf.fft(u4_prop_w)
    m4_w = c_nonlinear_operator(u4_prop, gamma, shock_factor, raman_fft, raman_fr, dt)
    k4_w = h * m4_w

    # 6. Assembly in frequency domain
    a_next_w = np.empty(n, dtype=np.complex128)
    gnlse_c_kernel.fused_rk4ip_assembly(a_i_w, k1_w, k2_w, k3_w, k4_w, exp_half_d, filter_window, a_next_w)
    a_next_t = sf.fft(a_next_w)

    return a_next_t, a_next_w


def _c_nonlinear_step(
    a_t: np.ndarray,
    a_w: np.ndarray,
    h: float,
    gamma: float,
    shock_factor: Optional[np.ndarray],
    raman_fft: Optional[np.ndarray],
    raman_fr: float,
    dt: float = 1.0,
) -> Tuple[np.ndarray, np.ndarray]:
    """Execute C-accelerated nonlinear substep over step h.

    - If self-steepening is OFF: evaluates exact unitary phase rotation with Raman B_eff.
    - If self-steepening is ON: integrates d A_tilde / dz = N(A) via RK4 substeps.
    """
    has_shock = (shock_factor is not None) and not np.allclose(shock_factor, 1.0)
    if not has_shock:
        int_t = np.abs(a_t) ** 2
        if raman_fr > 0.0 and raman_fft is not None:
            conv = np.real(dt * sf.fft(sf.ifft(int_t) * raman_fft))
            b_eff = (1.0 - raman_fr) * int_t + raman_fr * conv
        else:
            b_eff = int_t
        phi = gamma * h * b_eff
        a_nl_t = a_t * np.exp(1j * phi)
        a_nl_w = sf.ifft(a_nl_t)
        return a_nl_t, a_nl_w
    else:
        k1_w = h * c_nonlinear_operator(a_t, gamma, shock_factor, raman_fft, raman_fr, dt)

        u2_w = a_w + 0.5 * k1_w
        u2_t = sf.fft(u2_w)
        k2_w = h * c_nonlinear_operator(u2_t, gamma, shock_factor, raman_fft, raman_fr, dt)

        u3_w = a_w + 0.5 * k2_w
        u3_t = sf.fft(u3_w)
        k3_w = h * c_nonlinear_operator(u3_t, gamma, shock_factor, raman_fft, raman_fr, dt)

        u4_w = a_w + k3_w
        u4_t = sf.fft(u4_w)
        k4_w = h * c_nonlinear_operator(u4_t, gamma, shock_factor, raman_fft, raman_fr, dt)

        a_nl_w = a_w + (1.0 / 6.0) * (k1_w + 2.0 * k2_w + 2.0 * k3_w + k4_w)
        a_nl_t = sf.fft(a_nl_w)
        return a_nl_t, a_nl_w


def step_sssfm_c(
    a_t: np.ndarray,
    a_w: np.ndarray,
    h: float,
    d_omega: np.ndarray,
    gamma: float,
    shock_factor: Optional[np.ndarray],
    raman_fft: Optional[np.ndarray],
    raman_fr: float,
    filter_window: Optional[np.ndarray] = None,
    dt: float = 1.0,
) -> Tuple[np.ndarray, np.ndarray]:
    """Execute a single step h using C-accelerated S-SSFM."""
    n = len(a_t)
    exp_half_d = np.exp(0.5 * h * d_omega)

    # 1. First half linear dispersion step
    a_half_w = np.empty(n, dtype=np.complex128)
    gnlse_c_kernel.fused_linear_step(a_w, exp_half_d, a_half_w)
    a_half_t = sf.fft(a_half_w)

    # 2. Nonlinear step
    _, a_nl_w = _c_nonlinear_step(a_half_t, a_half_w, h, gamma, shock_factor, raman_fft, raman_fr, dt)

    # 3. Second half linear dispersion step
    a_next_w = np.empty(n, dtype=np.complex128)
    gnlse_c_kernel.fused_linear_step(a_nl_w, exp_half_d, a_next_w)

    if filter_window is not None:
        a_next_w = a_next_w * filter_window

    a_next_t = sf.fft(a_next_w)
    return a_next_t, a_next_w


def step_ssfm_c(
    a_t: np.ndarray,
    a_w: np.ndarray,
    h: float,
    d_omega: np.ndarray,
    gamma: float,
    shock_factor: Optional[np.ndarray],
    raman_fft: Optional[np.ndarray],
    raman_fr: float,
    filter_window: Optional[np.ndarray] = None,
    dt: float = 1.0,
) -> Tuple[np.ndarray, np.ndarray]:
    """Execute a single step h using C-accelerated standard SSFM."""
    n = len(a_t)
    exp_d = np.exp(h * d_omega)

    a_disp_w = np.empty(n, dtype=np.complex128)
    gnlse_c_kernel.fused_linear_step(a_w, exp_d, a_disp_w)
    a_disp_t = sf.fft(a_disp_w)

    a_next_t, a_next_w = _c_nonlinear_step(a_disp_t, a_disp_w, h, gamma, shock_factor, raman_fft, raman_fr, dt)

    if filter_window is not None:
        a_next_w = a_next_w * filter_window
        a_next_t = sf.fft(a_next_w)

    return a_next_t, a_next_w
