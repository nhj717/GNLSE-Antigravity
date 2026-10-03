"""Panel D: Chirp & Dispersion Reticle Plot for GNLSE Workstation.

Renders:
- Instantaneous Frequency Chirp δω(t) / (2π) [THz]
- Instantaneous Phase φ(t) [rad]
- Reticle crosshairs centered at (t=0, δf=0)
- Power threshold masking to suppress wing differentiator noise
"""

from __future__ import annotations

import math
from typing import Optional, Tuple
import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox

from src.gui.theme import (
    CYAN_ACCENT, PINK_ACCENT, TEXT_PRIMARY, TEXT_MUTED, BORDER_SUBTLE,
    SURFACE_LOW, BG_DARK
)


class ChirpReticleWidget(QWidget):
    """Panel D: Chirp and Phase Reticle Widget."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        # Plot Widget
        self.plot_widget = pg.PlotWidget()
        self.plot_item = self.plot_widget.getPlotItem()
        self.plot_item.setTitle("Chirp & Phase Reticle", color=TEXT_PRIMARY, size="11pt")
        self.plot_item.setLabel("bottom", "Time [ps]")
        self.plot_item.setLabel("left", "Chirp δf [THz]", color=CYAN_ACCENT)
        self.plot_item.showGrid(x=True, y=True, alpha=0.3)

        # Reticle Crosshair Lines (InfiniteLine)
        self.v_line = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen(color="#3a494a", width=1, style=Qt.PenStyle.DashLine))
        self.h_line = pg.InfiniteLine(angle=0, movable=False, pen=pg.mkPen(color="#3a494a", width=1, style=Qt.PenStyle.DashLine))
        self.plot_item.addItem(self.v_line, ignoreBounds=True)
        self.plot_item.addItem(self.h_line, ignoreBounds=True)

        # Dual ViewBox for Phase φ(t) on the right axis
        self.phase_view = pg.ViewBox()
        self.plot_item.showAxis("right")
        self.plot_item.getAxis("right").setLabel("Phase φ [rad]", color=PINK_ACCENT)
        self.plot_item.scene().addItem(self.phase_view)
        self.plot_item.getAxis("right").linkToView(self.phase_view)
        self.phase_view.setXLink(self.plot_item)

        # Curves
        # 1. Chirp Curve (Cyan)
        self.curve_chirp = self.plot_item.plot(
            pen=pg.mkPen(color=CYAN_ACCENT, width=2),
            name="Chirp δf(t) [THz]",
        )
        # 2. Phase Curve (Pink/Magenta) inside phase_view
        self.curve_phase = pg.PlotCurveItem(
            pen=pg.mkPen(color=PINK_ACCENT, width=1.5, style=Qt.PenStyle.DotLine),
            name="Phase φ(t) [rad]",
        )
        self.phase_view.addItem(self.curve_phase)

        # View update geometry hook
        self.plot_item.vb.sigResized.connect(self._update_views)

        # Legend
        self.legend = self.plot_item.addLegend(offset=(10, 10))
        self.legend.addItem(self.curve_chirp, "Chirp δf(t)")
        self.legend.addItem(self.curve_phase, "Phase φ(t)")

        # Default range
        self.set_x_range(-2.5, 2.5)
        self.plot_item.setYRange(-50.0, 50.0)
        self.phase_view.setYRange(-math.pi, math.pi)

        layout.addWidget(self.plot_widget)

    def _update_views(self) -> None:
        self.phase_view.setGeometry(self.plot_item.vb.sceneBoundingRect())
        self.phase_view.linkedViewChanged(self.plot_item.vb, self.phase_view.XAxis)

    def set_x_range(self, x_min: float, x_max: float) -> None:
        self.plot_item.setXRange(x_min, x_max, padding=0.0)

    def get_x_range(self) -> Tuple[float, float]:
        xr = self.plot_item.viewRange()[0]
        return float(xr[0]), float(xr[1])

    def update_data(
        self,
        t_s: np.ndarray,
        a_t: np.ndarray,
        threshold_fraction: float = 1e-3,
    ) -> None:
        """Compute and display instantaneous frequency chirp and unwrapped phase.
        
        Args:
            t_s: Time grid array in seconds [s].
            a_t: Complex field envelope A(t) [sqrt(W)].
            threshold_fraction: Fractional power threshold below which chirp is masked.
        """
        if len(t_s) < 2 or len(a_t) != len(t_s):
            return

        dt = float(t_s[1] - t_s[0])
        t_ps = t_s * 1e12
        power = np.abs(a_t) ** 2
        p_max = float(np.max(power))

        if p_max <= 0:
            self.curve_chirp.setData([], [])
            self.curve_phase.setData([], [])
            return

        # Phase φ(t) = unwrap(angle(A(t)))
        raw_phase = np.unwrap(np.angle(a_t))
        # Center phase around peak
        peak_idx = int(np.argmax(power))
        centered_phase = raw_phase - raw_phase[peak_idx]

        # Instantaneous angular frequency deviation δω(t) = - dφ / dt
        # Using centered finite differences
        delta_omega = -np.gradient(raw_phase, dt)
        # Chirp in THz: δf = δω / (2π * 10^12)
        chirp_thz = delta_omega / (2.0 * math.pi * 1e12)

        # Mask wings where power is below threshold to eliminate numerical differentiator noise
        mask = power >= (p_max * threshold_fraction)

        # Apply mask by inserting NaNs so lines break cleanly
        masked_chirp = np.where(mask, chirp_thz, np.nan)
        masked_phase = np.where(mask, centered_phase, np.nan)

        self.curve_chirp.setData(t_ps, masked_chirp)
        self.curve_phase.setData(t_ps, masked_phase)

        # Auto-scale phase view range
        valid_phase = masked_phase[mask]
        if len(valid_phase) > 0:
            p_min, p_max_val = float(np.min(valid_phase)), float(np.max(valid_phase))
            p_span = max(abs(p_max_val - p_min), 1.0)
            self.phase_view.setYRange(p_min - 0.1 * p_span, p_max_val + 0.1 * p_span)

        # Auto-scale chirp range reasonably
        valid_chirp = masked_chirp[mask]
        if len(valid_chirp) > 0:
            c_min, c_max = float(np.min(valid_chirp)), float(np.max(valid_chirp))
            c_span = max(abs(c_max - c_min), 5.0)
            self.plot_item.setYRange(c_min - 0.1 * c_span, c_max + 0.1 * c_span)

        self._update_views()
