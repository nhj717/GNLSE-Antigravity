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
    QPushButton, QFileDialog, QSlider, QSplitter, QGridLayout, QMessageBox
)

from src.solver.config import SimulationState
from .plots import DensityMapWidget, LinePlotWidget, envelope_to_time_ps, spectrum_to_db


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
        self.combo_cmap.addItems(["viridis", "inferno", "magma", "plasma", "jet"])
        self.combo_cmap.setCurrentText("viridis")
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
            colormap_name="inferno",
        )
        # Top-Right: Freq 2D
        self.plot_freq_2d = DensityMapWidget(
            title="Freq. domain",
            x_label="Wavelength [nm]",
            y_label="Distance [cm]",
            cbar_label="Normalized Spectral Density [dB]",
            colormap_name="inferno",
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

        # Center frequency omega0
        wl_nm, psd_db = spectrum_to_db(initial_state.a_w, initial_state.omega, self.omega0, db_floor=-200.0)
        self.plot_freq_1d.set_before_curve(wl_nm, psd_db)

    def update_live_state(self, state: SimulationState) -> None:
        """Update 1D 'after' curves in real-time during live simulation."""
        t_ps = envelope_to_time_ps(state.t)
        intensity = np.abs(state.a_t) ** 2
        self.plot_time_1d.set_after_curve(t_ps, intensity)

        wl_nm, psd_db = spectrum_to_db(state.a_w, state.omega, self.omega0, db_floor=-200.0)
        self.plot_freq_1d.set_after_curve(wl_nm, psd_db)

    def render_full_simulation(self, final_state: SimulationState, history: List[SimulationState]) -> None:
        """Render completed 2D density maps and final 1D profiles."""
        self.cached_final_state = final_state
        self.cached_history = history
        if not history:
            return

        N_steps = len(history)
        N_pts = len(final_state.t)

        time_map_db = np.zeros((N_steps, N_pts))
        spec_map_db = np.zeros((N_steps, N_pts))
        y_coords = np.zeros(N_steps)

        # Get wavelength coordinate
        wl_nm, _ = spectrum_to_db(history[0].a_w, history[0].omega, self.omega0)
        t_ps = envelope_to_time_ps(history[0].t)

        for i, s in enumerate(history):
            # Intensity in dB
            int_t = np.abs(s.a_t) ** 2
            max_int = np.max(int_t)
            if max_int > 0:
                time_map_db[i, :] = 10.0 * np.log10(np.maximum(int_t / max_int, 1e-4))
            else:
                time_map_db[i, :] = -40.0

            # Spectrum in dB
            _, s_db = spectrum_to_db(s.a_w, s.omega, self.omega0, db_floor=-40.0)
            spec_map_db[i, :] = s_db

            if self.current_sim_type == "spectrum_vs_distance":
                y_coords[i] = s.z * 100.0  # m to cm
            else:
                y_coords[i] = s.power / 1e3  # W to kW

        y_min = float(y_coords[0])
        y_max = float(y_coords[-1]) if y_coords[-1] > y_min else y_min + 1.0

        # Render 2D Freq map
        self.plot_freq_2d.update_data(spec_map_db, (float(wl_nm[0]), float(wl_nm[-1])), (y_min, y_max))

        # Render 2D Time map if distance mode
        if self.current_sim_type == "spectrum_vs_distance":
            self.plot_time_2d.update_data(time_map_db, (float(t_ps[0]), float(t_ps[-1])), (y_min, y_max))

        # Update final 1D line curves
        self.update_live_state(final_state)

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
                    wl_nm, sp_before = spectrum_to_db(self.cached_history[0].a_w, self.cached_history[0].omega, self.omega0, db_floor=-200.0)
                    if self.cached_final_state:
                        _, sp_after = spectrum_to_db(self.cached_final_state.a_w, self.cached_final_state.omega, self.omega0, db_floor=-200.0)
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
