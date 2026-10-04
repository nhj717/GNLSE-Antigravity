"""Decoupled QThread Worker Bridge for GNLSE Solver.

Executes numerical propagation on a background worker thread, streaming
states through a hardware-aware SignalThrottler, and enforcing clean
cooperative cancellation without event loop stalls or dangling threads.
"""

from __future__ import annotations

import time
import threading
from typing import List, Optional
from PyQt6.QtCore import QObject, QThread, pyqtSignal, pyqtSlot

from src.solver.config import FiberConfig, PulseConfig, SolverConfig, SimulationState
from src.solver.engine import solve_generator
from .throttler import SignalThrottler


class SolverWorker(QObject):
    """QObject worker designed to run inside a QThread."""

    # Qt Signals for GUI interaction
    state_updated = pyqtSignal(object)              # Emits SimulationState when throttled
    progress_updated = pyqtSignal(int, float, float)# (step, current_z_or_power, max_z_or_power)
    simulation_finished = pyqtSignal(object, list)  # (final_state, state_history)
    simulation_aborted = pyqtSignal()
    error_occurred = pyqtSignal(str)
    log_emitted = pyqtSignal(str, str)              # (level, message)

    def __init__(self) -> None:
        super().__init__()
        self._is_interrupted = threading.Event()
        self._is_paused = threading.Event()
        self._is_paused.set()  # Not paused by default (set means running)
        self.throttler = SignalThrottler(max_fps=15.0, display_live=True)
        self._running = False
        self._pulse: Optional[PulseConfig] = None
        self._fiber: Optional[FiberConfig] = None
        self._solver: Optional[SolverConfig] = None
        self._display_live: bool = True
        self._latest_state: Optional[SimulationState] = None
        self._state_lock = threading.Lock()
        self._has_new_state: bool = False

    def setup(
        self,
        pulse: PulseConfig,
        fiber: FiberConfig,
        solver: SolverConfig,
        display_live: bool = True,
    ) -> None:
        """Configure simulation parameters before thread start."""
        self._pulse = pulse
        self._fiber = fiber
        self._solver = solver
        self._display_live = display_live
        self._is_interrupted.clear()
        self._is_paused.set()
        with self._state_lock:
            self._latest_state = None
            self._has_new_state = False

    def get_latest_state(self) -> Optional[SimulationState]:
        """Atomically fetch and consume the latest simulation state for GUI rendering."""
        with self._state_lock:
            if self._has_new_state:
                self._has_new_state = False
                return self._latest_state
            return None

    @pyqtSlot()
    def start(self) -> None:
        """Entry slot executed directly inside the target QThread event loop."""
        if self._is_interrupted.is_set():
            self.simulation_aborted.emit()
            return
        if self._pulse is not None and self._fiber is not None and self._solver is not None:
            self.run_simulation(self._pulse, self._fiber, self._solver, self._display_live)

    def abort(self) -> None:
        """Signal cooperative cancellation to the solver loop."""
        self._is_interrupted.set()
        self._is_paused.set()  # Unpause if paused so thread can exit immediately

    def pause(self) -> None:
        """Pause propagation."""
        self._is_paused.clear()

    def resume(self) -> None:
        """Resume propagation."""
        self._is_paused.set()

    def is_paused(self) -> bool:
        """Return True if propagation is currently paused."""
        return not self._is_paused.is_set()

    @property
    def is_running(self) -> bool:
        return self._running

    def run_simulation(
        self,
        pulse: PulseConfig,
        fiber: FiberConfig,
        solver: SolverConfig,
        display_live: bool = True,
    ) -> None:
        """Execute simulation generator loop."""
        if self._is_interrupted.is_set():
            self.simulation_aborted.emit()
            self._running = False
            return
        self._running = True

        self.throttler.display_live = display_live
        self.throttler.reset()

        self.log_emitted.emit("INFO", f"Starting simulation ({solver.method}) in mode '{solver.simulation_type}'...")
        self.log_emitted.emit("INFO", f"Fiber length: {fiber.length * 100:.2f} cm, Pulse duration: {pulse.t_fwhm * 1e15:.1f} fs, Peak power: {pulse.p_peak / 1e3:.2f} kW")

        history: List[SimulationState] = []
        final_state: Optional[SimulationState] = None
        start_time = time.perf_counter()
        last_progress_emit = 0.0
        last_terminal_log = 0.0

        try:
            generator = solve_generator(pulse, fiber, solver)
            total_target = fiber.length if solver.simulation_type == "spectrum_vs_distance" else solver.power_max

            for state in generator:
                # Check cooperative cancellation
                if self._is_interrupted.is_set():
                    self.log_emitted.emit("WARN", "Simulation aborted by user.")
                    self.simulation_aborted.emit()
                    self._running = False
                    return

                # Check pause state
                self._is_paused.wait()

                # Re-check abort immediately after unpausing (Amendment 4)
                if self._is_interrupted.is_set():
                    self.log_emitted.emit("WARN", "Simulation aborted by user while paused.")
                    self.simulation_aborted.emit()
                    self._running = False
                    return

                final_state = state
                history.append(state)

                current_coord = state.z if solver.simulation_type == "spectrum_vs_distance" else state.power
                now = time.perf_counter()

                # Progress updates (capped at 10 Hz to reduce signal & layout overhead)
                if now - last_progress_emit >= 0.10:
                    self.progress_updated.emit(state.step, current_coord, total_target)
                    last_progress_emit = now

                # Real-time state buffering for non-blocking GUI polling
                if display_live:
                    with self._state_lock:
                        self._latest_state = state
                        self._has_new_state = True

                    # Real-time state animation throttling (legacy signal emission if external listener is connected)
                    if self.receivers(self.state_updated) > 0 and self.throttler.should_emit(now):
                        self.state_updated.emit(state)

            elapsed = time.perf_counter() - start_time
            steps = final_state.step if final_state else 0
            steps_per_sec = steps / max(elapsed, 1e-4)

            self.log_emitted.emit("INFO", f"Simulation completed in {elapsed:.2f} s ({steps_per_sec:.1f} steps/s, {len(history)} frames saved).")
            if final_state:
                self.log_emitted.emit("INFO", f"Final energy error: {final_state.rel_energy_err:.2e}, photon error: {final_state.rel_photon_err:.2e}")
                self.simulation_finished.emit(final_state, history)

        except Exception as exc:
            self.log_emitted.emit("ERROR", f"Simulation failed with error: {exc}")
            self.error_occurred.emit(str(exc))
        finally:
            self._running = False
