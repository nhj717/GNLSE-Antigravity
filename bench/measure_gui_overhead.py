import os
import time
import numpy as np
from PyQt6.QtWidgets import QApplication
from src.gui.main_window import MainWindow
from src.solver.config import PulseConfig, FiberConfig, DispersionConfig, SolverConfig

def benchmark():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    app = QApplication.instance() or QApplication([])

    window = MainWindow()
    window.show()

    # Use default Hult 2007 SCG parameters (representative of real runs)
    # 50 fs, 10 kW, 835 nm, 15 cm fiber, 2048 points
    pulse = PulseConfig(shape="sech", t_fwhm=50e-15, p_peak=10e3, center_wavelength=835e-9)
    disp = DispersionConfig.from_si(
        beta2=-1.276e-26,
        beta3=8.119e-41,
        beta4=-1.321e-55,
        beta5=3.032e-70,
        beta6=-4.196e-85,
        beta7=2.570e-100,
    )
    fiber = FiberConfig(
        length=0.03,  # 3 cm for quick benchmark
        gamma=0.11,
        loss_alpha_db=0.0,
        dispersion=disp,
        raman_fr=0.18,
        raman_tau1=12.2e-15,
        raman_tau2=32.0e-15,
    )
    solver = SolverConfig(
        simulation_type="spectrum_vs_distance",
        method="RK4IP",
        n_points=2048,
        time_window=6e-12,
        adaptive_step=True,
        initial_step=5e-5,
        min_step=1e-7,
        max_step=1e-3,
        tolerance=1e-4,
        filter_alias=False,
        raman_enabled=True,
        shock_enabled=True,
        z_records=400,
    )

    from PyQt6.QtCore import QEventLoop

    print("=== Testing with display_live=False ===")
    window._start_simulation(pulse, fiber, solver, display_live=False)
    loop = QEventLoop()
    window.worker.simulation_finished.connect(loop.quit)
    window.worker.error_occurred.connect(loop.quit)

    t0 = time.perf_counter()
    loop.exec()
    t_no_live = time.perf_counter() - t0
    print(f"display_live=False took: {t_no_live:.3f} s")

    # Wait for thread cleanup
    while window.worker_thread is not None and window.worker_thread.isRunning():
        app.processEvents()
        time.sleep(0.01)

    print("\n=== Testing with display_live=True ===")
    window._start_simulation(pulse, fiber, solver, display_live=True)
    loop2 = QEventLoop()
    window.worker.simulation_finished.connect(loop2.quit)
    window.worker.error_occurred.connect(loop2.quit)

    t0 = time.perf_counter()
    loop2.exec()
    t_live = time.perf_counter() - t0
    print(f"display_live=True took: {t_live:.3f} s")
    print(f"Slowdown factor: {t_live / t_no_live:.2f}x")

if __name__ == "__main__":
    benchmark()
