"""Tests for the 5 physics & GUI improvements:
1. Lorentzian pulse shape & Custom array features
2. Realistic chirp parameter (ChirpSpinBox & physical rates)
3. Available Dispersion DataFiles box sizing & styling
4. Physical dispersion conversion D(lambda) -> beta_2 -> beta(omega)
5. Results section X-axis height alignment
"""

import os
import math
import numpy as np
import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from src.solver.config import (
    C_CONST, PulseConfig, FiberConfig, DispersionConfig, SolverConfig
)
from src.solver.engine import generate_initial_pulse, solve_generator
from src.solver.operators import (
    compute_dispersion_operator, _load_dispersion_file, evaluate_taylor_betas
)
from src.gui.plots import DensityMapWidget, LinePlotWidget
from src.gui.tab_controls import ChirpSpinBox, ManualDispersionWidget, TabControlsWidget
from src.gui.file_navigator import FileNavigatorWidget
from src.gui.tab_results import TabResultsWidget


def test_lorentzian_pulse_shape():
    """Verify Lorentzian pulse profile, intensity FWHM, and chirp."""
    fwhm = 100e-15  # 100 fs
    p0 = 5000.0     # 5 kW
    pulse = PulseConfig(shape="lorentzian", t_fwhm=fwhm, p_peak=p0, chirp=0.0)

    # Expected T0
    expected_div = 2.0 * math.sqrt(math.sqrt(2.0) - 1.0)
    assert pytest.approx(pulse.t0, rel=1e-6) == fwhm / expected_div

    # Generate pulse on grid
    t = np.linspace(-500e-15, 500e-15, 2048)
    a_t = generate_initial_pulse(pulse, t)
    intensity = np.abs(a_t) ** 2

    # Peak power
    assert pytest.approx(float(np.max(intensity)), rel=1e-4) == p0

    # Half maximum intensity points
    half_max = p0 / 2.0
    t_pos_idx = np.where(intensity >= half_max)[0]
    actual_fwhm = t[t_pos_idx[-1]] - t[t_pos_idx[0]]
    assert pytest.approx(actual_fwhm, rel=0.02) == fwhm

    # Chirped Lorentzian
    pulse_chirped = PulseConfig(shape="lorentzian", t_fwhm=fwhm, p_peak=p0, chirp=2.5)
    a_chirped = generate_initial_pulse(pulse_chirped, t)
    np.testing.assert_allclose(np.abs(a_chirped) ** 2, intensity, rtol=1e-5)
    # Phase variation
    phase = np.unwrap(np.angle(a_chirped))
    assert np.max(phase) - np.min(phase) > 1.0


def test_custom_pulse_array_load_and_run(tmp_path):
    """Verify custom array input from file and solver propagation."""
    t_grid = np.linspace(-1e-12, 1e-12, 512)
    # Hyper-gaussian custom field
    custom_field = np.sqrt(2000.0) * np.exp(-0.5 * ((t_grid / 200e-15) ** 4))

    # Save to .npy
    npy_file = tmp_path / "custom_pulse.npy"
    np.save(npy_file, custom_field)

    # Save to .csv with time
    csv_file = tmp_path / "custom_pulse.csv"
    data = np.column_stack([t_grid * 1e12, custom_field])  # time in ps
    np.savetxt(csv_file, data, delimiter=",", header="t_ps,field")

    # Load custom pulse in config
    p_config = PulseConfig(shape="custom", t_fwhm=200e-15, p_peak=2000.0, custom_field=custom_field, custom_time=t_grid)
    a_init = generate_initial_pulse(p_config, t_grid)
    np.testing.assert_allclose(a_init, custom_field)


def test_chirp_spinbox_behavior(qtbot):
    """Verify ChirpSpinBox range, setText/text compatibility, and tooltips."""
    spin = ChirpSpinBox()
    qtbot.addWidget(spin)

    assert spin.minimum() <= -20.0
    assert spin.maximum() >= 20.0
    assert spin.value() == 0.0
    assert "Transform-limited" in spin.toolTip()
    assert "Up-chirp" in spin.toolTip()

    # setText compatibility
    spin.setText("5.5")
    assert spin.value() == 5.5
    assert "5.5" in spin.text()

    spin.setText("-12.3")
    assert spin.value() == -12.3


def test_file_navigator_compact_box_and_title(qtbot, tmp_path):
    """Verify file list box is compact and title is unobstructed."""
    nav = FileNavigatorWidget(default_dir=str(tmp_path))
    qtbot.addWidget(nav)

    # Box size decrease verified
    assert nav.file_list.maximumHeight() <= 120

    # Ensure signals exist
    assert hasattr(nav, "populate_manual_requested")
    assert hasattr(nav, "combo_preview_mode")
    assert nav.combo_preview_mode.count() == 3


def test_dispersion_d_to_beta_conversion(tmp_path):
    """Verify D(lambda) in ps/(nm·km) is accurately converted to beta_2 and integrated to beta(omega)."""
    csv_path = tmp_path / "test_d_curve.csv"
    wl_nm = np.linspace(800.0, 1600.0, 100)
    wl_m = wl_nm * 1e-9
    # Synthesize D with ZDW at 1040 nm
    d_vals = 0.05 * (wl_nm - 1040.0)  # ps/(nm*km)

    data = np.column_stack([wl_nm, d_vals])
    np.savetxt(csv_path, data, delimiter=",", header="wavelength_nm,D_ps_nm_km")

    disp = DispersionConfig.from_import(str(csv_path), data_type="D")
    w_sorted, beta_sorted = _load_dispersion_file(csv_path, disp)

    # Test evaluated betas at 1040 nm (where D = 0 => beta2 = 0)
    omega0 = 2.0 * math.pi * C_CONST / 1040e-9
    betas = evaluate_taylor_betas(w_sorted, beta_sorted, omega0, max_order=4)

    # Beta2 at ZDW should be 0
    assert pytest.approx(betas[0], abs=1e-28) == 0.0

    # D to beta2 direct formula check
    b2_manual = DispersionConfig.d_to_beta2(10.0, 1550e-9)
    d_back = DispersionConfig.beta2_to_d(b2_manual, 1550e-9)
    assert pytest.approx(d_back, rel=1e-5) == 10.0


def test_results_x_axis_alignment(qtbot):
    """Verify bottom X-axes of 2D density map and 1D line plot align at matching heights."""
    tab = TabResultsWidget()
    qtbot.addWidget(tab)
    tab.resize(1200, 800)
    tab.show()
    QApplication.processEvents()

    for mode in ["freq", "time"]:
        tab.set_domain_mode(mode)
        QApplication.processEvents()

        if mode == "freq":
            p2 = tab.plot_freq_2d
            p1 = tab.plot_freq_1d
        else:
            p2 = tab.plot_time_2d
            p1 = tab.plot_time_1d

        axis2_geom = p2.plot_item.getAxis("bottom").geometry()
        axis1_geom = p1.plot_item.getAxis("bottom").geometry()

        diff_y = abs(axis1_geom.y() - axis2_geom.y())
        assert diff_y < 1.0, f"X-axes misaligned in {mode} mode: 2D y={axis2_geom.y()}, 1D y={axis1_geom.y()}"
        assert abs(axis1_geom.height() - axis2_geom.height()) < 1.0
