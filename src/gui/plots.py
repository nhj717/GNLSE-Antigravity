"""Scientific Plotting Canvas Components for GNLSE Simulator using pyqtgraph.

Provides:
- DensityMapWidget: 2D waterfall evolution heatmap with colorbar and colormap selection.
- LinePlotWidget: 1D pulse profile or spectrum comparison ('before' vs 'after').
- Data transformation helpers for time [ps] and wavelength [nm] in scientific units.
"""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QSlider
from typing import Optional, Tuple, List

# Enable antialiasing for publication-quality curves
pg.setConfigOptions(antialias=True, background="k", foreground="w")

C_LIGHT = 299792458.0  # Speed of light in m/s


class DensityMapWidget(QWidget):
    """2D color density map showing evolution vs distance z [cm] or power P0 [kW]."""

    def __init__(
        self,
        title: str,
        x_label: str,
        y_label: str,
        cbar_label: str = "Normalized Intensity [dB]",
        colormap_name: str = "inferno",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Plot Widget
        self.plot_widget = pg.PlotWidget()
        self.plot_item = self.plot_widget.getPlotItem()
        self.plot_item.setTitle(title, color="w", size="11pt")
        self.plot_item.setLabel("left", y_label)
        self.plot_item.setLabel("bottom", x_label)
        self.plot_item.showGrid(x=True, y=True, alpha=0.3)

        # Image Item
        self.img_item = pg.ImageItem()
        self.plot_item.addItem(self.img_item)

        # Colorbar
        self.colorbar = pg.ColorBarItem(
            values=(-40, 0),
            colorMap=colormap_name,
            label=cbar_label,
            limits=(-80, 0),
            rounding=1,
            orientation="horizontal",
        )
        self.colorbar.setImageItem(self.img_item, insert_in=self.plot_item)

        layout.addWidget(self.plot_widget)

    def set_colormap(self, cmap_name: str) -> None:
        """Switch active colormap (e.g. viridis, inferno, magma, plasma, jet)."""
        try:
            if cmap_name.lower() == "jet":
                pos = np.array([0.0, 0.35, 0.5, 0.65, 1.0])
                color = np.array([
                    [0, 0, 143, 255],
                    [0, 255, 255, 255],
                    [255, 255, 0, 255],
                    [255, 127, 0, 255],
                    [128, 0, 0, 255]
                ], dtype=np.ubyte)
                cmap = pg.ColorMap(pos, color)
                self.colorbar.setColorMap(cmap)
            else:
                self.colorbar.setColorMap(cmap_name)
        except Exception:
            pass

    def set_db_floor(self, db_min: float) -> None:
        """Adjust dynamic range floor."""
        self.colorbar.setLevels((db_min, 0.0))

    def update_data(self, data_db: np.ndarray, x_range: Tuple[float, float], y_range: Tuple[float, float]) -> None:
        """Update 2D image data and coordinate bounds.
        
        Args:
            data_db: 2D array of shape (N_steps, N_points) in decibels.
            x_range: (x_min, x_max) e.g. (-2.5, 2.5) for Time [ps].
            y_range: (y_min, y_max) e.g. (0.0, 10.0) for Distance [cm].
        """
        if data_db.size == 0:
            return

        # pyqtgraph expects shape (width, height)
        # Transpose so x is columns (horizontal) and y is rows (vertical)
        img_data = data_db.T

        self.img_item.setImage(img_data, autoLevels=False)
        x_min, x_max = x_range
        y_min, y_max = y_range
        dx = (x_max - x_min) / max(img_data.shape[0], 1)
        dy = (y_max - y_min) / max(img_data.shape[1], 1)

        self.img_item.setRect(pg.QtCore.QRectF(x_min, y_min, x_max - x_min, y_max - y_min))


class LinePlotWidget(QWidget):
    """1D scientific line plot with 'before' (z=0) and 'after' (z=current) curves."""

    def __init__(
        self,
        title: str,
        x_label: str,
        y_label: str,
        log_y: bool = False,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.plot_widget = pg.PlotWidget()
        self.plot_item = self.plot_widget.getPlotItem()
        self.plot_item.setTitle(title, color="w", size="11pt")
        self.plot_item.setLabel("left", y_label)
        self.plot_item.setLabel("bottom", x_label)
        self.plot_item.showGrid(x=True, y=True, alpha=0.3)

        # Legend
        self.legend = self.plot_item.addLegend(offset=(10, 10))

        # Curves
        # 'before' curve: Blue (Hex #0099FF)
        self.curve_before = self.plot_item.plot(
            pen=pg.mkPen(color="#0099FF", width=2),
            name="before (Input at z = 0)",
        )
        # 'after' curve: Orange (Hex #FF8800)
        self.curve_after = self.plot_item.plot(
            pen=pg.mkPen(color="#FF8800", width=2),
            name="after (Current z)",
        )

        layout.addWidget(self.plot_widget)

    def set_before_curve(self, x: np.ndarray, y: np.ndarray) -> None:
        self.curve_before.setData(x, y)

    def set_after_curve(self, x: np.ndarray, y: np.ndarray, label: Optional[str] = None) -> None:
        self.curve_after.setData(x, y)
        if label and self.legend:
            # Update legend text if custom label passed
            pass

    def set_x_range(self, x_min: float, x_max: float) -> None:
        self.plot_item.setXRange(x_min, x_max)

    def set_y_limits(self, y_min: float, y_max: float) -> None:
        self.plot_item.setYRange(y_min, y_max)


def envelope_to_time_ps(t_s: np.ndarray) -> np.ndarray:
    """Convert time grid from seconds to picoseconds [ps]."""
    return t_s * 1e12


def envelope_to_wavelength_nm(omega_grid: np.ndarray, omega0: float) -> Tuple[np.ndarray, np.ndarray]:
    """Convert angular frequency grid to wavelength [nm] and return sorted (wl_nm, sort_indices)."""
    omega_total = omega0 + omega_grid
    MIN_OMEGA = 1e12  # well below any optical frequency
    valid_mask = omega_total > MIN_OMEGA
    
    valid_omega = omega_total[valid_mask]
    valid_wl_nm = (2.0 * np.pi * C_LIGHT / valid_omega) * 1e9
    valid_idx = np.where(valid_mask)[0]
    
    sort_order = np.argsort(valid_wl_nm)
    return valid_wl_nm[sort_order], valid_idx[sort_order]


def spectrum_to_db(a_w: np.ndarray, omega_grid: np.ndarray, omega0: float, db_floor: float = -200.0) -> Tuple[np.ndarray, np.ndarray]:
    """Calculate normalized spectral density in dB vs wavelength in nm with Jacobian correction."""
    wl_nm, sort_idx = envelope_to_wavelength_nm(omega_grid, omega0)

    # Power spectral density S(w) = |A_w|^2
    # Conversion to S(lambda): S(lambda) = S(w) * (2*pi*c / lambda^2)
    wl_m = wl_nm * 1e-9
    jacobian = 2.0 * np.pi * C_LIGHT / (wl_m**2)

    psd_lambda = np.abs(a_w[sort_idx]) ** 2 * jacobian
    max_val = np.max(psd_lambda)
    if max_val > 0:
        psd_db = 10.0 * np.log10(np.maximum(psd_lambda / max_val, 10 ** (db_floor / 10.0)))
    else:
        psd_db = np.full_like(psd_lambda, db_floor)

    return wl_nm, psd_db
