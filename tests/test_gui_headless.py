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
    all_labels = [lbl.text() for lbl in controls.findChildren(QLabel)] + [lbl.text() for lbl in window.manual_disp.findChildren(QLabel)]
    all_text = " ".join(all_labels)

    # Verify bracketed units specified in Blueprint Section 9.1
    required_units = [
        "[fs]", "[kW]", "[nm]", "[-]", "[cm]", "[W⁻¹·km⁻¹]", "[dB/km]",
        "[ps² m⁻¹] × 10⁻²", "[ps³ m⁻¹] × 10⁻⁵", "[ps⁴ m⁻¹] × 10⁻⁷", "[ps⁵ m⁻¹] × 10⁻¹⁰", "[ps⁶ m⁻¹] × 10⁻¹³", "[ps⁷ m⁻¹] × 10⁻¹⁶",
        "[points]", "[ps]", "[mm]"
    ]
    for unit in required_units:
        assert unit in all_text, f"Expected unit '{unit}' not found in parameter labels"

    # Verify dynamic T0 and omega0 readouts exist and are populated
    assert "T₀ =" in controls.lbl_t0_info.text()
    assert "ω₀ =" in controls.lbl_omega0_info.text()


def test_dynamic_layout_restructuring(qtbot):
    """Verify switching simulation type updates Tab 2 layout appropriately."""
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()

    # Switch to Results tab so widgets become active
    window.tabs.setCurrentIndex(1)

    results = window.tab_results
    controls = window.tab_controls

    # Switch to Time domain to verify temporal plots
    results.set_domain_mode("time")
    assert results.current_sim_type == "spectrum_vs_distance"
    assert results.plot_time_2d.isHidden() is False
    assert results.plot_time_1d.isHidden() is False

    # Switch to Spectrum vs Power (power sweep shown, time plots disabled)
    controls.combo_sim_type.setCurrentIndex(1)  # "Spectrum vs Power"
    assert results.current_sim_type == "spectrum_vs_power"
    assert results.plot_time_2d.isHidden() is True
    assert results.plot_time_1d.isHidden() is True
    assert results.plot_freq_2d.isHidden() is False
    assert results.plot_freq_1d.isHidden() is False

    # Switch back to Spectrum vs Distance and verify time domain can be activated
    controls.combo_sim_type.setCurrentIndex(0)
    assert results.current_sim_type == "spectrum_vs_distance"
    results.set_domain_mode("time")
    assert results.plot_time_2d.isHidden() is False
    assert results.plot_time_1d.isHidden() is False



def test_preset_loading(qtbot):
    """Verify preset selection populates parameters accurately."""
    window = MainWindow()
    qtbot.addWidget(window)
    controls = window.tab_controls

    # 1. Switch to index 1 (Soliton N=1)
    controls.combo_presets.setCurrentIndex(1)
    assert float(controls.txt_wavelength.text()) == 1550.0
    assert float(controls.txt_beta2.text()) == -2.14
    assert controls.chk_raman.isChecked() is False

    # 2. Switch to index 0 (Johan Hult 2007)
    controls.combo_presets.setCurrentIndex(0)
    assert float(controls.txt_wavelength.text()) == 850.0
    assert float(controls.txt_length.text()) == 10.0
    assert float(controls.txt_gamma.text()) == 45.0
    assert float(controls.txt_beta2.text()) == -1.276
    assert float(controls.txt_beta3.text()) == 8.119
    assert float(controls.txt_beta4.text()) == -1.321
    assert float(controls.txt_beta5.text()) == 3.032
    assert float(controls.txt_beta6.text()) == -4.196
    assert float(controls.txt_beta7.text()) == 2.570
    assert float(controls.txt_fwhm.text()) == 50.0
    assert controls.chk_raman.isChecked() is True

    # 3. Switch to index 2 (Telecom)
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


def test_file_navigator_use_file_selection(qtbot, tmp_path):
    """Verify file_navigator.file_selected works without crashing (_on_use_file)."""
    window = MainWindow()
    qtbot.addWidget(window)

    csv_path = tmp_path / "test_disp.csv"
    with open(csv_path, "w", encoding="utf-8") as f:
        f.write("wavelength_nm,D_ps_nm_km\n800.0,-20.0\n1000.0,0.0\n1200.0,15.0\n")

    window.file_navigator.active_file_path = str(csv_path)
    window.file_navigator.btn_use_dispersion.setEnabled(True)
    window.file_navigator._on_use_file()

    assert window.tab_controls.combo_disp_mode.currentIndex() == 1
    assert window.tab_controls.active_import_file == str(csv_path)
    assert window.file_navigator.txt_import_path.text() == str(csv_path)

    # Calling set_active_import_file directly also works without crash
    window.tab_controls.set_active_import_file(str(csv_path))
    assert window.file_navigator.txt_import_path.text() == str(csv_path)


def test_config_export_import_roundtrip(qtbot, tmp_path, monkeypatch):
    """Verify config export and import round-trip accurately restores beta values and solver settings."""
    window = MainWindow()
    qtbot.addWidget(window)
    controls = window.tab_controls
    manual_disp = window.manual_disp

    # Configure specific manual beta values and solver parameters
    manual_disp.txt_beta2.setText("-1.276")
    manual_disp.txt_beta3.setText("8.119")
    manual_disp.txt_beta4.setText("-1.321")
    manual_disp.txt_beta5.setText("3.032")
    manual_disp.txt_beta6.setText("-4.196")
    manual_disp.txt_beta7.setText("2.570")

    controls.combo_sim_type.setCurrentIndex(1)  # Spectrum vs Power
    controls.combo_method.setCurrentText("S-SSFM")
    controls.chk_adaptive.setChecked(False)
    controls.txt_power_min.setText("0.5")
    controls.txt_power_max.setText("12.0")
    controls.txt_power_steps.setText("60")
    controls.combo_grid_n.setCurrentText("4096")
    controls.txt_time_window.setText("15.0")
    controls.txt_init_step.setText("0.05")
    controls.txt_tolerance.setText("2e-5")

    # Export to json file
    export_file = str(tmp_path / "config_roundtrip.json")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: (export_file, "JSON Files (*.json)"))
    controls._on_export_config()
    assert os.path.exists(export_file)

    # Change settings to something different
    manual_disp.txt_beta2.setText("0.0")
    manual_disp.txt_beta3.setText("0.0")
    manual_disp.txt_beta4.setText("0.0")
    manual_disp.txt_beta5.setText("0.0")
    manual_disp.txt_beta6.setText("0.0")
    manual_disp.txt_beta7.setText("0.0")
    controls.combo_sim_type.setCurrentIndex(0)
    controls.combo_method.setCurrentText("RK4IP")
    controls.chk_adaptive.setChecked(True)
    controls.combo_grid_n.setCurrentText("1024")

    # Import back from the file
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args, **kwargs: (export_file, "JSON Files (*.json)"))
    controls._on_import_config()

    # Verify beta values restored accurately
    assert float(manual_disp.txt_beta2.text()) == pytest.approx(-1.276)
    assert float(manual_disp.txt_beta3.text()) == pytest.approx(8.119)
    assert float(manual_disp.txt_beta4.text()) == pytest.approx(-1.321)
    assert float(manual_disp.txt_beta5.text()) == pytest.approx(3.032)
    assert float(manual_disp.txt_beta6.text()) == pytest.approx(-4.196)
    assert float(manual_disp.txt_beta7.text()) == pytest.approx(2.570)

    # Verify solver settings restored accurately
    assert controls.combo_sim_type.currentIndex() == 1
    assert controls.combo_method.currentText() == "S-SSFM"
    assert controls.chk_adaptive.isChecked() is False
    assert float(controls.txt_power_min.text()) == pytest.approx(0.5)
    assert float(controls.txt_power_max.text()) == pytest.approx(12.0)
    assert int(controls.txt_power_steps.text()) == 60
    assert controls.combo_grid_n.currentText() == "4096"
    assert float(controls.txt_time_window.text()) == pytest.approx(15.0)
    assert float(controls.txt_init_step.text()) == pytest.approx(0.05)
    assert float(controls.txt_tolerance.text()) == pytest.approx(2e-5)


def test_auto_grid_combobox_preservation(qtbot):
    """Verify selecting 'Auto' grid is preserved during simulation run and exported correctly."""
    from src.gui.tab_controls import TabControlsWidget
    controls = TabControlsWidget()
    qtbot.addWidget(controls)

    controls.combo_grid_n.setCurrentText("Auto")
    assert controls.combo_grid_n.currentText() == "Auto"

    recorded = []
    controls.run_requested.connect(lambda p, f, s, d: recorded.append(s))
    controls._on_run_clicked()

    # Combobox must remain "Auto"
    assert controls.combo_grid_n.currentText() == "Auto"
    assert len(recorded) == 1
    # SolverConfig received a positive power-of-2 integer
    assert recorded[0].n_points >= 1024
    assert (recorded[0].n_points & (recorded[0].n_points - 1)) == 0


def test_defensive_parameter_input_handling(qtbot, monkeypatch):
    """Verify invalid inputs trigger warning dialog and do not crash."""
    from src.gui.tab_controls import TabControlsWidget
    controls = TabControlsWidget()
    qtbot.addWidget(controls)

    warnings = []
    from PyQt6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "warning", lambda parent, title, msg: warnings.append((title, msg)))

    # Set invalid non-numeric text in FWHM
    controls.txt_fwhm.setText("invalid_number")
    controls._on_run_clicked()

    assert len(warnings) == 1
    assert "Invalid Parameter" in warnings[0][0]

    # Test missing dispersion file warning in import mode
    controls.txt_fwhm.setText("50.0")
    controls.combo_disp_mode.setCurrentIndex(1)
    controls._on_run_clicked()

    assert len(warnings) == 2
    assert "Missing Dispersion File" in warnings[1][0]


def test_mainwindow_simulation_initialization_error(qtbot, monkeypatch):
    """Verify MainWindow handles initial solver generator failure gracefully."""
    window = MainWindow()
    qtbot.addWidget(window)

    errors = []
    from PyQt6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "critical", lambda parent, title, msg: errors.append((title, msg)))

    # Intentionally pass an invalid configuration that raises in solve_generator
    from src.gui import main_window
    def broken_generator(*args, **kwargs):
        raise RuntimeError("Simulated solver generator failure")

    monkeypatch.setattr(main_window, "solve_generator", broken_generator)

    window.tab_controls._on_run_clicked()

    assert len(errors) == 1
    assert "Simulation Initialization Error" in errors[0][0]
    assert "Status: Error" in window.lbl_status.text()
    assert window.tab_controls.btn_run.isEnabled() is True


def test_results_frequency_and_time_synchronization(qtbot):
    """Verify Ticket B1 & B3: 1D and 2D frequency plots have identical X limits, and time plots default to [-2.5, 2.5] ps."""
    from src.gui.tab_results import TabResultsWidget
    results = TabResultsWidget()
    qtbot.addWidget(results)

    # Verify default colormap is turbo
    assert results.combo_cmap.currentText() == "turbo"

    # Verify default frequency x-axis bounds on both 1D and 2D widgets
    assert pytest.approx(results.spin_wl_min.value()) == 500.0
    assert pytest.approx(results.spin_wl_max.value()) == 1200.0
    freq_1d_range = results.plot_freq_1d.get_x_range()
    freq_2d_range = results.plot_freq_2d.get_x_range()
    assert pytest.approx(freq_1d_range[0]) == 500.0
    assert pytest.approx(freq_1d_range[1]) == 1200.0
    assert pytest.approx(freq_2d_range[0]) == 500.0
    assert pytest.approx(freq_2d_range[1]) == 1200.0

    # Verify default time domain view range [-2.5, 2.5] ps
    time_1d_range = results.plot_time_1d.get_x_range()
    time_2d_range = results.plot_time_2d.get_x_range()
    assert pytest.approx(time_1d_range[0]) == -2.5
    assert pytest.approx(time_1d_range[1]) == 2.5
    assert pytest.approx(time_2d_range[0]) == -2.5
    assert pytest.approx(time_2d_range[1]) == 2.5

    # Verify 1D Freq plot Y range: [-200.0, 10.0] dB
    freq_1d_y = results.plot_freq_1d.get_y_range()
    assert pytest.approx(freq_1d_y[0]) == -200.0
    assert pytest.approx(freq_1d_y[1]) == 10.0

    # Verify Colormap levels: (-40.0, 0.0) dB
    assert results.plot_freq_2d.colorbar.levels() == (-40.0, 0.0)
    assert results.plot_time_2d.colorbar.levels() == (-40.0, 0.0)


def test_spinbox_adjustments_synchronize_1d_and_2d(qtbot):
    """Verify Ticket B1 & B2: adjusting spinbox bounds updates 1D and 2D widgets simultaneously and interactive 2D updates."""
    from src.gui.tab_results import TabResultsWidget
    results = TabResultsWidget()
    qtbot.addWidget(results)

    # Adjust spinboxes to custom window [650, 1050] nm
    results.spin_wl_min.setValue(650.0)
    results.spin_wl_max.setValue(1050.0)

    # Verify both 1D and 2D widgets updated simultaneously
    assert pytest.approx(results.plot_freq_1d.get_x_range()) == (650.0, 1050.0)
    assert pytest.approx(results.plot_freq_2d.get_x_range()) == (650.0, 1050.0)

    # Click Hult Window button
    results.btn_hult_window.click()
    assert pytest.approx(results.spin_wl_min.value()) == 500.0
    assert pytest.approx(results.spin_wl_max.value()) == 1200.0
    assert pytest.approx(results.plot_freq_1d.get_x_range()) == (500.0, 1200.0)
    assert pytest.approx(results.plot_freq_2d.get_x_range()) == (500.0, 1200.0)

    # Test interactive 2D colormap update with simulated history
    N = 256
    t = np.linspace(-5e-12, 5e-12, N)
    omega = 2.0 * np.pi * np.fft.fftfreq(N, d=(t[1] - t[0]))
    a_t = np.exp(-0.5 * (t / 1e-12) ** 2).astype(np.complex128)
    a_w = np.fft.fft(a_t)
    s1 = SimulationState(step=0, z=0.0, power=1.0, h=0.01, t=t, omega=omega, a_t=a_t, a_w=a_w, rel_energy_err=0.0, rel_photon_err=0.0)
    s2 = SimulationState(step=1, z=0.05, power=1.0, h=0.01, t=t, omega=omega, a_t=a_t, a_w=a_w, rel_energy_err=0.0, rel_photon_err=0.0)
    
    results.prepare_for_simulation(s1, "RK4IP", center_wavelength=850e-9)
    results.render_full_simulation(s2, [s1, s2])

    # Interactively change wavelength window
    results.spin_wl_min.setValue(700.0)
    results.spin_wl_max.setValue(950.0)
    rect = results.plot_freq_2d.img_item.mapRectToParent(results.plot_freq_2d.img_item.boundingRect())
    assert pytest.approx(rect.left()) == 700.0
    assert pytest.approx(rect.right()) == 950.0
    assert pytest.approx(results.plot_freq_1d.get_x_range()) == (700.0, 950.0)
    assert pytest.approx(results.plot_freq_2d.get_x_range()) == (700.0, 950.0)


def test_raw_spectrum_rendering_no_osa_smoothing(qtbot):
    """Verify raw simulation spectrum is rendered directly without artificial OSA smoothing filters and with strict normalization."""
    from src.gui.tab_results import TabResultsWidget
    from src.gui.plots import spectrum_to_db
    results = TabResultsWidget()
    qtbot.addWidget(results)

    # Verify combo_osa has been removed from results toolbar
    assert not hasattr(results, "combo_osa")
    assert not hasattr(results, "_get_active_osa_res")

    # Setup state with structured spectrum
    N = 512
    t = np.linspace(-5e-12, 5e-12, N)
    omega = 2.0 * np.pi * np.fft.fftfreq(N, d=(t[1] - t[0]))
    # Pulse with modulation to produce fringes
    a_t = (np.exp(-0.5 * (t / 0.5e-12) ** 2) + 0.5 * np.exp(-0.5 * ((t - 1e-12) / 0.3e-12) ** 2)).astype(np.complex128)
    a_w = np.fft.fft(a_t)
    s1 = SimulationState(step=0, z=0.0, power=1.0, h=0.01, t=t, omega=omega, a_t=a_t, a_w=a_w, rel_energy_err=0.0, rel_photon_err=0.0)
    s2 = SimulationState(step=1, z=0.1, power=1.0, h=0.01, t=t, omega=omega, a_t=a_t, a_w=a_w, rel_energy_err=0.0, rel_photon_err=0.0)

    results.prepare_for_simulation(s1, "RK4IP", center_wavelength=850e-9)
    results.render_full_simulation(s2, [s1, s2])

    # Verify 1D curve matches raw spectrum_to_db directly without smoothing
    x_after, y_after = results.plot_freq_1d.curve_after.getData()
    raw_wl, raw_db = spectrum_to_db(s2.a_w, s2.omega, results.omega0)
    np.testing.assert_allclose(x_after, raw_wl)
    np.testing.assert_allclose(y_after, raw_db)

    # Verify normalization peak is exactly 0.0 dB
    assert pytest.approx(np.max(y_after), abs=1e-10) == 0.0

    # Verify default view ranges
    assert results.plot_freq_2d.colorbar.levels() == (-40.0, 0.0)
    assert results.plot_time_2d.colorbar.levels() == (-40.0, 0.0)
    y_min, y_max = results.plot_freq_1d.get_y_range()
    assert pytest.approx(y_min) == -200.0
    assert pytest.approx(y_max) == 10.0


def test_immediate_window_close_during_simulation_teardown(qtbot):
    """Verify cooperative teardown cleanly joins and destroys QThread on rapid close without dangling threads."""
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()

    # Trigger simulation start
    window.tab_controls._on_run_clicked()
    assert window.worker_thread is not None

    # Immediately close window while thread is starting or running
    window.close()
    qtbot.wait(100)

    assert window.worker_thread is None or not window.worker_thread.isRunning()
    assert window.worker is None or not window.worker.is_running


def test_cyberpunk_theme_and_header_badges(qtbot):
    """Verify Phase 4 Cyberpunk theme palette and Top Header diagnostic badges."""
    window = MainWindow()
    qtbot.addWidget(window)

    # Verify theme stylesheet contains Google Stitch palette
    qss = window.styleSheet()
    assert "#0f131d" in qss  # BG_DARK
    assert "#00f5ff" in qss  # CYAN_ACCENT
    assert "#ff4b89" in qss  # PINK_ACCENT
    assert "#703eda" in qss  # PURPLE_ACCENT

    # Verify Header Diagnostic Badges
    assert "CORE:" in window.lbl_badge_core.text()
    assert window.lbl_badge_state.text() == "STATE: IDLE"
    assert "dz:" in window.lbl_badge_dz.text()
    assert "N:" in window.lbl_badge_grid.text()
    assert "RATE:" in window.lbl_badge_rate.text()

    # Verify Top Header Control Buttons
    assert window.btn_top_run.text() == "▶ RUN SIMULATION"
    assert window.btn_top_pause.text() == "❚❚ PAUSE"
    assert window.btn_top_stop.text() == "⏹ STOP"
    assert window.btn_top_export.text() == "💾 EXPORT DATA"
    assert window.btn_top_run.isEnabled() is True
    assert window.btn_top_pause.isEnabled() is False
    assert window.btn_top_stop.isEnabled() is False


def test_kpi_summary_banner_calculation(qtbot):
    """Verify Phase 4 KPI Summary Banner correctly computes N, L_D, L_NL, and energy error."""
    from src.gui.kpi_banner import KpiBannerWidget
    from src.solver.config import PulseConfig, FiberConfig, DispersionConfig, SimulationState

    banner = KpiBannerWidget()
    qtbot.addWidget(banner)

    # 1. Soliton N=1 configuration: T0 = 1.0 ps, P0 = 16.4615 W, gamma = 1.3e-3 W^-1 m^-1, beta2 = -2.14e-26 s^2/m
    pulse = PulseConfig(shape="sech", t_fwhm=1.762747e-12, p_peak=16.4615, center_wavelength=1550e-9)
    disp = DispersionConfig.from_si(beta2=-2.14e-26)
    fiber = FiberConfig(length=100.0, gamma=1.3e-3, dispersion=disp)

    banner.update_from_configs(pulse, fiber)

    assert "N = 1.00" in banner.card_n.lbl_value.text()
    assert "Fundamental Soliton" in banner.card_n.lbl_detail.text()
    assert "46.73 m" in banner.card_scales.lbl_value.text()  # L_D = 1e-24 / 2.14e-26 ≈ 46.73 m
    assert "46.73 m" in banner.card_scales.lbl_value.text()  # L_NL = 1 / (1.3e-3 * 16.4615) ≈ 46.73 m

    # 2. Add simulation state with conservation error
    N = 256
    t = np.linspace(-5e-12, 5e-12, N)
    omega = 2.0 * np.pi * np.fft.fftfreq(N, d=(t[1] - t[0]))
    a_t = np.sqrt(16.4615) * (1.0 / np.cosh(t / 1e-12)).astype(np.complex128)
    a_w = np.fft.ifft(a_t)
    state = SimulationState(step=10, z=5.0, power=16.4615, h=0.001, t=t, omega=omega, a_t=a_t, a_w=a_w, rel_energy_err=1.23e-8, rel_photon_err=4.56e-8)

    banner.update_from_configs(pulse, fiber, state)
    assert "1.23e-08" in banner.card_err.lbl_value.text()
    assert "Excellent" in banner.card_err.lbl_detail.text()


def test_panel_a_linear_and_log_scale_toggle(qtbot):
    """Verify Phase 4 Panel A Linear [W] and Log [dB] scale toggle."""
    from src.gui.tab_results import TabResultsWidget
    results = TabResultsWidget()
    qtbot.addWidget(results)

    # Prepare dummy data
    N = 256
    t_ps = np.linspace(-5.0, 5.0, N)
    power_w = 100.0 * np.exp(-((t_ps / 1.0) ** 2))

    results.plot_time_1d.set_before_curve(t_ps, power_w)
    results.plot_time_1d.set_after_curve(t_ps, power_w * 0.8)

    # Initial mode: Linear
    assert results.plot_time_1d.scale_mode == "linear"
    assert "Intensity [W]" in results.plot_time_1d.plot_item.getAxis("left").labelText

    # Toggle to Log (dB)
    results.btn_scale_log.click()
    assert results.plot_time_1d.scale_mode == "log_db"
    assert "Intensity [dB]" in results.plot_time_1d.plot_item.getAxis("left").labelText
    _, y_data = results.plot_time_1d.curve_after.getData()
    assert pytest.approx(np.max(y_data), abs=0.1) == 0.0  # Normalized 0 dB peak

    # Toggle back to Linear
    results.btn_scale_linear.click()
    assert results.plot_time_1d.scale_mode == "linear"
    assert "Intensity [W]" in results.plot_time_1d.plot_item.getAxis("left").labelText


def test_panel_d_chirp_and_phase_reticle(qtbot):
    """Verify Phase 4 Panel D Chirp & Phase Reticle computes instantaneous chirp and phase."""
    from src.gui.reticle_plot import ChirpReticleWidget
    reticle = ChirpReticleWidget()
    qtbot.addWidget(reticle)

    N = 512
    t = np.linspace(-5e-12, 5e-12, N)
    t0 = 1e-12
    # Chirped pulse with known quadratic phase phi(t) = -0.5 * C * (t/t0)^2
    chirp_c = 2.0
    a_t = np.sqrt(100.0) * np.exp(-0.5 * (1.0 + 1j * chirp_c) * ((t / t0) ** 2))

    reticle.update_data(t, a_t)

    # Chirp curve data should exist
    x_c, y_c = reticle.curve_chirp.getData()
    assert len(x_c) == N
    # Peak instantaneous frequency chirp: delta_omega = - dphi/dt = C * t / t0^2 -> linear chirp slope
    assert reticle.h_line.isVisible() is True
    assert reticle.v_line.isVisible() is True


def test_soliton_peak_tracking_table(qtbot):
    """Verify Phase 4 Soliton Peak Tracking Table identifies multi-soliton components."""
    from src.gui.soliton_tracker import SolitonTrackerWidget
    from src.solver.config import SimulationState, PulseConfig, FiberConfig, DispersionConfig

    tracker = SolitonTrackerWidget()
    qtbot.addWidget(tracker)

    N = 1024
    t = np.linspace(-10e-12, 10e-12, N)
    omega = 2.0 * np.pi * np.fft.fftfreq(N, d=(t[1] - t[0]))

    # Two distinct solitons separated in time:
    # Soliton 1 at t = 0 ps (P = 50 kW, FWHM = 50 fs)
    # Soliton 2 at t = +2.5 ps (P = 15 kW, FWHM = 80 fs)
    p1 = np.sqrt(50000.0) / np.cosh(t / (50e-15 / 1.763))
    p2 = np.sqrt(15000.0) / np.cosh((t - 2.5e-12) / (80e-15 / 1.763))
    a_t = (p1 + p2).astype(np.complex128)
    a_w = np.fft.ifft(a_t)

    state = SimulationState(step=50, z=0.1, power=50000.0, h=0.001, t=t, omega=omega, a_t=a_t, a_w=a_w, rel_energy_err=1e-6, rel_photon_err=1e-6)
    pulse = PulseConfig(shape="sech", t_fwhm=50e-15, p_peak=50000.0, center_wavelength=850e-9)
    fiber = FiberConfig(length=0.1, gamma=45e-3, dispersion=DispersionConfig.from_si(beta2=-1.276e-26))

    tracker.update_from_state(state, pulse, fiber)

    # Must detect both soliton components
    assert tracker.table.rowCount() >= 2
    # Row 0: Soliton 1
    assert "Soliton" in tracker.table.item(0, 0).text()
    assert float(tracker.table.item(0, 4).text()) >= 40.0  # ~50 kW
    # Row 1: Soliton 2
    assert float(tracker.table.item(1, 4).text()) >= 10.0  # ~15 kW
    assert pytest.approx(float(tracker.table.item(1, 2).text()), abs=0.2) == 2.5  # delay ~2.5 ps

    # Test copy to clipboard
    tracker._copy_to_clipboard()
    assert tracker.btn_copy_table.text() == "✅ Copied!"


def test_propagation_depth_scrubber_and_animation(qtbot):
    """Verify Phase 4 Propagation Depth Scrubber and interactive slice updating."""
    from src.gui.tab_results import TabResultsWidget
    from src.solver.config import SimulationState

    results = TabResultsWidget()
    qtbot.addWidget(results)

    N = 256
    t = np.linspace(-5e-12, 5e-12, N)
    omega = 2.0 * np.pi * np.fft.fftfreq(N, d=(t[1] - t[0]))
    a_t = np.exp(-0.5 * (t / 1e-12) ** 2).astype(np.complex128)
    a_w = np.fft.fft(a_t)

    s0 = SimulationState(step=0, z=0.00, power=100.0, h=0.01, t=t, omega=omega, a_t=a_t, a_w=a_w, rel_energy_err=0.0, rel_photon_err=0.0)
    s1 = SimulationState(step=1, z=0.05, power=90.0, h=0.01, t=t, omega=omega, a_t=a_t * 0.95, a_w=a_w * 0.95, rel_energy_err=1e-6, rel_photon_err=1e-6)
    s2 = SimulationState(step=2, z=0.10, power=80.0, h=0.01, t=t, omega=omega, a_t=a_t * 0.90, a_w=a_w * 0.90, rel_energy_err=2e-6, rel_photon_err=2e-6)

    results.prepare_for_simulation(s0, "RK4IP", center_wavelength=850e-9)
    results.render_full_simulation(s2, [s0, s1, s2])

    assert results.slider_z.isEnabled() is True
    assert results.slider_z.maximum() == 2
    assert results.slider_z.value() == 2

    # Scrub to intermediate step z = 5 cm
    results.slider_z.setValue(1)
    assert "z = 5.00 cm" in results.lbl_scrub_depth.text()
    assert results.plot_freq_2d.z_line.isVisible() is True
    assert pytest.approx(results.plot_freq_2d.z_line.value(), abs=0.01) == 5.0

    # Step buttons
    results.btn_step_prev.click()
    assert results.slider_z.value() == 0
    results.btn_step_next.click()
    assert results.slider_z.value() == 1

    # Animation play toggle
    results.btn_play_anim.click()
    assert results.anim_timer.isActive() is True
    results.btn_play_anim.click()
    assert results.anim_timer.isActive() is False


def test_latex_pgfplots_generation(qtbot):
    """Verify Phase 4 LaTeX TikZ/PGFPlots export generates valid compilation code."""
    from src.gui.tab_results import TabResultsWidget
    from src.solver.config import SimulationState
    from PyQt6.QtWidgets import QApplication

    results = TabResultsWidget()
    qtbot.addWidget(results)

    N = 256
    t = np.linspace(-5e-12, 5e-12, N)
    omega = 2.0 * np.pi * np.fft.fftfreq(N, d=(t[1] - t[0]))
    a_t = np.exp(-0.5 * (t / 1e-12) ** 2).astype(np.complex128)
    a_w = np.fft.fft(a_t)

    s1 = SimulationState(step=0, z=0.0, power=1.0, h=0.01, t=t, omega=omega, a_t=a_t, a_w=a_w, rel_energy_err=0.0, rel_photon_err=0.0)
    results.prepare_for_simulation(s1, "RK4IP", center_wavelength=850e-9)
    results.render_full_simulation(s1, [s1])

    results._copy_pgfplots_snippet()
    clipboard_text = QApplication.clipboard().text()

    assert "\\begin{tikzpicture}" in clipboard_text
    assert "\\begin{axis}" in clipboard_text
    assert "\\addplot" in clipboard_text
    assert "Wavelength" in clipboard_text
    assert "\\end{axis}" in clipboard_text
    assert "\\end{tikzpicture}" in clipboard_text


def test_domain_view_selector_and_aspect_ratio_optimization(qtbot):
    """Verify Domain View Selector (Time, Frequency only, All removed) and clean 2-column portrait layout."""
    from src.gui.tab_results import TabResultsWidget
    from src.solver.config import SimulationState

    results = TabResultsWidget()
    qtbot.addWidget(results)
    results.show()

    # 1. Default state: 'freq' domain mode (loaded from config.json)
    assert results.domain_mode == "freq"
    assert hasattr(results, "btn_view_time")
    assert hasattr(results, "btn_view_freq")
    assert not hasattr(results, "btn_view_all")
    assert not hasattr(results, "box_all_layout")
    assert results.btn_view_freq.isChecked() is True
    assert results.btn_view_time.isChecked() is False

    # In FREQ DOMAIN: Spectral plots shown, Temporal plots hidden
    assert results.plot_time_2d.isHidden() is True
    assert results.plot_time_1d.isHidden() is True
    assert results.plot_freq_2d.isHidden() is False
    assert results.plot_freq_1d.isHidden() is False
    assert results.box_pulse_scale.isHidden() is True
    assert not hasattr(results, "plot_chirp_reticle")

    # Verify minimum height optimization (ensuring tall portrait stature)
    assert results.plot_time_2d.minimumHeight() >= 380
    assert results.plot_freq_2d.minimumHeight() >= 380
    assert results.plot_time_1d.minimumHeight() >= 340
    assert results.plot_freq_1d.minimumHeight() >= 340

    # 2. Switch to TIME DOMAIN mode
    results.btn_view_time.click()
    assert results.domain_mode == "time"
    assert results.btn_view_time.isChecked() is True
    assert results.btn_view_freq.isChecked() is False

    # In TIME DOMAIN: Spectral plots hidden, Temporal plots shown
    # Panel D is NOT in grid_layout (clean 2-column portrait layout, no overlap)
    assert results.plot_freq_2d.isHidden() is True
    assert results.plot_freq_1d.isHidden() is True
    assert results.plot_time_2d.isHidden() is False
    assert results.plot_time_1d.isHidden() is False
    assert not hasattr(results, "plot_chirp_reticle")
    assert not hasattr(results, "plot_chirp_reticle")
    assert results.box_pulse_scale.isHidden() is False

    # Check 2-column placement in grid_layout (exactly 2 portrait columns: col 0 and col 1)
    idx_t2d = results.grid_layout.indexOf(results.plot_time_2d)
    idx_t1d = results.grid_layout.indexOf(results.plot_time_1d)
    r_t2d, c_t2d, _, _ = results.grid_layout.getItemPosition(idx_t2d)
    r_t1d, c_t1d, _, _ = results.grid_layout.getItemPosition(idx_t1d)
    assert r_t2d == 0 and c_t2d == 0
    assert r_t1d == 0 and c_t1d == 1

    # 3. Switch back to FREQUENCY DOMAIN mode
    results.btn_view_freq.click()
    assert results.domain_mode == "freq"
    assert results.btn_view_freq.isChecked() is True
    assert results.btn_view_time.isChecked() is False

    assert results.plot_time_2d.isHidden() is True
    assert results.plot_time_1d.isHidden() is True
    assert results.plot_freq_2d.isHidden() is False
    assert results.plot_freq_1d.isHidden() is False
    assert results.box_pulse_scale.isHidden() is True

    # Check 2-column placement in grid_layout (side-by-side in row 0)
    idx_f2d = results.grid_layout.indexOf(results.plot_freq_2d)
    idx_f1d = results.grid_layout.indexOf(results.plot_freq_1d)
    r_f2d, c_f2d, _, _ = results.grid_layout.getItemPosition(idx_f2d)
    r_f1d, c_f1d, _, _ = results.grid_layout.getItemPosition(idx_f1d)
    assert r_f2d == 0 and c_f2d == 0
    assert r_f1d == 0 and c_f1d == 1


def test_collapsible_telemetry_and_diagnostics_drawers(qtbot):
    """Verify collapsible KPI telemetry and bottom diagnostics drawers starting minimized with active splitter."""
    from src.gui.tab_results import TabResultsWidget

    results = TabResultsWidget()
    qtbot.addWidget(results)
    results.show()

    # KPI Banner collapsible toggle
    assert results.kpi_banner.isVisible() is True
    assert "▾" in results.btn_toggle_kpi.text()

    results.btn_toggle_kpi.click()
    assert results.kpi_banner.isVisible() is False
    assert "▸" in results.btn_toggle_kpi.text()

    results.btn_toggle_kpi.click()
    assert results.kpi_banner.isVisible() is True
    assert "▾" in results.btn_toggle_kpi.text()

    # Bottom Diagnostics Drawer starts MINIMIZED / collapsed initially
    assert results.sub_tabs.isVisible() is False
    assert "▸" in results.btn_toggle_bottom.text()

    # Expand via toggle button
    results.btn_toggle_bottom.click()
    assert results.sub_tabs.isVisible() is True
    assert "▾" in results.btn_toggle_bottom.text()

    # Collapse via toggle button
    results.btn_toggle_bottom.click()
    assert results.sub_tabs.isVisible() is False
    assert "▸" in results.btn_toggle_bottom.text()

    # Test dynamic expansion via mouse size adjuster (QSplitter handle)
    results._on_splitter_moved(700, 1)
    results.v_splitter.setSizes([700, 200])
    results._on_splitter_moved(700, 1)
    assert results.sub_tabs.isVisible() is True
    assert "▾" in results.btn_toggle_bottom.text()


def test_simulation_workflow_under_domain_modes(qtbot):
    """Verify live rendering and scrubber interaction while switching between Time and Frequency domains."""
    from src.gui.tab_results import TabResultsWidget
    from src.solver.config import SimulationState

    results = TabResultsWidget()
    qtbot.addWidget(results)
    results.show()

    N = 256
    t = np.linspace(-5e-12, 5e-12, N)
    omega = 2.0 * np.pi * np.fft.fftfreq(N, d=(t[1] - t[0]))
    a_t = np.exp(-0.5 * (t / 1e-12) ** 2).astype(np.complex128)
    a_w = np.fft.fft(a_t)

    s0 = SimulationState(step=0, z=0.0, power=1.0, h=0.05, t=t, omega=omega, a_t=a_t, a_w=a_w, rel_energy_err=0.0, rel_photon_err=0.0)
    s1 = SimulationState(step=1, z=0.05, power=1.0, h=0.05, t=t, omega=omega, a_t=a_t * 0.9, a_w=a_w * 0.9, rel_energy_err=1e-5, rel_photon_err=1e-5)
    s2 = SimulationState(step=2, z=0.10, power=1.0, h=0.05, t=t, omega=omega, a_t=a_t * 0.8, a_w=a_w * 0.8, rel_energy_err=2e-5, rel_photon_err=2e-5)

    # 1. Start in TIME DOMAIN mode
    results.set_domain_mode("time")
    results.prepare_for_simulation(s0, "RK4IP", center_wavelength=1550e-9)
    results.update_live_state(s1)
    results.render_full_simulation(s2, [s0, s1, s2])

    assert results.slider_z.isEnabled() is True
    assert results.slider_z.value() == 2
    assert results.plot_time_1d.isHidden() is False
    assert results.plot_time_2d.isHidden() is False
    # Reticle updated without polluting main time domain canvas
    assert not hasattr(results, "plot_chirp_reticle")

    # Scrub in TIME mode
    results.slider_z.setValue(1)
    assert "z = 5.00 cm" in results.lbl_scrub_depth.text()

    # 2. Switch to FREQUENCY DOMAIN mode and scrub
    results.set_domain_mode("freq")
    assert results.plot_freq_1d.isHidden() is False
    assert results.plot_freq_2d.isHidden() is False
    assert results.plot_time_1d.isHidden() is True
    results.slider_z.setValue(0)
    assert "z = 0.00 cm" in results.lbl_scrub_depth.text()

    # 3. Switching with legacy 'all' gracefully defaults to freq
    results.set_domain_mode("all")
    assert results.domain_mode == "freq"
    assert results.plot_freq_1d.isHidden() is False
    results.slider_z.setValue(2)
    assert "z = 10.00 cm" in results.lbl_scrub_depth.text()


def test_config_json_integration_and_fallback(tmp_path):
    """Verify config.json loads correctly and corrupted/missing files fall back gracefully."""
    import json
    from src.gui.config_loader import load_gui_config, save_gui_config, DEFAULT_CONFIG
    from src.gui.tab_results import TabResultsWidget

    # 1. Test missing file fallback
    missing_path = tmp_path / "non_existent_config.json"
    cfg_missing = load_gui_config(missing_path)
    assert cfg_missing["window"]["width"] == DEFAULT_CONFIG["window"]["width"]
    assert cfg_missing["results_view"]["default_domain"] == "FREQUENCY DOMAIN"

    # 2. Test corrupted json fallback without crashing
    corrupt_path = tmp_path / "corrupt_config.json"
    corrupt_path.write_text("{ this is invalid json syntax ::: ", encoding="utf-8")
    cfg_corrupt = load_gui_config(corrupt_path)
    assert cfg_corrupt["window"]["width"] == DEFAULT_CONFIG["window"]["width"]
    assert cfg_corrupt["results_view"]["default_colormap"] == "turbo"

    # 3. Test valid custom configuration
    custom_path = tmp_path / "custom_config.json"
    custom_dict = {
        "window": {"width": 1600, "height": 1000},
        "results_view": {
            "default_domain": "TIME DOMAIN",
            "default_colormap": "inferno",
            "default_db_floor": -50.0,
            "v_splitter_sizes": [900, 60],
            "diagnostics_minimized": True,
        }
    }
    save_gui_config(custom_dict, custom_path)
    cfg_loaded = load_gui_config(custom_path)
    assert cfg_loaded["window"]["width"] == 1600
    assert cfg_loaded["results_view"]["default_domain"] == "TIME DOMAIN"
    assert cfg_loaded["results_view"]["default_colormap"] == "inferno"

    # Test TabResultsWidget applies custom config
    w = TabResultsWidget(config=cfg_loaded["results_view"])
    assert w.domain_mode == "time"
    assert w.default_colormap == "inferno"
    assert w.default_db_floor == -50.0
    assert w.v_splitter_sizes == [900, 60]
    assert w.sub_tabs.isVisible() is False





def test_time_domain_only_two_portrait_plots_log_toggle_and_draggable_splitter(qtbot):
    """Time Domain: waterfall + profile only, portrait; Panel D gone; splitter draggable from minimized."""
    from src.gui.tab_results import TabResultsWidget

    results = TabResultsWidget()
    qtbot.addWidget(results)
    results.resize(1200, 900)
    results.show()
    qtbot.waitExposed(results)

    # Panel D completely removed
    assert not hasattr(results, "plot_chirp_reticle")
    for i in range(results.sub_tabs.count()):
        assert "Panel D" not in results.sub_tabs.tabText(i)

    results.set_domain_mode("time")
    qtbot.wait(50)
    assert results.grid_layout.count() == 2
    assert results.plot_time_2d.isVisible() and results.plot_time_1d.isVisible()
    assert not results.plot_freq_2d.isVisible() and not results.plot_freq_1d.isVisible()
    for w in (results.plot_time_2d, results.plot_time_1d):
        assert w.height() > w.width()

    # Linear/Log toggle
    results.btn_scale_log.click()
    assert results.plot_time_1d.scale_mode == "log_db"
    results.btn_scale_linear.click()
    assert results.plot_time_1d.scale_mode == "linear"

    # Splitter: starts minimized, handle present and draggable
    sp = results.v_splitter
    sizes = sp.sizes()
    assert sizes[1] < sizes[0] * 0.2
    assert sp.handleWidth() > 0 and sp.handle(1).isEnabled()
    assert not sp.isCollapsible(0) and sp.isCollapsible(1)
    total = sum(sizes)
    sp.setSizes([total - 300, 300])
    assert sp.sizes()[1] >= 250
