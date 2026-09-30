"""Automated Headless Concurrency & Throttling Tests for GNLSE Bridge.

Validates:
- SignalThrottler frame rate capping (<= 60 FPS) and turbo bypass
- SolverWorker lifecycle: execution, cooperative abort, pause/resume
"""

import time
import pytest
from PyQt6.QtCore import QCoreApplication
from src.bridge.throttler import SignalThrottler
from src.bridge.worker import SolverWorker
from src.solver.config import PulseConfig, FiberConfig, DispersionConfig, SolverConfig


def test_throttler_max_fps():
    """Verify throttler strictly bounds visual frame emissions to max_fps."""
    throttler = SignalThrottler(max_fps=60.0, display_live=True)
    min_interval = 1.0 / 60.0  # ~0.01667 s

    # Simulate 1000 incoming state frames across 0.1 seconds (10,000 steps/sec)
    t0 = 100.0
    for i in range(1000):
        t = t0 + i * (0.1 / 1000.0)  # 0.1 ms between steps
        throttler.should_emit(t)

    # In 0.1 seconds at 60 FPS, at most 6-7 frames can be emitted
    assert throttler.emitted_count <= 7
    assert throttler.dropped_count >= 993
    assert throttler.emitted_count + throttler.dropped_count == 1000


def test_throttler_turbo_mode_bypass():
    """Verify that when display_live is False, zero intermediate frames are emitted."""
    throttler = SignalThrottler(max_fps=60.0, display_live=False)

    for i in range(500):
        t = 100.0 + i * 0.001
        res = throttler.should_emit(t)
        assert res is False

    assert throttler.emitted_count == 0
    assert throttler.dropped_count == 500


def test_worker_execution_headless(qtbot):
    """Verify SolverWorker runs simulation and cleanly emits finished signal."""
    # Fast test configuration (Soliton N=1 with 512 points, 20 steps)
    pulse = PulseConfig(shape="sech", t_fwhm=1.76e-12, p_peak=16.46, center_wavelength=1550e-9)
    fiber = FiberConfig(
        length=5.0,  # 5 m
        gamma=1.3e-3,
        dispersion=DispersionConfig(mode="manual", betas=[-21.4e-27, 0.0, 0.0, 0.0, 0.0, 0.0]),
        raman_fr=0.0,
    )
    solver = SolverConfig(
        simulation_type="spectrum_vs_distance",
        method="RK4IP",
        n_points=512,
        time_window=20e-12,
        adaptive_step=False,
        initial_step=0.25,
    )

    worker = SolverWorker()
    with qtbot.waitSignal(worker.simulation_finished, timeout=5000) as blocker:
        worker.run_simulation(pulse, fiber, solver, display_live=True)

    final_state, history = blocker.args
    assert final_state is not None
    assert len(history) > 0
    assert final_state.z >= 5.0
    assert final_state.rel_energy_err < 1e-9


def test_worker_cooperative_abort(qtbot):
    """Verify abort() cleanly stops worker before reaching fiber end."""
    pulse = PulseConfig(shape="sech", t_fwhm=50e-15, p_peak=100.0, center_wavelength=835e-9)
    fiber = FiberConfig(
        length=1.0,  # 1 m (many steps)
        gamma=0.11,
        dispersion=DispersionConfig(mode="manual", betas=[-11.83e-27, 8.1e-41, 0.0, 0.0, 0.0, 0.0]),
        raman_fr=0.0,
    )
    solver = SolverConfig(
        simulation_type="spectrum_vs_distance",
        method="SSFM",
        n_points=512,
        time_window=10e-12,
        adaptive_step=False,
        initial_step=1e-4,
    )

    worker = SolverWorker()

    # Trigger abort immediately after start
    def abort_trigger():
        time.sleep(0.02)
        worker.abort()

    import threading
    t = threading.Thread(target=abort_trigger)
    t.start()

    with qtbot.waitSignal(worker.simulation_aborted, timeout=3000):
        worker.run_simulation(pulse, fiber, solver, display_live=False)

    t.join()
    assert worker.is_running is False


def test_worker_setup_and_start_slot(qtbot):
    """Verify worker setup() and start() slot execute cleanly."""
    pulse = PulseConfig(shape="sech", t_fwhm=50e-15, p_peak=100.0, center_wavelength=835e-9)
    fiber = FiberConfig(
        length=0.1,
        gamma=0.11,
        dispersion=DispersionConfig(mode="manual", betas=[-11.83e-27, 0.0, 0.0, 0.0, 0.0, 0.0]),
        raman_fr=0.0,
    )
    solver = SolverConfig(
        simulation_type="spectrum_vs_distance",
        method="SSFM",
        n_points=256,
        time_window=5e-12,
        adaptive_step=False,
        initial_step=0.05,
    )

    worker = SolverWorker()
    worker.setup(pulse, fiber, solver, display_live=False)

    with qtbot.waitSignal(worker.simulation_finished, timeout=3000) as blocker:
        worker.start()

    final_state, history = blocker.args
    assert final_state is not None
    assert final_state.z >= 0.1


def test_worker_pause_then_abort(qtbot):
    """Verify aborting while paused immediately terminates the worker."""
    pulse = PulseConfig(shape="sech", t_fwhm=50e-15, p_peak=100.0, center_wavelength=835e-9)
    fiber = FiberConfig(
        length=5.0,
        gamma=0.11,
        dispersion=DispersionConfig(mode="manual", betas=[-11.83e-27, 0.0, 0.0, 0.0, 0.0, 0.0]),
        raman_fr=0.0,
    )
    solver = SolverConfig(
        simulation_type="spectrum_vs_distance",
        method="SSFM",
        n_points=256,
        time_window=5e-12,
        adaptive_step=False,
        initial_step=1e-3,
    )

    worker = SolverWorker()
    worker.setup(pulse, fiber, solver, display_live=False)

    import threading
    def pause_then_abort():
        time.sleep(0.02)
        worker.pause()
        time.sleep(0.02)
        worker.abort()

    t = threading.Thread(target=pause_then_abort)
    t.start()

    with qtbot.waitSignal(worker.simulation_aborted, timeout=3000):
        worker.start()

    t.join()
    assert worker.is_running is False


def test_worker_pause_then_resume(qtbot):
    """Verify pausing and then resuming completes the simulation cleanly."""
    pulse = PulseConfig(shape="sech", t_fwhm=50e-15, p_peak=100.0, center_wavelength=835e-9)
    fiber = FiberConfig(
        length=0.1,
        gamma=0.11,
        dispersion=DispersionConfig(mode="manual", betas=[-11.83e-27, 0.0, 0.0, 0.0, 0.0, 0.0]),
        raman_fr=0.0,
    )
    solver = SolverConfig(
        simulation_type="spectrum_vs_distance",
        method="SSFM",
        n_points=256,
        time_window=5e-12,
        adaptive_step=False,
        initial_step=0.01,
    )

    worker = SolverWorker()
    worker.setup(pulse, fiber, solver, display_live=False)

    import threading
    def pause_then_resume():
        time.sleep(0.01)
        worker.pause()
        time.sleep(0.02)
        worker.resume()

    t = threading.Thread(target=pause_then_resume)
    t.start()

    with qtbot.waitSignal(worker.simulation_finished, timeout=4000) as blocker:
        worker.start()

    t.join()
    final_state, history = blocker.args
    assert final_state is not None
    assert pytest.approx(final_state.z, abs=1e-6) == 0.1
    assert worker.is_running is False
