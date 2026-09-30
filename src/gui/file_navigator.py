"""File Navigator & Dispersion Data Inspector for GNLSE Simulator.

Provides an interactive dock in Tab 1 for browsing, inspecting, and previewing
experimental and simulated fiber dispersion files (.h5 and .csv).
"""

from __future__ import annotations

import os
import csv
import h5py
import numpy as np
import pyqtgraph as pg
from typing import Optional, List, Dict, Any
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QFileDialog, QSplitter,
    QTableWidget, QTableWidgetItem, QGroupBox
)


class FileNavigatorWidget(QWidget):
    """Interactive browser and curve preview for .h5 and .csv dispersion data files."""

    file_selected = pyqtSignal(str)  # Emitted when user selects a file to load as active dispersion

    def __init__(self, default_dir: Optional[str] = None, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.current_dir = default_dir or os.getcwd()
        self.active_file_path: Optional[str] = None

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

        # Splitter: File list on top, preview & inspector on bottom
        splitter = QSplitter(Qt.Orientation.Vertical)

        # File List Group
        list_group = QGroupBox("Available Dispersion Data Files (.h5, .csv)")
        list_layout = QVBoxLayout(list_group)
        self.file_list = QListWidget()
        self.file_list.currentItemChanged.connect(self._on_file_selection_changed)
        list_layout.addWidget(self.file_list)
        splitter.addWidget(list_group)

        # Preview Group
        preview_group = QGroupBox("Dispersion Curve Preview & Metadata")
        preview_layout = QVBoxLayout(preview_group)

        # Inline mini plot for D(lambda) or beta(omega)
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
        preview_layout.addWidget(self.preview_plot)

        # Metadata Label
        self.lbl_metadata = QLabel("Select a file to inspect dataset structure.")
        self.lbl_metadata.setStyleSheet("font-family: monospace; font-size: 9pt; color: #CCCCCC;")
        preview_layout.addWidget(self.lbl_metadata)

        # Action Button: Use as Active Dispersion
        self.btn_use_dispersion = QPushButton("✓ Use Selected File as Active Dispersion")
        self.btn_use_dispersion.setStyleSheet("background-color: #2E7D32; color: white; font-weight: bold; padding: 6px;")
        self.btn_use_dispersion.setEnabled(False)
        self.btn_use_dispersion.clicked.connect(self._on_use_file)
        preview_layout.addWidget(self.btn_use_dispersion)

        splitter.addWidget(preview_group)
        layout.addWidget(splitter)

        self._refresh_list()

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
            self.active_file_path = None
            return

        full_path = current.data(Qt.ItemDataRole.UserRole)
        self.active_file_path = full_path
        self.btn_use_dispersion.setEnabled(True)
        self._inspect_file(full_path)

    def _inspect_file(self, file_path: str) -> None:
        """Parse and plot dispersion preview from .h5 or .csv."""
        try:
            wl = None
            d = None
            if file_path.lower().endswith((".h5", ".hdf5")):
                with h5py.File(file_path, "r") as h5f:
                    keys = list(h5f.keys())
                    self.lbl_metadata.setText(f"HDF5 Datasets: {keys}")
                    # Attempt preview
                    if "wavelength_nm" in h5f and "D" in h5f:
                        wl = np.array(h5f["wavelength_nm"])
                        d = np.array(h5f["D"])
                    elif "wavelength" in h5f and "D" in h5f:
                        wl = np.array(h5f["wavelength"])
                        d = np.array(h5f["D"])
                    elif "wavelength" in h5f and "beta" in h5f:
                        wl = np.array(h5f["wavelength"])
                        beta = np.array(h5f["beta"])
                        self.curve.setData(wl, beta)
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
                self.curve.setData(wl, d)
                # Check for Zero Dispersion Wavelength (ZDW)
                sign_changes = np.where(np.diff(np.sign(d)))[0]
                if len(sign_changes) > 0:
                    idx = sign_changes[0]
                    denom = d[idx + 1] - d[idx]
                    if abs(denom) > 1e-12:
                        zdw = float(wl[idx] + (0.0 - d[idx]) * (wl[idx + 1] - wl[idx]) / denom)
                        self.zdw_line.setValue(zdw)
                        self.zdw_line.show()
                        self.lbl_metadata.setText(f"{self.lbl_metadata.text()} | ZDW ≈ {zdw:.1f} nm")
                    else:
                        self.zdw_line.hide()
                else:
                    self.zdw_line.hide()
            else:
                self.zdw_line.hide()

        except Exception as exc:
            self.lbl_metadata.setText(f"Preview error: {exc}")
            self.zdw_line.hide()

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
            self.file_selected.emit(self.active_file_path)
