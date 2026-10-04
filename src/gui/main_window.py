"""Main Window Desktop Application for GNLSE Pulse Propagation Simulator.

Cyberpunk UltraPulse Laboratory Workstation:
- Top Header Diagnostic Strip & Title bar with telemetry / status badges and control buttons (RUN, PAUSE, STOP, EXPORT)
- Cyberpunk dark theme matching palette: #0f131d, #171b26, #1c1f2a, #262a35, cyan #00f5ff, pink #ff4b89, purple #703eda
- Tab 1: Setup, Controls, Advanced Physics Parameters & Dispersion File Navigator
- Tab 2: Multi-Panel Visualization Canvas (Panels A, B, C, D), KPI Summary Banner, Soliton Peak Tracking & Publication Pipeline
- Tab 3: Real-Time Diagnostic Logging & Conservation Audit Terminal
- Decoupled QThread SolverWorker with Signal Throttling & Cooperative Teardown
"""

from __future__ import annotations

import time
from typing import Optional, List
from PyQt6.QtCore import Qt, QThread, pyqtSlot, QTimer
from PyQt6.QtWidgets import (
    QStackedWidget, QMainWindow, QTabWidget, QWidget, QHBoxLayout, QVBoxLayout,
    QSplitter, QProgressBar, QLabel, QStatusBar, QMessageBox, QPushButton, QFrame
)

from src.solver.config import FiberConfig, PulseConfig, SolverConfig, SimulationState
from src.solver.engine import solve_generator
from src.bridge.worker import SolverWorker
from .theme import (
    apply_cyberpunk_theme, CYAN_ACCENT, CYAN_LIGHT, CYAN_DARK,
    PINK_ACCENT, PINK_DARK, PURPLE_ACCENT, AMBER_WARNING, GREEN_SUCCESS,
    SURFACE_LOW, SURFACE, SURFACE_HIGH, TEXT_PRIMARY, TEXT_MUTED, BORDER_SUBTLE, BORDER_COLOR
)
from .tab_controls import TabControlsWidget, ManualDispersionWidget
from .tab_results import TabResultsWidget
from .tab_logging import TabLoggingWidget
from .file_navigator import FileNavigatorWidget
from .config_loader import load_gui_config


class MainWindow(QMainWindow):
    """Main desktop workstation for GNLSE simulator."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        # Load GUI formatting preferences from config.json
        self.config = load_gui_config()
        win_cfg = self.config.get("window", {})
        win_title = win_cfg.get("title", "GNLSE Pulse Propagation Simulator — High Performance Laboratory")
        win_w = int(win_cfg.get("width", 1440))
        win_h = int(win_cfg.get("height", 940))

        self.setWindowTitle(win_title)
        self.resize(win_w, win_h)

        # Apply Cyberpunk Dark Theme with configured colors
        apply_cyberpunk_theme(self, self.config.get("theme"))

        # Main Central Container
        central_widget = QWidget()
        central_layout = QVBoxLayout(central_widget)
        central_layout.setContentsMargins(8, 8, 8, 4)
        central_layout.setSpacing(6)
        self.setCentralWidget(central_widget)

        # -------------------------------------------------------------
        # Top Header Diagnostic Strip & Title Bar
        # -------------------------------------------------------------
        header_frame = QFrame()
        header_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {SURFACE_LOW};
                border: 1px solid {BORDER_SUBTLE};
                border-radius: 8px;
                padding: 4px 8px;
            }}
        """)
        header_layout = QHBoxLayout(header_frame)
        header_layout.setContentsMargins(6, 4, 6, 4)
        header_layout.setSpacing(10)

        # Title & Subtitle
        title_box = QVBoxLayout()
        title_box.setSpacing(1)
        lbl_app_title = QLabel("⚡ GNLSE ULTRAPULSE // ADVANCED WORKSTATION")
        lbl_app_title.setStyleSheet(f"""
            color: {CYAN_ACCENT};
            font-size: 13px;
            font-weight: 800;
            letter-spacing: 0.8px;
        """)
        lbl_app_sub = QLabel("Nonlinear Schrödinger Equation Solver • Interaction Picture RK4IP / SSFM")
        lbl_app_sub.setStyleSheet(f"""
            color: {TEXT_MUTED};
            font-size: 9px;
            font-weight: 500;
        """)
        title_box.addWidget(lbl_app_title)
        title_box.addWidget(lbl_app_sub)
        header_layout.addLayout(title_box)

        header_layout.addStretch(1)

        # Telemetry Diagnostic Badges Strip
        badge_box = QHBoxLayout()
        badge_box.setSpacing(6)

        def make_badge(text: str, color: str = CYAN_ACCENT) -> QLabel:
            badge = QLabel(text)
            badge.setStyleSheet(f"""
                QLabel {{
                    background-color: {SURFACE};
                    border: 1px solid {BORDER_SUBTLE};
                    border-left: 2px solid {color};
                    border-radius: 4px;
                    color: {TEXT_PRIMARY};
                    font-size: 9px;
                    font-weight: 700;
                    padding: 4px 8px;
                }}
            """)
            return badge

        self.lbl_badge_core = make_badge("CORE: RK4IP [C-KERNEL]", CYAN_ACCENT)
        self.lbl_badge_state = make_badge("STATE: IDLE", TEXT_MUTED)
        self.lbl_badge_dz = make_badge("dz: 0.10 mm", PURPLE_ACCENT)
        self.lbl_badge_grid = make_badge("N: 8192", CYAN_ACCENT)
        self.lbl_badge_rate = make_badge("RATE: -- steps/s", GREEN_SUCCESS)

        badge_box.addWidget(self.lbl_badge_core)
        badge_box.addWidget(self.lbl_badge_state)
        badge_box.addWidget(self.lbl_badge_dz)
        badge_box.addWidget(self.lbl_badge_grid)
        badge_box.addWidget(self.lbl_badge_rate)
        header_layout.addLayout(badge_box)

        header_layout.addStretch(1)

        # Top Control Buttons
        btn_box = QHBoxLayout()
        btn_box.setSpacing(6)

        self.btn_top_run = QPushButton("▶ RUN SIMULATION")
        self.btn_top_run.setStyleSheet(f"""
            QPushButton {{
                background-color: {CYAN_ACCENT};
                color: {CYAN_DARK};
                font-weight: 800;
                font-size: 11px;
                border-radius: 4px;
                padding: 6px 14px;
                border: none;
            }}
            QPushButton:hover {{
                background-color: {CYAN_LIGHT};
            }}
            QPushButton:disabled {{
                background-color: {SURFACE_HIGH};
                color: {TEXT_MUTED};
            }}
        """)

        self.btn_top_pause = QPushButton("❚❚ PAUSE")
        self.btn_top_pause.setEnabled(False)
        self.btn_top_pause.setStyleSheet(f"""
            QPushButton {{
                background-color: {AMBER_WARNING};
                color: #171b26;
                font-weight: 800;
                font-size: 11px;
                border-radius: 4px;
                padding: 6px 10px;
                border: none;
            }}
            QPushButton:disabled {{
                background-color: {SURFACE_HIGH};
                color: {TEXT_MUTED};
            }}
        """)

        self.btn_top_stop = QPushButton("⏹ STOP")
        self.btn_top_stop.setEnabled(False)
        self.btn_top_stop.setStyleSheet(f"""
            QPushButton {{
                background-color: {PINK_ACCENT};
                color: {PINK_DARK};
                font-weight: 800;
                font-size: 11px;
                border-radius: 4px;
                padding: 6px 12px;
                border: none;
            }}
            QPushButton:disabled {{
                background-color: {SURFACE_HIGH};
                color: {TEXT_MUTED};
            }}
        """)

        self.btn_top_export = QPushButton("💾 EXPORT DATA")
        self.btn_top_export.setStyleSheet(f"""
            QPushButton {{
                background-color: {PURPLE_ACCENT};
                color: #ffffff;
                font-weight: 700;
                font-size: 11px;
                border-radius: 4px;
                padding: 6px 10px;
                border: none;
            }}
        """)

        btn_box.addWidget(self.btn_top_run)
        btn_box.addWidget(self.btn_top_pause)
        btn_box.addWidget(self.btn_top_stop)
        btn_box.addWidget(self.btn_top_export)
        header_layout.addLayout(btn_box)

        central_layout.addWidget(header_frame)

        # -------------------------------------------------------------
        # Main Tab Workstation
        # -------------------------------------------------------------
        self.tabs = QTabWidget()
        central_layout.addWidget(self.tabs, 1)

        # -------------------------------------------------------------
        # Tab 1: Setup, Controls & File Navigator
        # -------------------------------------------------------------
        self.tab1_widget = QWidget()
        tab1_layout = QHBoxLayout(self.tab1_widget)
        tab1_layout.setContentsMargins(4, 4, 4, 4)

        tab1_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.tab_controls = TabControlsWidget()
        self.file_navigator = FileNavigatorWidget()
        self.manual_disp = ManualDispersionWidget()

        self.tab_controls.set_external_widgets(self.manual_disp, self.file_navigator)

        self.disp_stack = QStackedWidget()
        self.disp_stack.addWidget(self.manual_disp)
        self.disp_stack.addWidget(self.file_navigator)

        tab1_splitter.addWidget(self.tab_controls)
        tab1_splitter.addWidget(self.disp_stack)
        tab1_splitter.setStretchFactor(0, 3)
        tab1_splitter.setStretchFactor(1, 2)

        tab1_layout.addWidget(tab1_splitter)
        self.tabs.addTab(self.tab1_widget, "⚙️ Setup & File Navigation")

        # -------------------------------------------------------------
        # Tab 2: Results & Visualization Canvas
        # -------------------------------------------------------------
        self.tab_results = TabResultsWidget(config=self.config.get("results_view"))
        self.tabs.addTab(self.tab_results, "📊 Results & Visualization")

        # -------------------------------------------------------------
        # Tab 3: System Logging
        # -------------------------------------------------------------
        self.tab_logging = TabLoggingWidget()
        self.tabs.addTab(self.tab_logging, "📜 System Logging")

        # -------------------------------------------------------------
        # Footer Status Bar with Solver Telemetry
        # -------------------------------------------------------------
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        self.lbl_status = QLabel("Status: Idle")
        self.lbl_step_info = QLabel("Step: 0")
        self.lbl_coord_info = QLabel("z: 0.00 cm / 0.00 cm")

        self.lbl_telemetry_grid = QLabel("Grid: N=8192 | T=12.5 ps")
        self.lbl_telemetry_rate = QLabel("Rate: 0 steps/s")

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedWidth(220)

        self.status_bar.addWidget(self.lbl_status, 1)
        self.status_bar.addPermanentWidget(self.lbl_telemetry_grid)
        self.status_bar.addPermanentWidget(self.lbl_telemetry_rate)
        self.status_bar.addPermanentWidget(self.lbl_step_info)
        self.status_bar.addPermanentWidget(self.lbl_coord_info)
        self.status_bar.addPermanentWidget(self.progress_bar)

        # -------------------------------------------------------------
        # Concurrency Worker & Thread Setup
        # -------------------------------------------------------------
        self.worker_thread: Optional[QThread] = None
        self.worker: Optional[SolverWorker] = None
        self._last_state_time = time.perf_counter()
        self._last_step = 0
        self._active_pulse: Optional[PulseConfig] = None
        self._active_fiber: Optional[FiberConfig] = None

        # Decoupled Non-Blocking Real-Time Render Timer (~10 FPS, interval 100 ms)
        # Capping live GUI updates to 10 FPS avoids saturating the Python GIL with Qt/pyqtgraph
        # paint operations, allowing the numerical solver worker to run at near-headless speeds.
        self._render_timer = QTimer(self)
        self._render_timer.setInterval(100)
        self._render_timer.timeout.connect(self._on_render_timer_tick)
        self._last_telemetry_time = 0.0

        # Wire UI interactions
        self.file_navigator.file_selected.connect(self.tab_controls.set_active_import_file)
        self.tab_controls.dispersion_mode_changed.connect(self.disp_stack.setCurrentIndex)
        self.tab_controls.simulation_type_changed.connect(self.tab_results.set_simulation_type)
        self.tab_controls.wavelength_changed.connect(self.tab_results.set_center_wavelength)
        self.tab_controls.run_requested.connect(self._start_simulation)
        self.tab_controls.pause_requested.connect(self._pause_simulation)
        self.tab_controls.resume_requested.connect(self._resume_simulation)
        self.tab_controls.abort_requested.connect(self._abort_simulation)

        # Wire Top Header Action buttons
        self.btn_top_run.clicked.connect(self.tab_controls._on_run_clicked)
        self.btn_top_pause.clicked.connect(self.tab_controls._on_pause_clicked)
        self.btn_top_stop.clicked.connect(self.tab_controls.abort_requested.emit)
        self.btn_top_export.clicked.connect(self.tab_results._on_export_clicked)

    def _start_simulation(
        self,
        pulse: PulseConfig,
        fiber: FiberConfig,
        solver: SolverConfig,
        display_live: bool,
    ) -> None:
        """Start asynchronous solver worker in dedicated QThread."""
        # Clean up / join any existing worker thread before creating a new one
        if self.worker_thread is not None and self.worker_thread.isRunning():
            if self.worker:
                self.worker.abort()
            self._cleanup_thread()

        self._active_pulse = pulse
        self._active_fiber = fiber
        self.tab_results.active_pulse_config = pulse
        self.tab_results.active_fiber_config = fiber

        self.lbl_status.setText("Status: Running...")
        self.lbl_badge_state.setText("STATE: SIMULATING")
        self.lbl_badge_state.setStyleSheet(f"""
            QLabel {{
                background-color: {SURFACE};
                border: 1px solid {BORDER_SUBTLE};
                border-left: 2px solid {CYAN_ACCENT};
                border-radius: 4px;
                color: {CYAN_ACCENT};
                font-size: 9px;
                font-weight: 700;
                padding: 4px 8px;
            }}
        """)
        self.lbl_badge_grid.setText(f"N: {solver.n_points}")
        self.lbl_badge_core.setText(f"CORE: {solver.method} [C-KERNEL]")
        self.lbl_telemetry_grid.setText(f"Grid: N={solver.n_points} | T={solver.time_window * 1e12:.1f} ps")

        # Top Buttons state
        self.btn_top_run.setEnabled(False)
        self.btn_top_pause.setEnabled(True)
        self.btn_top_stop.setEnabled(True)

        self.progress_bar.setValue(0)
        self._last_step = 0
        self._last_state_time = time.perf_counter()
        self._sim_start_time = time.perf_counter()

        # Generate initial state for 'before' plots
        try:
            initial_gen = solve_generator(pulse, fiber, solver)
            initial_state = next(initial_gen)
        except Exception as e:
            self.tab_controls.set_running_state(False)
            self._update_top_buttons(running=False)
            self.lbl_status.setText("Status: Error ⚠️")
            self.lbl_badge_state.setText("STATE: ERROR")
            QMessageBox.critical(self, "Simulation Initialization Error", f"Could not initialize simulation:\n{e}")
            return

        self.tab_results.prepare_for_simulation(
            initial_state, solver.method, center_wavelength=pulse.center_wavelength
        )
        self.tab_results.kpi_banner.update_from_configs(pulse, fiber, initial_state)

        # If live display is checked, switch to Results tab to watch animation
        if display_live:
            self.tabs.setCurrentIndex(1)

        # Create worker & thread
        self.worker_thread = QThread()
        self.worker = SolverWorker()
        self.worker.moveToThread(self.worker_thread)

        # Setup worker configuration before starting thread
        self.worker.setup(pulse, fiber, solver, display_live)

        # Connect signals (state_updated is decoupled via _render_timer pulling latest_state at 30 FPS)
        self.worker.progress_updated.connect(self._on_progress)
        self.worker.log_emitted.connect(self.tab_logging.append_log)
        self.worker.simulation_finished.connect(self._on_finished)
        self.worker.simulation_aborted.connect(self._on_aborted)
        self.worker.error_occurred.connect(self._on_error)

        # Start decoupled 10 FPS rendering timer if live display enabled
        self._last_telemetry_time = 0.0
        if display_live:
            self._render_timer.start(100)

        # Start thread - invokes worker.start slot on worker_thread context
        self.worker_thread.started.connect(self.worker.start)
        self.worker_thread.start()

    def _pause_simulation(self) -> None:
        self._render_timer.stop()
        if self.worker:
            self.worker.pause()
            self.lbl_status.setText("Status: Paused ❚❚")
            self.lbl_badge_state.setText("STATE: PAUSED")
            self.btn_top_pause.setText("▶ RESUME")
            self.tab_logging.append_log("WARN", "Simulation execution paused.")

    def _resume_simulation(self) -> None:
        if self.worker:
            self.worker.resume()
            self.lbl_status.setText("Status: Running...")
            self.lbl_badge_state.setText("STATE: SIMULATING")
            self.btn_top_pause.setText("❚❚ PAUSE")
            self.tab_logging.append_log("INFO", "Simulation execution resumed.")
            if getattr(self.worker, "_display_live", True):
                self._render_timer.start(100)

    def _abort_simulation(self) -> None:
        self._render_timer.stop()
        if self.worker:
            self.worker.abort()
            self.lbl_status.setText("Status: Aborting...")
            self.lbl_badge_state.setText("STATE: ABORTING")

    def _on_render_timer_tick(self) -> None:
        """Poll the solver worker for the latest state at ~30 FPS without Qt event loop saturation."""
        if self.worker is None:
            return
        state = self.worker.get_latest_state()
        if state is not None:
            self._on_state_updated(state)

    @pyqtSlot(object)
    def _on_state_updated(self, state: SimulationState, force_telemetry: bool = False) -> None:
        """Handle live state updates for visualization and conservation diagnostics."""
        self.tab_results.update_live_state(state)

        # Decimate telemetry, KPI banner, and logging updates to 10 Hz (interval >= 0.10 s)
        now = time.perf_counter()
        if force_telemetry or (now - self._last_telemetry_time >= 0.10):
            self._last_telemetry_time = now
            self.tab_logging.update_metrics(state.rel_energy_err, state.rel_photon_err, state.h)
            if self._active_pulse and self._active_fiber:
                self.tab_results.kpi_banner.update_from_configs(self._active_pulse, self._active_fiber, state)

            # Update telemetry badges
            h_mm = state.h * 1e3
            if h_mm >= 1.0:
                self.lbl_badge_dz.setText(f"dz: {h_mm:.2f} mm")
            else:
                self.lbl_badge_dz.setText(f"dz: {state.h * 1e6:.1f} μm")

    @pyqtSlot(int, float, float)
    def _on_progress(self, step: int, current_val: float, total_val: float) -> None:
        """Update status bar and diagnostic calculation rates."""
        now = time.perf_counter()
        dt = max(now - self._last_state_time, 1e-4)
        d_steps = step - self._last_step
        steps_per_sec = d_steps / dt
        self._last_step = step
        self._last_state_time = now

        elapsed = max(now - getattr(self, "_sim_start_time", now), 1e-4)
        val_rate = current_val / elapsed if current_val > 0 else 0.0
        remaining_val = max(total_val - current_val, 0.0)
        eta_sec = remaining_val / val_rate if val_rate > 0 else 0.0

        pct = int(min(max(current_val / max(total_val, 1e-9) * 100.0, 0.0), 100.0))
        self.progress_bar.setValue(pct)
        self.lbl_step_info.setText(f"Step: {step}")
        self.lbl_badge_rate.setText(f"RATE: {steps_per_sec:.0f} steps/s")
        self.lbl_telemetry_rate.setText(f"Rate: {steps_per_sec:.1f} steps/s")
        self.tab_logging.update_calc_rate(steps_per_sec, eta_sec)

        if self.tab_results.current_sim_type == "spectrum_vs_distance":
            self.lbl_coord_info.setText(f"z: {current_val * 100:.2f} cm / {total_val * 100:.2f} cm")
        else:
            self.lbl_coord_info.setText(f"P₀: {current_val / 1e3:.2f} kW / {total_val / 1e3:.2f} kW")

    @pyqtSlot(object, list)
    def _on_finished(self, final_state: SimulationState, history: list) -> None:
        """Handle simulation completion."""
        self._render_timer.stop()
        self.lbl_status.setText("Status: Completed ✅")
        self.lbl_badge_state.setText("STATE: COMPLETED")
        self.progress_bar.setValue(100)
        self.tab_controls.set_running_state(False)
        self._update_top_buttons(running=False)

        # Flush final state to live plots and telemetry
        self._on_state_updated(final_state, force_telemetry=True)

        # Render complete 2D density maps and activate scrubber
        self.tab_results.render_full_simulation(final_state, history)

        # Update Tab 3 metrics
        self.tab_logging.update_metrics(
            final_state.rel_energy_err,
            final_state.rel_photon_err,
            final_state.h,
            steps_per_sec=0.0,
        )

        # Switch to results tab to show finished plots
        self.tabs.setCurrentIndex(1)
        self._cleanup_thread()

    @pyqtSlot()
    def _on_aborted(self) -> None:
        self._render_timer.stop()
        self.lbl_status.setText("Status: Aborted ⏹")
        self.lbl_badge_state.setText("STATE: ABORTED")
        self.tab_controls.set_running_state(False)
        self._update_top_buttons(running=False)
        self._cleanup_thread()

    @pyqtSlot(str)
    def _on_error(self, err_msg: str) -> None:
        self._render_timer.stop()
        self.lbl_status.setText("Status: Error ⚠️")
        self.lbl_badge_state.setText("STATE: ERROR")
        self.tab_controls.set_running_state(False)
        self._update_top_buttons(running=False)
        QMessageBox.critical(self, "Simulation Error", f"An error occurred during simulation:\n{err_msg}")
        self._cleanup_thread()

    def _update_top_buttons(self, running: bool) -> None:
        self.btn_top_run.setEnabled(not running)
        self.btn_top_pause.setEnabled(running)
        self.btn_top_stop.setEnabled(running)
        self.btn_top_pause.setText("❚❚ PAUSE")

    def _cleanup_thread(self) -> None:
        self._render_timer.stop()
        if self.worker:
            self.worker.abort()
        if self.worker_thread and self.worker_thread.isRunning():
            self.worker_thread.quit()
            if not self.worker_thread.wait(2000):
                self.worker_thread.terminate()
                self.worker_thread.wait(500)
        self.worker_thread = None
        self.worker = None

    def closeEvent(self, event) -> None:
        """Cooperative teardown: cleanly abort thread on window close."""
        if self.worker:
            self.worker.abort()
        self._cleanup_thread()
        event.accept()
