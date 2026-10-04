"""Tests for effective mode area A_eff extraction and nonlinear coefficient gamma auto-tuning."""

import math
import numpy as np
import pytest
from PyQt6.QtCore import Qt
from src.solver.operators import extract_h5_aeff, compute_gamma_from_aeff
from src.gui.main_window import MainWindow
from src.gui.file_navigator import FileNavigatorWidget


def test_compute_gamma_from_aeff_analytic():
    """Verify physical formula gamma(lambda_0) = (2 * pi * n2) / (lambda_0 * A_eff)."""
    wl_0 = 850e-9
    a_eff = 10.58e-12  # 10.58 um^2 in m^2
    n2 = 2.6e-20

    gamma_si, gamma_km = compute_gamma_from_aeff(a_eff, wl_0, n2=n2)

    expected_si = (2.0 * math.pi * n2) / (wl_0 * a_eff)
    expected_km = expected_si * 1e3

    assert pytest.approx(gamma_si, rel=1e-6) == expected_si
    assert pytest.approx(gamma_km, rel=1e-6) == expected_km
    assert pytest.approx(gamma_km, rel=1e-3) == 18.1656


def test_extract_h5_aeff_valid_file():
    """Verify extraction of A_eff from waveguide.h5 across groups and wavelengths."""
    file_path = "data/waveguide.h5"

    # Test group '20230330_4_ideal' at 850 nm
    aeff_850 = extract_h5_aeff(file_path, "20230330_4_ideal", carrier_wl_m=850e-9)
    assert aeff_850 is not None
    assert 2.0e-12 < aeff_850 < 4.0e-12  # approx 3.129 um^2 = 3.129e-12 m^2

    gamma_si, gamma_km = compute_gamma_from_aeff(aeff_850, 850e-9)
    assert pytest.approx(gamma_km, rel=1e-2) == 61.43

    # Test group '20230330_4_ideal' at 1550 nm
    aeff_1550 = extract_h5_aeff(file_path, "20230330_4_ideal", carrier_wl_m=1550e-9)
    assert aeff_1550 is not None
    assert aeff_1550 > aeff_850  # Mode area expands at longer wavelength


def test_extract_h5_aeff_backward_compatibility():
    """Verify graceful handling when HDF5 does not contain A_eff or for invalid paths."""
    # twisted_waveguide.h5 has no A_eff
    res = extract_h5_aeff("data/twisted_waveguide.h5", "/", carrier_wl_m=850e-9)
    assert res is None

    # Non-existent file
    res_none = extract_h5_aeff("data/non_existent.h5", "/", carrier_wl_m=850e-9)
    assert res_none is None


def test_file_navigator_aeff_signal_and_readout(qtbot):
    """Verify FileNavigatorWidget emits aeff_evaluated and updates its preview label."""
    nav = FileNavigatorWidget(default_dir="data")
    qtbot.addWidget(nav)

    received_signals = []
    nav.aeff_evaluated.connect(lambda aeff, gamma: received_signals.append((aeff, gamma)))

    nav.carrier_wavelength_m = 850e-9
    nav._inspect_file("data/waveguide.h5")

    # Group 20230330_4_ideal should be selected by default and evaluated
    assert len(received_signals) >= 1
    aeff, gamma = received_signals[-1]
    assert pytest.approx(aeff * 1e12, rel=1e-2) == 3.13
    assert pytest.approx(gamma, rel=1e-2) == 61.43
    assert "A_eff" in nav.lbl_aeff_evaluated.text()
    assert "Auto-tuned γ" in nav.lbl_aeff_evaluated.text()


def test_gui_auto_gamma_integration_headless(qtbot):
    """Verify end-to-end integration: selecting H5 updates TabControls txt_gamma and badge."""
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    controls = window.tab_controls
    nav = window.file_navigator

    # Initial default gamma
    assert controls.txt_gamma.text() == "45.0"
    assert controls.chk_auto_gamma.isChecked() is True

    # Select waveguide.h5
    nav.carrier_wavelength_m = 850e-9
    nav._inspect_file("data/waveguide.h5")

    # Gamma should be auto-tuned to ~61.43 W^-1 km^-1
    current_gamma = float(controls.txt_gamma.text())
    assert pytest.approx(current_gamma, rel=1e-2) == 61.43
    assert controls.lbl_gamma_aeff_badge.isVisible() is True
    assert "Auto-tuned" in controls.lbl_gamma_aeff_badge.text()

    # Changing carrier wavelength to 1550 nm in tab_controls updates gamma
    controls.txt_wavelength.setText("1550.0")
    new_gamma = float(controls.txt_gamma.text())
    assert new_gamma < current_gamma  # Mode area expands at 1550nm so gamma decreases

    # Unchecking auto-tune checkbox allows manual edit without overwrite
    controls.chk_auto_gamma.setChecked(False)
    assert controls.lbl_gamma_aeff_badge.isVisible() is False
    controls.txt_gamma.setText("99.9")
    controls.txt_wavelength.setText("850.0")
    assert controls.txt_gamma.text() == "99.9"  # Preserved manual edit
