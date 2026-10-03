"""Soliton Peak Tracking Table Widget for GNLSE Workstation.

Detects and analyzes localized soliton components in the propagated optical field:
- Soliton ID
- Central λ [nm]
- Temporal Delay τ [ps]
- FWHM Duration [fs]
- Peak Power [kW]
- Energy [nJ / pJ]
- Raman Index / Soliton Order N
"""

from __future__ import annotations

import math
from typing import Optional, List, Dict, Any
import numpy as np
import scipy.signal
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem, QHeaderView, QPushButton, QApplication
)

from src.gui.theme import (
    CYAN_ACCENT, PINK_ACCENT, PURPLE_ACCENT, TEXT_PRIMARY, TEXT_MUTED,
    SURFACE_LOW, SURFACE, SURFACE_HIGH, BORDER_SUBTLE
)
from src.solver.config import PulseConfig, FiberConfig, SimulationState


class SolitonTrackerWidget(QWidget):
    """Component for localized soliton component decomposition and peak tracking."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Header bar
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        self.lbl_title = QLabel("⚡ SOLITON PEAK TRACKING & DECOMPOSITION")
        self.lbl_title.setStyleSheet(f"""
            color: {CYAN_ACCENT};
            font-size: 10px;
            font-weight: bold;
            letter-spacing: 0.5px;
        """)
        header.addWidget(self.lbl_title)
        header.addStretch()

        self.btn_copy_table = QPushButton("📋 Copy Table")
        self.btn_copy_table.setStyleSheet("padding: 2px 8px; font-size: 10px;")
        self.btn_copy_table.clicked.connect(self._copy_to_clipboard)
        header.addWidget(self.btn_copy_table)

        layout.addLayout(header)

        # Table Widget
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "Soliton ID",
            "Central λ [nm]",
            "Delay τ [ps]",
            "FWHM [fs]",
            "Peak P₀ [kW]",
            "Energy [nJ]",
            "Order / Raman Index",
        ])

        # Header styling
        header_view = self.table.horizontalHeader()
        header_view.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setMinimumHeight(50)

        layout.addWidget(self.table)

    def clear(self) -> None:
        self.table.setRowCount(0)

    def update_from_state(
        self,
        state: SimulationState,
        pulse: Optional[PulseConfig] = None,
        fiber: Optional[FiberConfig] = None,
    ) -> None:
        """Detect temporal peaks and populate soliton decomposition parameters."""
        t_s = state.t
        a_t = state.a_t
        dt = float(t_s[1] - t_s[0]) if len(t_s) > 1 else 1e-15
        power_w = np.abs(a_t) ** 2
        p_max = float(np.max(power_w))

        self.table.setRowCount(0)
        if p_max <= 0:
            return

        # Find temporal peaks with prominence >= 3% of maximum peak
        min_distance = max(4, len(t_s) // 256)
        peak_indices, properties = scipy.signal.find_peaks(
            power_w,
            height=p_max * 0.03,
            prominence=p_max * 0.02,
            distance=min_distance,
        )

        if len(peak_indices) == 0:
            # Fallback to single primary peak
            peak_indices = np.array([int(np.argmax(power_w))])

        # Sort peaks by peak power descending (primary soliton first)
        sorted_order = np.argsort(power_w[peak_indices])[::-1]
        peak_indices = peak_indices[sorted_order]

        # Limit to top 8 solitons
        peak_indices = peak_indices[:8]

        # Optical constants for central wavelength estimate
        c_light = 299792458.0
        center_wl_nm = (pulse.center_wavelength * 1e9) if pulse else 850.0
        omega0 = pulse.omega_0 if pulse else (2.0 * math.pi * c_light / (center_wl_nm * 1e-9))
        beta2 = abs(fiber.dispersion.beta2) if (fiber and abs(fiber.dispersion.beta2) > 1e-35) else 2e-26
        gamma = fiber.gamma if (fiber and fiber.gamma > 0) else 1e-3

        # Compute instantaneous frequency for local central wavelength
        raw_phase = np.unwrap(np.angle(a_t))
        d_omega = -np.gradient(raw_phase, dt)

        self.table.setRowCount(len(peak_indices))

        for row_idx, p_idx in enumerate(peak_indices):
            p_val = float(power_w[p_idx])
            t_val_ps = float(t_s[p_idx]) * 1e12

            # FWHM duration
            half_p = p_val * 0.5
            # Scan left
            left_idx = p_idx
            while left_idx > 0 and power_w[left_idx] >= half_p:
                left_idx -= 1
            # Scan right
            right_idx = p_idx
            while right_idx < len(power_w) - 1 and power_w[right_idx] >= half_p:
                right_idx += 1

            fwhm_fs = float(t_s[right_idx] - t_s[left_idx]) * 1e15
            if fwhm_fs <= 0:
                fwhm_fs = dt * 1e15

            # Energy inside soliton lobe (integration from left valley to right valley)
            v_left = max(0, left_idx - (right_idx - left_idx))
            v_right = min(len(power_w), right_idx + (right_idx - left_idx) + 1)
            lobe_energy_nj = float(np.sum(power_w[v_left:v_right]) * dt) * 1e9

            # Central wavelength via instantaneous frequency
            local_omega = omega0 + d_omega[p_idx]
            if local_omega > 0:
                local_wl_nm = (2.0 * math.pi * c_light / local_omega) * 1e9
                # Bound to reasonable optical range
                local_wl_nm = min(max(local_wl_nm, 350.0), 2400.0)
            else:
                local_wl_nm = center_wl_nm

            # Soliton order N = sqrt(gamma * P0 * T0^2 / |beta2|)
            t0_s = (fwhm_fs * 1e-15) / 1.7627
            n_order = math.sqrt(max(gamma * p_val * (t0_s ** 2) / beta2, 0.0))

            # Raman index flag
            if row_idx == 0 and abs(t_val_ps) < 0.2:
                id_str = f"Soliton #1 (Pump/Core)"
            else:
                id_str = f"Soliton #{row_idx + 1}"

            # Create table items
            item_id = QTableWidgetItem(id_str)
            item_id.setForeground(Qt.GlobalColor.cyan)
            item_id.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            item_wl = QTableWidgetItem(f"{local_wl_nm:.1f}")
            item_wl.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            item_delay = QTableWidgetItem(f"{t_val_ps:+.2f}")
            item_delay.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            item_fwhm = QTableWidgetItem(f"{fwhm_fs:.1f}")
            item_fwhm.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            item_peak = QTableWidgetItem(f"{p_val / 1e3:.2f}")
            item_peak.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            item_energy = QTableWidgetItem(f"{lobe_energy_nj:.3f}")
            item_energy.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            item_order = QTableWidgetItem(f"N = {n_order:.2f}")
            item_order.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            self.table.setItem(row_idx, 0, item_id)
            self.table.setItem(row_idx, 1, item_wl)
            self.table.setItem(row_idx, 2, item_delay)
            self.table.setItem(row_idx, 3, item_fwhm)
            self.table.setItem(row_idx, 4, item_peak)
            self.table.setItem(row_idx, 5, item_energy)
            self.table.setItem(row_idx, 6, item_order)

    def _copy_to_clipboard(self) -> None:
        """Copy formatted table content to system clipboard as TSV."""
        rows = self.table.rowCount()
        cols = self.table.columnCount()
        if rows == 0:
            return

        headers = [self.table.horizontalHeaderItem(c).text() for c in range(cols)]
        lines = ["\t".join(headers)]

        for r in range(rows):
            row_vals = []
            for c in range(cols):
                item = self.table.item(r, c)
                row_vals.append(item.text() if item else "")
            lines.append("\t".join(row_vals))

        tsv_data = "\n".join(lines)
        QApplication.clipboard().setText(tsv_data)
        self.btn_copy_table.setText("✅ Copied!")
        from PyQt6.QtCore import QTimer
        self._reset_timer = QTimer(self)
        self._reset_timer.setSingleShot(True)
        self._reset_timer.timeout.connect(lambda: self.btn_copy_table.setText("📋 Copy Table"))
        self._reset_timer.start(1500)
