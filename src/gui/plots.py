"""Scientific Plotting Canvas Components for GNLSE Simulator using pyqtgraph.

Provides:
- DensityMapWidget: 2D waterfall evolution heatmap with colorbar and colormap selection.
- LinePlotWidget: 1D pulse profile or spectrum comparison ('before' vs 'after').
- Data transformation helpers for time [ps] and wavelength [nm] in scientific units.
"""

from __future__ import annotations

import math
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
        colormap_name: str = "turbo",
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

        # Depth Scrubber Crosshair Indicator Line
        self.z_line = pg.InfiniteLine(
            angle=0, movable=False,
            pen=pg.mkPen(color="#00f5ff", width=1.5, style=Qt.PenStyle.DashLine)
        )
        self.z_line.setVisible(False)
        self.plot_item.addItem(self.z_line, ignoreBounds=True)

        # Colorbar
        self.colorbar = pg.ColorBarItem(
            values=(-40.0, 0.0),
            colorMap=colormap_name,
            label=cbar_label,
            limits=(-80.0, 0.0),
            rounding=1,
            orientation="horizontal",
        )
        self.colorbar.setImageItem(self.img_item, insert_in=self.plot_item)
        self.colorbar.setLevels((-40.0, 0.0))

        layout.addWidget(self.plot_widget)

    def set_z_indicator(self, z_val: Optional[float]) -> None:
        """Display or hide horizontal z position indicator crosshair."""
        if z_val is None:
            self.z_line.setVisible(False)
        else:
            self.z_line.setValue(z_val)
            self.z_line.setVisible(True)

    def set_colormap(self, cmap_name: str) -> None:
        """Switch active colormap (e.g. turbo, viridis, inferno, magma, plasma, jet)."""
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

    def set_x_range(self, x_min: float, x_max: float) -> None:
        """Set x-axis display range."""
        self.plot_item.setXRange(x_min, x_max, padding=0.0)

    def get_x_range(self) -> Tuple[float, float]:
        """Return the current x-axis display range (x_min, x_max)."""
        xr = self.plot_item.viewRange()[0]
        return float(xr[0]), float(xr[1])

    def set_y_limits(self, y_min: float, y_max: float) -> None:
        """Set y-axis display range."""
        self.plot_item.setYRange(y_min, y_max, padding=0.0)

    def get_y_range(self) -> Tuple[float, float]:
        """Return the current y-axis display range (y_min, y_max)."""
        yr = self.plot_item.viewRange()[1]
        return float(yr[0]), float(yr[1])

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
        self.default_y_label = y_label
        self.scale_mode = "linear" if not log_y else "log_db"
        self._raw_before_x: np.ndarray = np.array([])
        self._raw_before_y: np.ndarray = np.array([])
        self._raw_after_x: np.ndarray = np.array([])
        self._raw_after_y: np.ndarray = np.array([])

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
        self._raw_before_x = np.asarray(x, dtype=float)
        self._raw_before_y = np.asarray(y, dtype=float)
        self._render_curves()

    def set_after_curve(self, x: np.ndarray, y: np.ndarray, label: Optional[str] = None) -> None:
        self._raw_after_x = np.asarray(x, dtype=float)
        self._raw_after_y = np.asarray(y, dtype=float)
        self._render_curves()

    def set_scale_mode(self, mode: str) -> None:
        """Switch between 'linear' and 'log_db' display scaling."""
        if mode not in ("linear", "log_db"):
            return
        self.scale_mode = mode
        if mode == "log_db":
            self.plot_item.setLabel("left", "Normalized Intensity [dB]")
            self.set_y_limits(-60.0, 5.0)
        else:
            self.plot_item.setLabel("left", self.default_y_label)
            self.plot_item.enableAutoRange(axis="y")
        self._render_curves()

    def _render_curves(self) -> None:
        # Before curve
        if len(self._raw_before_x) > 0 and len(self._raw_before_y) > 0:
            if self.scale_mode == "log_db" and "Intensity" in self.default_y_label:
                y_max = max(float(np.max(self._raw_before_y)), 1e-30)
                y_disp = 10.0 * np.log10(np.maximum(self._raw_before_y, 1e-30) / y_max)
                self.curve_before.setData(self._raw_before_x, y_disp)
            else:
                self.curve_before.setData(self._raw_before_x, self._raw_before_y)

        # After curve
        if len(self._raw_after_x) > 0 and len(self._raw_after_y) > 0:
            if self.scale_mode == "log_db" and "Intensity" in self.default_y_label:
                y_max = max(float(np.max(self._raw_after_y)), 1e-30)
                y_disp = 10.0 * np.log10(np.maximum(self._raw_after_y, 1e-30) / y_max)
                self.curve_after.setData(self._raw_after_x, y_disp)
            else:
                self.curve_after.setData(self._raw_after_x, self._raw_after_y)

    def set_x_range(self, x_min: float, x_max: float) -> None:
        self.plot_item.setXRange(x_min, x_max, padding=0.0)

    def get_x_range(self) -> Tuple[float, float]:
        """Return the current x-axis display range (x_min, x_max)."""
        xr = self.plot_item.viewRange()[0]
        return float(xr[0]), float(xr[1])

    def set_y_limits(self, y_min: float, y_max: float) -> None:
        self.plot_item.setYRange(y_min, y_max, padding=0.0)

    def get_y_range(self) -> Tuple[float, float]:
        """Return the current y-axis display range (y_min, y_max)."""
        yr = self.plot_item.viewRange()[1]
        return float(yr[0]), float(yr[1])


def envelope_to_time_ps(t_s: np.ndarray) -> np.ndarray:
    """Convert time grid from seconds to picoseconds [ps]."""
    return t_s * 1e12


def envelope_to_wavelength_nm(
    omega_grid: np.ndarray,
    omega0: float,
    wl_min_nm: float = 300.0,
    wl_max_nm: float = 2500.0,
) -> Tuple[np.ndarray, np.ndarray]:
    """Convert angular frequency grid to wavelength [nm] and return sorted (wl_nm, sort_indices).

    Filters only physically relevant optical wavelengths lambda in [wl_min_nm, wl_max_nm] (default [300, 2500] nm),
    corresponding to omega_total in [2*pi*c / wl_max, 2*pi*c / wl_min].
    Permanently prevents DC division singularities from producing millimeter wavelengths (>= 10^6 nm).
    """
    omega_total = omega0 + omega_grid
    omega_min = (2.0 * np.pi * C_LIGHT) / (wl_max_nm * 1e-9)
    omega_max = (2.0 * np.pi * C_LIGHT) / (wl_min_nm * 1e-9)

    valid_mask = (omega_total >= omega_min) & (omega_total <= omega_max)

    valid_omega = omega_total[valid_mask]
    valid_wl_nm = (2.0 * np.pi * C_LIGHT / valid_omega) * 1e9
    valid_idx = np.where(valid_mask)[0]

    sort_order = np.argsort(valid_wl_nm)
    return valid_wl_nm[sort_order], valid_idx[sort_order]


def smooth_spectrum_osa(
    wl_nm: np.ndarray,
    psd_db: np.ndarray,
    resolution_nm: float = 1.0,
    db_floor: float = -200.0,
) -> np.ndarray:
    """Simulate Optical Spectrum Analyzer (OSA) resolution bandwidth smoothing via Gaussian convolution.

    Args:
        wl_nm: Wavelength grid in nanometers [nm] (must be 1D, monotonically sorted).
        psd_db: Normalized power spectral density in dB.
        resolution_nm: OSA resolution bandwidth FWHM in nm (e.g. 1.0 nm or 0.1 nm).
                       If <= 0.0, smoothing is bypassed.
        db_floor: Dynamic range floor in dB.

    Returns:
        Smoothed PSD array in dB, normalized to 0 dB max.
    """
    if resolution_nm <= 0.0 or len(psd_db) <= 1:
        return psd_db.copy()

    # Convert dB to linear PSD: S = 10^(psd_db / 10)
    s = 10.0 ** (psd_db / 10.0)

    # Construct Gaussian kernel in wavelength:
    # sigma = resolution_nm / (2 * sqrt(2 * ln 2)) ≈ resolution_nm / 2.35482
    sigma = resolution_nm / (2.0 * math.sqrt(2.0 * math.log(2.0)))
    d_lambda = float(np.mean(np.diff(wl_nm))) if len(wl_nm) > 1 else 1.0
    if abs(d_lambda) < 1e-15:
        return psd_db.copy()

    # Kernel half-width in points
    n_half = max(1, int(round(4.0 * sigma / abs(d_lambda))))
    kernel_x = np.arange(-n_half, n_half + 1) * d_lambda
    kernel = np.exp(-0.5 * (kernel_x / sigma) ** 2)
    kernel_sum = np.sum(kernel)
    if kernel_sum > 0:
        kernel = kernel / kernel_sum
    else:
        return psd_db.copy()

    # Convolve: S_smooth = np.convolve(S, kernel, mode='same')
    s_smooth = np.convolve(s, kernel, mode="same")

    # Convert back to dB:
    max_val = float(np.max(s_smooth))
    if max_val > 0.0:
        psd_smooth_db = 10.0 * np.log10(np.maximum(s_smooth / max_val, 10.0 ** (db_floor / 10.0)))
    else:
        psd_smooth_db = np.full_like(s_smooth, db_floor)

    return psd_smooth_db


def spectrum_to_db(
    a_w: np.ndarray,
    omega_grid: np.ndarray,
    omega0: float,
    db_floor: float = -200.0,
    wl_min_nm: float = 300.0,
    wl_max_nm: float = 2500.0,
    resolution_nm: Optional[float] = None,
) -> Tuple[np.ndarray, np.ndarray]:
    """Calculate normalized spectral density in dB vs wavelength in nm with Jacobian correction.

    Uses physically clamped wavelength array to strictly compute Jacobian 2*pi*c / lambda^2
    over valid optical wavelengths. Exact normalization:
    psd_db = 10.0 * np.log10((psd_lambda + 1e-30) / (np.max(psd_lambda) + 1e-30))
    """
    wl_nm, sort_idx = envelope_to_wavelength_nm(
        omega_grid, omega0, wl_min_nm=wl_min_nm, wl_max_nm=wl_max_nm
    )

    if len(wl_nm) == 0:
        return wl_nm, np.array([], dtype=float)

    # Power spectral density S(w) = |A_w|^2
    # Conversion to S(lambda): S(lambda) = S(w) * (2*pi*c / lambda^2)
    wl_m = wl_nm * 1e-9
    jacobian = 2.0 * np.pi * C_LIGHT / (wl_m**2)

    psd_lambda = np.abs(a_w[sort_idx]) ** 2 * jacobian
    psd_db = 10.0 * np.log10((psd_lambda + 1e-30) / (np.max(psd_lambda) + 1e-30))

    return wl_nm, psd_db
