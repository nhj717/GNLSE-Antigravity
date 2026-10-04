"""GNLSE propagation engine with SSFM, S-SSFM, and RK4IP solvers.

Provides:
- Pure NumPy baseline implementations of:
  * RK4IP (4th-order Runge-Kutta in the Interaction Picture, Hult 2007)
  * S-SSFM (Symmetrized Split-Step Fourier Method)
  * SSFM (Standard Split-Step Fourier Method)
- Generator-based stepping interface: solve_generator(pulse, fiber, solver)
- Adaptive step size control via step-doubling local error estimation
- Spectral-vs-distance and spectral-vs-power simulation modes
- Dynamic dispatch hooks for compiled Cython acceleration
"""

from __future__ import annotations

import copy
import math
import time
from typing import Callable, Generator, Optional
import numpy as np

from .config import (
    C_CONST,
    FiberConfig,
    PulseConfig,
    SimulationState,
    SolverConfig,
)
from .operators import (
    compute_dispersion_operator,
    compute_energy,
    compute_nonlinear_operator,
    compute_photon_number,
    compute_shock_factor,
    relative_error,
    super_gaussian_filter,
)
from .raman import prepare_raman_fft
from .accel import get_accel_stepper, is_accel_available, fft_backend as sf


def generate_initial_pulse(pulse: PulseConfig, t: np.ndarray) -> np.ndarray:
    """Generate complex envelope field A(0, T) [sqrt(W)] on the temporal grid."""
    p0 = pulse.p_peak
    chirp = pulse.chirp

    if pulse.shape == "sech":
        t0 = pulse.t0
        # Prevent overflow for large |t / t0| in cosh
        arg = np.clip(t / t0, -50.0, 50.0)
        envelope = np.sqrt(p0) / np.cosh(arg)
        if abs(chirp) > 1e-15:
            phase = -0.5 * chirp * ((t / t0) ** 2)
            return (envelope * np.exp(1j * phase)).astype(np.complex128)
        return envelope.astype(np.complex128)

    elif pulse.shape == "gaussian":
        t0 = pulse.t0
        if abs(chirp) > 1e-15:
            exponent = -0.5 * (1.0 + 1j * chirp) * ((t / t0) ** 2)
        else:
            exponent = -0.5 * ((t / t0) ** 2)
        return (np.sqrt(p0) * np.exp(exponent)).astype(np.complex128)

    elif pulse.shape == "lorentzian":
        t0 = pulse.t0
        envelope = np.sqrt(p0) / (1.0 + (t / t0) ** 2)
        if abs(chirp) > 1e-15:
            phase = -0.5 * chirp * ((t / t0) ** 2)
            return (envelope * np.exp(1j * phase)).astype(np.complex128)
        return envelope.astype(np.complex128)

    elif pulse.shape == "custom":
        if pulse.custom_field is None:
            raise ValueError("custom_field must be supplied when pulse shape is 'custom'.")
        c_field = np.asarray(pulse.custom_field, dtype=np.complex128)
        if pulse.custom_time is not None:
            c_time = np.asarray(pulse.custom_time, dtype=np.float64)
            re_interp = np.interp(t, c_time, np.real(c_field), left=0.0, right=0.0)
            im_interp = np.interp(t, c_time, np.imag(c_field), left=0.0, right=0.0)
            return (re_interp + 1j * im_interp).astype(np.complex128)
        if len(c_field) == len(t):
            return c_field
        raise ValueError(
            f"custom_field length ({len(c_field)}) does not match grid points ({len(t)}) and custom_time is not provided."
        )

    else:
        raise ValueError(f"Unsupported pulse shape '{pulse.shape}'")


# ============================================================================
# Stepping Kernels (Pure NumPy)
# ============================================================================

def step_rk4ip(
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
) -> tuple[np.ndarray, np.ndarray]:
    """Execute a single step h using RK4IP (Hult 2007, Eq. 12).

    Advances the field from z to z + h.
    """
    exp_half_d = np.exp(0.5 * h * d_omega)

    # 1. Interaction picture midpoint field A_I
    a_i_w = exp_half_d * a_w
    a_i = np.fft.fft(a_i_w)

    # 2. Stage k1 = exp(h/2 * D) * [h * N(A)]
    m1_w = compute_nonlinear_operator(a_t, gamma, shock_factor, raman_fft, raman_fr, dt)
    k1_w = h * exp_half_d * m1_w
    k1 = np.fft.fft(k1_w)

    # 3. Stage k2 = h * N(A_I + k1 / 2)
    u2 = a_i + 0.5 * k1
    m2_w = compute_nonlinear_operator(u2, gamma, shock_factor, raman_fft, raman_fr, dt)
    k2_w = h * m2_w
    k2 = np.fft.fft(k2_w)

    # 4. Stage k3 = h * N(A_I + k2 / 2)
    u3 = a_i + 0.5 * k2
    m3_w = compute_nonlinear_operator(u3, gamma, shock_factor, raman_fft, raman_fr, dt)
    k3_w = h * m3_w

    # 5. Stage k4 = h * N(exp(h/2 * D) * [A_I + k3])
    u4_prop_w = exp_half_d * (a_i_w + k3_w)
    u4_prop = np.fft.fft(u4_prop_w)
    m4_w = compute_nonlinear_operator(u4_prop, gamma, shock_factor, raman_fft, raman_fr, dt)
    k4_w = h * m4_w

    # 6. Assembly in frequency domain:
    # A(z+h) = exp(h/2 * D) * [A_I + k1/6 + k2/3 + k3/3] + k4/6
    sum_mid_w = a_i_w + (1.0 / 6.0) * k1_w + (1.0 / 3.0) * k2_w + (1.0 / 3.0) * k3_w
    a_next_w = exp_half_d * sum_mid_w + (1.0 / 6.0) * k4_w

    if filter_window is not None:
        a_next_w = a_next_w * filter_window

    a_next_t = np.fft.fft(a_next_w)
    return a_next_t, a_next_w


def _nonlinear_step_rk4(
    a_w: np.ndarray,
    h: float,
    gamma: float,
    shock_factor: Optional[np.ndarray],
    raman_fft: Optional[np.ndarray],
    raman_fr: float,
    dt: float = 1.0,
) -> np.ndarray:
    """Evaluate nonlinear step exp(h * N) in frequency domain using 4th-order Runge-Kutta."""
    a_t = np.fft.fft(a_w)
    k1_w = h * compute_nonlinear_operator(a_t, gamma, shock_factor, raman_fft, raman_fr, dt)

    u2_t = np.fft.fft(a_w + 0.5 * k1_w)
    k2_w = h * compute_nonlinear_operator(u2_t, gamma, shock_factor, raman_fft, raman_fr, dt)

    u3_t = np.fft.fft(a_w + 0.5 * k2_w)
    k3_w = h * compute_nonlinear_operator(u3_t, gamma, shock_factor, raman_fft, raman_fr, dt)

    u4_t = np.fft.fft(a_w + k3_w)
    k4_w = h * compute_nonlinear_operator(u4_t, gamma, shock_factor, raman_fft, raman_fr, dt)

    return a_w + (1.0 / 6.0) * (k1_w + 2.0 * k2_w + 2.0 * k3_w + k4_w)


def _nonlinear_step(
    a_t: np.ndarray,
    a_w: np.ndarray,
    h: float,
    gamma: float,
    shock_factor: Optional[np.ndarray],
    raman_fft: Optional[np.ndarray],
    raman_fr: float,
    dt: float = 1.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Execute nonlinear substep over distance h.

    - If self-steepening is OFF: evaluates exact unitary phase rotation
      including full Raman B_eff(T), maintaining strict energy conservation without Euler amplification.
    - If self-steepening is ON: integrates d A_tilde / dz = N(A) via RK4
      frequency substeps for unconditional numerical stability on the imaginary axis.
    """
    has_shock = (shock_factor is not None) and not np.allclose(shock_factor, 1.0)
    if not has_shock:
        intensity = np.abs(a_t) ** 2
        if raman_fr > 0.0 and raman_fft is not None:
            from .raman import raman_convolution
            i_conv = raman_convolution(intensity, raman_fft, dt)
            b_eff = (1.0 - raman_fr) * intensity + raman_fr * i_conv
        else:
            b_eff = intensity
        nl_phase = gamma * b_eff * h
        a_nl_t = a_t * np.exp(1j * nl_phase)
        a_nl_w = np.fft.ifft(a_nl_t)
        return a_nl_t, a_nl_w
    else:
        a_nl_w = _nonlinear_step_rk4(a_w, h, gamma, shock_factor, raman_fft, raman_fr, dt)
        a_nl_t = np.fft.fft(a_nl_w)
        return a_nl_t, a_nl_w


def step_sssfm(
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
) -> tuple[np.ndarray, np.ndarray]:
    """Execute a single step h using Symmetrized Split-Step Fourier Method (S-SSFM)."""
    exp_half_d = np.exp(0.5 * h * d_omega)

    # First half dispersive step
    a_half_w = exp_half_d * a_w
    a_half_t = np.fft.fft(a_half_w)

    # Nonlinear step
    _, a_nl_w = _nonlinear_step(a_half_t, a_half_w, h, gamma, shock_factor, raman_fft, raman_fr, dt)

    # Second half dispersive step
    a_next_w = exp_half_d * a_nl_w

    if filter_window is not None:
        a_next_w = a_next_w * filter_window

    a_next_t = np.fft.fft(a_next_w)
    return a_next_t, a_next_w


def step_ssfm(
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
) -> tuple[np.ndarray, np.ndarray]:
    """Execute a single step h using standard asymmetric Split-Step Fourier Method (SSFM)."""
    exp_d = np.exp(h * d_omega)

    # Dispersive step
    a_disp_w = exp_d * a_w
    a_disp_t = np.fft.fft(a_disp_w)

    # Nonlinear step
    a_next_t, a_next_w = _nonlinear_step(a_disp_t, a_disp_w, h, gamma, shock_factor, raman_fft, raman_fr, dt)

    if filter_window is not None:
        a_next_w = a_next_w * filter_window
        a_next_t = np.fft.fft(a_next_w)

    return a_next_t, a_next_w


def get_stepper(method: str, use_accel: bool = True) -> tuple[Callable[..., Any], int]:
    """Return stepper function and method order p.

    Dispatches to compiled Cython kernel if requested and available, else pure NumPy.
    """
    if use_accel and is_accel_available():
        accel_fn = get_accel_stepper(method)
        if accel_fn is not None:
            order = 4 if method == "RK4IP" else (2 if method == "S-SSFM" else 1)
            return accel_fn, order

    if method == "RK4IP":
        return step_rk4ip, 4
    elif method == "S-SSFM":
        return step_sssfm, 2
    elif method == "SSFM":
        return step_ssfm, 1
    else:
        raise ValueError(f"Unknown solver method: {method}")


# ============================================================================
# Generator-Based Master Stepper
# ============================================================================

def solve_generator(
    pulse: PulseConfig,
    fiber: FiberConfig,
    solver: SolverConfig,
) -> Generator[SimulationState, None, None]:
    """Generator-based GNLSE solver yielding SimulationState at propagation intervals.

    Supports:
    - simulation_type = 'spectrum_vs_distance': Propagates pulse along fiber of length L
    - simulation_type = 'spectrum_vs_power': Sweeps peak power, yielding output state at z = L
    """
    if solver.simulation_type == "spectrum_vs_power":
        yield from _solve_spectrum_vs_power(pulse, fiber, solver)
    else:
        yield from _solve_spectrum_vs_distance(pulse, fiber, solver)


def _solve_spectrum_vs_power(
    pulse: PulseConfig,
    fiber: FiberConfig,
    solver: SolverConfig,
) -> Generator[SimulationState, None, None]:
    """Sweep input peak power and yield state at fiber output z = L for each power."""
    powers = np.linspace(solver.power_min, solver.power_max, solver.power_steps)
    dist_solver = copy.deepcopy(solver)
    dist_solver.simulation_type = "spectrum_vs_distance"
    dist_solver.z_records = None  # We will take the last state

    for step_idx, p_in in enumerate(powers):
        p_config = copy.deepcopy(pulse)
        p_config.p_peak = float(p_in)

        final_state: Optional[SimulationState] = None
        for state in _solve_spectrum_vs_distance(p_config, fiber, dist_solver):
            final_state = state

        if final_state is not None:
            # Yield output state tagged with input power and index
            yield SimulationState(
                step=step_idx,
                z=fiber.length,
                power=float(p_in),
                h=final_state.h,
                t=final_state.t,
                omega=final_state.omega,
                a_t=final_state.a_t,
                a_w=final_state.a_w,
                rel_energy_err=final_state.rel_energy_err,
                rel_photon_err=final_state.rel_photon_err,
            )


def _solve_spectrum_vs_distance(
    pulse: PulseConfig,
    fiber: FiberConfig,
    solver: SolverConfig,
) -> Generator[SimulationState, None, None]:
    """Execute pulse propagation along fiber distance z from 0 to L."""
    n_points = solver.n_points
    t_max = solver.time_window
    dt = t_max / n_points

    # Retarded time grid centered at 0: T_n = (-N/2 + n) * Delta T
    t = (np.arange(n_points, dtype=np.float64) - (n_points / 2.0)) * dt

    # Angular frequency offset grid Omega_k = 2 * pi * fftfreq(N, d=dt)
    omega = 2.0 * np.pi * np.fft.fftfreq(n_points, d=dt)

    # Carrier frequency
    omega_0 = pulse.omega_0

    # Linear dispersion operator D(Omega)
    d_omega = compute_dispersion_operator(
        omega=omega,
        dispersion=fiber.dispersion,
        alpha_si=fiber.alpha_si,
        omega0=omega_0,
    )

    # Raman setup
    raman_fr = fiber.raman_fr if solver.raman_enabled else 0.0
    raman_fft = None
    if raman_fr > 0.0:
        raman_fft = prepare_raman_fft(
            n_points=n_points,
            dt=dt,
            tau1=fiber.raman_tau1,
            tau2=fiber.raman_tau2,
        )

    # Self-steepening shock factor
    shock_factor = compute_shock_factor(
        omega=omega,
        omega0=omega_0,
        enabled=solver.shock_enabled,
    )

    # Anti-aliasing filter
    filter_window = None
    if solver.filter_alias:
        filter_window = super_gaussian_filter(
            omega=omega,
            cutoff_fraction=solver.filter_cutoff,
            order=solver.filter_order,
        )

    # Initial optical pulse field
    a_t = generate_initial_pulse(pulse, t)
    a_w = np.fft.ifft(a_t)

    # Baseline conservation quantities at z = 0
    e_0 = compute_energy(a_t, dt)
    n_ph_0 = compute_photon_number(a_w, omega, omega_0, dt)

    stepper_fn, method_order = get_stepper(solver.method)

    z = 0.0
    total_length = fiber.length
    step_count = 0
    consecutive_rejections = 0
    current_h = min(solver.initial_step, total_length)
    last_progress_time = time.perf_counter()
    last_progress_step = 0

    # Yield initial state at z = 0
    yield SimulationState(
        step=step_count,
        z=0.0,
        power=float(np.max(np.abs(a_t) ** 2)),
        h=current_h,
        t=t,
        omega=omega,
        a_t=a_t.copy(),
        a_w=a_w.copy(),
        rel_energy_err=0.0,
        rel_photon_err=0.0,
    )

    # Target recording grid for z_records
    z_records = solver.z_records
    next_record_z = total_length / z_records if (z_records and z_records > 1) else None

    # Propagation loop
    while z < total_length - 1e-13:
        # Prevent stepping past fiber end
        if z + current_h > total_length:
            current_h = total_length - z

        # Bound step size by maximum allowable nonlinear phase shift (Spec §2.8 & stability controls)
        p_peak_cur = float(np.max(np.abs(a_t) ** 2))
        phi_max = 0.08  # rad, max nonlinear phase shift Delta phi_NL <= phi_max
        if fiber.gamma > 0.0 and p_peak_cur > 0.0:
            h_nl_max = phi_max / (fiber.gamma * p_peak_cur)
            current_h = min(current_h, h_nl_max)
            current_h = max(current_h, solver.min_step)

        if not solver.adaptive_step:
            # Fixed-step propagation
            a_t, a_w = stepper_fn(
                a_t,
                a_w,
                current_h,
                d_omega,
                fiber.gamma,
                shock_factor,
                raman_fft,
                raman_fr,
                filter_window,
                dt=dt,
            )
            if np.isnan(a_t).any():
                raise RuntimeError(f"Simulation encountered NaN at z = {z*100:.4f} cm in fixed-step mode.")
            z += current_h
            step_count += 1
            accepted = True
        else:
            # Adaptive step-doubling local error control (Spec §2.8)
            # Evaluate substeps without filter to isolate differential equation truncation error
            # 1. Coarse step: size h
            a_c_t, a_c_w = stepper_fn(
                a_t,
                a_w,
                current_h,
                d_omega,
                fiber.gamma,
                shock_factor,
                raman_fft,
                raman_fr,
                None,
                dt=dt,
            )

            # 2. Fine step: two steps of size h / 2
            half_h = 0.5 * current_h
            a_m_t, a_m_w = stepper_fn(
                a_t,
                a_w,
                half_h,
                d_omega,
                fiber.gamma,
                shock_factor,
                raman_fft,
                raman_fr,
                None,
                dt=dt,
            )
            a_f_t, a_f_w = stepper_fn(
                a_m_t,
                a_m_w,
                half_h,
                d_omega,
                fiber.gamma,
                shock_factor,
                raman_fft,
                raman_fr,
                None,
                dt=dt,
            )

            # 3. Anomaly detection: prevent NaNs or non-finite divergence
            norm_fine = float(np.linalg.norm(a_f_t))
            is_anomaly = (
                not np.isfinite(norm_fine)
                or np.isnan(a_f_t).any()
                or np.isnan(a_c_t).any()
            )

            if is_anomaly:
                delta = float("inf")
            else:
                delta = float(np.linalg.norm(a_f_t - a_c_t) / (norm_fine + 1e-30))

            if not is_anomaly and delta <= solver.tolerance:
                # Step Accepted
                if filter_window is not None:
                    a_f_w = a_f_w * filter_window
                    a_f_t = sf.fft(a_f_w) if is_accel_available() else np.fft.fft(a_f_w)
                z += current_h
                a_t = a_f_t
                a_w = a_f_w
                step_count += 1
                accepted = True
                consecutive_rejections = 0

                # Step-size adjustment: h_new = h * f_safety * (tol / delta)^(1 / (p + 1))
                scale = solver.safety_factor * ((solver.tolerance / max(delta, 1e-15)) ** (1.0 / (method_order + 1)))
                scale = min(max(scale, 0.5), 2.0)
                current_h = min(max(current_h * scale, solver.min_step), solver.max_step)
            else:
                # Step Rejected
                consecutive_rejections += 1
                accepted = False

                if is_anomaly:
                    # Harsh backoff upon detecting numerical anomaly to rescue convergence
                    current_h = max(current_h * 0.25, solver.min_step)
                    if current_h <= solver.min_step * 1.001 and consecutive_rejections >= 20:
                        raise RuntimeError(
                            f"Simulation halted: step size hit min_step ({solver.min_step:.2e} m) "
                            f"and failed to recover from numerical anomaly after {consecutive_rejections} rejections at z = {z*100:.4f} cm"
                        )
                elif current_h <= solver.min_step * 1.001:
                    if consecutive_rejections >= 50:
                        raise RuntimeError(
                            f"Simulation halted: step size hit min_step ({solver.min_step:.2e} m) "
                            f"and failed to converge after {consecutive_rejections} rejections at z = {z*100:.4f} cm"
                        )
                    elif consecutive_rejections >= 3:
                        # Step floor reached: force-accept fine step only if physically valid (no NaNs)
                        print(
                            f"[WARN] Step floor reached at z = {z*100:.4f} cm (h = {current_h*1e6:.4f} um, "
                            f"delta = {delta:.2e}): forcing step to prevent halt",
                            flush=True,
                        )
                        if filter_window is not None:
                            a_f_w = a_f_w * filter_window
                            a_f_t = sf.fft(a_f_w) if is_accel_available() else np.fft.fft(a_f_w)
                        z += current_h
                        a_t = a_f_t
                        a_w = a_f_w
                        step_count += 1
                        accepted = True
                        consecutive_rejections = 0
                        current_h = min(solver.min_step * 2.0, solver.max_step)
                    else:
                        scale = solver.safety_factor * ((solver.tolerance / delta) ** (1.0 / (method_order + 1)))
                        scale = min(max(scale, 0.1), 0.5)
                        current_h = max(current_h * scale, solver.min_step)
                else:
                    scale = solver.safety_factor * ((solver.tolerance / delta) ** (1.0 / (method_order + 1)))
                    scale = min(max(scale, 0.1), 0.5)
                    current_h = max(current_h * scale, solver.min_step)

        if accepted:
            # Heartbeat / progress log periodically
            now = time.perf_counter()
            if (step_count - last_progress_step >= 500) or (now - last_progress_time >= 1.0):
                pct = (z / total_length) * 100.0 if total_length > 0 else 100.0
                print(
                    f"Progress: z = {z*100:.2f} cm / {total_length*100:.2f} cm ({pct:.1f}%), "
                    f"step = {step_count}, h = {current_h*1e6:.2f} um",
                    flush=True,
                )
                last_progress_time = now
                last_progress_step = step_count

            # Check if this state should be yielded
            is_final = z >= total_length - 1e-13
            should_yield = False

            if is_final:
                should_yield = True
                pct = 100.0
                print(
                    f"Progress: z = {z*100:.2f} cm / {total_length*100:.2f} cm ({pct:.1f}%), "
                    f"step = {step_count}, h = {current_h*1e6:.2f} um [COMPLETED]",
                    flush=True,
                )
            elif z_records is None:
                should_yield = True
            elif next_record_z is not None and z >= next_record_z:
                should_yield = True
                next_record_z += total_length / z_records

            if should_yield:
                e_cur = compute_energy(a_t, dt)
                n_ph_cur = compute_photon_number(a_w, omega, omega_0, dt)
                rel_e_err = relative_error(e_cur, e_0)
                rel_ph_err = relative_error(n_ph_cur, n_ph_0)

                yield SimulationState(
                    step=step_count,
                    z=z,
                    power=float(np.max(np.abs(a_t) ** 2)),
                    h=current_h,
                    t=t,
                    omega=omega,
                    a_t=a_t.copy(),
                    a_w=a_w.copy(),
                    rel_energy_err=rel_e_err,
                    rel_photon_err=rel_ph_err,
                )
