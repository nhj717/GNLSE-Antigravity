"""File Navigator & Dispersion Data Inspector for GNLSE Simulator.

Provides an interactive dock in Tab 1 for browsing, inspecting, and previewing
experimental and simulated fiber dispersion files (.h5 and .csv), including
exact conversion between dispersion parameter D(lambda) and actual propagation constant beta(omega).
"""

from __future__ import annotations

import os
import csv
import math
import h5py
import numpy as np
import pyqtgraph as pg
from typing import Optional, List, Dict, Any
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QListWidget, QListWidgetItem, QFileDialog, QSplitter,
    QTableWidget, QTableWidgetItem, QGroupBox
)

from src.solver.config import C_CONST, DispersionConfig
from src.solver.operators import (
    _load_dispersion_file,
    evaluate_taylor_betas,
    extract_h5_aeff,
    compute_gamma_from_aeff,
)


class FileNavigatorWidget(QWidget):
    """Interactive browser and curve preview for .h5 and .csv dispersion data files."""

    file_selected = pyqtSignal(str)  # Emitted when user selects a file to load as active dispersion
    populate_manual_requested = pyqtSignal(list)  # Emitted with [b2, b3, b4, b5, b6, b7] in SI units
    aeff_evaluated = pyqtSignal(float, float)  # Emitted with (a_eff_m2, gamma_w_km) when A_eff is extracted

    def __init__(self, default_dir: Optional[str] = None, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.current_dir = default_dir or os.getcwd()
        self.active_file_path: Optional[str] = None
        self.carrier_wavelength_m: float = 850e-9  # default 850 nm
        self._latest_betas_si: list[float] = [0.0] * 6

        # Cached curves for preview switching
        self._cur_wl_nm: Optional[np.ndarray] = None
        self._cur_d_ps_nm_km: Optional[np.ndarray] = None
        self._cur_beta2_ps2_km: Optional[np.ndarray] = None
        self._cur_omega_rad_s: Optional[np.ndarray] = None
        self._cur_beta_rad_m: Optional[np.ndarray] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # Header box: Directory browse
        top_box = QHBoxLayout()
        self.btn_browse = QPushButton("📁 Browse Folder")
        self.btn_browse.clicked.connect(self._on_browse_dir)
        self.btn_add_file = QPushButton("＋ Add File")
        self.btn_add_file.clicked.connect(self._on_add_file)
        self.btn_refresh = QPushButton("🔄 Refresh")
        self.btn_refresh.clicked.connect(self._refresh_list)
        self.lbl_current_path = QLabel(f"Path: {self.current_dir}")
        self.lbl_current_path.setStyleSheet("color: #888888; font-size: 9pt;")
        top_box.addWidget(self.btn_browse)
        top_box.addWidget(self.btn_add_file)
        top_box.addWidget(self.btn_refresh)
        top_box.addWidget(self.lbl_current_path, 1)
        layout.addLayout(top_box)

        # Splitter: File list on top (compact), preview & inspector on bottom
        splitter = QSplitter(Qt.Orientation.Vertical)

        # File List Group (compact height for a couple of files)
        list_group = QGroupBox("Available Dispersion Data Files (.h5, .csv)")
        list_group.setMaximumHeight(135)
        list_layout = QVBoxLayout(list_group)
        list_layout.setContentsMargins(6, 12, 6, 6)
        self.file_list = QListWidget()
        self.file_list.setMaximumHeight(90)
        self.file_list.currentItemChanged.connect(self._on_file_selection_changed)
        list_layout.addWidget(self.file_list)
        splitter.addWidget(list_group)

        # Preview Group
        preview_group = QGroupBox("Dispersion Curve Preview & Physical β Extraction")
        preview_layout = QVBoxLayout(preview_group)
        preview_layout.setContentsMargins(6, 12, 6, 6)

        # Curve selector (D vs beta_2 vs beta)
        view_box = QHBoxLayout()
        view_box.addWidget(QLabel("Display Curve:"))
        self.combo_preview_mode = QComboBox()
        self.combo_preview_mode.addItems([
            "Dispersion D(λ) [ps/(nm·km)]",
            "GVD β₂(λ) [ps²/km]",
            "Propagation Constant β(ω) [rad/m]"
        ])
        self.combo_preview_mode.currentIndexChanged.connect(self._render_active_preview_curve)
        view_box.addWidget(self.combo_preview_mode, 1)
        preview_layout.addLayout(view_box)

        # Inline mini plot for D(lambda), beta2(lambda), or beta(omega)
        self.preview_plot = pg.PlotWidget()
        self.preview_plot.setTitle("Dispersion Profile D(λ) [ps/(nm·km)]", color="w", size="10pt")
        self.preview_plot.setLabel("bottom", "Wavelength [nm]")
        self.preview_plot.setLabel("left", "D [ps/(nm·km)]")
        self.preview_plot.showGrid(x=True, y=True, alpha=0.3)
        self.curve = self.preview_plot.plot(pen=pg.mkPen(color="#00FFCC", width=2))

        # Zero Dispersion Wavelength (ZDW) crosshairs
        self.zero_line = pg.InfiniteLine(pos=0.0, angle=0, pen=pg.mkPen("#888888", style=Qt.PenStyle.DashLine, width=1))
        self.zdw_line = pg.InfiniteLine(pos=0.0, angle=90, pen=pg.mkPen("#FFCC00", style=Qt.PenStyle.DashLine, width=1.5), label="ZDW")
        self.zdw_line.hide()
        self.preview_plot.addItem(self.zero_line)
        self.preview_plot.addItem(self.zdw_line)
        preview_layout.addWidget(self.preview_plot, 1)

        # Metadata Label
        self.lbl_metadata = QLabel("Select a file to inspect dataset structure.")
        self.lbl_metadata.setStyleSheet("font-family: monospace; font-size: 9pt; color: #CCCCCC;")
        preview_layout.addWidget(self.lbl_metadata)

        # HDF5 Selection Controls
        h5_layout = QFormLayout()
        h5_layout.setContentsMargins(0, 0, 0, 0)
        self.combo_group = QComboBox()
        self.combo_x = QComboBox()
        self.combo_y = QComboBox()
        h5_layout.addRow("HDF5 Group:", self.combo_group)
        h5_layout.addRow("X Dataset:", self.combo_x)
        h5_layout.addRow("Y Dataset:", self.combo_y)
        preview_layout.addLayout(h5_layout)

        self.combo_group.currentTextChanged.connect(self._on_h5_group_changed)
        self.combo_x.currentTextChanged.connect(self._update_h5_preview)
        self.combo_y.currentTextChanged.connect(self._update_h5_preview)

        # Physical Beta Evaluation & Transfer Panel
        beta_box = QVBoxLayout()
        self.lbl_beta_evaluated = QLabel("Physical β at λ₀: —")
        self.lbl_beta_evaluated.setStyleSheet("font-family: monospace; font-size: 9pt; color: #00FFCC; padding: 4px; background: #171b26; border-radius: 4px;")
        beta_box.addWidget(self.lbl_beta_evaluated)

        self.lbl_aeff_evaluated = QLabel("Effective Mode Area A_eff at λ₀: —")
        self.lbl_aeff_evaluated.setStyleSheet("font-family: monospace; font-size: 9pt; color: #FFB300; padding: 4px; background: #171b26; border-radius: 4px;")
        beta_box.addWidget(self.lbl_aeff_evaluated)

        self.btn_transfer_betas = QPushButton("📋 Transfer Evaluated β₂–β₇ to Manual Inputs")
        self.btn_transfer_betas.setStyleSheet("background-color: #313540; color: #63f7ff; font-weight: bold; padding: 5px;")
        self.btn_transfer_betas.setEnabled(False)
        self.btn_transfer_betas.clicked.connect(self._on_transfer_betas_clicked)
        beta_box.addWidget(self.btn_transfer_betas)
        preview_layout.addLayout(beta_box)

        # Action Button: Use as Active Dispersion
        self.btn_use_dispersion = QPushButton("✓ Use Selected File as Active Dispersion")
        self.btn_use_dispersion.setStyleSheet("background-color: #2E7D32; color: white; font-weight: bold; padding: 6px;")
        self.btn_use_dispersion.setEnabled(False)
        self.btn_use_dispersion.clicked.connect(self._on_use_file)
        preview_layout.addWidget(self.btn_use_dispersion)

        active_box = QHBoxLayout()
        active_box.addWidget(QLabel("Active Dispersion File:"))
        self.txt_import_path = QLineEdit()
        self.txt_import_path.setReadOnly(True)
        self.txt_import_path.setPlaceholderText("No active dispersion file selected")
        active_box.addWidget(self.txt_import_path)
        preview_layout.addLayout(active_box)

        splitter.addWidget(preview_group)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([110, 500])
        layout.addWidget(splitter)

        self._refresh_list()

    def set_center_wavelength(self, wl_m: float) -> None:
        """Update active carrier wavelength and re-evaluate physical beta coefficients."""
        if wl_m > 0:
            self.carrier_wavelength_m = float(wl_m)
            self._reevaluate_betas()

    def _on_browse_dir(self) -> None:
        selected_dir = QFileDialog.getExistingDirectory(self, "Select Directory with Dispersion Files", self.current_dir)
        if selected_dir:
            self.current_dir = selected_dir
            self.lbl_current_path.setText(f"Path: {self.current_dir}")
            self._refresh_list()

    def _refresh_list(self) -> None:
        self.file_list.clear()
        if not os.path.exists(self.current_dir):
            return

        supported_exts = (".h5", ".hdf5", ".csv")
        files = [f for f in sorted(os.listdir(self.current_dir)) if f.lower().endswith(supported_exts)]

        for f in files:
            full_path = os.path.join(self.current_dir, f)
            icon_str = "📊 " if f.lower().endswith(".csv") else "🗄️ "
            item = QListWidgetItem(f"{icon_str}{f}")
            item.setData(Qt.ItemDataRole.UserRole, full_path)
            self.file_list.addItem(item)

    def _on_file_selection_changed(self, current: Optional[QListWidgetItem], previous: Optional[QListWidgetItem]) -> None:
        if not current:
            self.btn_use_dispersion.setEnabled(False)
            self.btn_transfer_betas.setEnabled(False)
            self.active_file_path = None
            return

        full_path = current.data(Qt.ItemDataRole.UserRole)
        self.active_file_path = full_path
        self.btn_use_dispersion.setEnabled(True)
        self._inspect_file(full_path)

    def _inspect_file(self, file_path: str) -> None:
        """Parse and plot dispersion preview from .h5 or .csv with exact beta extraction."""
        self.active_file_path = file_path
        try:
            wl = None
            d = None
            if file_path.lower().endswith((".h5", ".hdf5")):
                self.combo_group.blockSignals(True)
                self.combo_group.clear()
                with h5py.File(file_path, "r") as h5f:
                    groups = self._traverse_h5(h5f)
                    self.combo_group.addItems(groups)

                    # Prefer a group that actually contains datasets rather than empty root
                    chosen_idx = 0
                    for idx, grp_path in enumerate(groups):
                        grp_node = h5f if grp_path == "/" else h5f[grp_path.rstrip("/")]
                        if any(isinstance(v, h5py.Dataset) for v in grp_node.values()):
                            chosen_idx = idx
                            break
                    self.combo_group.setCurrentIndex(chosen_idx)

                self.combo_group.blockSignals(False)
                if self.combo_group.count() > 0:
                    self._on_h5_group_changed(self.combo_group.itemText(chosen_idx))
                return

            elif file_path.lower().endswith(".csv"):
                with open(file_path, "r", encoding="utf-8") as f:
                    reader = csv.reader(f)
                    header = next(reader, None)
                    rows = [row for row in reader if row]
                    self.lbl_metadata.setText(f"CSV Header: {header} | Total Rows: {len(rows)}")

                    # Parse columns if numerical
                    if header and len(rows) > 0:
                        data = np.genfromtxt(file_path, delimiter=",", skip_header=1)
                        if data.ndim == 2 and data.shape[1] >= 2:
                            wl = data[:, 0]
                            d = data[:, 1]

            if wl is not None and d is not None:
                self._process_and_cache_curves(wl, d, x_is_wl_nm=True, y_is_d=True)
                self._render_active_preview_curve()
                self._reevaluate_betas()

        except Exception as exc:
            self.lbl_metadata.setText(f"Preview error: {exc}")
            self.zdw_line.hide()

    def _process_and_cache_curves(
        self,
        x_raw: np.ndarray,
        y_raw: np.ndarray,
        x_is_wl_nm: bool = True,
        y_is_d: bool = True,
        x_name: str = "",
        y_name: str = "",
    ) -> None:
        """Calculate coherent D(lambda), beta2(lambda), and beta(omega) curves."""
        x = np.asarray(x_raw, dtype=float)
        y = np.asarray(y_raw, dtype=float)

        # 1. Determine wavelength [m] and omega [rad/s]
        if np.all(x > 1e9) or "omega" in x_name or "freq" in x_name:
            omega = x
            wl_m = 2.0 * math.pi * C_CONST / np.maximum(omega, 1e-10)
        elif "um" in x_name or (np.all(x > 0.01) and np.all(x < 50.0)):
            wl_m = x * 1e-6
            omega = 2.0 * math.pi * C_CONST / wl_m
        elif np.all(x > 50.0) or "nm" in x_name or x_is_wl_nm:
            wl_m = x * 1e-9
            omega = 2.0 * math.pi * C_CONST / wl_m
        elif np.all(x < 1e-3):
            wl_m = x
            omega = 2.0 * math.pi * C_CONST / wl_m
        else:
            wl_m = x * 1e-9
            omega = 2.0 * math.pi * C_CONST / np.maximum(wl_m, 1e-12)

        wl_nm = wl_m * 1e9

        # 2. Determine y nature
        y_abs_max = float(np.max(np.abs(y)))
        is_d = y_is_d or (y_name in ("d", "disp", "dispersion", "d_ps_nm_km")) or (0.01 < y_abs_max < 1e5 and not "beta" in y_name)
        is_beta2 = (y_name in ("beta2", "b2")) or (1e-30 < y_abs_max < 1e-20)
        is_beta0 = (y_name in ("beta", "beta0", "b0")) or (y_abs_max > 1e5 and not is_d)

        # Sort ascending by omega for spline operations
        sort_w = np.argsort(omega)
        w_sorted = omega[sort_w]
        wl_m_sorted = wl_m[sort_w]
        wl_nm_sorted = wl_nm[sort_w]
        y_sorted = y[sort_w]

        from scipy.interpolate import CubicSpline
        if is_d:
            d_sorted = y_sorted
            # beta2 = - (lambda^2 / (2*pi*c)) * (D * 1e-6)
            b2_sorted = - (wl_m_sorted ** 2 / (2.0 * math.pi * C_CONST)) * (d_sorted * 1e-6)
            cs_b2 = CubicSpline(w_sorted, b2_sorted)
            cs_beta = cs_b2.antiderivative(2)
            beta_sorted = cs_beta(w_sorted)
        elif is_beta2:
            b2_sorted = y_sorted
            # D = - (2*pi*c / lambda^2) * beta2 / 1e-6
            d_sorted = - (2.0 * math.pi * C_CONST / (wl_m_sorted ** 2)) * b2_sorted / 1e-6
            cs_b2 = CubicSpline(w_sorted, b2_sorted)
            cs_beta = cs_b2.antiderivative(2)
            beta_sorted = cs_beta(w_sorted)
        else:
            # direct beta(omega)
            beta_sorted = y_sorted
            cs_beta = CubicSpline(w_sorted, beta_sorted)
            b2_sorted = cs_beta.derivative(2)(w_sorted)
            d_sorted = - (2.0 * math.pi * C_CONST / (wl_m_sorted ** 2)) * b2_sorted / 1e-6

        # Sort ascending by wavelength for plotting
        sort_wl = np.argsort(wl_nm_sorted)
        self._cur_wl_nm = wl_nm_sorted[sort_wl]
        self._cur_d_ps_nm_km = d_sorted[sort_wl]
        self._cur_beta2_ps2_km = (b2_sorted * 1e27)[sort_wl]  # s^2/m -> ps^2/km
        self._cur_omega_rad_s = w_sorted
        self._cur_beta_rad_m = beta_sorted

    def _render_active_preview_curve(self) -> None:
        """Render the chosen curve (D, beta2, or beta) into the preview plot."""
        if self._cur_wl_nm is None or len(self._cur_wl_nm) == 0:
            return

        mode = self.combo_preview_mode.currentIndex()
        if mode == 0:  # Dispersion D(lambda)
            self.preview_plot.setTitle("Dispersion Profile D(λ) [ps/(nm·km)]", color="w", size="10pt")
            self.preview_plot.setLabel("bottom", "Wavelength [nm]")
            self.preview_plot.setLabel("left", "D [ps/(nm·km)]")
            self.curve.setData(self._cur_wl_nm, self._cur_d_ps_nm_km)

            # Detect ZDW
            self._update_zdw(self._cur_wl_nm, self._cur_d_ps_nm_km)

        elif mode == 1:  # GVD beta2(lambda)
            self.preview_plot.setTitle("Group Velocity Dispersion β₂(λ) [ps²/km]", color="w", size="10pt")
            self.preview_plot.setLabel("bottom", "Wavelength [nm]")
            self.preview_plot.setLabel("left", "β₂ [ps²/km]")
            self.curve.setData(self._cur_wl_nm, self._cur_beta2_ps2_km)

            # Detect ZDW where beta2 crosses 0
            self._update_zdw(self._cur_wl_nm, self._cur_beta2_ps2_km)

        else:  # Propagation constant beta(omega)
            self.preview_plot.setTitle("Propagation Constant β(ω) [rad/m]", color="w", size="10pt")
            self.preview_plot.setLabel("bottom", "Frequency ω [×10¹⁵ rad/s]")
            self.preview_plot.setLabel("left", "β [rad/m]")
            w_disp = self._cur_omega_rad_s / 1e15
            self.curve.setData(w_disp, self._cur_beta_rad_m)
            self.zdw_line.hide()

    def _update_zdw(self, x: np.ndarray, y: np.ndarray) -> None:
        sign_changes = np.where(np.diff(np.sign(y)))[0]
        if len(sign_changes) > 0:
            idx = sign_changes[0]
            denom = y[idx + 1] - y[idx]
            if abs(denom) > 1e-12:
                zdw = float(x[idx] + (0.0 - y[idx]) * (x[idx + 1] - x[idx]) / denom)
                self.zdw_line.setValue(zdw)
                self.zdw_line.show()
                cur_meta = self.lbl_metadata.text()
                if "ZDW ≈" not in cur_meta:
                    self.lbl_metadata.setText(f"{cur_meta} | ZDW ≈ {zdw:.1f} nm")
            else:
                self.zdw_line.hide()
        else:
            self.zdw_line.hide()

    def _reevaluate_betas(self) -> None:
        """Evaluate Taylor dispersion coefficients beta_2 through beta_7 at carrier wavelength."""
        if self._cur_omega_rad_s is None or self._cur_beta_rad_m is None:
            self.lbl_beta_evaluated.setText("Physical β at λ₀: —")
            self.btn_transfer_betas.setEnabled(False)
            return

        w0 = 2.0 * math.pi * C_CONST / self.carrier_wavelength_m
        try:
            betas = evaluate_taylor_betas(self._cur_omega_rad_s, self._cur_beta_rad_m, w0, max_order=7)
            self._latest_betas_si = betas
            b2_ps2_km = betas[0] * 1e27  # s^2/m -> ps^2/km
            b3_ps3_km = betas[1] * 1e39  # s^3/m -> ps^3/km
            wl_nm = self.carrier_wavelength_m * 1e9

            self.lbl_beta_evaluated.setText(
                f"Physical β at λ₀={wl_nm:.1f}nm: "
                f"β₂={betas[0]:.3e} s²/m ({b2_ps2_km:+.2f} ps²/km) | "
                f"β₃={betas[1]:.3e} s³/m ({b3_ps3_km:+.3f} ps³/km)"
            )
            self.btn_transfer_betas.setEnabled(True)
        except Exception as exc:
            self.lbl_beta_evaluated.setText(f"β evaluation error: {exc}")
            self.btn_transfer_betas.setEnabled(False)

        self._reevaluate_aeff()

    def _reevaluate_aeff(self) -> None:
        """Extract A_eff and calculate gamma at current carrier wavelength if active file is HDF5."""
        if not self.active_file_path or not self.active_file_path.endswith((".h5", ".hdf5")):
            self.lbl_aeff_evaluated.setText("Effective Mode Area A_eff at λ₀: —")
            return

        grp_name = self.combo_group.currentText() if hasattr(self, "combo_group") else "/"
        try:
            aeff_m2 = extract_h5_aeff(self.active_file_path, grp_name, self.carrier_wavelength_m)
            if aeff_m2 is not None and aeff_m2 > 0:
                gamma_si, gamma_km = compute_gamma_from_aeff(aeff_m2, self.carrier_wavelength_m)
                aeff_um2 = aeff_m2 * 1e12
                wl_nm = self.carrier_wavelength_m * 1e9
                self.lbl_aeff_evaluated.setText(
                    f"A_eff(λ₀={wl_nm:.1f}nm) = {aeff_um2:.2f} µm² | Auto-tuned γ = {gamma_km:.2f} W⁻¹·km⁻¹"
                )
                self.aeff_evaluated.emit(aeff_m2, gamma_km)
            else:
                self.lbl_aeff_evaluated.setText("Effective Mode Area A_eff: Not present in file (manual γ)")
        except Exception as exc:
            self.lbl_aeff_evaluated.setText(f"A_eff extraction error: {exc}")

    def _on_transfer_betas_clicked(self) -> None:
        """Emit populate_manual_requested with the evaluated beta coefficients."""
        if self._latest_betas_si and any(abs(b) > 0 for b in self._latest_betas_si):
            self.populate_manual_requested.emit(self._latest_betas_si)

    def _on_add_file(self) -> None:
        fpath, _ = QFileDialog.getOpenFileName(self, "Add Dispersion File", self.current_dir, "Dispersion Files (*.h5 *.hdf5 *.csv)")
        if fpath:
            fname = os.path.basename(fpath)
            icon_str = "📊 " if fname.lower().endswith(".csv") else "🗄️ "
            item = QListWidgetItem(f"{icon_str}{fname}")
            item.setData(Qt.ItemDataRole.UserRole, fpath)
            self.file_list.addItem(item)
            self.file_list.setCurrentItem(item)

    def _on_use_file(self) -> None:
        if self.active_file_path:
            self.txt_import_path.setText(self.active_file_path)
            self.file_selected.emit(self.active_file_path)

    def _traverse_h5(self, node, path="/", groups=None):
        if groups is None: groups = []
        if isinstance(node, h5py.Group):
            groups.append(path)
            for key, val in node.items():
                self._traverse_h5(val, path + key + "/", groups)
        return groups

    def _on_h5_group_changed(self, group_path: str):
        if not self.active_file_path or not self.active_file_path.endswith((".h5", ".hdf5")):
            return
        try:
            with h5py.File(self.active_file_path, "r") as f:
                if group_path == "/": group = f
                else: group = f[group_path.rstrip("/")]

                datasets = [k for k, v in group.items() if isinstance(v, h5py.Dataset)]
                self.combo_x.blockSignals(True)
                self.combo_y.blockSignals(True)
                self.combo_x.clear()
                self.combo_y.clear()
                self.combo_x.addItems(datasets)
                self.combo_y.addItems(datasets)

                # auto-select
                if "wl_um" in datasets: self.combo_x.setCurrentText("wl_um")
                elif "wavelength" in datasets: self.combo_x.setCurrentText("wavelength")
                elif "wl" in datasets: self.combo_x.setCurrentText("wl")
                elif "omega" in datasets: self.combo_x.setCurrentText("omega")

                if "D" in datasets: self.combo_y.setCurrentText("D")
                elif "beta0" in datasets: self.combo_y.setCurrentText("beta0")
                elif "beta" in datasets: self.combo_y.setCurrentText("beta")
                elif "beta2" in datasets: self.combo_y.setCurrentText("beta2")

                self.combo_x.blockSignals(False)
                self.combo_y.blockSignals(False)
                self._update_h5_preview()
        except Exception:
            pass

    def _update_h5_preview(self):
        if not self.active_file_path or not self.active_file_path.endswith((".h5", ".hdf5")):
            return
        g = self.combo_group.currentText()
        x_name = self.combo_x.currentText()
        y_name = self.combo_y.currentText()
        if not x_name or not y_name:
            return
        try:
            with h5py.File(self.active_file_path, "r") as f:
                if g == "/": group = f
                else: group = f[g.rstrip("/")]
                raw_x = np.array(group[x_name])
                raw_y = np.array(group[y_name])
                y_val = np.real(raw_y) if np.iscomplexobj(raw_y) else raw_y

                self.lbl_metadata.setText(f"Group: {g} | X: {x_name} (shape {raw_x.shape}) | Y: {y_name} (shape {raw_y.shape})")
                self._process_and_cache_curves(raw_x, y_val, x_name=x_name, y_name=y_name)
                self._render_active_preview_curve()
                self._reevaluate_betas()
        except Exception as exc:
            self.lbl_metadata.setText(f"HDF5 error: {exc}")
