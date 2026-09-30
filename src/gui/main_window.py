"""Main Window Desktop Application for GNLSE Pulse Propagation Simulator.

Integrates:
- Tab 1: Setup, Control Cards & .h5/.csv Dispersion File Navigator
- Tab 2: Dynamic 2x2 and 1x2 Scientific pyqtgraph Visualization Workstation
- Tab 3: Real-Time Diagnostic Logging & Conservation Monitor
- Decoupled QThread SolverWorker with Signal Throttling & Cooperative Teardown
"""

from __future__ import annotations

import time
from typing import Optional, List
from PyQt6.QtCore import Qt, QThread, pyqtSlot
from PyQt6.QtWidgets import (
    QMainWindow, QTabWidget, QWidget, QHBoxLayout, QSplitter,
    QProgressBar, QLabel, QStatusBar, QMessageBox
)

from src.solver.config import FiberConfig, PulseConfig, SolverConfig, SimulationState
from src.solver.engine import solve_generator
from src.bridge.worker import SolverWorker
from .tab_controls import TabControlsWidget
from .tab_results import TabResultsWidget
from .tab_logging import TabLoggingWidget
from .file_navigator import FileNavigatorWidget


class MainWindow(QMainWindow):
    """Main desktop workstation for GNLSE simulator."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("GNLSE Pulse Propagation Simulator — High Performance Laboratory")
        self.resize(1380, 920)

        # Main Tab Widget
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        # -------------------------------------------------------------
        # Tab 1: Setup, Controls & File Navigator
        # -------------------------------------------------------------
        self.tab1_widget = QWidget()
        tab1_layout = QHBoxLayout(self.tab1_widget)
        tab1_layout.setContentsMargins(4, 4, 4, 4)

        tab1_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.tab_controls = TabControlsWidget()
        self.file_navigator = FileNavigatorWidget()
        tab1_splitter.addWidget(self.tab_controls)
        tab1_splitter.addWidget(self.file_navigator)
        tab1_splitter.setStretchFactor(0, 3)
        tab1_splitter.setStretchFactor(1, 2)

        tab1_layout.addWidget(tab1_splitter)
        self.tabs.addTab(self.tab1_widget, "⚙️ Setup & File Navigation")

        # -------------------------------------------------------------
        # Tab 2: Results & Visualization
        # -------------------------------------------------------------
        self.tab_results = TabResultsWidget()
        self.tabs.addTab(self.tab_results, "📊 Results & Visualization")

        # -------------------------------------------------------------
        # Tab 3: System Logging
        # -------------------------------------------------------------
        self.tab_logging = TabLoggingWidget()
        self.tabs.addTab(self.tab_logging, "📜 System Logging")

        # -------------------------------------------------------------
        # Status Bar
        # -------------------------------------------------------------
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        self.lbl_status = QLabel("Status: Idle")
        self.lbl_step_info = QLabel("Step: 0")
        self.lbl_coord_info = QLabel("z: 0.00 cm / 0.00 cm")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedWidth(220)

        self.status_bar.addWidget(self.lbl_status, 1)
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

        # Wire UI interactions
        self.file_navigator.file_selected.connect(self.tab_controls.set_active_import_file)
        self.tab_controls.simulation_type_changed.connect(self.tab_results.set_simulation_type)
        self.tab_controls.wavelength_changed.connect(self.tab_results.set_center_wavelength)
        self.tab_controls.run_requested.connect(self._start_simulation)
        self.tab_controls.pause_requested.connect(self._pause_simulation)
        self.tab_controls.resume_requested.connect(self._resume_simulation)
        self.tab_controls.abort_requested.connect(self._abort_simulation)

    def _start_simulation(
        self,
        pulse: PulseConfig,
        fiber: FiberConfig,
        solver: SolverConfig,
        display_live: bool,
    ) -> None:
        # Clean up / join any existing worker thread before creating a new one
        if self.worker_thread is not None and self.worker_thread.isRunning():
            if self.worker:
                self.worker.abort()
            self._cleanup_thread()

        self.lbl_status.setText("Status: Running...")
        self.progress_bar.setValue(0)
        self._last_step = 0
        self._last_state_time = time.perf_counter()
        self._sim_start_time = time.perf_counter()

        # Generate initial state for 'before' plots
        initial_gen = solve_generator(pulse, fiber, solver)
        initial_state = next(initial_gen)
        self.tab_results.prepare_for_simulation(
            initial_state, solver.method, center_wavelength=pulse.center_wavelength
        )

        # If live display is checked, switch to Results tab to watch animation
        if display_live:
            self.tabs.setCurrentIndex(1)

        # Create worker & thread
        self.worker_thread = QThread()
        self.worker = SolverWorker()
        self.worker.moveToThread(self.worker_thread)

        # Setup worker configuration before starting thread
        self.worker.setup(pulse, fiber, solver, display_live)

        # Connect signals
        self.worker.state_updated.connect(self._on_state_updated)
        self.worker.progress_updated.connect(self._on_progress)
        self.worker.log_emitted.connect(self.tab_logging.append_log)
        self.worker.simulation_finished.connect(self._on_finished)
        self.worker.simulation_aborted.connect(self._on_aborted)
        self.worker.error_occurred.connect(self._on_error)

        # Start thread - invokes worker.start slot on worker_thread context
        self.worker_thread.started.connect(self.worker.start)
        self.worker_thread.start()

    def _pause_simulation(self) -> None:
        if self.worker:
            self.worker.pause()
            self.lbl_status.setText("Status: Paused ❚❚")
            self.tab_logging.append_log("WARN", "Simulation execution paused.")

    def _resume_simulation(self) -> None:
        if self.worker:
            self.worker.resume()
            self.lbl_status.setText("Status: Running...")
            self.tab_logging.append_log("INFO", "Simulation execution resumed.")

    def _abort_simulation(self) -> None:
        if self.worker:
            self.worker.abort()
            self.lbl_status.setText("Status: Aborting...")

    @pyqtSlot(object)
    def _on_state_updated(self, state: SimulationState) -> None:
        """Handle throttled live state updates for visualization and conservation diagnostics."""
        self.tab_results.update_live_state(state)
        self.tab_logging.update_metrics(state.rel_energy_err, state.rel_photon_err, state.h)

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
        self.tab_logging.update_calc_rate(steps_per_sec, eta_sec)

        if self.tab_results.current_sim_type == "spectrum_vs_distance":
            self.lbl_coord_info.setText(f"z: {current_val * 100:.2f} cm / {total_val * 100:.2f} cm")
        else:
            self.lbl_coord_info.setText(f"P₀: {current_val / 1e3:.2f} kW / {total_val / 1e3:.2f} kW")

    @pyqtSlot(object, list)
    def _on_finished(self, final_state: SimulationState, history: list) -> None:
        """Handle simulation completion."""
        self.lbl_status.setText("Status: Completed ✅")
        self.progress_bar.setValue(100)
        self.tab_controls.set_running_state(False)

        # Render complete 2D density maps
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
        self.lbl_status.setText("Status: Aborted ⏹")
        self.tab_controls.set_running_state(False)
        self._cleanup_thread()

    @pyqtSlot(str)
    def _on_error(self, err_msg: str) -> None:
        self.lbl_status.setText("Status: Error ⚠️")
        self.tab_controls.set_running_state(False)
        QMessageBox.critical(self, "Simulation Error", f"An error occurred during simulation:\n{err_msg}")
        self._cleanup_thread()

    def _cleanup_thread(self) -> None:
        if self.worker_thread and self.worker_thread.isRunning():
            self.worker_thread.quit()
            if not self.worker_thread.wait(2000):
                self.worker_thread.terminate()
                self.worker_thread.wait(500)
        self.worker_thread = None
        self.worker = None

    def closeEvent(self, event) -> None:
        """Cooperative teardown: cleanly abort thread on window close."""
        if self.worker and self.worker.is_running:
            self.worker.abort()
        self._cleanup_thread()
        event.accept()
