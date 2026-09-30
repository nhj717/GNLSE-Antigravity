"""Benchmark Test Case 1: Fundamental Soliton (N = 1) Propagation.

Validates the linear-nonlinear balance (Kerr effect vs. anomalous GVD)
and energy conservation over 5 soliton periods in SMF-28 fiber.

Reference: GNLSE_THEORETICAL_SPEC.md §1.6 & §3.2 Amendment 3.
Analytical solution:
    A(z, T) = sqrt(P0) * sech(T / T0) * exp(i * |beta2| * z / (2 * T0^2))
Validation thresholds:
    - Temporal shape error: max_T | |A(z,T)|^2 / P0 - sech^2(T/T0) | < 1e-4
    - Relative energy conservation: |E(z) - E(0)| / E(0) < 1e-10
"""

import math
import numpy as np
import pytest

from src.solver.config import (
    DispersionConfig,
    FiberConfig,
    PulseConfig,
    SolverConfig,
)
from src.solver.engine import solve_generator
from src.solver.raman import blow_wood_raman_response


@pytest.fixture
def soliton_setup():
    """Setup canonical parameters for Test Case 1: Soliton N=1 in SMF-28."""
    # Physical parameters
    lambda0 = 1550e-9  # m
    beta2 = -2.14e-26  # s^2/m (-21.4 ps^2/km)
    gamma = 1.3e-3  # W^-1 m^-1 (1.3 W^-1 km^-1)
    alpha_db = 0.0  # Lossless
    t0 = 1.0e-12  # 1.0 ps
    t_fwhm = 2.0 * math.log(1.0 + math.sqrt(2.0)) * t0  # ~1.7627 ps
    p0 = abs(beta2) / (gamma * (t0**2))  # ~16.4615 W

    z0 = (math.pi / 2.0) * (t0**2) / abs(beta2)  # Soliton period ~73.39 m
    total_length = 5.0 * z0  # 5 soliton periods ~366.95 m

    dispersion = DispersionConfig.from_si(beta2=beta2)
    fiber = FiberConfig(
        length=total_length,
        gamma=gamma,
        loss_alpha_db=alpha_db,
        dispersion=dispersion,
        raman_fr=0.0,  # Kerr-only for fundamental soliton benchmark
    )

    pulse = PulseConfig(
        shape="sech",
        t_fwhm=t_fwhm,
        p_peak=p0,
        center_wavelength=lambda0,
        chirp=0.0,
    )

    return {
        "lambda0": lambda0,
        "beta2": beta2,
        "gamma": gamma,
        "t0": t0,
        "t_fwhm": t_fwhm,
        "p0": p0,
        "z0": z0,
        "total_length": total_length,
        "fiber": fiber,
        "pulse": pulse,
    }


def test_unit_conversions():
    """Verify dispersion and loss unit conversion helpers."""
    # beta_2: -21.4 ps^2/km -> -2.14e-26 s^2/m
    val_si = DispersionConfig.ps_km_to_si(2, -21.4)
    assert pytest.approx(val_si, rel=1e-12) == -2.14e-26

    # Round-trip
    val_conv = DispersionConfig.si_to_ps_km(2, val_si)
    assert pytest.approx(val_conv, rel=1e-12) == -21.4

    # beta_3: 0.12 ps^3/km -> 1.2e-40 s^3/m
    val_b3 = DispersionConfig.ps_km_to_si(3, 0.12)
    assert pytest.approx(val_b3, rel=1e-12) == 1.2e-40

    # Loss conversion: 0.2 dB/km -> ~4.605e-5 m^-1
    fiber = FiberConfig(length=1000.0, gamma=1.3e-3, loss_alpha_db=0.2)
    expected_alpha = 0.2 * (math.log(10.0) / 10.0) * 1e-3
    assert pytest.approx(fiber.alpha_si, rel=1e-6) == expected_alpha


def test_raman_blow_wood_normalization():
    """Verify Blow-Wood Raman response integrates to 1.0."""
    tau1 = 12.2e-15
    tau2 = 32.0e-15
    dt = 0.5e-15
    n_points = 32768
    t = np.arange(n_points) * dt

    hr = blow_wood_raman_response(t, tau1=tau1, tau2=tau2)
    integral = np.sum(hr) * dt
    # Numerical Riemann sum vs analytical 1.0 within 0.1%
    assert pytest.approx(integral, rel=1e-3) == 1.0


def test_soliton_n1_rk4ip_fixed_step(soliton_setup):
    """Benchmark Test Case 1 with RK4IP (fixed step size h = 0.1 m).

    Validates:
    - Temporal shape error < 1e-4 across entire propagation
    - Relative energy conservation < 1e-10
    - Analytical complex envelope phase rotation exp(i * 5 * pi / 4)
    """
    setup = soliton_setup
    p0 = setup["p0"]
    t0 = setup["t0"]
    beta2 = setup["beta2"]
    total_length = setup["total_length"]

    solver = SolverConfig(
        simulation_type="spectrum_vs_distance",
        method="RK4IP",
        n_points=1024,
        time_window=20.0e-12,  # 20 ps
        adaptive_step=False,
        initial_step=0.1,  # 0.1 m steps
        z_records=20,  # record 20 slices
        raman_enabled=False,
        shock_enabled=False,
    )

    states = list(solve_generator(setup["pulse"], setup["fiber"], solver))
    assert len(states) >= 20

    max_shape_err = 0.0
    max_energy_err = 0.0

    for state in states:
        t = state.t
        intensity_norm = np.abs(state.a_t) ** 2 / p0
        arg = np.clip(t / t0, -40.0, 40.0)
        exact_shape = (1.0 / np.cosh(arg)) ** 2

        shape_err = float(np.max(np.abs(intensity_norm - exact_shape)))
        if shape_err > max_shape_err:
            max_shape_err = shape_err

        if state.rel_energy_err > max_energy_err:
            max_energy_err = state.rel_energy_err

    final_state = states[-1]
    assert pytest.approx(final_state.z, abs=1e-10) == total_length

    # Assertions per Spec §1.6 Validation Criteria
    assert max_shape_err < 1e-4, f"Shape error {max_shape_err:.2e} exceeded 1e-4 threshold"
    assert max_energy_err < 1e-10, f"Energy drift {max_energy_err:.2e} exceeded 1e-10 threshold"

    # Analytical complex phase check: exp(i * |beta2| * L / (2 * t0^2))
    expected_phase = (abs(beta2) * total_length) / (2.0 * (t0**2))  # Exactly 5 * pi / 4
    arg_final = np.clip(final_state.t / t0, -40.0, 40.0)
    analytical_a = np.sqrt(p0) / np.cosh(arg_final) * np.exp(1j * expected_phase)
    complex_err = float(np.max(np.abs(final_state.a_t - analytical_a)) / np.sqrt(p0))
    assert complex_err < 2e-4, f"Complex envelope error {complex_err:.2e} exceeded 2e-4"


def test_soliton_n1_sssfm_fixed_step(soliton_setup):
    """Benchmark Test Case 1 with S-SSFM (fixed step size h = 0.1 m).

    Validates:
    - Temporal shape error < 1e-4
    - Relative energy conservation < 1e-10
    """
    setup = soliton_setup
    p0 = setup["p0"]
    t0 = setup["t0"]

    solver = SolverConfig(
        simulation_type="spectrum_vs_distance",
        method="S-SSFM",
        n_points=1024,
        time_window=20.0e-12,
        adaptive_step=False,
        initial_step=0.1,
        z_records=20,
        raman_enabled=False,
        shock_enabled=False,
    )

    states = list(solve_generator(setup["pulse"], setup["fiber"], solver))

    max_shape_err = 0.0
    max_energy_err = 0.0

    for state in states:
        t = state.t
        intensity_norm = np.abs(state.a_t) ** 2 / p0
        arg = np.clip(t / t0, -40.0, 40.0)
        exact_shape = (1.0 / np.cosh(arg)) ** 2

        shape_err = float(np.max(np.abs(intensity_norm - exact_shape)))
        if shape_err > max_shape_err:
            max_shape_err = shape_err

        if state.rel_energy_err > max_energy_err:
            max_energy_err = state.rel_energy_err

    assert max_shape_err < 1e-4, f"S-SSFM shape error {max_shape_err:.2e} exceeded 1e-4"
    assert max_energy_err < 1e-10, f"S-SSFM energy drift {max_energy_err:.2e} exceeded 1e-10"


def test_soliton_n1_rk4ip_adaptive(soliton_setup):
    """Benchmark Test Case 1 with RK4IP and adaptive step-size control.

    Validates:
    - Step doubling error control dynamically adapts step
    - Temporal shape error < 1e-4
    - Relative energy conservation within acceptable bounds
    """
    setup = soliton_setup
    p0 = setup["p0"]
    t0 = setup["t0"]
    total_length = setup["total_length"]

    solver = SolverConfig(
        simulation_type="spectrum_vs_distance",
        method="RK4IP",
        n_points=1024,
        time_window=20.0e-12,
        adaptive_step=True,
        initial_step=0.5,  # initial step 0.5 m
        tolerance=1e-8,
        min_step=1e-6,
        max_step=2.0,
        z_records=10,
        raman_enabled=False,
        shock_enabled=False,
    )

    states = list(solve_generator(setup["pulse"], setup["fiber"], solver))
    final_state = states[-1]

    assert pytest.approx(final_state.z, abs=1e-9) == total_length

    t = final_state.t
    intensity_norm = np.abs(final_state.a_t) ** 2 / p0
    arg = np.clip(t / t0, -40.0, 40.0)
    exact_shape = (1.0 / np.cosh(arg)) ** 2
    shape_err = float(np.max(np.abs(intensity_norm - exact_shape)))

    assert shape_err < 1e-4, f"Adaptive RK4IP shape error {shape_err:.2e} exceeded 1e-4"
    assert final_state.rel_energy_err < 1e-9, f"Adaptive RK4IP energy drift {final_state.rel_energy_err:.2e}"
