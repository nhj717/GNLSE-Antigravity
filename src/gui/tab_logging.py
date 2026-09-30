"""Tab 3: Real-Time Diagnostic Logging & Conservation Monitor for GNLSE Simulator."""

from __future__ import annotations

import time
import os
from typing import Optional
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit,
    QPushButton, QGroupBox, QGridLayout, QFileDialog, QMessageBox, QApplication
)


class TabLoggingWidget(QWidget):
    """Tab 3 logging terminal and live numerical conservation monitor."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        # -------------------------------------------------------------
        # 1. Numerical Conservation Dashboard Cards
        # -------------------------------------------------------------
        metrics_group = QGroupBox("Physical Conservation & Execution Diagnostics")
        grid = QGridLayout(metrics_group)

        self.lbl_energy_err = QLabel("0.00e+00")
        self.lbl_energy_err.setStyleSheet("font-size: 13pt; font-weight: bold; color: #4CAF50;")
        grid.addWidget(QLabel("Relative Energy Error |ΔE(z)/E(0)| [-]:"), 0, 0)
        grid.addWidget(self.lbl_energy_err, 0, 1)

        self.lbl_photon_err = QLabel("0.00e+00")
        self.lbl_photon_err.setStyleSheet("font-size: 13pt; font-weight: bold; color: #4CAF50;")
        grid.addWidget(QLabel("Relative Photon Error |ΔN_ph(z)/N_ph(0)| [-]:"), 0, 2)
        grid.addWidget(self.lbl_photon_err, 0, 3)

        self.lbl_step_size = QLabel("0.000 mm")
        self.lbl_step_size.setStyleSheet("font-size: 13pt; font-weight: bold; color: #2196F3;")
        grid.addWidget(QLabel("Step Size h(z) [mm]:"), 1, 0)
        grid.addWidget(self.lbl_step_size, 1, 1)

        self.lbl_calc_speed = QLabel("0.0 steps/s")
        self.lbl_calc_speed.setStyleSheet("font-size: 13pt; font-weight: bold; color: #FF9800;")
        grid.addWidget(QLabel("Calculation Rate [steps/s]:"), 1, 2)
        grid.addWidget(self.lbl_calc_speed, 1, 3)

        self.lbl_eta = QLabel("-- s")
        self.lbl_eta.setStyleSheet("font-size: 13pt; font-weight: bold; color: #00BCD4;")
        grid.addWidget(QLabel("Estimated Time of Arrival (ETA) [s]:"), 2, 0)
        grid.addWidget(self.lbl_eta, 2, 1)

        layout.addWidget(metrics_group)

        # -------------------------------------------------------------
        # 2. Console Terminal
        # -------------------------------------------------------------
        log_group = QGroupBox("Simulation Event Log")
        log_layout = QVBoxLayout(log_group)

        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.console.setStyleSheet(
            "background-color: #121212; color: #ECEFF1; font-family: monospace; font-size: 10pt;"
        )
        log_layout.addWidget(self.console)

        # Log Toolbar
        tool_row = QHBoxLayout()
        self.btn_clear = QPushButton("Clear Console")
        self.btn_clear.clicked.connect(self.console.clear)
        self.btn_copy = QPushButton("Copy to Clipboard")
        self.btn_copy.clicked.connect(self._copy_to_clipboard)
        self.btn_save = QPushButton("Save Log to File (.txt)...")
        self.btn_save.clicked.connect(self._save_log)

        tool_row.addWidget(self.btn_clear)
        tool_row.addWidget(self.btn_copy)
        tool_row.addWidget(self.btn_save)
        tool_row.addStretch(1)

        log_layout.addLayout(tool_row)
        layout.addWidget(log_group, 1)

        self.append_log("INFO", "GNLSE Diagnostic Logger initialized.")

    def append_log(self, level: str, message: str) -> None:
        """Append timestamped entry with severity coloring."""
        now_str = time.strftime("%H:%M:%S")
        color_map = {
            "INFO": "#2196F3",     # Blue
            "STEP": "#4CAF50",     # Green
            "WARN": "#FFC107",     # Amber
            "ERROR": "#F44336",    # Red
        }
        color = color_map.get(level.upper(), "#ECEFF1")
        html_msg = f"<span style='color: #888888;'>[{now_str}]</span> <b style='color: {color};'>[{level.upper()}]</b> {message}"
        self.console.append(html_msg)

    def update_metrics(self, energy_err: float, photon_err: float, h_m: float, steps_per_sec: float = 0.0) -> None:
        """Update diagnostic metric cards."""
        self.lbl_energy_err.setText(f"{energy_err:.2e}")
        # Color red if error exceeds threshold
        if abs(energy_err) > 1e-3:
            self.lbl_energy_err.setStyleSheet("font-size: 13pt; font-weight: bold; color: #F44336;")
        else:
            self.lbl_energy_err.setStyleSheet("font-size: 13pt; font-weight: bold; color: #4CAF50;")

        self.lbl_photon_err.setText(f"{photon_err:.2e}")
        if abs(photon_err) > 1e-2:
            self.lbl_photon_err.setStyleSheet("font-size: 13pt; font-weight: bold; color: #F44336;")
        else:
            self.lbl_photon_err.setStyleSheet("font-size: 13pt; font-weight: bold; color: #4CAF50;")

        self.lbl_step_size.setText(f"{h_m * 1e3:.4f} mm")
        if steps_per_sec > 0:
            self.lbl_calc_speed.setText(f"{steps_per_sec:.1f} steps/s")

    def update_calc_rate(self, steps_per_sec: float, eta_sec: float = 0.0) -> None:
        """Update live calculation rate and ETA readout."""
        self.lbl_calc_speed.setText(f"{steps_per_sec:.1f} steps/s")
        if eta_sec > 0:
            self.lbl_eta.setText(f"{eta_sec:.1f} s")
        else:
            self.lbl_eta.setText("-- s")

    def _copy_to_clipboard(self) -> None:
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(self.console.toPlainText())

    def _save_log(self) -> None:
        fpath, _ = QFileDialog.getSaveFileName(
            self, "Save Simulation Log", "gnlse_simulation_log.txt", "Text Files (*.txt)"
        )
        if fpath:
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(self.console.toPlainText())
            QMessageBox.information(self, "Save Log", f"Log saved to:\n{fpath}")
