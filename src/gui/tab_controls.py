"""Tab 1 Controls: Parameter Cards, Preset Selector, and Execution Controls.

Enforces strict scientific typography and physical units in brackets across all fields.
"""

from __future__ import annotations

import math
from typing import Optional, List
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QComboBox,
    QCheckBox, QPushButton, QGroupBox, QScrollArea, QFormLayout, QFileDialog
)

from src.solver.config import (
    PulseConfig, FiberConfig, DispersionConfig, SolverConfig,
    ps2_km_to_si, ps3_km_to_si, psk_km_to_si
)


class TabControlsWidget(QWidget):
    """Tab 1 parameter control panel with strict scientific units and presets."""

    run_requested = pyqtSignal(object, object, object, bool)  # (pulse, fiber, solver, display_live)
    pause_requested = pyqtSignal()
    resume_requested = pyqtSignal()
    abort_requested = pyqtSignal()
    simulation_type_changed = pyqtSignal(str)  # "spectrum_vs_distance" or "spectrum_vs_power"
    wavelength_changed = pyqtSignal(float)     # wavelength in meters

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(4, 4, 4, 4)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        layout = QVBoxLayout(container)

        # -------------------------------------------------------------
        # 1. Preset Selector Card
        # -------------------------------------------------------------
        preset_group = QGroupBox("Configuration Presets")
        preset_layout = QHBoxLayout(preset_group)
        self.combo_presets = QComboBox()
        self.combo_presets.addItems([
            "Johan Hult 2007 Benchmark (PCF SCG at 835 nm)",
            "Fundamental Soliton N=1 Invariant (SMF-28 at 1550 nm)",
            "Standard Telecom Pulse (SMF-28 at 1550 nm)",
            "Custom User Configuration",
        ])
        self.combo_presets.currentIndexChanged.connect(self._on_preset_changed)
        preset_layout.addWidget(QLabel("Preset:"))
        preset_layout.addWidget(self.combo_presets, 1)
        layout.addWidget(preset_group)

        # -------------------------------------------------------------
        # 2. Simulation Mode & Algorithm Card
        # -------------------------------------------------------------
        mode_group = QGroupBox("Simulation Mode & Split-Step Algorithm")
        mode_form = QFormLayout(mode_group)

        self.combo_sim_type = QComboBox()
        self.combo_sim_type.addItems(["Spectrum vs Distance", "Spectrum vs Power"])
        self.combo_sim_type.currentIndexChanged.connect(self._on_sim_type_changed)
        mode_form.addRow("Simulation Type:", self.combo_sim_type)

        self.combo_method = QComboBox()
        self.combo_method.addItems(["RK4IP", "S-SSFM", "SSFM"])
        mode_form.addRow("Split-Step Method:", self.combo_method)

        self.chk_adaptive = QCheckBox("Enable Local Error Adaptive Step Size")
        self.chk_adaptive.setChecked(True)
        mode_form.addRow("Step Control:", self.chk_adaptive)

        self.txt_init_step = QLineEdit("0.1")  # mm
        mode_form.addRow("Initial Step: h_init [mm]:", self.txt_init_step)

        self.txt_tolerance = QLineEdit("1e-5")
        mode_form.addRow("Error Tolerance: tol [-]:", self.txt_tolerance)

        layout.addWidget(mode_group)

        # -------------------------------------------------------------
        # 3. Input Pulse Configuration Card
        # -------------------------------------------------------------
        pulse_group = QGroupBox("Input Optical Pulse Parameters")
        pulse_form = QFormLayout(pulse_group)

        self.combo_pulse_shape = QComboBox()
        self.combo_pulse_shape.addItems(["Sech (Hyperbolic Secant)", "Gaussian", "Custom Array"])
        self.combo_pulse_shape.currentIndexChanged.connect(self._update_t0_display)
        pulse_form.addRow("Envelope Shape:", self.combo_pulse_shape)

        self.txt_fwhm = QLineEdit("50.0")  # fs
        self.txt_fwhm.textChanged.connect(self._update_t0_display)
        pulse_form.addRow("Duration: Pulse FWHM [fs]:", self.txt_fwhm)

        self.lbl_t0_info = QLabel("T₀ = 28.36 fs")
        self.lbl_t0_info.setStyleSheet("color: #888888; font-size: 9pt;")
        pulse_form.addRow("", self.lbl_t0_info)

        self.txt_peak_power = QLineEdit("10.0")  # kW
        pulse_form.addRow("Peak Power: P₀ [kW]:", self.txt_peak_power)

        # Power sweep fields (active only when Spectrum vs Power is chosen)
        self.txt_power_min = QLineEdit("0.1")  # kW
        self.txt_power_max = QLineEdit("15.0")  # kW
        self.txt_power_steps = QLineEdit("50")  # points
        pulse_form.addRow("Sweep Min: P_min [kW]:", self.txt_power_min)
        pulse_form.addRow("Sweep Max: P_max [kW]:", self.txt_power_max)
        pulse_form.addRow("Sweep Points: N_P [points]:", self.txt_power_steps)
        self._set_power_sweep_visible(False)

        self.txt_wavelength = QLineEdit("835.0")  # nm
        self.txt_wavelength.textChanged.connect(self._update_omega0_display)
        pulse_form.addRow("Wavelength: Carrier λ₀ [nm]:", self.txt_wavelength)

        self.lbl_omega0_info = QLabel("ω₀ = 2.257 × 10¹⁵ rad/s (f₀ = 359.03 THz)")
        self.lbl_omega0_info.setStyleSheet("color: #888888; font-size: 9pt;")
        pulse_form.addRow("", self.lbl_omega0_info)

        self.txt_chirp = QLineEdit("0.0")  # dimensionless
        pulse_form.addRow("Chirp Parameter: C [-]:", self.txt_chirp)

        layout.addWidget(pulse_group)

        # -------------------------------------------------------------
        # 4. Fiber & Dispersion Card
        # -------------------------------------------------------------
        fiber_group = QGroupBox("Fiber Properties & Dispersion Profile")
        fiber_form = QFormLayout(fiber_group)

        self.txt_length = QLineEdit("15.0")  # cm
        fiber_form.addRow("Length: Fiber Length L [cm]:", self.txt_length)

        self.txt_gamma = QLineEdit("110.0")  # W^-1 km^-1
        self.txt_gamma.setToolTip("1 W⁻¹·km⁻¹ = 10⁻³ W⁻¹·m⁻¹")
        fiber_form.addRow("Nonlinearity: Gamma γ [W⁻¹·km⁻¹]:", self.txt_gamma)

        self.txt_loss = QLineEdit("0.0")  # dB/km
        fiber_form.addRow("Loss: Linear Attenuation α [dB/km]:", self.txt_loss)

        self.chk_raman = QCheckBox("Enable Raman Scattering (f_R = 0.18, τ₁ = 12.2 fs, τ₂ = 32.0 fs)")
        self.chk_raman.setChecked(True)
        self.chk_raman.toggled.connect(self._check_raman_advisory)
        fiber_form.addRow("Raman Effect:", self.chk_raman)

        self.chk_shock = QCheckBox("Enable Self-Steepening Shock (1 + Ω/ω₀)")
        self.chk_shock.setChecked(True)
        fiber_form.addRow("Self-Steepening:", self.chk_shock)

        self.combo_disp_mode = QComboBox()
        self.combo_disp_mode.addItems(["Manual Input (β₂ through β₇)", "Import Dispersion File (.h5 / .csv)"])
        self.combo_disp_mode.currentIndexChanged.connect(self._on_disp_mode_changed)
        fiber_form.addRow("Dispersion Mode:", self.combo_disp_mode)

        # Manual beta inputs (beta2 to beta7)
        self.txt_beta2 = QLineEdit("-11.83")  # ps^2/km
        self.txt_beta3 = QLineEdit("0.081")   # ps^3/km
        self.txt_beta4 = QLineEdit("-0.000116") # ps^4/km
        self.txt_beta5 = QLineEdit("0.00000259")# ps^5/km
        self.txt_beta6 = QLineEdit("0.0000000538")# ps^6/km
        self.txt_beta7 = QLineEdit("0.0")     # ps^7/km

        fiber_form.addRow("β₂ [ps²/km]:", self.txt_beta2)
        fiber_form.addRow("β₃ [ps³/km]:", self.txt_beta3)
        fiber_form.addRow("β₄ [ps⁴/km]:", self.txt_beta4)
        fiber_form.addRow("β₅ [ps⁵/km]:", self.txt_beta5)
        fiber_form.addRow("β₆ [ps⁶/km]:", self.txt_beta6)
        fiber_form.addRow("β₇ [ps⁷/km]:", self.txt_beta7)

        # Import file display
        self.txt_import_path = QLineEdit("")
        self.txt_import_path.setReadOnly(True)
        self.txt_import_path.setPlaceholderText("Select file from right navigator or browse...")
        self.btn_browse_disp = QPushButton("Browse...")
        self.btn_browse_disp.clicked.connect(self._on_browse_file)
        import_row = QHBoxLayout()
        import_row.addWidget(self.txt_import_path)
        import_row.addWidget(self.btn_browse_disp)
        fiber_form.addRow("Active File:", import_row)
        self._set_manual_betas_visible(True)
        self._set_import_path_visible(False)

        layout.addWidget(fiber_group)

        # -------------------------------------------------------------
        # 5. Numerical Grid Card
        # -------------------------------------------------------------
        grid_group = QGroupBox("Discretization Grid")
        grid_form = QFormLayout(grid_group)

        self.combo_grid_n = QComboBox()
        self.combo_grid_n.addItems(["1024", "2048", "4096", "8192", "16384"])
        self.combo_grid_n.setCurrentText("8192")
        self.combo_grid_n.currentIndexChanged.connect(self._check_raman_advisory)
        grid_form.addRow("Grid Size: N [points]:", self.combo_grid_n)

        self.txt_time_window = QLineEdit("12.5")  # ps
        self.txt_time_window.textChanged.connect(self._check_raman_advisory)
        grid_form.addRow("Time Window: T_max [ps]:", self.txt_time_window)

        # Raman temporal sampling advisory readout
        self.lbl_raman_warning = QLabel("")
        self.lbl_raman_warning.setStyleSheet("color: #FFC107; font-size: 9pt; font-weight: bold;")
        self.lbl_raman_warning.setWordWrap(True)
        self.lbl_raman_warning.hide()
        grid_form.addRow("", self.lbl_raman_warning)

        layout.addWidget(grid_group)

        # -------------------------------------------------------------
        # 6. Execution Control Toolbar Card
        # -------------------------------------------------------------
        exec_group = QGroupBox("Simulation Execution & Streaming")
        exec_layout = QVBoxLayout(exec_group)

        self.chk_display_live = QCheckBox("Display as the simulation runs (Live Animation <= 60 FPS)")
        self.chk_display_live.setChecked(True)
        exec_layout.addWidget(self.chk_display_live)

        btn_row = QHBoxLayout()
        self.btn_run = QPushButton("▶ Run Simulation")
        self.btn_run.setStyleSheet("background-color: #2E7D32; color: white; font-weight: bold; padding: 10px; font-size: 11pt;")
        self.btn_run.clicked.connect(self._on_run_clicked)

        self._is_paused = False
        self.btn_pause = QPushButton("❚❚ Pause")
        self.btn_pause.setEnabled(False)
        self.btn_pause.setStyleSheet("background-color: #FFA000; color: white; font-weight: bold;")
        self.btn_pause.clicked.connect(self._on_pause_clicked)

        self.btn_abort = QPushButton("⏹ Abort")
        self.btn_abort.setEnabled(False)
        self.btn_abort.setStyleSheet("background-color: #D32F2F; color: white; font-weight: bold;")
        self.btn_abort.clicked.connect(self.abort_requested.emit)

        btn_row.addWidget(self.btn_run, 2)
        btn_row.addWidget(self.btn_pause, 1)
        btn_row.addWidget(self.btn_abort, 1)
        exec_layout.addLayout(btn_row)

        layout.addWidget(exec_group)

        scroll.setWidget(container)
        main_layout.addWidget(scroll)

        self._update_t0_display()
        self._update_omega0_display()
        self._check_raman_advisory()

    def set_active_import_file(self, file_path: str) -> None:
        """Called by FileNavigator when user selects a dispersion file."""
        self.combo_disp_mode.setCurrentIndex(1)  # Switch to import mode
        self.txt_import_path.setText(file_path)

    def _on_disp_mode_changed(self, index: int) -> None:
        is_manual = (index == 0)
        self._set_manual_betas_visible(is_manual)
        self._set_import_path_visible(not is_manual)

    def _set_manual_betas_visible(self, visible: bool) -> None:
        self.txt_beta2.setVisible(visible)
        self.txt_beta3.setVisible(visible)
        self.txt_beta4.setVisible(visible)
        self.txt_beta5.setVisible(visible)
        self.txt_beta6.setVisible(visible)
        self.txt_beta7.setVisible(visible)

    def _set_import_path_visible(self, visible: bool) -> None:
        self.txt_import_path.setVisible(visible)
        self.btn_browse_disp.setVisible(visible)

    def _on_browse_file(self) -> None:
        fpath, _ = QFileDialog.getOpenFileName(self, "Select Dispersion File", "", "Dispersion Files (*.h5 *.hdf5 *.csv)")
        if fpath:
            self.txt_import_path.setText(fpath)

    def _on_sim_type_changed(self, index: int) -> None:
        is_power = (index == 1)
        self._set_power_sweep_visible(is_power)
        mode_str = "spectrum_vs_power" if is_power else "spectrum_vs_distance"
        self.simulation_type_changed.emit(mode_str)

    def _set_power_sweep_visible(self, visible: bool) -> None:
        self.txt_power_min.setVisible(visible)
        self.txt_power_max.setVisible(visible)
        self.txt_power_steps.setVisible(visible)
        self.txt_peak_power.setVisible(not visible)

    def _on_preset_changed(self, index: int) -> None:
        if index == 0:
            # Hult 2007 Benchmark
            self.txt_fwhm.setText("50.0")
            self.txt_peak_power.setText("10.0")
            self.txt_wavelength.setText("835.0")
            self.txt_chirp.setText("0.0")
            self.txt_length.setText("15.0")
            self.txt_gamma.setText("110.0")
            self.txt_loss.setText("0.0")
            self.chk_raman.setChecked(True)
            self.chk_shock.setChecked(True)
            self.combo_disp_mode.setCurrentIndex(0)
            self.txt_beta2.setText("-11.83")
            self.txt_beta3.setText("0.081")
            self.txt_beta4.setText("-0.000116")
            self.txt_beta5.setText("0.00000259")
            self.txt_beta6.setText("0.0000000538")
            self.txt_beta7.setText("0.0")
            self.combo_grid_n.setCurrentText("8192")
            self.txt_time_window.setText("12.5")
            self.combo_method.setCurrentText("RK4IP")
        elif index == 1:
            # Soliton N=1 Invariant
            self.txt_fwhm.setText("1762.78")  # T0 = 1.0 ps -> FWHM = 1.763 ps
            self.txt_peak_power.setText("0.0164615")  # 16.46 W = 0.01646 kW
            self.txt_wavelength.setText("1550.0")
            self.txt_chirp.setText("0.0")
            self.txt_length.setText("36695.0")  # 366.95 m in cm
            self.txt_gamma.setText("1.3")      # W^-1 km^-1
            self.txt_loss.setText("0.0")
            self.chk_raman.setChecked(False)
            self.chk_shock.setChecked(False)
            self.combo_disp_mode.setCurrentIndex(0)
            self.txt_beta2.setText("-21.4")
            self.txt_beta3.setText("0.0")
            self.txt_beta4.setText("0.0")
            self.txt_beta5.setText("0.0")
            self.txt_beta6.setText("0.0")
            self.txt_beta7.setText("0.0")
            self.combo_grid_n.setCurrentText("1024")
            self.txt_time_window.setText("20.0")
            self.combo_method.setCurrentText("RK4IP")
        elif index == 2:
            # Standard Telecom Pulse (SMF-28 at 1550 nm)
            self.combo_pulse_shape.setCurrentIndex(1)  # Gaussian
            self.txt_fwhm.setText("10000.0")  # 10 ps
            self.txt_peak_power.setText("0.05")  # 50 W
            self.txt_wavelength.setText("1550.0")
            self.txt_chirp.setText("0.0")
            self.txt_length.setText("500000.0")  # 5 km in cm
            self.txt_gamma.setText("1.3")
            self.txt_loss.setText("0.2")
            self.chk_raman.setChecked(False)
            self.chk_shock.setChecked(False)
            self.combo_disp_mode.setCurrentIndex(0)
            self.txt_beta2.setText("-21.4")
            self.txt_beta3.setText("0.0")
            self.txt_beta4.setText("0.0")
            self.txt_beta5.setText("0.0")
            self.txt_beta6.setText("0.0")
            self.txt_beta7.setText("0.0")
            self.combo_grid_n.setCurrentText("2048")
            self.txt_time_window.setText("100.0")
            self.combo_method.setCurrentText("RK4IP")

        self._update_t0_display()
        self._update_omega0_display()
        self._check_raman_advisory()

    def _on_pause_clicked(self) -> None:
        if self._is_paused:
            self._is_paused = False
            self.btn_pause.setText("❚❚ Pause")
            self.btn_pause.setStyleSheet("background-color: #FFA000; color: white; font-weight: bold;")
            self.resume_requested.emit()
        else:
            self._is_paused = True
            self.btn_pause.setText("▶ Resume")
            self.btn_pause.setStyleSheet("background-color: #388E3C; color: white; font-weight: bold;")
            self.pause_requested.emit()

    def _update_t0_display(self) -> None:
        try:
            fwhm_fs = float(self.txt_fwhm.text())
            is_gauss = "Gaussian" in self.combo_pulse_shape.currentText()
            div = 2.0 * math.sqrt(math.log(2.0)) if is_gauss else 2.0 * math.log(1.0 + math.sqrt(2.0))
            t0_fs = fwhm_fs / div
            self.lbl_t0_info.setText(f"T₀ = {t0_fs:.2f} fs")
        except Exception:
            pass

    def _update_omega0_display(self) -> None:
        try:
            wl_nm = float(self.txt_wavelength.text())
            wl_m = max(wl_nm * 1e-9, 1e-12)
            c = 299792458.0
            omega0 = 2.0 * math.pi * c / wl_m
            f0_thz = (c / wl_m) / 1e12
            self.lbl_omega0_info.setText(f"ω₀ = {omega0:.3e} rad/s (f₀ = {f0_thz:.2f} THz)")
            self.wavelength_changed.emit(wl_m)
        except Exception:
            pass

    def _check_raman_advisory(self) -> None:
        """Inspect SolverConfig temporal sampling vs Raman Blow-Wood timescale."""
        if not self.chk_raman.isChecked():
            self.lbl_raman_warning.hide()
            return

        try:
            grid_n = int(self.combo_grid_n.currentText())
            t_max = float(self.txt_time_window.text()) * 1e-12
            solver_tmp = SolverConfig(n_points=grid_n, time_window=t_max)
            ok, msg = solver_tmp.check_raman_sampling()
            if not ok:
                self.lbl_raman_warning.setText(f"⚠️ Advisory: {msg}")
                self.lbl_raman_warning.show()
            else:
                self.lbl_raman_warning.hide()
        except Exception:
            self.lbl_raman_warning.hide()

    def _on_run_clicked(self) -> None:
        """Parse inputs into strongly typed configs and request run."""
        pulse_shape = "sech" if "Sech" in self.combo_pulse_shape.currentText() else "gaussian"
        t_fwhm = float(self.txt_fwhm.text()) * 1e-15
        p_peak = float(self.txt_peak_power.text()) * 1e3
        wl0 = float(self.txt_wavelength.text()) * 1e-9
        chirp = float(self.txt_chirp.text())

        pulse = PulseConfig(shape=pulse_shape, t_fwhm=t_fwhm, p_peak=p_peak, center_wavelength=wl0, chirp=chirp)

        length_m = float(self.txt_length.text()) * 1e-2  # cm to m
        gamma_si = float(self.txt_gamma.text()) * 1e-3   # W^-1 km^-1 to W^-1 m^-1
        loss_db = float(self.txt_loss.text())

        # Dispersion config
        if self.combo_disp_mode.currentIndex() == 0:
            betas = [
                ps2_km_to_si(float(self.txt_beta2.text())),
                ps3_km_to_si(float(self.txt_beta3.text())),
                psk_km_to_si(float(self.txt_beta4.text()), 4),
                psk_km_to_si(float(self.txt_beta5.text()), 5),
                psk_km_to_si(float(self.txt_beta6.text()), 6),
                psk_km_to_si(float(self.txt_beta7.text()), 7),
            ]
            disp = DispersionConfig(mode="manual", betas=betas)
        else:
            disp = DispersionConfig(mode="import", import_path=self.txt_import_path.text())

        raman_fr = 0.18 if self.chk_raman.isChecked() else 0.0
        fiber = FiberConfig(
            length=length_m,
            gamma=gamma_si,
            loss_alpha_db=loss_db,
            dispersion=disp,
            raman_fr=raman_fr,
        )

        sim_type = "spectrum_vs_power" if self.combo_sim_type.currentIndex() == 1 else "spectrum_vs_distance"
        method = self.combo_method.currentText()
        grid_n = int(self.combo_grid_n.currentText())
        t_max = float(self.txt_time_window.text()) * 1e-12
        adaptive = self.chk_adaptive.isChecked()
        h_init = float(self.txt_init_step.text()) * 1e-3  # mm to m
        tol = float(self.txt_tolerance.text())

        # Bound intermediate record frames to 400 to prevent multi-GB memory exhaustion
        z_records = 400 if sim_type == "spectrum_vs_distance" else None

        solver = SolverConfig(
            simulation_type=sim_type,
            method=method,
            n_points=grid_n,
            time_window=t_max,
            adaptive_step=adaptive,
            initial_step=h_init,
            tolerance=tol,
            z_records=z_records,
            power_min=float(self.txt_power_min.text()) * 1e3,
            power_max=float(self.txt_power_max.text()) * 1e3,
            power_steps=int(self.txt_power_steps.text()),
        )

        display_live = self.chk_display_live.isChecked()
        self.btn_run.setEnabled(False)
        self.btn_pause.setEnabled(True)
        self.btn_abort.setEnabled(True)

        self.run_requested.emit(pulse, fiber, solver, display_live)

    def set_running_state(self, running: bool) -> None:
        self.btn_run.setEnabled(not running)
        self.btn_pause.setEnabled(running)
        self.btn_abort.setEnabled(running)
        self._is_paused = False
        self.btn_pause.setText("❚❚ Pause")
        self.btn_pause.setStyleSheet("background-color: #FFA000; color: white; font-weight: bold;")
