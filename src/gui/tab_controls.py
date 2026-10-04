"""Tab 1 Controls: Parameter Cards, Preset Selector, and Execution Controls.

Enforces strict scientific typography and physical units in brackets across all fields.
"""

from __future__ import annotations

import os
import math
from typing import Optional, List
import numpy as np
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QComboBox,
    QCheckBox, QPushButton, QGroupBox, QScrollArea, QFormLayout, QFileDialog, QStackedWidget,
    QMessageBox, QDoubleSpinBox, QDialog, QPlainTextEdit, QDialogButtonBox
)

from src.solver.config import (
    PulseConfig, FiberConfig, DispersionConfig, SolverConfig,
    ps2_km_to_si, ps3_km_to_si, psk_km_to_si
)


class ChirpSpinBox(QDoubleSpinBox):
    """Scientific chirp factor spinbox supporting dimensionless C in [-20.0, 20.0]."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setRange(-50.0, 50.0)
        self.setSingleStep(0.1)
        self.setDecimals(2)
        self.setValue(0.0)
        self.setToolTip(
            "Dimensionless linear frequency chirp parameter C in exp(-i C t² / (2 T₀²)).\n"
            "• C = 0.0: Transform-limited pulse (default)\n"
            "• Realistic ultrafast laser range: [-20.0, +20.0]\n"
            "• Up-chirp (C > 0): frequencies increase with time (red leading, blue trailing)\n"
            "• Down-chirp (C < 0): frequencies decrease with time (blue leading, red trailing)\n"
            "• Physical chirp rate: df/dt = -C / (2π T₀²)"
        )

    def text(self) -> str:
        return f"{self.value():.4g}"

    def setText(self, val: str) -> None:
        try:
            self.setValue(float(val))
        except (ValueError, TypeError):
            pass


class CustomPulseDialog(QDialog):
    """Dialog for manual entry or pasting of custom pulse array data."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Enter Custom Pulse Array Data")
        self.resize(480, 320)
        layout = QVBoxLayout(self)

        lbl = QLabel(
            "Paste or enter pulse numeric samples (field amplitude or intensity).\n"
            "Format: One value per line, or space/comma separated values."
        )
        lbl.setStyleSheet("color: #CCCCCC; font-size: 9pt;")
        layout.addWidget(lbl)

        self.edit = QPlainTextEdit()
        self.edit.setPlaceholderText("e.g. 0.0, 0.1, 0.5, 1.0, 0.5, 0.1, 0.0 ...")
        layout.addWidget(self.edit)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def get_data(self) -> Optional[np.ndarray]:
        text = self.edit.toPlainText().strip()
        if not text:
            return None
        text_clean = text.replace(",", " ")
        try:
            vals = [complex(s) if ("j" in s or "J" in s) else float(s) for s in text_clean.split()]
            if len(vals) == 0:
                return None
            return np.array(vals)
        except Exception:
            return None


class ManualDispersionWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QFormLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.txt_beta2 = QLineEdit("-1.276")
        self.txt_beta3 = QLineEdit("8.119")
        self.txt_beta4 = QLineEdit("-1.321")
        self.txt_beta5 = QLineEdit("3.032")
        self.txt_beta6 = QLineEdit("-4.196")
        self.txt_beta7 = QLineEdit("2.570")

        layout.addRow("β₂ [ps² m⁻¹] × 10⁻²:", self.txt_beta2)
        layout.addRow("β₃ [ps³ m⁻¹] × 10⁻⁵:", self.txt_beta3)
        layout.addRow("β₄ [ps⁴ m⁻¹] × 10⁻⁷:", self.txt_beta4)
        layout.addRow("β₅ [ps⁵ m⁻¹] × 10⁻¹⁰:", self.txt_beta5)
        layout.addRow("β₆ [ps⁶ m⁻¹] × 10⁻¹³:", self.txt_beta6)
        layout.addRow("β₇ [ps⁷ m⁻¹] × 10⁻¹⁶:", self.txt_beta7)

    def get_betas_si(self):
        from src.solver.config import DispersionConfig
        try:
            b2 = DispersionConfig.ps_m_to_si(2, float(self.txt_beta2.text()) * 10**-2)
            b3 = DispersionConfig.ps_m_to_si(3, float(self.txt_beta3.text()) * 10**-5)
            b4 = DispersionConfig.ps_m_to_si(4, float(self.txt_beta4.text()) * 10**-7)
            b5 = DispersionConfig.ps_m_to_si(5, float(self.txt_beta5.text()) * 10**-10)
            b6 = DispersionConfig.ps_m_to_si(6, float(self.txt_beta6.text()) * 10**-13)
            b7 = DispersionConfig.ps_m_to_si(7, float(self.txt_beta7.text()) * 10**-16)
            return [b2, b3, b4, b5, b6, b7]
        except ValueError:
            return [0.0] * 6

    def set_betas_si(self, betas_si: list[float]) -> None:
        """Populate the 6 manual input fields with physical SI beta coefficients."""
        from src.solver.config import DispersionConfig
        exponents = {2: -2, 3: -5, 4: -7, 5: -10, 6: -13, 7: -16}
        boxes = [self.txt_beta2, self.txt_beta3, self.txt_beta4, self.txt_beta5, self.txt_beta6, self.txt_beta7]
        for idx, (k, exp) in enumerate(exponents.items()):
            if idx < len(betas_si):
                b_si = float(betas_si[idx])
                val_ps_m = DispersionConfig.si_to_ps_m(k, b_si)
                mantissa = val_ps_m / (10 ** exp)
                boxes[idx].setText(f"{mantissa:.4f}")


class TabControlsWidget(QWidget):
    """Tab 1 parameter control panel with strict scientific units and presets."""

    run_requested = pyqtSignal(object, object, object, bool)  # (pulse, fiber, solver, display_live)
    pause_requested = pyqtSignal()
    resume_requested = pyqtSignal()
    abort_requested = pyqtSignal()
    simulation_type_changed = pyqtSignal(str)  # "spectrum_vs_distance" or "spectrum_vs_power"
    wavelength_changed = pyqtSignal(float)
    dispersion_mode_changed = pyqtSignal(int)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        self.manual_disp = None
        self.file_nav = None
        self.active_import_file: str = ""
        self._custom_field: Optional[np.ndarray] = None
        self._custom_time: Optional[np.ndarray] = None
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
            "Johan Hult 2007 Benchmark (PCF SCG at 850 nm)",
            "Fundamental Soliton N=1 Invariant (SMF-28 at 1550 nm)",
            "Standard Telecom Pulse (SMF-28 at 1550 nm)",
            "Custom User Configuration",
        ])
        self.combo_presets.currentIndexChanged.connect(self._on_preset_changed)
        preset_layout.addWidget(QLabel("Preset:"))
        preset_layout.addWidget(self.combo_presets, 1)
        
        btn_layout = QHBoxLayout()
        self.btn_import_config = QPushButton("📂 Import Config")
        self.btn_export_config = QPushButton("💾 Export Config")
        btn_layout.addWidget(self.btn_import_config)
        btn_layout.addWidget(self.btn_export_config)
        preset_layout.addLayout(btn_layout)
        
        self.btn_import_config.clicked.connect(self._on_import_config)
        self.btn_export_config.clicked.connect(self._on_export_config)

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
        self.combo_pulse_shape.addItems([
            "Sech (Hyperbolic Secant)",
            "Gaussian",
            "Lorentzian",
            "Custom Array",
        ])
        self.combo_pulse_shape.currentIndexChanged.connect(self._on_pulse_shape_changed)
        pulse_form.addRow("Envelope Shape:", self.combo_pulse_shape)

        # Custom Pulse Container (visible when Custom Array is chosen)
        self.custom_pulse_box = QWidget()
        custom_layout = QVBoxLayout(self.custom_pulse_box)
        custom_layout.setContentsMargins(0, 4, 0, 4)

        custom_btn_row = QHBoxLayout()
        self.btn_load_pulse_file = QPushButton("📁 Load Pulse File (.npy, .csv, .txt)")
        self.btn_load_pulse_file.clicked.connect(self._on_load_custom_pulse_file)
        self.btn_enter_pulse_data = QPushButton("✏️ Enter Array Data...")
        self.btn_enter_pulse_data.clicked.connect(self._on_enter_custom_pulse_data)
        custom_btn_row.addWidget(self.btn_load_pulse_file)
        custom_btn_row.addWidget(self.btn_enter_pulse_data)
        custom_layout.addLayout(custom_btn_row)

        self.lbl_custom_pulse_status = QLabel("No custom array loaded. Click above to load or enter data.")
        self.lbl_custom_pulse_status.setStyleSheet("color: #ffab00; font-size: 9pt;")
        custom_layout.addWidget(self.lbl_custom_pulse_status)
        pulse_form.addRow("Custom Pulse:", self.custom_pulse_box)
        self.custom_pulse_box.hide()

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

        self.txt_wavelength = QLineEdit("850.0")  # nm
        self.txt_wavelength.textChanged.connect(self._update_omega0_display)
        pulse_form.addRow("Wavelength: Carrier λ₀ [nm]:", self.txt_wavelength)

        self.lbl_omega0_info = QLabel("ω₀ = 2.218 × 10¹⁵ rad/s (f₀ = 352.69 THz)")
        self.lbl_omega0_info.setStyleSheet("color: #888888; font-size: 9pt;")
        pulse_form.addRow("", self.lbl_omega0_info)

        self.txt_chirp = ChirpSpinBox()
        self.txt_chirp.valueChanged.connect(self._update_chirp_display)
        pulse_form.addRow("Chirp Parameter: C [-]:", self.txt_chirp)

        self.lbl_chirp_info = QLabel("C = 0.00 (Transform-limited)")
        self.lbl_chirp_info.setStyleSheet("color: #888888; font-size: 9pt;")
        pulse_form.addRow("", self.lbl_chirp_info)

        layout.addWidget(pulse_group)

        # -------------------------------------------------------------
        # 4. Fiber & Dispersion Card
        # -------------------------------------------------------------
        fiber_group = QGroupBox("Fiber Properties & Dispersion Profile")
        fiber_form = QFormLayout(fiber_group)

        self.txt_length = QLineEdit("10.0")  # cm
        fiber_form.addRow("Length: Fiber Length L [cm]:", self.txt_length)

        self.txt_gamma = QLineEdit("45.0")  # W^-1 km^-1
        self.txt_gamma.setToolTip("1 W⁻¹·km⁻¹ = 10⁻³ W⁻¹·m⁻¹")
        fiber_form.addRow("Nonlinearity: Gamma γ [W⁻¹·km⁻¹]:", self.txt_gamma)

        self.chk_auto_gamma = QCheckBox("Auto-tune γ from imported A_eff")
        self.chk_auto_gamma.setChecked(True)
        self.chk_auto_gamma.toggled.connect(self._on_auto_gamma_toggled)
        fiber_form.addRow("", self.chk_auto_gamma)

        self.lbl_gamma_aeff_badge = QLabel("")
        self.lbl_gamma_aeff_badge.setStyleSheet("color: #00FFCC; font-size: 8.5pt; font-style: italic;")
        self.lbl_gamma_aeff_badge.hide()
        fiber_form.addRow("", self.lbl_gamma_aeff_badge)

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

        layout.addWidget(fiber_group)

        # -------------------------------------------------------------
        # 5. Numerical Grid Card
        # -------------------------------------------------------------
        grid_group = QGroupBox("Discretization Grid")
        grid_form = QFormLayout(grid_group)

        self.combo_grid_n = QComboBox()
        self.combo_grid_n.addItems(["1024", "2048", "4096", "8192", "16384", "32768", "65536", "131072", "Auto"])
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
        self.active_import_file = file_path
        if self.file_nav is not None:
            self.file_nav.active_file_path = file_path
            if hasattr(self.file_nav, "txt_import_path") and self.file_nav.txt_import_path is not None:
                self.file_nav.txt_import_path.setText(file_path)
            if hasattr(self.file_nav, "_reevaluate_aeff"):
                self.file_nav._reevaluate_aeff()
        elif self.txt_import_path is not None:
            self.txt_import_path.setText(file_path)

    def _on_auto_gamma_toggled(self, checked: bool) -> None:
        if checked and hasattr(self, "_last_aeff_gamma") and self._last_aeff_gamma is not None:
            self._apply_auto_gamma(self._last_aeff_m2, self._last_aeff_gamma)
        elif not checked:
            self.lbl_gamma_aeff_badge.hide()

    def _on_aeff_evaluated(self, a_eff_m2: float, gamma_w_km: float) -> None:
        self._last_aeff_m2 = a_eff_m2
        self._last_aeff_gamma = gamma_w_km
        if self.chk_auto_gamma.isChecked():
            self._apply_auto_gamma(a_eff_m2, gamma_w_km)

    def _apply_auto_gamma(self, a_eff_m2: float, gamma_w_km: float) -> None:
        self.txt_gamma.blockSignals(True)
        self.txt_gamma.setText(f"{gamma_w_km:.3f}")
        self.txt_gamma.blockSignals(False)
        aeff_um2 = a_eff_m2 * 1e12
        self.lbl_gamma_aeff_badge.setText(
            f"⚡ Auto-tuned: A_eff = {aeff_um2:.2f} µm² → γ = {gamma_w_km:.2f} W⁻¹·km⁻¹"
        )
        self.lbl_gamma_aeff_badge.show()

    def _on_disp_mode_changed(self, index: int) -> None:
        self.dispersion_mode_changed.emit(index)

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
            self.txt_wavelength.setText("850.0")
            self.txt_chirp.setText("0.0")
            self.txt_length.setText("10.0")
            self.txt_gamma.setText("45.0")
            self.txt_loss.setText("0.0")
            self.chk_raman.setChecked(True)
            self.chk_shock.setChecked(True)
            self.combo_disp_mode.setCurrentIndex(0)
            if self.manual_disp:
                self.manual_disp.txt_beta2.setText("-1.276")
                self.manual_disp.txt_beta3.setText("8.119")
                self.manual_disp.txt_beta4.setText("-1.321")
                self.manual_disp.txt_beta5.setText("3.032")
                self.manual_disp.txt_beta6.setText("-4.196")
                self.manual_disp.txt_beta7.setText("2.570")
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
            if self.manual_disp: self.manual_disp.txt_beta2.setText("-2.14")
            if self.manual_disp: self.manual_disp.txt_beta3.setText("0.0")
            if self.manual_disp: self.manual_disp.txt_beta4.setText("0.0")
            if self.manual_disp: self.manual_disp.txt_beta5.setText("0.0")
            if self.manual_disp: self.manual_disp.txt_beta6.setText("0.0")
            if self.manual_disp: self.manual_disp.txt_beta7.setText("0.0")
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
            if self.manual_disp: self.manual_disp.txt_beta2.setText("-2.14")
            if self.manual_disp: self.manual_disp.txt_beta3.setText("0.0")
            if self.manual_disp: self.manual_disp.txt_beta4.setText("0.0")
            if self.manual_disp: self.manual_disp.txt_beta5.setText("0.0")
            if self.manual_disp: self.manual_disp.txt_beta6.setText("0.0")
            if self.manual_disp: self.manual_disp.txt_beta7.setText("0.0")
            self.combo_grid_n.setCurrentText("2048")
            self.txt_time_window.setText("100.0")
            self.combo_method.setCurrentText("RK4IP")

        self.lbl_gamma_aeff_badge.hide()
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

    def _on_pulse_shape_changed(self) -> None:
        txt = self.combo_pulse_shape.currentText()
        is_custom = "Custom" in txt
        self.custom_pulse_box.setVisible(is_custom)
        self.txt_fwhm.setEnabled(not is_custom)
        self._update_t0_display()
        self._update_chirp_display()

    def _on_load_custom_pulse_file(self) -> None:
        fpath, _ = QFileDialog.getOpenFileName(
            self, "Load Custom Pulse Array", "", "Pulse Files (*.npy *.csv *.txt *.dat);;All Files (*)"
        )
        if not fpath:
            return

        try:
            suffix = os.path.splitext(fpath)[1].lower()
            if suffix == ".npy":
                data = np.load(fpath)
            else:
                for delim in (",", None, "\t", ";"):
                    try:
                        data = np.loadtxt(fpath, delimiter=delim)
                        if data.size > 0:
                            break
                    except Exception:
                        continue
                else:
                    raise ValueError("Could not parse numeric table from file.")

            if data.ndim == 1:
                self._custom_field = np.asarray(data, dtype=complex)
                self._custom_time = None
            elif data.ndim == 2 and data.shape[1] >= 2:
                t_col = data[:, 0]
                f_col = data[:, 1]
                max_t = np.max(np.abs(t_col))
                if max_t > 10.0:
                    t_s = t_col * 1e-15
                elif max_t > 1e-6:
                    t_s = t_col * 1e-12
                else:
                    t_s = t_col
                self._custom_time = t_s
                self._custom_field = np.asarray(f_col, dtype=complex)
            else:
                self._custom_field = np.asarray(data.flatten(), dtype=complex)
                self._custom_time = None

            n_pts = len(self._custom_field)
            peak_w = float(np.max(np.abs(self._custom_field) ** 2))
            fname = os.path.basename(fpath)
            self.lbl_custom_pulse_status.setText(
                f"✓ Loaded {n_pts} pts from {fname} (Peak Power: {peak_w:.2f} W)"
            )
            self.lbl_custom_pulse_status.setStyleSheet("color: #00e676; font-size: 9pt; font-weight: bold;")
            self.txt_peak_power.setText(f"{peak_w * 1e-3:.4g}")
        except Exception as exc:
            QMessageBox.critical(self, "Load Error", f"Failed to load pulse file: {exc}")

    def _on_enter_custom_pulse_data(self) -> None:
        dlg = CustomPulseDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            arr = dlg.get_data()
            if arr is not None and len(arr) > 0:
                self._custom_field = np.asarray(arr, dtype=complex)
                self._custom_time = None
                n_pts = len(self._custom_field)
                peak_w = float(np.max(np.abs(self._custom_field) ** 2))
                self.lbl_custom_pulse_status.setText(
                    f"✓ Custom array: {n_pts} samples entered (Peak Power: {peak_w:.2f} W)"
                )
                self.lbl_custom_pulse_status.setStyleSheet("color: #00e676; font-size: 9pt; font-weight: bold;")
                self.txt_peak_power.setText(f"{peak_w * 1e-3:.4g}")
            else:
                QMessageBox.warning(self, "Invalid Data", "Could not parse numbers from input text.")

    def _update_t0_display(self) -> None:
        try:
            fwhm_fs = float(self.txt_fwhm.text())
            txt = self.combo_pulse_shape.currentText()
            if "Gaussian" in txt:
                div = 2.0 * math.sqrt(math.log(2.0))
            elif "Lorentzian" in txt:
                div = 2.0 * math.sqrt(math.sqrt(2.0) - 1.0)
            elif "Custom" in txt:
                self.lbl_t0_info.setText("T₀ defined by custom array")
                return
            else:
                div = 2.0 * math.log(1.0 + math.sqrt(2.0))
            t0_fs = fwhm_fs / div
            self.lbl_t0_info.setText(f"T₀ = {t0_fs:.2f} fs")
        except Exception:
            pass

    def _update_chirp_display(self) -> None:
        c_val = self.txt_chirp.value()
        try:
            fwhm_fs = float(self.txt_fwhm.text())
            txt = self.combo_pulse_shape.currentText()
            if "Gaussian" in txt:
                div = 2.0 * math.sqrt(math.log(2.0))
            elif "Lorentzian" in txt:
                div = 2.0 * math.sqrt(math.sqrt(2.0) - 1.0)
            else:
                div = 2.0 * math.log(1.0 + math.sqrt(2.0))
            t0_s = (fwhm_fs * 1e-15) / div
            # Linear chirp rate df/dt = -C / (2 * pi * T0^2) in THz/ps = 10^12 / 10^-12 = 10^24 s^-2
            chirp_rate_thz_ps = - c_val / (2.0 * math.pi * (t0_s ** 2)) / 1e24
        except Exception:
            chirp_rate_thz_ps = 0.0

        if abs(c_val) < 1e-6:
            self.lbl_chirp_info.setText("C = 0.00 (Transform-limited)")
        elif c_val > 0:
            self.lbl_chirp_info.setText(f"Up-chirp: C = +{c_val:.2f} (df/dt ≈ {chirp_rate_thz_ps:+.2f} THz/ps)")
        else:
            self.lbl_chirp_info.setText(f"Down-chirp: C = {c_val:.2f} (df/dt ≈ {chirp_rate_thz_ps:+.2f} THz/ps)")

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
            g_text = self.combo_grid_n.currentText()
            t_max = float(self.txt_time_window.text()) * 1e-12
            if g_text == "Auto":
                from src.solver.config import compute_auto_grid_size
                fwhm_fs = float(self.txt_fwhm.text())
                if "Gaussian" in self.combo_pulse_shape.currentText():
                    div = 2.0 * math.sqrt(math.log(2.0))
                elif "Lorentzian" in self.combo_pulse_shape.currentText():
                    div = 2.0 * math.sqrt(math.sqrt(2.0) - 1.0)
                else:
                    div = 2.0 * math.log(1.0 + math.sqrt(2.0))
                t0_s = (fwhm_fs * 1e-15) / div
                grid_n = compute_auto_grid_size(t_max, t0_s, self.chk_raman.isChecked())
            else:
                grid_n = int(g_text)
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
        try:
            txt_shape = self.combo_pulse_shape.currentText()
            if "Lorentzian" in txt_shape:
                pulse_shape = "lorentzian"
            elif "Gaussian" in txt_shape:
                pulse_shape = "gaussian"
            elif "Custom" in txt_shape:
                pulse_shape = "custom"
            else:
                pulse_shape = "sech"

            t_fwhm = float(self.txt_fwhm.text()) * 1e-15
            p_peak = float(self.txt_peak_power.text()) * 1e3
            wl0 = float(self.txt_wavelength.text()) * 1e-9
            chirp = float(self.txt_chirp.text())

            if pulse_shape == "custom":
                if self._custom_field is None:
                    QMessageBox.warning(
                        self,
                        "Missing Custom Pulse Data",
                        "Please load a pulse file (.npy, .csv, .txt) or enter custom pulse array data.",
                    )
                    return
                pulse = PulseConfig(
                    shape="custom",
                    t_fwhm=t_fwhm,
                    p_peak=p_peak,
                    center_wavelength=wl0,
                    chirp=chirp,
                    custom_field=self._custom_field,
                    custom_time=self._custom_time,
                )
            else:
                pulse = PulseConfig(shape=pulse_shape, t_fwhm=t_fwhm, p_peak=p_peak, center_wavelength=wl0, chirp=chirp)

            length_m = float(self.txt_length.text()) * 1e-2  # cm to m
            gamma_si = float(self.txt_gamma.text()) * 1e-3   # W^-1 km^-1 to W^-1 m^-1
            loss_db = float(self.txt_loss.text())

            # Dispersion config
            if self.combo_disp_mode.currentIndex() == 0:
                betas = self.manual_disp.get_betas_si() if self.manual_disp else [0.0]*6
                disp = DispersionConfig(mode="manual", betas=betas)
            else:
                import_path = ""
                if self.file_nav and hasattr(self.file_nav, 'active_file_path') and self.file_nav.active_file_path:
                    import_path = self.file_nav.active_file_path
                elif getattr(self, "active_import_file", None):
                    import_path = self.active_import_file

                if not import_path or not os.path.exists(import_path):
                    QMessageBox.warning(
                        self,
                        "Missing Dispersion File",
                        "Please select a valid dispersion file (.h5 / .csv) before running in import mode.",
                    )
                    return

                h5_group = self.file_nav.combo_group.currentText() if hasattr(self.file_nav, 'combo_group') else None
                h5_dataset_x = self.file_nav.combo_x.currentText() if hasattr(self.file_nav, 'combo_x') else None
                h5_dataset_y = self.file_nav.combo_y.currentText() if hasattr(self.file_nav, 'combo_y') else None
                disp = DispersionConfig(mode="import", import_path=import_path,
                                        h5_group=h5_group, h5_dataset_x=h5_dataset_x, h5_dataset_y=h5_dataset_y)

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
            g_text = self.combo_grid_n.currentText()
            t_max = float(self.txt_time_window.text()) * 1e-12
            if g_text == "Auto":
                from src.solver.config import compute_auto_grid_size
                fwhm_fs = float(self.txt_fwhm.text())
                is_gauss = "Gaussian" in self.combo_pulse_shape.currentText()
                div = 2.0 * math.sqrt(math.log(2.0)) if is_gauss else 2.0 * math.log(1.0 + math.sqrt(2.0))
                t0_s = (fwhm_fs * 1e-15) / div
                grid_n = compute_auto_grid_size(t_max, t0_s, self.chk_raman.isChecked())
            else:
                grid_n = int(g_text)
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
                raman_enabled=self.chk_raman.isChecked(),
                shock_enabled=self.chk_shock.isChecked(),
            )
        except ValueError as e:
            QMessageBox.warning(self, "Invalid Parameter", f"Please check input values:\n{e}")
            return

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


    @property
    def txt_beta2(self): return self.manual_disp.txt_beta2 if self.manual_disp else None
    @property
    def txt_beta3(self): return self.manual_disp.txt_beta3 if self.manual_disp else None
    @property
    def txt_beta4(self): return self.manual_disp.txt_beta4 if self.manual_disp else None
    @property
    def txt_beta5(self): return self.manual_disp.txt_beta5 if self.manual_disp else None
    @property
    def txt_beta6(self): return self.manual_disp.txt_beta6 if self.manual_disp else None
    @property
    def txt_beta7(self): return self.manual_disp.txt_beta7 if self.manual_disp else None
    @property
    def txt_import_path(self): return self.file_nav.txt_import_path if self.file_nav else None

    def set_external_widgets(self, manual_disp, file_nav):
        self.manual_disp = manual_disp
        self.file_nav = file_nav
        if self.file_nav is not None:
            if hasattr(self.file_nav, "populate_manual_requested"):
                self.file_nav.populate_manual_requested.connect(self._on_populate_manual_betas)
            if hasattr(self.file_nav, "aeff_evaluated"):
                self.file_nav.aeff_evaluated.connect(self._on_aeff_evaluated)
            if hasattr(self.file_nav, "set_center_wavelength"):
                self.wavelength_changed.connect(self.file_nav.set_center_wavelength)
                try:
                    wl_nm = float(self.txt_wavelength.text())
                    self.file_nav.set_center_wavelength(wl_nm * 1e-9)
                except Exception:
                    pass

    def _on_populate_manual_betas(self, betas_si: list[float]) -> None:
        if self.manual_disp:
            self.manual_disp.set_betas_si(betas_si)
            self.combo_disp_mode.setCurrentIndex(0)  # switch to manual
            QMessageBox.information(
                self,
                "Dispersion Coefficients Transferred",
                "Physical dispersion coefficients β₂ through β₇ have been loaded into Manual Input fields.",
            )

    def _on_export_config(self) -> None:
        import json
        fpath, _ = QFileDialog.getSaveFileName(self, "Export Configuration", "", "JSON Files (*.json)")
        if not fpath:
            return

        try:
            txt_shape = self.combo_pulse_shape.currentText()
            if "Lorentzian" in txt_shape:
                pulse_shape = "lorentzian"
            elif "Gaussian" in txt_shape:
                pulse_shape = "gaussian"
            elif "Custom" in txt_shape:
                pulse_shape = "custom"
            else:
                pulse_shape = "sech"

            p = PulseConfig(
                shape=pulse_shape,
                t_fwhm=float(self.txt_fwhm.text()) * 1e-15,
                p_peak=float(self.txt_peak_power.text()) * 1e3,
                center_wavelength=float(self.txt_wavelength.text()) * 1e-9,
                chirp=float(self.txt_chirp.text()),
                custom_field=self._custom_field if pulse_shape == "custom" else None,
                custom_time=self._custom_time if pulse_shape == "custom" else None,
            )

            if self.combo_disp_mode.currentIndex() == 0:
                betas = self.manual_disp.get_betas_si() if self.manual_disp else [0.0] * 6
                disp = DispersionConfig(mode="manual", betas=betas)
            else:
                import_path = ""
                if self.file_nav and hasattr(self.file_nav, 'active_file_path') and self.file_nav.active_file_path:
                    import_path = self.file_nav.active_file_path
                elif getattr(self, "active_import_file", None):
                    import_path = self.active_import_file

                h5_group = self.file_nav.combo_group.currentText() if hasattr(self.file_nav, 'combo_group') else None
                h5_dataset_x = self.file_nav.combo_x.currentText() if hasattr(self.file_nav, 'combo_x') else None
                h5_dataset_y = self.file_nav.combo_y.currentText() if hasattr(self.file_nav, 'combo_y') else None
                disp = DispersionConfig(
                    mode="import",
                    import_path=import_path,
                    h5_group=h5_group,
                    h5_dataset_x=h5_dataset_x,
                    h5_dataset_y=h5_dataset_y,
                )

            f = FiberConfig(
                length=float(self.txt_length.text()) * 1e-2,
                gamma=float(self.txt_gamma.text()) * 1e-3,
                loss_alpha_db=float(self.txt_loss.text()),
                dispersion=disp,
                raman_fr=0.18 if self.chk_raman.isChecked() else 0.0,
            )

            g_text = self.combo_grid_n.currentText()
            t_max = float(self.txt_time_window.text()) * 1e-12
            if g_text == "Auto":
                from src.solver.config import compute_auto_grid_size
                fwhm_fs = float(self.txt_fwhm.text())
                if "Gaussian" in self.combo_pulse_shape.currentText():
                    div = 2.0 * math.sqrt(math.log(2.0))
                elif "Lorentzian" in self.combo_pulse_shape.currentText():
                    div = 2.0 * math.sqrt(math.sqrt(2.0) - 1.0)
                else:
                    div = 2.0 * math.log(1.0 + math.sqrt(2.0))
                t0_s = (fwhm_fs * 1e-15) / div
                grid_n = compute_auto_grid_size(t_max, t0_s, self.chk_raman.isChecked())
            else:
                grid_n = int(g_text)

            s = SolverConfig(
                simulation_type="spectrum_vs_power" if self.combo_sim_type.currentIndex() == 1 else "spectrum_vs_distance",
                method=self.combo_method.currentText(),
                n_points=grid_n,
                time_window=t_max,
                adaptive_step=self.chk_adaptive.isChecked(),
                initial_step=float(self.txt_init_step.text()) * 1e-3,
                tolerance=float(self.txt_tolerance.text()),
                power_min=float(self.txt_power_min.text()) * 1e3,
                power_max=float(self.txt_power_max.text()) * 1e3,
                power_steps=int(self.txt_power_steps.text()),
                raman_enabled=self.chk_raman.isChecked(),
                shock_enabled=self.chk_shock.isChecked(),
            )

            data = {
                "pulse": p.to_dict(),
                "fiber": f.to_dict(),
                "solver": s.to_dict(),
            }
            if p.custom_field is not None:
                data["pulse"]["custom_field"] = p.custom_field.tolist()
            if p.custom_time is not None:
                data["pulse"]["custom_time"] = p.custom_time.tolist()

            with open(fpath, "w") as out:
                json.dump(data, out, indent=4)
        except ValueError as e:
            QMessageBox.warning(self, "Invalid Parameter", f"Please check input values:\n{e}")
            return

    def _on_import_config(self) -> None:
        import json
        fpath, _ = QFileDialog.getOpenFileName(self, "Import Configuration", "", "JSON Files (*.json)")
        if fpath:
            try:
                with open(fpath, "r") as inf:
                    data = json.load(inf)
                if "pulse" in data:
                    p = PulseConfig.from_dict(data["pulse"])
                    self.txt_fwhm.setText(str(p.t_fwhm * 1e15))
                    self.txt_peak_power.setText(str(p.p_peak * 1e-3))
                    self.txt_wavelength.setText(str(p.center_wavelength * 1e9))
                    self.txt_chirp.setText(str(p.chirp))
                    if p.shape == "sech":
                        self.combo_pulse_shape.setCurrentIndex(0)
                    elif p.shape == "gaussian":
                        self.combo_pulse_shape.setCurrentIndex(1)
                    elif p.shape == "lorentzian":
                        self.combo_pulse_shape.setCurrentIndex(2)
                    elif p.shape == "custom":
                        self.combo_pulse_shape.setCurrentIndex(3)
                        self._custom_field = p.custom_field
                        self._custom_time = p.custom_time
                        if p.custom_field is not None:
                            self.lbl_custom_pulse_status.setText(
                                f"✓ Custom array: {len(p.custom_field)} samples loaded"
                            )
                            self.lbl_custom_pulse_status.setStyleSheet("color: #00e676; font-size: 9pt; font-weight: bold;")

                if "fiber" in data:
                    f = FiberConfig.from_dict(data["fiber"])
                    self.txt_length.setText(str(f.length * 1e2))
                    self.txt_gamma.setText(str(f.gamma * 1e3))
                    self.txt_loss.setText(str(f.loss_alpha_db))
                    self.chk_raman.setChecked(f.raman_fr > 0)

                    if hasattr(f, 'dispersion') and type(f.dispersion) is dict:
                        d = DispersionConfig.from_dict(f.dispersion)
                    else:
                        d = f.dispersion

                    if d.mode == "manual":
                        self.combo_disp_mode.setCurrentIndex(0)
                        if self.manual_disp and d.betas:
                            exp_map = {2: -2, 3: -5, 4: -7, 5: -10, 6: -13, 7: -16}
                            beta_widgets = {
                                2: self.manual_disp.txt_beta2,
                                3: self.manual_disp.txt_beta3,
                                4: self.manual_disp.txt_beta4,
                                5: self.manual_disp.txt_beta5,
                                6: self.manual_disp.txt_beta6,
                                7: self.manual_disp.txt_beta7,
                            }
                            for k in range(2, 8):
                                if k - 2 < len(d.betas):
                                    beta_si = d.betas[k - 2]
                                    exponent = exp_map[k]
                                    mantissa = round(DispersionConfig.si_to_ps_m(k, beta_si) / (10 ** exponent), 6)
                                    beta_widgets[k].setText(f"{mantissa:g}")
                    else:
                        self.combo_disp_mode.setCurrentIndex(1)
                        if d.import_path:
                            self.set_active_import_file(d.import_path)

                if "solver" in data:
                    s = SolverConfig.from_dict(data["solver"])
                    if s.simulation_type == "spectrum_vs_power":
                        self.combo_sim_type.setCurrentIndex(1)
                    else:
                        self.combo_sim_type.setCurrentIndex(0)
                    if s.method in ["RK4IP", "S-SSFM", "SSFM"]:
                        self.combo_method.setCurrentText(s.method)
                    self.chk_adaptive.setChecked(bool(s.adaptive_step))
                    if s.power_min is not None:
                        self.txt_power_min.setText(str(s.power_min * 1e-3))
                    if s.power_max is not None:
                        self.txt_power_max.setText(str(s.power_max * 1e-3))
                    if s.power_steps is not None:
                        self.txt_power_steps.setText(str(s.power_steps))
                    self.combo_grid_n.setCurrentText(str(s.n_points))
                    self.txt_time_window.setText(str(s.time_window * 1e12))
                    self.txt_init_step.setText(str(s.initial_step * 1e3))
                    self.txt_tolerance.setText(str(s.tolerance))
                    if hasattr(s, 'raman_enabled'):
                        self.chk_raman.setChecked(bool(s.raman_enabled))
                    if hasattr(s, 'shock_enabled'):
                        self.chk_shock.setChecked(bool(s.shock_enabled))

                self.combo_presets.setCurrentIndex(3)
            except Exception as e:
                QMessageBox.critical(self, "Configuration Import Error", f"Failed to import configuration:\n{e}")
