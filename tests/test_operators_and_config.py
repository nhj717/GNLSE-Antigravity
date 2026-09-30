"""Comprehensive unit tests for configuration, operators, and alternative solver modes."""

import math
import numpy as np
import pytest
import h5py

from src.solver.config import (
    C_CONST,
    DispersionConfig,
    FiberConfig,
    PulseConfig,
    SolverConfig,
)
from src.solver.operators import (
    compute_dispersion_operator,
    compute_energy,
    compute_nonlinear_operator,
    compute_photon_number,
    compute_shock_factor,
    relative_error,
    super_gaussian_filter,
)
from src.solver.engine import (
    generate_initial_pulse,
    solve_generator,
)


def test_dispersion_import_csv(tmp_path):
    """Test importing dispersion curve from CSV."""
    csv_file = tmp_path / "fiber_dispersion.csv"
    # Create synthetic beta(omega) curve
    lambda_nm = np.linspace(800, 1600, 100)
    omega_arr = 2.0 * math.pi * C_CONST / (lambda_nm * 1e-9)
    # Quadratic beta(omega)
    beta0 = 1e7
    beta1 = 5e-9
    beta2 = -2e-26
    beta_arr = beta0 + beta1 * (omega_arr - 2e15) + 0.5 * beta2 * ((omega_arr - 2e15) ** 2)

    # Save as CSV with header
    data = np.column_stack([lambda_nm, beta_arr])
    np.savetxt(csv_file, data, delimiter=",", header="wavelength_nm,beta")

    disp = DispersionConfig.from_import(str(csv_file))
    omega_grid = np.linspace(-1e13, 1e13, 64)
    omega0 = 2e15
    d_op = compute_dispersion_operator(omega_grid, disp, alpha_si=0.0, omega0=omega0)

    # Should match 0.5 * 1j * beta2 * omega^2
    expected_d = 0.5 * 1j * beta2 * (omega_grid ** 2)
    np.testing.assert_allclose(d_op, expected_d, rtol=1e-3, atol=1e-3)


def test_dispersion_import_h5(tmp_path):
    """Test importing dispersion curve from HDF5."""
    h5_file = tmp_path / "fiber_dispersion.h5"
    omega_arr = np.linspace(1e15, 3e15, 100)
    beta2 = -1.5e-26
    beta_arr = 0.5 * beta2 * ((omega_arr - 2e15) ** 2)

    with h5py.File(h5_file, "w") as f:
        f.create_dataset("omega", data=omega_arr)
        f.create_dataset("beta", data=beta_arr)

    disp = DispersionConfig.from_import(str(h5_file))
    omega_grid = np.linspace(-1e13, 1e13, 64)
    omega0 = 2e15
    d_op = compute_dispersion_operator(omega_grid, disp, alpha_si=0.0, omega0=omega0)
    expected_d = 0.5 * 1j * beta2 * (omega_grid ** 2)
    np.testing.assert_allclose(d_op, expected_d, rtol=1e-3, atol=1e-3)


def test_pulse_gaussian_and_custom():
    """Test Gaussian and custom pulse generation."""
    t = np.linspace(-5e-12, 5e-12, 1024)
    pulse_g = PulseConfig(shape="gaussian", t_fwhm=1e-12, p_peak=100.0, chirp=1.5)
    a_g = generate_initial_pulse(pulse_g, t)
    assert len(a_g) == 1024
    assert pytest.approx(np.max(np.abs(a_g) ** 2), rel=1e-3) == 100.0

    # Custom shape
    custom_field = 10.0 * np.exp(-((t / 1e-12) ** 4))
    pulse_c = PulseConfig(shape="custom", t_fwhm=1e-12, p_peak=100.0, custom_field=custom_field)
    a_c = generate_initial_pulse(pulse_c, t)
    np.testing.assert_allclose(a_c, custom_field)


def test_shock_factor_dc_clamping():
    """Test DC singularity clamping in compute_shock_factor."""
    omega0 = 1.0e15
    # Omega extends below -omega0
    omega = np.array([-2.0e15, -1.0e15, -0.5e15, 0.0, 0.5e15])
    factor = compute_shock_factor(omega, omega0=omega0, enabled=True)

    # Clamping: at -2e15, 1 + (-2) = -1 -> clamped to 0.0
    assert factor[0] == 0.0
    assert factor[1] == 0.0
    assert pytest.approx(factor[2]) == 0.5
    assert pytest.approx(factor[3]) == 1.0
    assert pytest.approx(factor[4]) == 1.5


def test_anti_aliasing_filter():
    """Test super-Gaussian frequency filter profile."""
    omega = np.linspace(-1e15, 1e15, 1000)
    w = super_gaussian_filter(omega, cutoff_fraction=0.9, order=20)

    # Center should be exactly 1.0
    center_idx = len(omega) // 2
    assert pytest.approx(w[center_idx]) == 1.0

    # Near 0.5 * omega_max should be ~1.0
    idx_quarter = len(omega) * 3 // 4
    assert w[idx_quarter] > 0.99

    # At the edge (|omega| = omega_max > 0.9 * omega_max), it should be suppressed
    assert w[0] < 0.1
    assert w[-1] < 0.1


def test_spectrum_vs_power_mode():
    """Test spectrum_vs_power simulation generator."""
    pulse = PulseConfig(shape="sech", t_fwhm=1.0e-12, p_peak=10.0)
    fiber = FiberConfig(length=1.0, gamma=1.0e-3, dispersion=DispersionConfig.from_si(beta2=-2e-26))
    solver = SolverConfig(
        simulation_type="spectrum_vs_power",
        method="RK4IP",
        n_points=512,
        time_window=10e-12,
        adaptive_step=False,
        initial_step=0.5,
        power_min=1.0,
        power_max=10.0,
        power_steps=5,
    )

    states = list(solve_generator(pulse, fiber, solver))
    assert len(states) == 5
    assert pytest.approx(states[0].power) == 1.0
    assert pytest.approx(states[-1].power) == 10.0
    for s in states:
        assert s.z == 1.0


def test_config_serialization_round_trip():
    """Verify full round-trip serialization/deserialization of configs works with solve_generator."""
    orig_pulse = PulseConfig(shape="sech", t_fwhm=1.0e-12, p_peak=50.0, center_wavelength=1550e-9)
    orig_fiber = FiberConfig(
        length=0.1,
        gamma=2.5e-3,
        dispersion=DispersionConfig.from_si(beta2=-20e-27, beta3=0.1e-39),
        raman_fr=0.18,
    )
    orig_solver = SolverConfig(
        n_points=512,
        time_window=10e-12,
        adaptive_step=False,
        initial_step=0.05,
        z_records=2,
    )

    # Test round trip to_dict -> from_dict
    pulse_dict = orig_pulse.to_dict()
    fiber_dict = orig_fiber.to_dict()
    solver_dict = orig_solver.to_dict()

    deserialized_pulse = PulseConfig.from_dict(pulse_dict)
    deserialized_fiber = FiberConfig.from_dict(fiber_dict)
    deserialized_solver = SolverConfig.from_dict(solver_dict)

    # Verify nested types
    assert isinstance(deserialized_fiber.dispersion, DispersionConfig)
    assert deserialized_fiber.dispersion.beta2 == orig_fiber.dispersion.beta2
    assert deserialized_fiber.dispersion.beta3 == orig_fiber.dispersion.beta3
    assert deserialized_fiber.gamma == orig_fiber.gamma
    assert deserialized_pulse.t_fwhm == orig_pulse.t_fwhm
    assert deserialized_solver.n_points == orig_solver.n_points

    # Verify default FiberConfig().to_dict() round trip works with solve_generator
    default_fiber = FiberConfig.from_dict(FiberConfig().to_dict())
    assert isinstance(default_fiber.dispersion, DispersionConfig)

    # Verify execution in solve_generator with deserialized configs
    states = list(solve_generator(deserialized_pulse, deserialized_fiber, deserialized_solver))
    assert len(states) >= 2
    assert pytest.approx(states[-1].z, abs=1e-6) == 0.1

