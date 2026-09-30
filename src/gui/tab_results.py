"""Tab 2: Results & Visualization Canvas for GNLSE Simulator.

Dynamically renders:
- 2x2 Grid for 'Spectrum vs Distance' (Time 2D + Freq 2D, Time 1D before/after + Freq 1D before/after).
- 1x2 Grid for 'Spectrum vs Power' (Power-Sweep 2D + Freq 1D before/after, time plots removed).
Includes publication-grade scientific labeling and high-res export tooling.
"""

from __future__ import annotations

import os
import csv
import h5py
import numpy as np
from typing import Optional, List
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPainter, QPdfWriter
try:
    from PyQt6.QtSvg import QSvgGenerator
except ImportError:
    QSvgGenerator = None
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QPushButton, QFileDialog, QSlider, QDoubleSpinBox, QSplitter, QGridLayout, QMessageBox
)

from src.solver.config import SimulationState
from .plots import (
    DensityMapWidget,
    LinePlotWidget,
    envelope_to_time_ps,
    spectrum_to_db,
)


class TabResultsWidget(QWidget):
    """Tab 2 results workstation supporting dynamic 2x2 and 1x2 grid layouts."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self.current_sim_type = "spectrum_vs_distance"
        self.cached_history: List[SimulationState] = []
        self.cached_final_state: Optional[SimulationState] = None
        self.initial_state: Optional[SimulationState] = None
        self.center_wavelength: float = 1550e-9
        self.omega0: float = 2.0 * np.pi * 299792458.0 / self.center_wavelength
        self.MAX_DISPLAY_BINS: int = 1024

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(6, 6, 6, 6)

        # -------------------------------------------------------------
        # 1. Header Toolbar
        # -------------------------------------------------------------
        header_bar = QHBoxLayout()
        self.lbl_title = QLabel("Simulation Results — Idle")
        self.lbl_title.setStyleSheet("font-size: 13pt; font-weight: bold; color: #FFFFFF;")
        header_bar.addWidget(self.lbl_title, 1)

        # Colormap dropdown
        header_bar.addWidget(QLabel("Colormap:"))
        self.combo_cmap = QComboBox()
        self.combo_cmap.addItems(["turbo", "viridis", "inferno", "magma", "plasma", "jet"])
        self.combo_cmap.setCurrentText("turbo")
        self.combo_cmap.currentTextChanged.connect(self._on_cmap_changed)
        header_bar.addWidget(self.combo_cmap)

        # dB Range slider
        header_bar.addWidget(QLabel("Dynamic Range:"))
        self.slider_db = QSlider(Qt.Orientation.Horizontal)
        self.slider_db.setRange(20, 80)
        self.slider_db.setValue(40)
        self.slider_db.valueChanged.connect(self._on_db_slider_changed)
        self.lbl_db_val = QLabel("-40 dB")
        header_bar.addWidget(self.slider_db)
        header_bar.addWidget(self.lbl_db_val)

        # Export Button
        self.btn_export = QPushButton("💾 Export Results...")
        self.btn_export.setStyleSheet("background-color: #388E3C; color: white; font-weight: bold; padding: 6px 12px;")
        self.btn_export.clicked.connect(self._on_export_clicked)
        header_bar.addWidget(self.btn_export)

        main_layout.addLayout(header_bar)

        # -------------------------------------------------------------
        # 2. Dynamic Plot Grid Container
        # -------------------------------------------------------------
        self.plot_container = QWidget()
        self.grid_layout = QGridLayout(self.plot_container)
        self.grid_layout.setContentsMargins(0, 0, 0, 0)
        self.grid_layout.setSpacing(6)

        # Instantiate plots
        # Top-Left: Time 2D
        self.plot_time_2d = DensityMapWidget(
            title="Time domain",
            x_label="Time [ps]",
            y_label="Distance [cm]",
            cbar_label="Normalized Intensity [dB]",
            colormap_name="turbo",
        )
        # Top-Right: Freq 2D
        self.plot_freq_2d = DensityMapWidget(
            title="Freq. domain",
            x_label="Wavelength [nm]",
            y_label="Distance [cm]",
            cbar_label="Normalized Spectral Density [dB]",
            colormap_name="turbo",
        )
        # Bottom-Left: Time 1D
        self.plot_time_1d = LinePlotWidget(
            title="Time domain",
            x_label="Time [ps]",
            y_label="Intensity [W]",
        )
        # Bottom-Right: Freq 1D
        self.plot_freq_1d = LinePlotWidget(
            title="Freq. domain",
            x_label="Wavelength [nm]",
            y_label="Spectral Power [dB]",
        )

        # Default view ranges:
        # Time 1D & 2D: [-2.5, 2.5] ps
        self.plot_time_1d.set_x_range(-2.5, 2.5)
        self.plot_time_2d.set_x_range(-2.5, 2.5)

        # Freq 1D & 2D: [500.0, 1200.0] nm
        self.plot_freq_1d.set_x_range(500.0, 1200.0)
        self.plot_freq_2d.set_x_range(500.0, 1200.0)

        # 1D Freq plot Y range: [-200.0, 10.0] dB
        self.plot_freq_1d.set_y_limits(-200.0, 10.0)

        # Colormap levels: (-40.0, 0.0) dB
        self.plot_time_2d.set_db_floor(-40.0)
        self.plot_freq_2d.set_db_floor(-40.0)

        # Wavelength Window Control Toolbar for 1D Freq Plot
        self.wl_toolbar = QHBoxLayout()
        self.wl_toolbar.setContentsMargins(4, 0, 4, 0)
        self.wl_toolbar.addWidget(QLabel("λ Range [nm]:"))
        
        self.spin_wl_min = QDoubleSpinBox()
        self.spin_wl_min.setRange(100.0, 5000.0)
        self.spin_wl_min.setValue(500.0)
        self.spin_wl_min.setDecimals(1)
        
        self.spin_wl_max = QDoubleSpinBox()
        self.spin_wl_max.setRange(100.0, 5000.0)
        self.spin_wl_max.setValue(1200.0)
        self.spin_wl_max.setDecimals(1)
        
        self.btn_wl_reset = QPushButton("Reset Fit")
        self.btn_hult_window = QPushButton("🎯 Hult Window (500–1200 nm)")

        self.wl_toolbar.addWidget(self.spin_wl_min)
        self.wl_toolbar.addWidget(QLabel("to"))
        self.wl_toolbar.addWidget(self.spin_wl_max)
        self.wl_toolbar.addWidget(self.btn_wl_reset)
        self.wl_toolbar.addWidget(self.btn_hult_window)
        self.wl_toolbar.addStretch()
        
        # Add toolbar to the LinePlotWidget's vertical layout
        self.plot_freq_1d.layout().addLayout(self.wl_toolbar)
        
        self.spin_wl_min.valueChanged.connect(self._on_wl_range_changed)
        self.spin_wl_max.valueChanged.connect(self._on_wl_range_changed)
        self.btn_wl_reset.clicked.connect(self._on_wl_reset_clicked)
        self.btn_hult_window.clicked.connect(self._on_hult_window_clicked)
        
        # apply initial range
        self._on_wl_range_changed()

        main_layout.addWidget(self.plot_container, 1)

        # Set default 2x2 layout
        self.set_simulation_type("spectrum_vs_distance")

    def set_center_wavelength(self, center_wavelength: float) -> None:
        """Dynamically calibrate carrier wavelength and center frequency omega0."""
        self.center_wavelength = max(float(center_wavelength), 100e-9)
        self.omega0 = 2.0 * np.pi * 299792458.0 / self.center_wavelength

    def set_simulation_type(self, sim_type: str) -> None:
        """Dynamically adapt layout between 2x2 (Distance) and 1x2 (Power Sweep)."""
        self.current_sim_type = sim_type

        # Remove widgets from grid without breaking parent hierarchy
        for w in (self.plot_time_2d, self.plot_freq_2d, self.plot_time_1d, self.plot_freq_1d):
            self.grid_layout.removeWidget(w)

        if sim_type == "spectrum_vs_distance":
            # 2x2 Grid Layout
            self.plot_time_2d.show()
            self.plot_time_1d.show()
            self.plot_freq_2d.show()
            self.plot_freq_1d.show()

            self.plot_time_2d.plot_item.setLabel("left", "Distance [cm]")
            self.plot_time_2d.plot_item.setLabel("bottom", "Time [ps]")
            self.plot_time_2d.plot_item.setTitle("Time domain")

            self.plot_freq_2d.plot_item.setLabel("left", "Distance [cm]")
            self.plot_freq_2d.plot_item.setLabel("bottom", "Wavelength [nm]")
            self.plot_freq_2d.plot_item.setTitle("Freq. domain")

            self.plot_time_1d.plot_item.setLabel("left", "Intensity [W]")
            self.plot_time_1d.plot_item.setLabel("bottom", "Time [ps]")
            self.plot_time_1d.plot_item.setTitle("Time domain")

            self.plot_freq_1d.plot_item.setLabel("left", "Spectral Power [dB]")
            self.plot_freq_1d.plot_item.setLabel("bottom", "Wavelength [nm]")
            self.plot_freq_1d.plot_item.setTitle("Freq. domain")

            self.grid_layout.addWidget(self.plot_time_2d, 0, 0)
            self.grid_layout.addWidget(self.plot_freq_2d, 0, 1)
            self.grid_layout.addWidget(self.plot_time_1d, 1, 0)
            self.grid_layout.addWidget(self.plot_freq_1d, 1, 1)
        else:
            # 1x2 Grid Layout (Time plots removed)
            self.plot_time_2d.hide()
            self.plot_time_1d.hide()
            self.plot_freq_2d.show()
            self.plot_freq_1d.show()

            self.plot_freq_2d.plot_item.setLabel("left", "Peak Power P₀ [kW]")
            self.plot_freq_2d.plot_item.setLabel("bottom", "Wavelength [nm]")
            self.plot_freq_2d.plot_item.setTitle("Power-Sweep Spectral Density")

            self.plot_freq_1d.plot_item.setLabel("left", "Spectral Power [dB]")
            self.plot_freq_1d.plot_item.setLabel("bottom", "Wavelength [nm]")
            self.plot_freq_1d.plot_item.setTitle("Freq. domain")

            self.grid_layout.addWidget(self.plot_freq_2d, 0, 0)
            self.grid_layout.addWidget(self.plot_freq_1d, 0, 1)

    def prepare_for_simulation(
        self,
        initial_state: SimulationState,
        method: str,
        center_wavelength: Optional[float] = None,
    ) -> None:
        """Initialize plots with 'before' curve at z = 0 using active pulse wavelength."""
        self.initial_state = initial_state
        self.cached_history = []
        self.cached_final_state = None
        if center_wavelength is not None:
            self.set_center_wavelength(center_wavelength)

        sim_title = "Spectrum vs Distance" if self.current_sim_type == "spectrum_vs_distance" else "Spectrum vs Power"
        self.lbl_title.setText(f"Simulation with {method} Method — {sim_title}")

        # Set initial 'before' curves
        t_ps = envelope_to_time_ps(initial_state.t)
        intensity_0 = np.abs(initial_state.a_t) ** 2
        self.plot_time_1d.set_before_curve(t_ps, intensity_0)

        # Default time domain view range [-2.5, 2.5] ps
        self.plot_time_1d.set_x_range(-2.5, 2.5)
        self.plot_time_2d.set_x_range(-2.5, 2.5)

        # Center frequency omega0 - Raw simulation spectrum
        wl_nm, psd_db = spectrum_to_db(initial_state.a_w, initial_state.omega, self.omega0)
        self.plot_freq_1d.set_before_curve(wl_nm, psd_db)

        # Default ranges
        self.plot_freq_1d.set_y_limits(-200.0, 10.0)
        db_val = float(self.slider_db.value())
        self.plot_time_2d.set_db_floor(-db_val)
        self.plot_freq_2d.set_db_floor(-db_val)

        # -----------------------------
        # Live 2D Colormap Initialization
        # -----------------------------
        self.MAX_DISPLAY_BINS = getattr(self, "MAX_DISPLAY_BINS", 1024)
        wl_min = self.spin_wl_min.value()
        wl_max = self.spin_wl_max.value()
        
        self.display_wl = np.linspace(wl_min, wl_max, self.MAX_DISPLAY_BINS)
        self.display_t = t_ps

        self.plot_freq_1d.set_x_range(wl_min, wl_max)
        self.plot_freq_2d.set_x_range(wl_min, wl_max)

        N_pts_time = len(t_ps)
        N_pts_freq = len(self.display_wl)

        MAX_STEPS = 5000
        self.live_time_map = np.full((MAX_STEPS, N_pts_time), -40.0)
        self.live_freq_map = np.full((MAX_STEPS, N_pts_freq), -40.0)
        self.live_y_coords = np.zeros(MAX_STEPS)
        self.live_step_idx = 0

    def update_live_state(self, state: SimulationState) -> None:
        """Update 1D 'after' curves and live 2D maps in real-time."""
        t_ps = envelope_to_time_ps(state.t)
        intensity = np.abs(state.a_t) ** 2
        self.plot_time_1d.set_after_curve(t_ps, intensity)

        wl_nm, psd_db = spectrum_to_db(state.a_w, state.omega, self.omega0)
        self.plot_freq_1d.set_after_curve(wl_nm, psd_db)

        # Update Live 2D Map
        if self.live_step_idx < self.live_time_map.shape[0]:
            idx = self.live_step_idx
            
            # Time map: exact normalization 10.0 * np.log10((I + 1e-30) / (np.max(I) + 1e-30))
            self.live_time_map[idx, :] = 10.0 * np.log10((intensity + 1e-30) / (np.max(intensity) + 1e-30))
            
            # Freq map interpolated into uniform self.display_wl
            self.live_freq_map[idx, :] = np.interp(self.display_wl, wl_nm, psd_db)
            
            if self.current_sim_type == "spectrum_vs_distance":
                self.live_y_coords[idx] = state.z * 100.0
            else:
                self.live_y_coords[idx] = state.power / 1e3
                
            y_min = float(self.live_y_coords[0])
            y_max = float(self.live_y_coords[idx]) if self.live_y_coords[idx] > y_min else y_min + 1.0
            
            wl_min = float(self.display_wl[0])
            wl_max = float(self.display_wl[-1])
            # Update density widgets
            self.plot_freq_2d.update_data(self.live_freq_map[:idx+1, :], (wl_min, wl_max), (y_min, y_max))
            
            if self.current_sim_type == "spectrum_vs_distance":
                self.plot_time_2d.update_data(self.live_time_map[:idx+1, :], (float(t_ps[0]), float(t_ps[-1])), (y_min, y_max))

            self.live_step_idx += 1

    def render_full_simulation(self, final_state: SimulationState, history: List[SimulationState]) -> None:
        """Render completed 2D density maps and final 1D profiles."""
        self.cached_final_state = final_state
        self.cached_history = history
        if not history:
            return

        wl_min = self.spin_wl_min.value()
        wl_max = self.spin_wl_max.value()
        N_steps = len(history)
        t_ps = envelope_to_time_ps(history[0].t)
        
        N_pts_time = len(t_ps)
        N_pts_freq = getattr(self, "MAX_DISPLAY_BINS", 1024)
        self.display_wl = np.linspace(wl_min, wl_max, N_pts_freq)

        time_map_db = np.zeros((N_steps, N_pts_time))
        spec_map_db = np.zeros((N_steps, N_pts_freq))
        y_coords = np.zeros(N_steps)

        for i, s in enumerate(history):
            # Intensity in dB: exact normalization 10.0 * np.log10((I + 1e-30) / (np.max(I) + 1e-30))
            int_t = np.abs(s.a_t) ** 2
            time_map_db[i, :] = 10.0 * np.log10((int_t + 1e-30) / (np.max(int_t) + 1e-30))

            # Spectrum in dB: exact normalization interpolated onto uniform self.display_wl
            s_wl_nm, s_db = spectrum_to_db(s.a_w, s.omega, self.omega0)
            spec_map_db[i, :] = np.interp(self.display_wl, s_wl_nm, s_db)

            if self.current_sim_type == "spectrum_vs_distance":
                y_coords[i] = s.z * 100.0  # m to cm
            else:
                y_coords[i] = s.power / 1e3  # W to kW

        y_min = float(y_coords[0])
        y_max = float(y_coords[-1]) if y_coords[-1] > y_min else y_min + 1.0

        # Render 2D Freq map
        self.plot_freq_2d.update_data(spec_map_db, (wl_min, wl_max), (y_min, y_max))
        self.plot_freq_2d.set_x_range(wl_min, wl_max)
        self.plot_freq_1d.set_x_range(wl_min, wl_max)
        self.plot_freq_1d.set_y_limits(-200.0, 10.0)

        # Render 2D Time map if distance mode
        if self.current_sim_type == "spectrum_vs_distance":
            self.plot_time_2d.update_data(time_map_db, (float(t_ps[0]), float(t_ps[-1])), (y_min, y_max))
            self.plot_time_2d.set_x_range(-2.5, 2.5)
            self.plot_time_1d.set_x_range(-2.5, 2.5)

        # Update final 1D line curves
        # Note: Do not call update_live_state here as it would duplicate the 1D update and advance the live_step_idx.
        t_ps_final = envelope_to_time_ps(final_state.t)
        intensity_final = np.abs(final_state.a_t) ** 2
        self.plot_time_1d.set_after_curve(t_ps_final, intensity_final)
        
        wl_nm_final, psd_db_final = spectrum_to_db(final_state.a_w, final_state.omega, self.omega0)
        self.plot_freq_1d.set_after_curve(wl_nm_final, psd_db_final)

    def _on_cmap_changed(self, cmap_name: str) -> None:
        self.plot_time_2d.set_colormap(cmap_name)
        self.plot_freq_2d.set_colormap(cmap_name)

    def _on_db_slider_changed(self, val: int) -> None:
        self.lbl_db_val.setText(f"-{val} dB")
        self.plot_time_2d.set_db_floor(-float(val))
        self.plot_freq_2d.set_db_floor(-float(val))

    def export_to_file(self, fpath: str) -> tuple[bool, str]:
        """Export publication figure snapshot or numerical data matrix without UI modal blocks.

        Returns:
            (success: bool, message: str)
        """
        if not self.cached_history:
            return False, "No simulation results to export. Run a simulation first."

        try:
            if fpath.endswith((".h5", ".hdf5")):
                with h5py.File(fpath, "w") as h5f:
                    wl_nm, _ = spectrum_to_db(self.cached_history[0].a_w, self.cached_history[0].omega, self.omega0)
                    t_ps = envelope_to_time_ps(self.cached_history[0].t)
                    h5f.attrs["simulation_type"] = self.current_sim_type
                    h5f.attrs["center_wavelength_nm"] = self.center_wavelength * 1e9
                    h5f.attrs["omega0_rad_s"] = self.omega0
                    h5f.attrs["num_steps"] = len(self.cached_history)

                    h5f.create_dataset("time_ps", data=t_ps)
                    h5f.create_dataset("wavelength_nm", data=wl_nm)
                    if self.current_sim_type == "spectrum_vs_distance":
                        z_m = np.array([s.z for s in self.cached_history])
                        h5f.create_dataset("z_m", data=z_m)
                        h5f.create_dataset("z_cm", data=z_m * 100.0)
                    else:
                        power_w = np.array([s.power for s in self.cached_history])
                        h5f.create_dataset("power_w", data=power_w)
                        h5f.create_dataset("power_kw", data=power_w / 1e3)

                    a_t_matrix = np.array([s.a_t for s in self.cached_history])
                    a_w_matrix = np.array([s.a_w for s in self.cached_history])
                    h5f.create_dataset("a_t_envelope", data=a_t_matrix)
                    h5f.create_dataset("a_w_spectrum", data=a_w_matrix)

                return True, f"Data exported successfully to:\n{fpath}"

            elif fpath.endswith(".csv"):
                with open(fpath, "w", newline="", encoding="utf-8") as csvfile:
                    writer = csv.writer(csvfile)
                    writer.writerow(["# GNLSE Simulation Data Export"])
                    writer.writerow([f"# Simulation Type: {self.current_sim_type}"])
                    writer.writerow([f"# Center Wavelength [nm]: {self.center_wavelength * 1e9:.3f}"])
                    writer.writerow([f"# Carrier Frequency omega0 [rad/s]: {self.omega0:.6e}"])
                    writer.writerow(["time_ps", "intensity_before_W", "intensity_after_W", "wavelength_nm", "spectral_power_before_dB", "spectral_power_after_dB"])

                    t_ps = envelope_to_time_ps(self.cached_history[0].t)
                    int_before = np.abs(self.cached_history[0].a_t) ** 2
                    int_after = np.abs(self.cached_final_state.a_t) ** 2 if self.cached_final_state else int_before
                    wl_nm, sp_before = spectrum_to_db(self.cached_history[0].a_w, self.cached_history[0].omega, self.omega0)
                    if self.cached_final_state:
                        _, sp_after = spectrum_to_db(self.cached_final_state.a_w, self.cached_final_state.omega, self.omega0)
                    else:
                        sp_after = sp_before

                    for i in range(len(t_ps)):
                        writer.writerow([f"{t_ps[i]:.6e}", f"{int_before[i]:.6e}", f"{int_after[i]:.6e}", f"{wl_nm[i]:.6e}", f"{sp_before[i]:.6e}", f"{sp_after[i]:.6e}"])

                return True, f"CSV dataset exported successfully to:\n{fpath}"

            elif fpath.endswith(".png"):
                pixmap = self.plot_container.grab()
                pixmap.save(fpath, "PNG")
                return True, f"Figure saved to:\n{fpath}"

            elif fpath.endswith(".pdf"):
                writer = QPdfWriter(fpath)
                painter = QPainter(writer)
                pixmap = self.plot_container.grab()
                painter.drawPixmap(0, 0, pixmap.scaled(writer.width(), writer.height(), Qt.AspectRatioMode.KeepAspectRatio))
                painter.end()
                return True, f"PDF figure saved to:\n{fpath}"

            elif fpath.endswith(".svg"):
                if QSvgGenerator is not None:
                    generator = QSvgGenerator()
                    generator.setFileName(fpath)
                    generator.setSize(self.plot_container.size())
                    generator.setViewBox(self.plot_container.rect())
                    generator.setTitle("GNLSE Simulation Results")
                    painter = QPainter(generator)
                    self.plot_container.render(painter)
                    painter.end()
                    return True, f"SVG figure saved to:\n{fpath}"
                else:
                    return False, "QSvgGenerator not available; export to SVG skipped."
            else:
                return False, f"Unsupported file format for path: {fpath}"
        except Exception as exc:
            return False, f"Failed to export data: {exc}"

    def _on_hult_window_clicked(self) -> None:
        """Reset wavelength range spinboxes to Hult benchmark window [500, 1200] nm."""
        self.spin_wl_min.setValue(500.0)
        self.spin_wl_max.setValue(1200.0)
        self._on_wl_range_changed()

    def _on_wl_range_changed(self) -> None:
        wl_min = self.spin_wl_min.value()
        wl_max = self.spin_wl_max.value()
        if wl_min >= wl_max:
            return

        if hasattr(self.plot_freq_1d, "set_x_range"):
            self.plot_freq_1d.set_x_range(wl_min, wl_max)
        if hasattr(self.plot_freq_2d, "set_x_range"):
            self.plot_freq_2d.set_x_range(wl_min, wl_max)

        self.MAX_DISPLAY_BINS = getattr(self, "MAX_DISPLAY_BINS", 1024)
        self.display_wl = np.linspace(wl_min, wl_max, self.MAX_DISPLAY_BINS)

        if self.cached_history and self.cached_final_state is not None:
            N_steps = len(self.cached_history)
            spec_map_db = np.zeros((N_steps, len(self.display_wl)))
            y_coords = np.zeros(N_steps)
            for i, s in enumerate(self.cached_history):
                s_wl_nm, s_db = spectrum_to_db(s.a_w, s.omega, self.omega0)
                spec_map_db[i, :] = np.interp(self.display_wl, s_wl_nm, s_db)
                if self.current_sim_type == "spectrum_vs_distance":
                    y_coords[i] = s.z * 100.0
                else:
                    y_coords[i] = s.power / 1e3

            y_min = float(y_coords[0])
            y_max = float(y_coords[-1]) if y_coords[-1] > y_min else y_min + 1.0
            self.plot_freq_2d.update_data(spec_map_db, (wl_min, wl_max), (y_min, y_max))

    def _on_wl_reset_clicked(self) -> None:
        if hasattr(self.plot_freq_1d, "plot_item"):
            self.plot_freq_1d.plot_item.enableAutoRange(axis="x")
        if hasattr(self.plot_freq_2d, "plot_item"):
            self.plot_freq_2d.plot_item.enableAutoRange(axis="x")

    def _on_export_clicked(self) -> None:
        """Export publication figure snapshot or raw simulation dataset."""
        if not self.cached_history:
            QMessageBox.information(self, "Export", "No simulation results to export. Run a simulation first.")
            return

        fpath, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export Results",
            os.path.join(os.getcwd(), "simulation_result.h5"),
            "HDF5 Dataset (*.h5);;CSV Matrix (*.csv);;PNG Figure (*.png);;PDF Document (*.pdf);;SVG Vector Graphics (*.svg)",
        )
        if not fpath:
            return

        success, msg = self.export_to_file(fpath)
        if success:
            QMessageBox.information(self, "Export", msg)
        else:
            QMessageBox.critical(self, "Export Error", msg)
