"""Benchmark: Hult 2007 SCG, adaptive step-doubling.

Usage:
  python -m bench.bench_solver                # Run active accelerated solver (pyFFTW)
  python -m bench.bench_solver --scipy        # Run C-accelerated with scipy.fft
  python -m bench.bench_solver --noaccel      # Run pure NumPy baseline
  python -m bench.bench_solver --compare      # Complete comparison suite (NumPy vs scipy vs pyFFTW)
"""

import sys
import time
import cProfile
import pstats
import numpy as np
from src.solver.config import PulseConfig, FiberConfig, DispersionConfig, SolverConfig
from src.solver import engine
from src.solver.accel import fft_backend


def build(method="RK4IP", n=2048, length=0.10):
    betas = [-1.276e-26, 8.119e-41, -1.321e-55, 3.032e-70, -4.196e-85, 2.570e-100]
    disp = DispersionConfig.from_si(
        beta2=betas[0],
        beta3=betas[1],
        beta4=betas[2],
        beta5=betas[3],
        beta6=betas[4],
        beta7=betas[5],
    )
    fiber = FiberConfig(
        length=length,
        gamma=0.045,
        loss_alpha_db=0.0,
        dispersion=disp,
        raman_fr=0.18,
        raman_tau1=12.2e-15,
        raman_tau2=32.0e-15,
    )
    pulse = PulseConfig(shape="sech", t_fwhm=50e-15, p_peak=1e4, center_wavelength=850e-9)
    solver = SolverConfig(
        simulation_type="spectrum_vs_distance",
        method=method,
        n_points=n,
        time_window=6e-12,
        adaptive_step=True,
        initial_step=5e-5,
        min_step=1e-7,
        max_step=1e-3,
        tolerance=1e-4,
        filter_alias=False,
        raman_enabled=True,
        shock_enabled=True,
        z_records=10,
    )
    return pulse, fiber, solver


def run(method):
    t0 = time.perf_counter()
    st = list(engine.solve_generator(*build(method)))
    return time.perf_counter() - t0, st


def run_comparison():
    methods = ["RK4IP", "S-SSFM", "SSFM"]
    print("=" * 78)
    print("GNLSE FULL-PROPAGATION BENCHMARK (Hult 2007 SCG: 10 cm, N=2048, adaptive)")
    print("=" * 78)
    print(f"{'Method':<10} | {'Pure NumPy':>12} | {'C + scipy':>12} | {'C + pyFFTW':>12} | {'Speedup':>9} | {'Max Rel Err':>12}")
    print("-" * 78)

    results = {}
    for m in methods:
        # 1. Pure NumPy baseline
        orig_accel = engine.is_accel_available
        engine.is_accel_available = lambda: False
        t_np, st_np = run(m)
        engine.is_accel_available = orig_accel

        # 2. C + scipy.fft
        fft_backend.set_fft_backend("scipy")
        t_scipy, st_scipy = run(m)

        # 3. C + pyFFTW
        fft_backend.set_fft_backend("pyfftw")
        t_pyfftw, st_pyfftw = run(m)

        # Verify numerical equivalence
        diff_t = np.max(np.abs(st_np[-1].a_t - st_pyfftw[-1].a_t)) / np.max(np.abs(st_np[-1].a_t))
        diff_w = np.max(np.abs(st_np[-1].a_w - st_pyfftw[-1].a_w)) / np.max(np.abs(st_np[-1].a_w))
        max_diff = max(diff_t, diff_w)

        speedup = t_np / t_pyfftw
        print(f"{m:<10} | {t_np:>10.3f}s | {t_scipy:>10.3f}s | {t_pyfftw:>10.3f}s | {speedup:>8.2f}x | {max_diff:>12.2e}")
        results[m] = {"np": t_np, "scipy": t_scipy, "pyfftw": t_pyfftw, "max_diff": max_diff}

    print("=" * 78)
    return results


if __name__ == "__main__":
    if "--compare" in sys.argv:
        run_comparison()
        sys.exit(0)

    if "--scipy" in sys.argv:
        fft_backend.set_fft_backend("scipy")
        print("Using FFT backend: scipy.fft")
    elif "--noaccel" in sys.argv:
        engine.is_accel_available = lambda: False
        print("Using Pure NumPy baseline")
    else:
        fft_backend.set_fft_backend("pyfftw")
        print(f"Using FFT backend: {fft_backend.get_fft_backend()}")

    if "--profile" in sys.argv:
        cProfile.run("run('RK4IP')", "/tmp/prof")
        pstats.Stats("/tmp/prof").sort_stats("tottime").print_stats(14)
        sys.exit()

    out = {}
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    for m in ["RK4IP", "S-SSFM", "SSFM"]:
        t_best = 1e9
        for _ in range(2):
            dt, st = run(m)
            if dt < t_best:
                t_best = dt
        print(f"{m}: best {t_best:.3f}s steps={st[-1].step}")
        out[m + "_a_t"] = st[-1].a_t
        out[m + "_a_w"] = st[-1].a_w

    if args:
        import os
        if os.path.exists(args[0]):
            ref = np.load(args[0])
            for k in out:
                print(k, "maxrel", np.max(np.abs(out[k] - ref[k])) / np.max(np.abs(ref[k])))
        else:
            np.savez(args[0], **out)
