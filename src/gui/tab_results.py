"""Tab 2: Results & Visualization Workstation for GNLSE Simulator.

Multi-panel Cyberpunk Laboratory Canvas:
- KPI Summary Banner (Soliton Dynamics N, Scales L_D / L_NL, Bandwidth, Raman Shift, Energy Error)
- Panel A: Temporal Pulse Evolution |A(z,t)|² (with Linear and Log dB scale toggles)
- Panel B: Spectral Power Density S(λ) [dBm / nm]
- Panel C: 2D Waterfall / Spectrogram Colormap with propagation depth slider (z-slider) and animation controls
- Soliton Peak Tracking Table: Styled QTableWidget with localized soliton components
- Publication & Data Pipeline: Export Vector SVG/PDF, Full Mesh .h5, NumPy, LaTeX PGFPlots Snippet
"""

from __future__ import annotations

import os
import time
import csv
import math
import h5py
import numpy as np
from typing import Optional, List, Tuple
from PyQt6.QtCore import Qt, QTimer, pyqtSlot
from PyQt6.QtGui import QPainter, QPdfWriter
try:
    from PyQt6.QtSvg import QSvgGenerator
except ImportError:
    QSvgGenerator = None
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QPushButton, QFileDialog, QSlider, QDoubleSpinBox, QSplitter,
    QGridLayout, QMessageBox, QTabWidget, QApplication,
    QScrollArea, QButtonGroup, QFrame
)

from src.solver.config import SimulationState, PulseConfig, FiberConfig
from .plots import (
    DensityMapWidget,
    LinePlotWidget,
    envelope_to_time_ps,
    spectrum_to_db,
)
from .theme import (
    CYAN_ACCENT, CYAN_BRIGHT, PINK_ACCENT, PURPLE_ACCENT, GREEN_SUCCESS, AMBER_WARNING,
    SURFACE_LOW, SURFACE, SURFACE_HIGH, TEXT_PRIMARY, TEXT_MUTED, BORDER_SUBTLE,
    BORDER_COLOR, BG_DARK
)
from .kpi_banner import KpiBannerWidget
from .soliton_tracker import SolitonTrackerWidget
from .config_loader import load_gui_config


class TabResultsWidget(QWidget):
    """Tab 2 results workstation with multi-panel visualization and publication pipeline."""

    def __init__(self, parent: Optional[QWidget] = None, config: Optional[dict] = None) -> None:
        super().__init__(parent)

        # Load GUI formatting preferences from config.json (or passed config)
        if config is None:
            full_cfg = load_gui_config()
            config = full_cfg.get("results_view", {})
        self.config = config

        self.current_sim_type = "spectrum_vs_distance"
        def_domain = str(config.get("default_domain", "FREQUENCY DOMAIN")).lower()
        self.domain_mode: str = "time" if "time" in def_domain else "freq"
        self.default_colormap: str = str(config.get("default_colormap", "turbo"))
        self.default_db_floor: float = float(config.get("default_db_floor", -40.0))
        self.default_time_range: List[float] = list(config.get("time_range_ps", [-2.5, 2.5]))
        self.default_wl_range: List[float] = list(config.get("wl_range_nm", [500.0, 1200.0]))
        self.v_splitter_sizes: List[int] = list(config.get("v_splitter_sizes", [950, 50]))
        self.diagnostics_minimized: bool = bool(config.get("diagnostics_minimized", True))

        self.cached_history: List[SimulationState] = []
        self.cached_final_state: Optional[SimulationState] = None
        self.initial_state: Optional[SimulationState] = None
        self.center_wavelength: float = 1550e-9
        self.omega0: float = 2.0 * np.pi * 299792458.0 / self.center_wavelength
        self.MAX_DISPLAY_BINS: int = 1024
        self.active_pulse_config: Optional[PulseConfig] = None
        self.active_fiber_config: Optional[FiberConfig] = None

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(6, 6, 6, 6)
        main_layout.setSpacing(5)

        # -------------------------------------------------------------
        # 1. KPI Summary Banner (Collapsible)
        # -------------------------------------------------------------
        self.kpi_banner = KpiBannerWidget()
        main_layout.addWidget(self.kpi_banner)

        # -------------------------------------------------------------
        # 2. Results Header Toolbar (Domain Selector + Title + Actions)
        # -------------------------------------------------------------
        header_bar = QHBoxLayout()
        header_bar.setContentsMargins(2, 2, 2, 2)
        header_bar.setSpacing(6)

        # Domain View Selector Segmented Group (Time Domain & Frequency Domain only)
        lbl_view = QLabel("VIEW:")
        lbl_view.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 10px; font-weight: bold; letter-spacing: 0.5px;")
        header_bar.addWidget(lbl_view)

        self.btn_group_domain = QButtonGroup(self)
        self.btn_group_domain.setExclusive(True)

        self.btn_view_time = QPushButton("⏱ TIME DOMAIN")
        self.btn_view_time.setCheckable(True)
        self.btn_view_time.setChecked(self.domain_mode == "time")
        self.btn_view_time.setToolTip("Focus exclusively on temporal evolution and envelope |A(z,t)|²")
        self.btn_view_time.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_group_domain.addButton(self.btn_view_time)

        self.btn_view_freq = QPushButton("🌊 FREQUENCY DOMAIN")
        self.btn_view_freq.setCheckable(True)
        self.btn_view_freq.setChecked(self.domain_mode == "freq")
        self.btn_view_freq.setToolTip("Focus exclusively on spectral evolution and output power density S(λ)")
        self.btn_view_freq.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_group_domain.addButton(self.btn_view_freq)

        self.btn_view_time.clicked.connect(lambda: self.set_domain_mode("time"))
        self.btn_view_freq.clicked.connect(lambda: self.set_domain_mode("freq"))

        header_bar.addWidget(self.btn_view_time)
        header_bar.addWidget(self.btn_view_freq)

        sep1 = QFrame()
        sep1.setFrameShape(QFrame.Shape.VLine)
        sep1.setStyleSheet(f"color: {BORDER_SUBTLE};")
        header_bar.addWidget(sep1)

        self.lbl_title = QLabel("Simulation Results — Idle")
        self.lbl_title.setStyleSheet(f"font-size: 11pt; font-weight: bold; color: {CYAN_ACCENT};")
        header_bar.addWidget(self.lbl_title, 1)

        # KPI Telemetry Toggle Button
        self.btn_toggle_kpi = QPushButton("📊 KPI Telemetry ▾")
        self.btn_toggle_kpi.setToolTip("Expand or collapse the KPI telemetry banner")
        self.btn_toggle_kpi.setStyleSheet(f"background-color: {SURFACE_LOW}; color: {CYAN_ACCENT}; border: 1px solid {BORDER_SUBTLE}; border-radius: 4px; padding: 4px 8px; font-weight: bold; font-size: 10px;")
        self.btn_toggle_kpi.clicked.connect(self._toggle_kpi_banner)
        header_bar.addWidget(self.btn_toggle_kpi)

        # LaTeX Snippet Button
        self.btn_copy_pgfplots = QPushButton("📋 Copy LaTeX")
        self.btn_copy_pgfplots.setStyleSheet(f"background-color: {PURPLE_ACCENT}; color: white; font-weight: bold; padding: 4px 8px; font-size: 10px; border-radius: 4px;")
        self.btn_copy_pgfplots.setToolTip("Copy publication-ready LaTeX TikZ/PGFPlots code to clipboard")
        self.btn_copy_pgfplots.clicked.connect(self._copy_pgfplots_snippet)
        header_bar.addWidget(self.btn_copy_pgfplots)

        # Export Button
        self.btn_export = QPushButton("💾 Export Results...")
        self.btn_export.setStyleSheet("background-color: #2E7D32; color: white; font-weight: bold; padding: 4px 10px; font-size: 10px; border-radius: 4px;")
        self.btn_export.clicked.connect(self._on_export_clicked)
        header_bar.addWidget(self.btn_export)

        main_layout.addLayout(header_bar)

        # -------------------------------------------------------------
        # 3. Contextual Controls Strip
        # -------------------------------------------------------------
        controls_bar = QHBoxLayout()
        controls_bar.setContentsMargins(4, 1, 4, 1)
        controls_bar.setSpacing(10)

        # Panel A Scale Toggle (Linear / Log dB)
        self.box_pulse_scale = QWidget()
        box_ps_l = QHBoxLayout(self.box_pulse_scale)
        box_ps_l.setContentsMargins(0, 0, 0, 0)
        box_ps_l.setSpacing(3)
        lbl_scale = QLabel("Pulse Scale:")
        lbl_scale.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 10px; font-weight: bold;")
        box_ps_l.addWidget(lbl_scale)

        self.btn_scale_linear = QPushButton("Linear [W]")
        self.btn_scale_linear.setCheckable(True)
        self.btn_scale_linear.setChecked(True)
        self.btn_scale_linear.setStyleSheet(f"padding: 3px 8px; font-size: 10px; background-color: {SURFACE_HIGH};")

        self.btn_scale_log = QPushButton("Log [dB]")
        self.btn_scale_log.setCheckable(True)
        self.btn_scale_log.setChecked(False)
        self.btn_scale_log.setStyleSheet(f"padding: 3px 8px; font-size: 10px; background-color: {SURFACE_LOW};")

        self.btn_scale_linear.clicked.connect(lambda: self._set_pulse_scale("linear"))
        self.btn_scale_log.clicked.connect(lambda: self._set_pulse_scale("log_db"))

        box_ps_l.addWidget(self.btn_scale_linear)
        box_ps_l.addWidget(self.btn_scale_log)
        controls_bar.addWidget(self.box_pulse_scale)

        # Colormap dropdown
        lbl_cmap = QLabel("Colormap:")
        lbl_cmap.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 10px; font-weight: bold;")
        controls_bar.addWidget(lbl_cmap)
        self.combo_cmap = QComboBox()
        self.combo_cmap.addItems(["turbo", "viridis", "inferno", "magma", "plasma", "jet"])
        self.combo_cmap.setCurrentText(self.default_colormap)
        self.combo_cmap.currentTextChanged.connect(self._on_cmap_changed)
        controls_bar.addWidget(self.combo_cmap)

        # dB Range slider
        lbl_floor = QLabel("Floor:")
        lbl_floor.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 10px; font-weight: bold;")
        controls_bar.addWidget(lbl_floor)
        self.slider_db = QSlider(Qt.Orientation.Horizontal)
        self.slider_db.setRange(20, 80)
        self.slider_db.setValue(int(abs(self.default_db_floor)))
        self.slider_db.setFixedWidth(80)
        self.slider_db.valueChanged.connect(self._on_db_slider_changed)
        self.lbl_db_val = QLabel(f"-{int(abs(self.default_db_floor))} dB")
        controls_bar.addWidget(self.slider_db)
        controls_bar.addWidget(self.lbl_db_val)

        controls_bar.addStretch()
        main_layout.addLayout(controls_bar)

        # -------------------------------------------------------------
        # 4. Dynamic Plot Grid Container (Scrollable with Tall Min Heights)
        # -------------------------------------------------------------
        self.plot_container = QWidget()
        self.grid_layout = QGridLayout(self.plot_container)
        self.grid_layout.setContentsMargins(0, 0, 0, 0)
        self.grid_layout.setSpacing(6)

        # Instantiate plots with generous portrait heights (more height than width)
        self.plot_time_2d = DensityMapWidget(
            title="Time domain",
            x_label="Time [ps]",
            y_label="Distance [cm]",
            cbar_label="Normalized Intensity [dB]",
            colormap_name=self.default_colormap,
        )
        self.plot_freq_2d = DensityMapWidget(
            title="Freq. domain",
            x_label="Wavelength [nm]",
            y_label="Distance [cm]",
            cbar_label="Normalized Spectral Density [dB]",
            colormap_name=self.default_colormap,
        )
        self.plot_time_1d = LinePlotWidget(
            title="Time domain",
            x_label="Time [ps]",
            y_label="Intensity [W]",
        )
        self.plot_freq_1d = LinePlotWidget(
            title="Freq. domain",
            x_label="Wavelength [nm]",
            y_label="Spectral Power [dB]",
        )

        # Enforce generous minimum heights so plots never collapse into horizontal ribbons
        self.plot_time_2d.setMinimumHeight(380)
        self.plot_freq_2d.setMinimumHeight(380)
        self.plot_time_1d.setMinimumHeight(340)
        self.plot_freq_1d.setMinimumHeight(340)

        # Default view ranges from config
        self.plot_time_1d.set_x_range(self.default_time_range[0], self.default_time_range[1])
        self.plot_time_2d.set_x_range(self.default_time_range[0], self.default_time_range[1])
        self.plot_freq_1d.set_x_range(self.default_wl_range[0], self.default_wl_range[1])
        self.plot_freq_2d.set_x_range(self.default_wl_range[0], self.default_wl_range[1])
        self.plot_freq_1d.set_y_limits(-200.0, 10.0)
        self.plot_time_2d.set_db_floor(self.default_db_floor)
        self.plot_freq_2d.set_db_floor(self.default_db_floor)

        # Wavelength Window Control Toolbar for Freq View (placed in controls_bar for perfect graph alignment)
        self.box_wl_toolbar = QWidget()
        self.wl_toolbar = QHBoxLayout(self.box_wl_toolbar)
        self.wl_toolbar.setContentsMargins(0, 0, 0, 0)
        self.wl_toolbar.setSpacing(4)
        lbl_wl = QLabel("λ Range [nm]:")
        lbl_wl.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 10px; font-weight: bold;")
        self.wl_toolbar.addWidget(lbl_wl)

        self.spin_wl_min = QDoubleSpinBox()
        self.spin_wl_min.setRange(100.0, 5000.0)
        self.spin_wl_min.setValue(self.default_wl_range[0])
        self.spin_wl_min.setDecimals(1)

        self.spin_wl_max = QDoubleSpinBox()
        self.spin_wl_max.setRange(100.0, 5000.0)
        self.spin_wl_max.setValue(self.default_wl_range[1])
        self.spin_wl_max.setDecimals(1)

        self.btn_wl_reset = QPushButton("Reset Fit")
        self.btn_wl_reset.setStyleSheet(f"padding: 3px 6px; font-size: 10px; background-color: {SURFACE_LOW};")
        self.btn_hult_window = QPushButton("🎯 Hult Window (500–1200 nm)")
        self.btn_hult_window.setStyleSheet(f"padding: 3px 6px; font-size: 10px; background-color: {SURFACE_LOW};")

        self.wl_toolbar.addWidget(self.spin_wl_min)
        self.wl_toolbar.addWidget(QLabel("to"))
        self.wl_toolbar.addWidget(self.spin_wl_max)
        self.wl_toolbar.addWidget(self.btn_wl_reset)
        self.wl_toolbar.addWidget(self.btn_hult_window)

        # Place box_wl_toolbar in controls_bar right before the stretch
        controls_bar.insertWidget(controls_bar.count() - 1, self.box_wl_toolbar)

        self.spin_wl_min.valueChanged.connect(self._on_wl_range_changed)
        self.spin_wl_max.valueChanged.connect(self._on_wl_range_changed)
        self.btn_wl_reset.clicked.connect(self._on_wl_reset_clicked)
        self.btn_hult_window.clicked.connect(self._on_hult_window_clicked)
        self._on_wl_range_changed()

        # Scroll area wrapping plot container to ensure tall graphs remain unconstrained
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll_area.setWidget(self.plot_container)
        self.scroll_area.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        # Splitter between Main Visualizer and Bottom Diagnostics & Soliton Pipeline
        v_splitter = QSplitter(Qt.Orientation.Vertical)
        v_splitter.addWidget(self.scroll_area)

        # -------------------------------------------------------------
        # 5. Interactive Propagation Scrubber Toolbar
        # -------------------------------------------------------------
        self.bottom_container = QWidget()
        bottom_layout = QVBoxLayout(self.bottom_container)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(4)

        scrubber_bar = QHBoxLayout()
        scrubber_bar.setContentsMargins(4, 2, 4, 2)
        scrubber_bar.setSpacing(6)
        scrubber_bar.addWidget(QLabel("z-Scrubber:"))

        self.btn_step_prev = QPushButton("◀ Step")
        self.btn_step_prev.setEnabled(False)
        self.btn_step_prev.clicked.connect(self._step_back)
        scrubber_bar.addWidget(self.btn_step_prev)

        self.btn_play_anim = QPushButton("▶ Play Evolution")
        self.btn_play_anim.setEnabled(False)
        self.btn_play_anim.setStyleSheet(f"background-color: {SURFACE_HIGH}; color: {CYAN_ACCENT}; font-weight: bold;")
        self.btn_play_anim.clicked.connect(self._toggle_animation)
        scrubber_bar.addWidget(self.btn_play_anim)

        self.btn_step_next = QPushButton("Step ▶")
        self.btn_step_next.setEnabled(False)
        self.btn_step_next.clicked.connect(self._step_forward)
        scrubber_bar.addWidget(self.btn_step_next)

        self.slider_z = QSlider(Qt.Orientation.Horizontal)
        self.slider_z.setRange(0, 0)
        self.slider_z.setEnabled(False)
        self.slider_z.valueChanged.connect(self._on_scrubber_changed)
        scrubber_bar.addWidget(self.slider_z, 1)

        self.lbl_scrub_depth = QLabel("z = 0.00 cm / 0.00 cm")
        self.lbl_scrub_depth.setStyleSheet(f"font-weight: bold; color: {CYAN_ACCENT}; min-width: 150px;")
        scrubber_bar.addWidget(self.lbl_scrub_depth)

        # Bottom drawer toggle button
        self.btn_toggle_bottom = QPushButton("Diagnostics & Solitons ▾")
        self.btn_toggle_bottom.setToolTip("Expand or collapse bottom diagnostics and soliton table")
        self.btn_toggle_bottom.setStyleSheet(f"background-color: {SURFACE_LOW}; color: {TEXT_PRIMARY}; border: 1px solid {BORDER_SUBTLE}; border-radius: 4px; padding: 3px 8px; font-size: 10px; font-weight: bold;")
        self.btn_toggle_bottom.clicked.connect(self._toggle_bottom_panel)
        scrubber_bar.addWidget(self.btn_toggle_bottom)

        bottom_layout.addLayout(scrubber_bar)

        # -------------------------------------------------------------
        # 6. Bottom Tabs: Soliton Tracker & Data Pipeline
        # -------------------------------------------------------------
        self.sub_tabs = QTabWidget()
        self.sub_tabs.setMinimumHeight(0)


        # Sub-Tab 2: Soliton Peak Tracking Table
        self.soliton_tracker = SolitonTrackerWidget()
        self.sub_tabs.addTab(self.soliton_tracker, "⚡ Soliton Peak Tracking")

        # Sub-Tab 3: Publication & Data Pipeline
        pub_widget = QWidget()
        pub_layout = QHBoxLayout(pub_widget)
        pub_layout.setContentsMargins(12, 12, 12, 12)
        pub_layout.setSpacing(12)

        card_vec = QWidget()
        cv_layout = QVBoxLayout(card_vec)
        cv_layout.addWidget(QLabel("<b>Vector Publication Graphics</b>"))
        btn_svg = QPushButton("📄 Export Vector SVG (.svg)")
        btn_svg.clicked.connect(lambda: self._export_specific_format("svg"))
        btn_pdf = QPushButton("📑 Export Publication PDF (.pdf)")
        btn_pdf.clicked.connect(lambda: self._export_specific_format("pdf"))
        btn_png = QPushButton("🖼️ Export High-Res PNG (.png)")
        btn_png.clicked.connect(lambda: self._export_specific_format("png"))
        cv_layout.addWidget(btn_svg)
        cv_layout.addWidget(btn_pdf)
        cv_layout.addWidget(btn_png)
        pub_layout.addWidget(card_vec)

        card_num = QWidget()
        cn_layout = QVBoxLayout(card_num)
        cn_layout.addWidget(QLabel("<b>Numerical Data Pipeline</b>"))
        btn_h5 = QPushButton("💾 Save Full Mesh HDF5 (.h5)")
        btn_h5.clicked.connect(lambda: self._export_specific_format("h5"))
        btn_npz = QPushButton("📦 Save NumPy Compressed (.npz)")
        btn_npz.clicked.connect(self._export_numpy_compressed)
        btn_csv = QPushButton("📊 Export CSV Matrix (.csv)")
        btn_csv.clicked.connect(lambda: self._export_specific_format("csv"))
        cn_layout.addWidget(btn_h5)
        cn_layout.addWidget(btn_npz)
        cn_layout.addWidget(btn_csv)
        pub_layout.addWidget(card_num)

        card_pgf = QWidget()
        cp_layout = QVBoxLayout(card_pgf)
        cp_layout.addWidget(QLabel("<b>LaTeX Scientific Snippets</b>"))
        btn_copy_pgf = QPushButton("📋 Copy LaTeX PGFPlots Spectrum")
        btn_copy_pgf.setStyleSheet(f"background-color: {PURPLE_ACCENT}; color: white; font-weight: bold;")
        btn_copy_pgf.clicked.connect(self._copy_pgfplots_snippet)
        cp_layout.addWidget(btn_copy_pgf)
        lbl_hint = QLabel("Generates publication-ready TikZ / PGFPlots code with automatic coordinate decimation and SI axes.")
        lbl_hint.setWordWrap(True)
        lbl_hint.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 10px;")
        cp_layout.addWidget(lbl_hint)
        cp_layout.addStretch()
        pub_layout.addWidget(card_pgf)

        self.sub_tabs.addTab(pub_widget, "📤 Publication & Data Pipeline")

        self.bottom_container.setMinimumHeight(0)
        bottom_layout.addWidget(self.sub_tabs)
        v_splitter.addWidget(self.bottom_container)
        v_splitter.setStretchFactor(0, 9)
        v_splitter.setStretchFactor(1, 1)
        v_splitter.setCollapsible(0, False)
        v_splitter.setCollapsible(1, True)
        self.v_splitter = v_splitter
        self.v_splitter.splitterMoved.connect(self._on_splitter_moved)

        # Initial bottom drawer state (minimized by default from config)
        if self.diagnostics_minimized:
            self.sub_tabs.setVisible(False)
            self.btn_toggle_bottom.setText("Diagnostics & Solitons ▸")
        else:
            self.sub_tabs.setVisible(True)
            self.btn_toggle_bottom.setText("Diagnostics & Solitons ▾")
        self.v_splitter.setSizes(self.v_splitter_sizes)

        main_layout.addWidget(v_splitter, 1)

        # Animation timer
        self.anim_timer = QTimer(self)
        self.anim_timer.setInterval(50)
        self.anim_timer.timeout.connect(self._advance_animation)

        # Initialize button styles and default layout
        self._update_domain_button_styles()
        self.set_simulation_type("spectrum_vs_distance")

    def _on_splitter_moved(self, pos: int, index: int) -> None:
        """Dynamically manage sub_tabs visibility when user drags splitter handle."""
        sizes = self.v_splitter.sizes()
        total_h = self.v_splitter.height()
        bottom_h = (total_h - pos) if (pos > 0 and total_h > pos) else (sizes[1] if len(sizes) >= 2 else 0)
        is_expanded = (bottom_h > 55) or (len(sizes) >= 2 and sum(sizes) > 0 and sizes[1] / sum(sizes) > 0.15)
        if is_expanded and not self.sub_tabs.isVisible():
            self.sub_tabs.setVisible(True)
            self.btn_toggle_bottom.setText("Diagnostics & Solitons ▾")
        elif not is_expanded and self.sub_tabs.isVisible() and bottom_h <= 45:
            self.sub_tabs.setVisible(False)
            self.btn_toggle_bottom.setText("Diagnostics & Solitons ▸")

    def _toggle_kpi_banner(self) -> None:
        """Toggle visibility of the KPI Summary Banner."""
        vis = not self.kpi_banner.isVisible()
        self.kpi_banner.setVisible(vis)
        self.btn_toggle_kpi.setText("📊 KPI Telemetry ▾" if vis else "📊 KPI Telemetry ▸")

    def _toggle_bottom_panel(self) -> None:
        """Toggle visibility of the bottom diagnostics and solitons drawer."""
        vis = not self.sub_tabs.isVisible()
        self.sub_tabs.setVisible(vis)
        self.btn_toggle_bottom.setText("Diagnostics & Solitons ▾" if vis else "Diagnostics & Solitons ▸")
        sizes = self.v_splitter.sizes()
        total = sum(sizes) if sum(sizes) > 0 else 940
        if vis:
            if len(sizes) >= 2 and sizes[1] < 120:
                bottom_h = max(220, int(total * 0.28))
                self.v_splitter.setSizes([total - bottom_h, bottom_h])
        else:
            self.v_splitter.setSizes([total - 45, 45])

    def showEvent(self, event) -> None:
        """Ensure initial splitter sizes are enforced on first window presentation."""
        super().showEvent(event)
        if not getattr(self, "_initial_splitter_set", False):
            self._initial_splitter_set = True
            if hasattr(self, "v_splitter") and hasattr(self, "v_splitter_sizes"):
                self.v_splitter.setSizes(self.v_splitter_sizes)

    def _update_domain_button_styles(self) -> None:
        """Apply active/inactive cyberpunk styles to domain selector buttons."""
        style_active = f"""
            QPushButton {{
                background-color: {SURFACE_HIGH};
                color: {CYAN_ACCENT};
                border: 1.5px solid {CYAN_ACCENT};
                border-radius: 4px;
                padding: 5px 12px;
                font-weight: 700;
                font-size: 11px;
                letter-spacing: 0.5px;
            }}
        """
        style_inactive = f"""
            QPushButton {{
                background-color: {SURFACE_LOW};
                color: {TEXT_MUTED};
                border: 1px solid {BORDER_SUBTLE};
                border-radius: 4px;
                padding: 5px 12px;
                font-weight: 600;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background-color: {SURFACE};
                color: {TEXT_PRIMARY};
                border-color: {BORDER_COLOR};
            }}
        """
        self.btn_view_time.setStyleSheet(style_active if self.domain_mode == "time" else style_inactive)
        self.btn_view_freq.setStyleSheet(style_active if self.domain_mode == "freq" else style_inactive)

    def set_domain_mode(self, mode: str) -> None:
        """Switch between 'time' and 'freq' domain visualization modes."""
        if mode not in ("time", "freq"):
            mode = "freq"
        self.domain_mode = mode
        self.btn_view_time.setChecked(mode == "time")
        self.btn_view_freq.setChecked(mode == "freq")
        self._update_domain_button_styles()
        self._apply_layout()
        if getattr(self, "_latest_live_state", None) is not None:
            self.update_live_state(self._latest_live_state, force=True)

    def set_all_layout_mode(self, layout_mode: str) -> None:
        """Legacy helper maintained for backward compatibility."""
        pass

    def _set_pulse_scale(self, mode: str) -> None:
        """Toggle between linear and log_db scales for Panel A."""
        if mode == "linear":
            self.btn_scale_linear.setChecked(True)
            self.btn_scale_log.setChecked(False)
            self.btn_scale_linear.setStyleSheet(f"padding: 3px 8px; font-size: 10px; background-color: {SURFACE_HIGH}; border: 1px solid {CYAN_ACCENT};")
            self.btn_scale_log.setStyleSheet(f"padding: 3px 8px; font-size: 10px; background-color: {SURFACE_LOW};")
        else:
            self.btn_scale_linear.setChecked(False)
            self.btn_scale_log.setChecked(True)
            self.btn_scale_log.setStyleSheet(f"padding: 3px 8px; font-size: 10px; background-color: {SURFACE_HIGH}; border: 1px solid {CYAN_ACCENT};")
            self.btn_scale_linear.setStyleSheet(f"padding: 3px 8px; font-size: 10px; background-color: {SURFACE_LOW};")
        self.plot_time_1d.set_scale_mode(mode)

    def set_center_wavelength(self, center_wavelength: float) -> None:
        """Dynamically calibrate carrier wavelength and center frequency omega0."""
        self.center_wavelength = max(float(center_wavelength), 100e-9)
        self.omega0 = 2.0 * np.pi * 299792458.0 / self.center_wavelength

    def set_simulation_type(self, sim_type: str) -> None:
        """Dynamically adapt layout between distance evolution and power sweep."""
        self.current_sim_type = sim_type
        if sim_type == "spectrum_vs_power":
            self.btn_view_time.setEnabled(False)
            self.btn_view_time.setToolTip("Time domain is unavailable for Power Sweep simulations")
            if self.domain_mode == "time":
                self.set_domain_mode("freq")
        else:
            self.btn_view_time.setEnabled(True)
            self.btn_view_time.setToolTip("Focus exclusively on temporal evolution and envelope |A(z,t)|²")
        self._apply_layout()

    def _apply_layout(self) -> None:
        """Apply active domain mode and layout arrangement to the plot container."""
        # 1. Remove plot widgets from grid without deleting them
        for w in (self.plot_time_2d, self.plot_time_1d, self.plot_freq_2d, self.plot_freq_1d):
            self.grid_layout.removeWidget(w)

        # Clear stretch factors
        for r in range(4):
            self.grid_layout.setRowStretch(r, 0)
        for c in range(5):
            self.grid_layout.setColumnStretch(c, 0)

        # 2. Contextual controls visibility
        is_time = (self.domain_mode == "time" and self.current_sim_type != "spectrum_vs_power")
        self.box_pulse_scale.setVisible(is_time)
        self.box_wl_toolbar.setVisible(not is_time)

        # 3. Simulation Type: Power Sweep
        if self.current_sim_type == "spectrum_vs_power":
            self.plot_time_2d.hide()
            self.plot_time_1d.hide()

            self.plot_freq_2d.plot_item.setLabel("left", "Peak Power P₀ [kW]")
            self.plot_freq_2d.plot_item.setLabel("bottom", "Wavelength [nm]")
            self.plot_freq_2d.plot_item.setTitle("Power-Sweep Spectral Density")

            self.plot_freq_1d.plot_item.setLabel("left", "Spectral Power [dB]")
            self.plot_freq_1d.plot_item.setLabel("bottom", "Wavelength [nm]")
            self.plot_freq_1d.plot_item.setTitle("Freq. domain")

            self.grid_layout.addWidget(self.plot_freq_2d, 0, 0)
            self.grid_layout.addWidget(self.plot_freq_1d, 0, 1)
            self.plot_freq_2d.show()
            self.plot_freq_1d.show()

            self.grid_layout.setRowStretch(0, 1)
            self.grid_layout.setColumnStretch(0, 1)
            self.grid_layout.setColumnStretch(1, 1)
            return

        # 4. Simulation Type: Distance Evolution
        if self.domain_mode == "time":
            # Time Domain Focus: 2 portrait columns side-by-side (generous height > width)
            self.plot_freq_2d.hide()
            self.plot_freq_1d.hide()

            self.plot_time_2d.plot_item.setLabel("left", "Distance [cm]")
            self.plot_time_2d.plot_item.setLabel("bottom", "Time [ps]")
            self.plot_time_2d.plot_item.setTitle("Temporal Waterfall |A(z,t)|²")

            y_lbl = "Normalized Intensity [dB]" if self.plot_time_1d.scale_mode == "log_db" else "Intensity [W]"
            self.plot_time_1d.plot_item.setLabel("left", y_lbl)
            self.plot_time_1d.plot_item.setLabel("bottom", "Time [ps]")
            self.plot_time_1d.plot_item.setTitle("Temporal Pulse Profile |A(t)|²")

            self.grid_layout.addWidget(self.plot_time_2d, 0, 0)
            self.grid_layout.addWidget(self.plot_time_1d, 0, 1)
            self.plot_time_2d.show()
            self.plot_time_1d.show()

            self.grid_layout.setRowStretch(0, 1)
            self.grid_layout.setColumnStretch(0, 1)
            self.grid_layout.setColumnStretch(1, 1)

        else:
            # Frequency Domain Focus: 2 portrait columns side-by-side (generous height > width)
            self.plot_time_2d.hide()
            self.plot_time_1d.hide()

            self.plot_freq_2d.plot_item.setLabel("left", "Distance [cm]")
            self.plot_freq_2d.plot_item.setLabel("bottom", "Wavelength [nm]")
            self.plot_freq_2d.plot_item.setTitle("Spectral Waterfall S(z, λ)")

            self.plot_freq_1d.plot_item.setLabel("left", "Spectral Power [dB]")
            self.plot_freq_1d.plot_item.setLabel("bottom", "Wavelength [nm]")
            self.plot_freq_1d.plot_item.setTitle("Spectral Power Density S(λ)")

            self.grid_layout.addWidget(self.plot_freq_2d, 0, 0)
            self.grid_layout.addWidget(self.plot_freq_1d, 0, 1)
            self.plot_freq_2d.show()
            self.plot_freq_1d.show()

            self.grid_layout.setRowStretch(0, 1)
            self.grid_layout.setColumnStretch(0, 1)
            self.grid_layout.setColumnStretch(1, 1)

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

        # Stop any running animation
        self.anim_timer.stop()
        self.btn_play_anim.setText("▶ Play Evolution")
        self.slider_z.setEnabled(False)
        self.btn_step_prev.setEnabled(False)
        self.btn_step_next.setEnabled(False)
        self.btn_play_anim.setEnabled(False)

        sim_title = "Spectrum vs Distance" if self.current_sim_type == "spectrum_vs_distance" else "Spectrum vs Power"
        self.lbl_title.setText(f"Simulation with {method} Method — {sim_title}")

        # Set initial 'before' curves
        t_ps = envelope_to_time_ps(initial_state.t)
        intensity_0 = np.abs(initial_state.a_t) ** 2
        self.plot_time_1d.set_before_curve(t_ps, intensity_0)

        # Default time domain view range [-2.5, 2.5] ps
        self.plot_time_1d.set_x_range(-2.5, 2.5)
        self.plot_time_2d.set_x_range(-2.5, 2.5)

        # Set stable initial Y-limits for temporal pulse with headroom (avoids continuous axis tick churn)
        p_max = float(np.max(intensity_0))
        self.plot_time_1d.set_y_limits(0.0, p_max * 1.25 if p_max > 0 else 1.0)

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
        self._latest_live_state = None
        self._last_2d_update_time = 0.0

    def update_live_state(self, state: SimulationState, force: bool = False) -> None:
        """Update 1D 'after' curves and live 2D maps in real-time."""
        self._latest_live_state = state
        is_time_domain = (self.domain_mode == "time" and self.current_sim_type != "spectrum_vs_power")

        intensity: Optional[np.ndarray] = None
        t_ps: Optional[np.ndarray] = None
        wl_nm: Optional[np.ndarray] = None
        psd_db: Optional[np.ndarray] = None

        if is_time_domain:
            t_ps = envelope_to_time_ps(state.t)
            intensity = np.abs(state.a_t) ** 2
            if len(t_ps) > 1024:
                ds = len(t_ps) // 1024
                self.plot_time_1d.set_after_curve(t_ps[::ds], intensity[::ds])
            else:
                self.plot_time_1d.set_after_curve(t_ps, intensity)
        else:
            wl_nm, psd_db = spectrum_to_db(state.a_w, state.omega, self.omega0)
            if len(wl_nm) > 1024:
                ds = len(wl_nm) // 1024
                self.plot_freq_1d.set_after_curve(wl_nm[::ds], psd_db[::ds])
            else:
                self.plot_freq_1d.set_after_curve(wl_nm, psd_db)

        # Decimate 2D waterfall image updates to ~6.6 Hz (>= 150 ms) to minimize image copy/LUT overhead
        now = time.perf_counter()
        if force or (now - getattr(self, "_last_2d_update_time", 0.0) >= 0.15):
            self._last_2d_update_time = now
            if self.live_step_idx < self.live_time_map.shape[0]:
                idx = self.live_step_idx
                if self.current_sim_type == "spectrum_vs_distance":
                    self.live_y_coords[idx] = state.z * 100.0
                else:
                    self.live_y_coords[idx] = state.power / 1e3

                y_min = float(self.live_y_coords[0])
                y_max = float(self.live_y_coords[idx]) if self.live_y_coords[idx] > y_min else y_min + 1.0

                if is_time_domain:
                    if intensity is None:
                        intensity = np.abs(state.a_t) ** 2
                    if t_ps is None:
                        t_ps = envelope_to_time_ps(state.t)
                    self.live_time_map[idx, :] = 10.0 * np.log10((intensity + 1e-30) / (np.max(intensity) + 1e-30))
                    self.plot_time_2d.update_data(
                        self.live_time_map[:idx + 1, :],
                        (float(t_ps[0]), float(t_ps[-1])),
                        (y_min, y_max),
                    )
                else:
                    if wl_nm is None or psd_db is None:
                        wl_nm, psd_db = spectrum_to_db(state.a_w, state.omega, self.omega0)
                    self.live_freq_map[idx, :] = np.interp(self.display_wl, wl_nm, psd_db)
                    wl_min = float(self.display_wl[0])
                    wl_max = float(self.display_wl[-1])
                    self.plot_freq_2d.update_data(
                        self.live_freq_map[:idx + 1, :],
                        (wl_min, wl_max),
                        (y_min, y_max),
                    )

                self.live_step_idx += 1

    def render_full_simulation(self, final_state: SimulationState, history: List[SimulationState]) -> None:
        """Render completed 2D density maps, final 1D profiles, and activate scrubber."""
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
            int_t = np.abs(s.a_t) ** 2
            time_map_db[i, :] = 10.0 * np.log10((int_t + 1e-30) / (np.max(int_t) + 1e-30))

            s_wl_nm, s_db = spectrum_to_db(s.a_w, s.omega, self.omega0)
            spec_map_db[i, :] = np.interp(self.display_wl, s_wl_nm, s_db)

            if self.current_sim_type == "spectrum_vs_distance":
                y_coords[i] = s.z * 100.0
            else:
                y_coords[i] = s.power / 1e3

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
        t_ps_final = envelope_to_time_ps(final_state.t)
        intensity_final = np.abs(final_state.a_t) ** 2
        self.plot_time_1d.set_after_curve(t_ps_final, intensity_final)

        wl_nm_final, psd_db_final = spectrum_to_db(final_state.a_w, final_state.omega, self.omega0)
        self.plot_freq_1d.set_after_curve(wl_nm_final, psd_db_final)


        # Soliton Peak Tracking Table
        self.soliton_tracker.update_from_state(final_state, self.active_pulse_config, self.active_fiber_config)

        # Update KPI Banner
        if self.active_pulse_config and self.active_fiber_config:
            self.kpi_banner.update_from_configs(self.active_pulse_config, self.active_fiber_config, final_state)

        # Enable Scrubber controls
        self.slider_z.setEnabled(True)
        self.btn_step_prev.setEnabled(True)
        self.btn_step_next.setEnabled(True)
        self.btn_play_anim.setEnabled(True)
        self.slider_z.setRange(0, len(history) - 1)
        self.slider_z.setValue(len(history) - 1)

        total_coord = history[-1].z * 100.0 if self.current_sim_type == "spectrum_vs_distance" else history[-1].power / 1e3
        unit = "cm" if self.current_sim_type == "spectrum_vs_distance" else "kW"
        self.lbl_scrub_depth.setText(f"z = {total_coord:.2f} {unit} / {total_coord:.2f} {unit}")

    # -----------------------------------------------------------------
    # Scrubber & Animation Control Slots
    # -----------------------------------------------------------------
    def _on_scrubber_changed(self, idx: int) -> None:
        """Handle z-slider scrubbing across saved simulation history."""
        if not self.cached_history or idx < 0 or idx >= len(self.cached_history):
            return

        state = self.cached_history[idx]
        t_ps = envelope_to_time_ps(state.t)
        intensity = np.abs(state.a_t) ** 2
        self.plot_time_1d.set_after_curve(t_ps, intensity)

        wl_nm, psd_db = spectrum_to_db(state.a_w, state.omega, self.omega0)
        self.plot_freq_1d.set_after_curve(wl_nm, psd_db)


        # Soliton decomposition at current slice
        self.soliton_tracker.update_from_state(state, self.active_pulse_config, self.active_fiber_config)

        # Indicator lines on 2D density maps
        coord_val = state.z * 100.0 if self.current_sim_type == "spectrum_vs_distance" else state.power / 1e3
        total_coord = self.cached_history[-1].z * 100.0 if self.current_sim_type == "spectrum_vs_distance" else self.cached_history[-1].power / 1e3
        unit = "cm" if self.current_sim_type == "spectrum_vs_distance" else "kW"

        self.plot_freq_2d.set_z_indicator(coord_val)
        if self.current_sim_type == "spectrum_vs_distance":
            self.plot_time_2d.set_z_indicator(coord_val)

        self.lbl_scrub_depth.setText(f"z = {coord_val:.2f} {unit} / {total_coord:.2f} {unit}")

    def _toggle_animation(self) -> None:
        if self.anim_timer.isActive():
            self.anim_timer.stop()
            self.btn_play_anim.setText("▶ Play Evolution")
        else:
            if self.slider_z.value() >= self.slider_z.maximum():
                self.slider_z.setValue(0)
            self.anim_timer.start()
            self.btn_play_anim.setText("❚❚ Pause Evolution")

    def _advance_animation(self) -> None:
        curr = self.slider_z.value()
        if curr < self.slider_z.maximum():
            self.slider_z.setValue(curr + 1)
        else:
            self.anim_timer.stop()
            self.btn_play_anim.setText("▶ Play Evolution")

    def _step_back(self) -> None:
        curr = self.slider_z.value()
        if curr > 0:
            self.slider_z.setValue(curr - 1)

    def _step_forward(self) -> None:
        curr = self.slider_z.value()
        if curr < self.slider_z.maximum():
            self.slider_z.setValue(curr + 1)

    # -----------------------------------------------------------------
    # LaTeX PGFPlots Generator
    # -----------------------------------------------------------------
    def _copy_pgfplots_snippet(self) -> None:
        """Generate publication-ready LaTeX TikZ/PGFPlots code and copy to clipboard."""
        if not self.cached_history:
            QMessageBox.information(self, "LaTeX Snippet", "Run a simulation first to generate LaTeX PGFPlots code.")
            return

        state = self.cached_final_state or self.cached_history[-1]
        wl_nm, psd_db = spectrum_to_db(state.a_w, state.omega, self.omega0)
        wl_min = float(self.spin_wl_min.value())
        wl_max = float(self.spin_wl_max.value())
        z_cm = float(state.z * 100.0)

        mask = (wl_nm >= wl_min) & (wl_nm <= wl_max)
        x_filtered = wl_nm[mask]
        y_filtered = psd_db[mask]

        # Decimate to ~100 points
        if len(x_filtered) > 100:
            step = len(x_filtered) // 100
            x_filtered = x_filtered[::step]
            y_filtered = y_filtered[::step]

        coords_str = "\n        ".join([f"({xi:.2f}, {yi:.2f})" for xi, yi in zip(x_filtered, y_filtered)])

        latex_code = f"""% ============================================================================
% GNLSE Simulation Output — Publication PGFPlots Snippet
% Generated by GNLSE Ultrapulse Workstation
% Method: {self.current_sim_type} | Distance: {z_cm:.2f} cm | Wavelength: {self.center_wavelength * 1e9:.1f} nm
% ============================================================================
\\begin{{tikzpicture}}
\\begin{{axis}}[
    width=10.5cm,
    height=6.5cm,
    grid=both,
    grid style={{line width=.2pt, draw=gray!25}},
    major grid style={{line width=.4pt, draw=gray!40}},
    xlabel={{Wavelength $\\lambda$ [nm]}},
    ylabel={{Spectral Power Density [dB]}},
    xmin={wl_min:.0f}, xmax={wl_max:.0f},
    ymin=-80, ymax=5,
    legend pos=north east,
    legend style={{font=\\footnotesize, fill=white, fill opacity=0.9}},
    tick label style={{font=\\footnotesize}},
    label style={{font=\\small}}
]
\\addplot[
    color=cyan!80!blue,
    line width=1.2pt
] coordinates {{
        {coords_str}
}};
\\addlegendentry{{Output Spectrum ($z = {z_cm:.2f}\\text{{ cm}}$)}}
\\end{{axis}}
\\end{{tikzpicture}}
"""
        QApplication.clipboard().setText(latex_code)
        self.btn_copy_pgfplots.setText("✅ Copied!")
        self._copy_reset_timer = QTimer(self)
        self._copy_reset_timer.setSingleShot(True)
        self._copy_reset_timer.timeout.connect(lambda: self.btn_copy_pgfplots.setText("📋 Copy LaTeX"))
        self._copy_reset_timer.start(1500)

    # -----------------------------------------------------------------
    # Export Handlers
    # -----------------------------------------------------------------
    def _export_specific_format(self, fmt: str) -> None:
        if not self.cached_history:
            QMessageBox.information(self, "Export", "No simulation results to export. Run a simulation first.")
            return

        filters = {
            "svg": "SVG Vector Graphics (*.svg)",
            "pdf": "PDF Document (*.pdf)",
            "png": "PNG Figure (*.png)",
            "h5": "HDF5 Dataset (*.h5)",
            "csv": "CSV Matrix (*.csv)",
        }
        fpath, _ = QFileDialog.getSaveFileName(
            self,
            f"Export {fmt.upper()} File",
            os.path.join(os.getcwd(), f"simulation_result.{fmt}"),
            filters.get(fmt, "All Files (*)"),
        )
        if not fpath:
            return

        ok, msg = self.export_to_file(fpath)
        if ok:
            QMessageBox.information(self, "Export Successful", msg)
        else:
            QMessageBox.critical(self, "Export Error", msg)

    def _export_numpy_compressed(self) -> None:
        """Save full mesh as NumPy .npz archive."""
        if not self.cached_history:
            QMessageBox.information(self, "Export", "No simulation results to export. Run a simulation first.")
            return

        fpath, _ = QFileDialog.getSaveFileName(
            self,
            "Save NumPy Archive",
            os.path.join(os.getcwd(), "simulation_result.npz"),
            "NumPy Archive (*.npz)",
        )
        if not fpath:
            return

        try:
            t_s = self.cached_history[0].t
            omega = self.cached_history[0].omega
            z_m = np.array([s.z for s in self.cached_history])
            a_t_matrix = np.array([s.a_t for s in self.cached_history])
            a_w_matrix = np.array([s.a_w for s in self.cached_history])

            np.savez_compressed(
                fpath,
                t=t_s,
                omega=omega,
                z=z_m,
                a_t=a_t_matrix,
                a_w=a_w_matrix,
                center_wavelength=self.center_wavelength,
                omega0=self.omega0,
            )
            QMessageBox.information(self, "Export Successful", f"Saved full mesh NumPy archive to:\n{fpath}")
        except Exception as e:
            QMessageBox.critical(self, "Export Error", f"Failed to save .npz archive:\n{e}")

    def export_to_file(self, fpath: str) -> tuple[bool, str]:
        """Export publication figure snapshot or numerical data matrix without UI modal blocks."""
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

    def _on_cmap_changed(self, cmap_name: str) -> None:
        self.plot_time_2d.set_colormap(cmap_name)
        self.plot_freq_2d.set_colormap(cmap_name)

    def _on_db_slider_changed(self, val: int) -> None:
        self.lbl_db_val.setText(f"-{val} dB")
        self.plot_time_2d.set_db_floor(-float(val))
        self.plot_freq_2d.set_db_floor(-float(val))

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
