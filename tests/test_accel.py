"""Unit and equivalence tests for compiled C-acceleration backend."""

import pytest
import numpy as np

from src.solver.accel import is_accel_available, get_accel_stepper
from src.solver.engine import step_rk4ip, step_sssfm, step_ssfm, solve_generator
from src.solver.config import PulseConfig, FiberConfig, DispersionConfig, SolverConfig


def test_accel_availability():
    """Verify that compiled C backend is discovered and active."""
    assert is_accel_available() is True
    assert get_accel_stepper("RK4IP") is not None
    assert get_accel_stepper("S-SSFM") is not None
    assert get_accel_stepper("SSFM") is not None


def test_rk4ip_c_equivalence():
    """Verify compiled C RK4IP matches pure NumPy baseline to machine precision."""
    c_rk4ip = get_accel_stepper("RK4IP")
    assert c_rk4ip is not None

    np.random.seed(12345)
    n = 1024
    at = np.random.randn(n) + 1j * np.random.randn(n)
    aw = np.fft.ifft(at)
    d_omega = -1j * np.linspace(-1e12, 1e12, n) ** 2 * 1e-26
    shock = np.linspace(0.85, 1.15, n)
    r_fft = np.random.randn(n) + 1j * np.random.randn(n)
    filt = np.linspace(1.0, 0.6, n)

    t_py, w_py = step_rk4ip(at, aw, 0.005, d_omega, 1.5e-3, shock, r_fft, 0.18, filt)
    t_c, w_c = c_rk4ip(at, aw, 0.005, d_omega, 1.5e-3, shock, r_fft, 0.18, filt)

    diff_t = float(np.max(np.abs(t_py - t_c)))
    diff_w = float(np.max(np.abs(w_py - w_c)))

    assert diff_t < 1e-12, f"Temporal mismatch: {diff_t:.2e}"
    assert diff_w < 1e-12, f"Spectral mismatch: {diff_w:.2e}"


def test_sssfm_c_equivalence():
    """Verify compiled C S-SSFM matches pure NumPy baseline."""
    c_sssfm = get_accel_stepper("S-SSFM")
    assert c_sssfm is not None

    np.random.seed(54321)
    n = 1024
    at = np.random.randn(n) + 1j * np.random.randn(n)
    aw = np.fft.ifft(at)
    d_omega = -1j * np.linspace(-1e12, 1e12, n) ** 2 * 1e-26
    shock = np.ones(n)

    t_py, w_py = step_sssfm(at, aw, 0.005, d_omega, 1.5e-3, shock, None, 0.0)
    t_c, w_c = c_sssfm(at, aw, 0.005, d_omega, 1.5e-3, shock, None, 0.0)

    diff_t = float(np.max(np.abs(t_py - t_c)))
    diff_w = float(np.max(np.abs(w_py - w_c)))

    assert diff_t < 1e-12, f"Temporal mismatch: {diff_t:.2e}"
    assert diff_w < 1e-12, f"Spectral mismatch: {diff_w:.2e}"


def test_soliton_propagation_with_accel():
    """Verify fundamental Soliton N=1 propagation using active compiled backend."""
    pulse = PulseConfig(shape="sech", t_fwhm=1.7627e-12, p_peak=16.4615, center_wavelength=1550e-9)
    fiber = FiberConfig(
        length=73.39,  # 1 soliton period z0
        gamma=1.3e-3,
        dispersion=DispersionConfig(mode="manual", betas=[-21.4e-27, 0.0, 0.0, 0.0, 0.0, 0.0]),
        raman_fr=0.0,
    )
    solver = SolverConfig(
        simulation_type="spectrum_vs_distance",
        method="RK4IP",
        n_points=1024,
        time_window=20e-12,
        adaptive_step=False,
        initial_step=0.1,
        z_records=10,
        raman_enabled=False,
        shock_enabled=False,
    )

    states = list(solve_generator(pulse, fiber, solver))
    final = states[-1]

    t0 = 1.0e-12
    p0 = 16.4615
    norm_int = np.abs(final.a_t) ** 2 / p0
    exact = (1.0 / np.cosh(np.clip(final.t / t0, -40, 40))) ** 2
    shape_err = float(np.max(np.abs(norm_int - exact)))

    assert shape_err < 1e-4, f"Accelerated RK4IP shape error: {shape_err:.2e}"
    assert final.rel_energy_err < 1e-10, f"Accelerated RK4IP energy drift: {final.rel_energy_err:.2e}"
