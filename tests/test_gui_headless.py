"""Automated Headless GUI Tests for GNLSE Desktop Simulator using pytest-qt.

Validates:
- Offscreen instantiation of MainWindow and all three tabs
- Strict scientific unit notation across Tab 1 parameter input labels
- Dynamic restructuring of Tab 2 results canvas between 2x2 (Distance) and 1x2 (Power Sweep)
- Preset loading integrity (Hult 2007, Soliton N=1, Telecom pulse)
- Dynamic carrier wavelength calibration (never hardcoded 835 nm)
- Asynchronous worker thread execution and QThread slot affinity
- Bounded memory waterfall decimation (z_records = 400)
- Raman grid sampling advisory in GUI
- Interactive pause/resume GUI toggle
- Tab 2 export functionality (HDF5, CSV)
- File navigator preview and ZDW crosshair detection
"""

import os
import math
import numpy as np
import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QFileDialog
from src.gui.main_window import MainWindow
from src.solver.config import SimulationState


def test_mainwindow_instantiation_headless(qtbot):
    """Verify MainWindow initializes without errors under offscreen platform."""
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()

    assert window.tabs.count() == 3
    assert "Setup" in window.tabs.tabText(0)
    assert "Results" in window.tabs.tabText(1)
    assert "Logging" in window.tabs.tabText(2)
    assert window.lbl_status.text() == "Status: Idle"


def test_scientific_unit_labels_integrity(qtbot):
    """Verify all parameter input labels explicitly include physical units in brackets."""
    window = MainWindow()
    qtbot.addWidget(window)

    controls = window.tab_controls

    # Collect all QLabel texts in controls
    all_labels = [lbl.text() for lbl in controls.findChildren(QLabel)]
    all_text = " ".join(all_labels)

    # Verify bracketed units specified in Blueprint Section 9.1
    required_units = [
        "[fs]", "[kW]", "[nm]", "[-]", "[cm]", "[W⁻¹·km⁻¹]", "[dB/km]",
        "[ps²/km]", "[ps³/km]", "[ps⁴/km]", "[ps⁵/km]", "[ps⁶/km]", "[ps⁷/km]",
        "[points]", "[ps]", "[mm]"
    ]
    for unit in required_units:
        assert unit in all_text, f"Expected unit '{unit}' not found in parameter labels"

    # Verify dynamic T0 and omega0 readouts exist and are populated
    assert "T₀ =" in controls.lbl_t0_info.text()
    assert "ω₀ =" in controls.lbl_omega0_info.text()


def test_dynamic_layout_restructuring(qtbot):
    """Verify switching simulation type updates Tab 2 from 2x2 to 1x2."""
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()

    # Switch to Results tab so widgets become active
    window.tabs.setCurrentIndex(1)

    results = window.tab_results
    controls = window.tab_controls

    # Default is Spectrum vs Distance (2x2 grid)
    assert results.current_sim_type == "spectrum_vs_distance"
    assert results.plot_time_2d.isHidden() is False
    assert results.plot_time_1d.isHidden() is False

    # Switch to Spectrum vs Power (1x2 grid, time plots hidden)
    controls.combo_sim_type.setCurrentIndex(1)  # "Spectrum vs Power"
    assert results.current_sim_type == "spectrum_vs_power"
    assert results.plot_time_2d.isHidden() is True
    assert results.plot_time_1d.isHidden() is True
    assert results.plot_freq_2d.isHidden() is False
    assert results.plot_freq_1d.isHidden() is False

    # Switch back to Spectrum vs Distance (2x2 grid restored)
    controls.combo_sim_type.setCurrentIndex(0)
    assert results.current_sim_type == "spectrum_vs_distance"
    assert results.plot_time_2d.isHidden() is False
    assert results.plot_time_1d.isHidden() is False


def test_preset_loading(qtbot):
    """Verify preset selection populates parameters accurately."""
    window = MainWindow()
    qtbot.addWidget(window)
    controls = window.tab_controls

    # 1. Select Johan Hult 2007 preset
    controls.combo_presets.setCurrentIndex(0)
    assert float(controls.txt_wavelength.text()) == 835.0
    assert float(controls.txt_beta2.text()) == -11.83
    assert float(controls.txt_fwhm.text()) == 50.0
    assert controls.chk_raman.isChecked() is True

    # 2. Select Soliton N=1 preset
    controls.combo_presets.setCurrentIndex(1)
    assert float(controls.txt_wavelength.text()) == 1550.0
    assert float(controls.txt_beta2.text()) == -21.4
    assert controls.chk_raman.isChecked() is False

    # 3. Select Telecom preset
    controls.combo_presets.setCurrentIndex(2)
    assert float(controls.txt_wavelength.text()) == 1550.0
    assert float(controls.txt_fwhm.text()) == 10000.0
    assert float(controls.txt_loss.text()) == 0.2
    assert controls.chk_raman.isChecked() is False


def test_dynamic_wavelength_calibration(qtbot):
    """Verify Tab 2 dynamically calibrates carrier wavelength and omega0."""
    window = MainWindow()
    qtbot.addWidget(window)

    # 1. Load Soliton N=1 preset (1550 nm)
    window.tab_controls.combo_presets.setCurrentIndex(1)
    # Trigger simulation start
    window.tab_controls._on_run_clicked()

    # Verify Tab 2 calibrated to 1550 nm
    assert pytest.approx(window.tab_results.center_wavelength) == 1550e-9
    expected_omega0 = 2.0 * math.pi * 299792458.0 / 1550e-9
    assert pytest.approx(window.tab_results.omega0) == expected_omega0

    # Clean up worker thread
    if window.worker:
        window._abort_simulation()
        qtbot.wait(200)
    window._cleanup_thread()


def test_asynchronous_worker_thread_execution(qtbot):
    """Verify simulation runs asynchronously in worker_thread without blocking main thread."""
    from PyQt6.QtCore import QThread
    window = MainWindow()
    qtbot.addWidget(window)

    # Quick test setup
    window.tab_controls.combo_presets.setCurrentIndex(1)
    window.tab_controls.txt_length.setText("10.0")  # 10 m
    window.tab_controls.chk_display_live.setChecked(False)

    window.tab_controls._on_run_clicked()

    assert window.worker_thread is not None
    assert window.worker_thread.isRunning()
    assert window.worker.thread() == window.worker_thread
    assert window.worker.thread() != QThread.currentThread()

    # Trigger cooperative abort and verify clean thread teardown
    window._abort_simulation()
    qtbot.wait(300)
    assert window.worker_thread is None or not window.worker_thread.isRunning()


def test_bounded_memory_waterfall_decimation(qtbot):
    """Verify Ticket SW-3: z_records=400 is strictly enforced for spectrum_vs_distance."""
    from src.gui.tab_controls import TabControlsWidget
    controls = TabControlsWidget()
    qtbot.addWidget(controls)

    recorded_solver = []
    controls.run_requested.connect(lambda p, f, s, d: recorded_solver.append(s))

    controls.combo_sim_type.setCurrentIndex(0)  # spectrum_vs_distance
    controls._on_run_clicked()

    assert len(recorded_solver) == 1
    assert recorded_solver[0].z_records == 400

    # In spectrum_vs_power, z_records is None
    controls.combo_sim_type.setCurrentIndex(1)  # spectrum_vs_power
    controls._on_run_clicked()
    assert len(recorded_solver) == 2
    assert recorded_solver[1].z_records is None


def test_raman_advisory_in_gui(qtbot):
    """Verify Ticket PH-1: GUI displays advisory warning when Delta T exceeds tau1/4."""
    from src.gui.tab_controls import TabControlsWidget
    controls = TabControlsWidget()
    qtbot.addWidget(controls)

    # Enable Raman
    controls.chk_raman.setChecked(True)

    # Set undersampled grid: N=1024, Time Window=20 ps -> dt = 19.53 fs > 3.05 fs
    controls.combo_grid_n.setCurrentText("1024")
    controls.txt_time_window.setText("20.0")

    assert controls.lbl_raman_warning.isHidden() is False
    assert "exceeds Raman threshold" in controls.lbl_raman_warning.text()

    # Increase grid points to N=8192: dt = 2.44 fs < 3.05 fs -> Advisory clears
    controls.combo_grid_n.setCurrentText("8192")
    assert controls.lbl_raman_warning.isHidden() is True


def test_pause_resume_toggle_gui(qtbot):
    """Verify GUI pause/resume button toggles state and status cleanly."""
    window = MainWindow()
    qtbot.addWidget(window)
    controls = window.tab_controls

    controls.combo_presets.setCurrentIndex(1)
    controls.txt_length.setText("50.0")
    controls.chk_display_live.setChecked(False)

    controls._on_run_clicked()
    assert controls.btn_pause.isEnabled() is True
    assert controls.btn_pause.text() == "❚❚ Pause"

    # Click pause
    controls.btn_pause.click()
    assert controls._is_paused is True
    assert controls.btn_pause.text() == "▶ Resume"
    assert "Paused" in window.lbl_status.text()
    assert window.worker.is_paused() is True

    # Click resume
    controls.btn_pause.click()
    assert controls._is_paused is False
    assert controls.btn_pause.text() == "❚❚ Pause"
    assert "Running" in window.lbl_status.text()
    assert window.worker.is_paused() is False

    # Abort cleanly
    controls.btn_abort.click()
    qtbot.wait(200)
    window._cleanup_thread()


def test_tab2_export_hdf5_and_csv(qtbot, tmp_path):
    """Verify Tab 2 export creates valid HDF5 and CSV datasets with dynamic wavelength."""
    import h5py
    from src.gui.tab_results import TabResultsWidget

    results = TabResultsWidget()
    qtbot.addWidget(results)
    N = 256
    t = np.linspace(-5e-12, 5e-12, N)
    omega = 2.0 * np.pi * np.fft.fftfreq(N, d=(t[1] - t[0]))
    a_t = np.exp(-0.5 * (t / 1e-12) ** 2).astype(np.complex128)
    a_w = np.fft.fft(a_t)

    s1 = SimulationState(step=0, z=0.0, power=1.0, h=0.01, t=t, omega=omega, a_t=a_t, a_w=a_w, rel_energy_err=0.0, rel_photon_err=0.0)
    s2 = SimulationState(step=1, z=0.1, power=0.9, h=0.01, t=t, omega=omega, a_t=a_t * 0.95, a_w=a_w * 0.95, rel_energy_err=1e-5, rel_photon_err=1e-6)

    # Prepare with 1550 nm wavelength
    results.prepare_for_simulation(s1, "RK4IP", center_wavelength=1550e-9)
    results.render_full_simulation(s2, [s1, s2])

    assert results.center_wavelength == 1550e-9

    # Test HDF5 Export
    h5_file = str(tmp_path / "test_out.h5")
    ok, msg = results.export_to_file(h5_file)
    assert ok is True
    assert os.path.exists(h5_file)
    with h5py.File(h5_file, "r") as h5f:
        assert "time_ps" in h5f
        assert "wavelength_nm" in h5f
        assert "a_t_envelope" in h5f
        assert "a_w_spectrum" in h5f
        assert pytest.approx(h5f.attrs["center_wavelength_nm"]) == 1550.0

    # Test CSV Export
    csv_file = str(tmp_path / "test_out.csv")
    ok, msg = results.export_to_file(csv_file)
    assert ok is True
    assert os.path.exists(csv_file)
    with open(csv_file, "r") as f:
        content = f.read()
        assert "1550.000" in content
        assert "time_ps" in content
        assert "spectral_power_after_dB" in content


def test_file_navigator_zdw_and_preview(tmp_path):
    """Verify FileNavigator inspects CSV dispersion data and detects ZDW crosshair."""
    from src.gui.file_navigator import FileNavigatorWidget

    csv_path = tmp_path / "dispersion_test.csv"
    # D(lambda) crossing zero at 1040 nm
    with open(csv_path, "w", encoding="utf-8") as f:
        f.write("wavelength_nm,D_ps_nm_km\n")
        f.write("800.0,-24.0\n")
        f.write("1000.0,-4.0\n")
        f.write("1040.0,0.0\n")
        f.write("1100.0,6.0\n")
        f.write("1200.0,16.0\n")

    navigator = FileNavigatorWidget(default_dir=str(tmp_path))
    assert navigator.file_list.count() == 1

    navigator._inspect_file(str(csv_path))
    assert navigator.zdw_line.isVisible() is True
    assert pytest.approx(navigator.zdw_line.value(), abs=1.0) == 1040.0
    assert "ZDW ≈ 1040" in navigator.lbl_metadata.text()


def test_tab3_diagnostics_and_logging(qtbot):
    """Verify Tab 3 displays live physical conservation errors, calculation rate, and ETA."""
    from src.gui.tab_logging import TabLoggingWidget
    tab_log = TabLoggingWidget()
    qtbot.addWidget(tab_log)

    tab_log.update_metrics(energy_err=1.23e-6, photon_err=4.56e-5, h_m=1e-4, steps_per_sec=120.5)
    assert tab_log.lbl_energy_err.text() == "1.23e-06"
    assert tab_log.lbl_photon_err.text() == "4.56e-05"
    assert "0.1000 mm" in tab_log.lbl_step_size.text()

    tab_log.update_calc_rate(steps_per_sec=250.0, eta_sec=3.5)
    assert "250.0 steps/s" in tab_log.lbl_calc_speed.text()
    assert "3.5 s" in tab_log.lbl_eta.text()
    assert "GNLSE Diagnostic Logger initialized" in tab_log.console.toPlainText()
