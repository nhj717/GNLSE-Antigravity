"""Microbenchmark: compares NumPy, C + scipy.fft, and C + pyFFTW at operator and stepper level."""

import time
import numpy as np
import scipy.fft as sf

from bench.bench_solver import build
from src.solver import engine
from src.solver.accel import c_steppers as cs, fft_backend
from src.solver.operators import (
    compute_dispersion_operator,
    compute_shock_factor,
    compute_nonlinear_operator,
)
from src.solver.raman import prepare_raman_fft

p, f, s = build()
n = s.n_points
dt = s.time_window / n
t = (np.arange(n) - n / 2) * dt
om = 2 * np.pi * np.fft.fftfreq(n, d=dt)
d = compute_dispersion_operator(omega=om, dispersion=f.dispersion, alpha_si=f.alpha_si, omega0=p.omega_0)
R = prepare_raman_fft(n_points=n, dt=dt, tau1=f.raman_tau1, tau2=f.raman_tau2)
sh = compute_shock_factor(omega=om, omega0=p.omega_0, enabled=True)
at = engine.generate_initial_pulse(p, t)
aw = np.fft.ifft(at)
args = (d, f.gamma, sh, R, f.raman_fr, None)


def tm(fn, h=1e-4, k=300, repeat=5):
    best = 1e9
    for _ in range(repeat):
        t0 = time.perf_counter()
        for _ in range(k):
            fn(at, aw, h, *args, dt=dt)
        best = min(best, (time.perf_counter() - t0) / k)
    return best * 1e6


def run_micro():
    print("=" * 72)
    print(f"GNLSE MICROBENCHMARK (N={n}, dt={dt:.2e} s)")
    print("=" * 72)

    # 1. 1D FFT Microbenchmarks
    cin = at.copy()
    fft_backend.set_fft_backend("pyfftw")
    for _ in range(100):
        fft_backend.fft(cin)
    t0 = time.perf_counter()
    for _ in range(5000):
        fft_backend.fft(cin)
    t_pyfftw_fft = (time.perf_counter() - t0) * 1e6 / 5000

    fft_backend.set_fft_backend("scipy")
    for _ in range(100):
        fft_backend.fft(cin)
    t0 = time.perf_counter()
    for _ in range(5000):
        fft_backend.fft(cin)
    t_scipy_fft = (time.perf_counter() - t0) * 1e6 / 5000

    print(f"1D FFT (N={n}):")
    print(f"  scipy.fft: {t_scipy_fft:.2f} us")
    print(f"  pyFFTW:    {t_pyfftw_fft:.2f} us  ({t_scipy_fft / t_pyfftw_fft:.2f}x speedup)")
    print("-" * 72)

    # 2. Stepper benchmarks
    print(f"{'Stepper':<18} | {'NumPy':>10} | {'C + scipy':>12} | {'C + pyFFTW':>12} | {'Speedup':>9}")
    print("-" * 72)

    for name, np_fn, c_fn in [
        ("RK4IP", engine.step_rk4ip, cs.step_rk4ip_c),
        ("S-SSFM", engine.step_sssfm, cs.step_sssfm_c),
        ("SSFM", engine.step_ssfm, cs.step_ssfm_c),
    ]:
        # NumPy baseline
        t_np = tm(np_fn)

        # C + scipy
        fft_backend.set_fft_backend("scipy")
        t_scipy = tm(c_fn)

        # C + pyFFTW
        fft_backend.set_fft_backend("pyfftw")
        t_pyfftw = tm(c_fn)

        speedup = t_np / t_pyfftw
        print(f"{name:<18} | {t_np:>7.1f} us | {t_scipy:>9.1f} us | {t_pyfftw:>9.1f} us | {speedup:>8.2f}x")

    # S-SSFM without shock
    sh1 = np.ones(n)
    global args
    old_args = args
    args = (d, f.gamma, sh1, R, f.raman_fr, None)
    t_np_noshock = tm(engine.step_sssfm)
    fft_backend.set_fft_backend("scipy")
    t_scipy_noshock = tm(cs.step_sssfm_c)
    fft_backend.set_fft_backend("pyfftw")
    t_pyfftw_noshock = tm(cs.step_sssfm_c)
    speedup_noshock = t_np_noshock / t_pyfftw_noshock
    print(f"{'S-SSFM (no shock)':<18} | {t_np_noshock:>7.1f} us | {t_scipy_noshock:>9.1f} us | {t_pyfftw_noshock:>9.1f} us | {speedup_noshock:>8.2f}x")
    args = old_args

    print("-" * 72)
    # 3. Equivalence check
    fft_backend.set_fft_backend("pyfftw")
    a_py = engine.step_rk4ip(at, aw, 1e-4, d, f.gamma, sh, R, f.raman_fr, None, dt=dt)
    a_c_pyfftw = cs.step_rk4ip_c(at, aw, 1e-4, d, f.gamma, sh, R, f.raman_fr, None, dt=dt)
    fft_backend.set_fft_backend("scipy")
    a_c_scipy = cs.step_rk4ip_c(at, aw, 1e-4, d, f.gamma, sh, R, f.raman_fr, None, dt=dt)

    rel_diff_pyfftw = np.max(np.abs(a_py[0] - a_c_pyfftw[0])) / np.max(np.abs(a_py[0]))
    rel_diff_scipy = np.max(np.abs(a_py[0] - a_c_scipy[0])) / np.max(np.abs(a_py[0]))

    print(f"Max relative difference vs NumPy baseline:")
    print(f"  C + pyFFTW:  {rel_diff_pyfftw:.2e}")
    print(f"  C + scipy:   {rel_diff_scipy:.2e}")
    print("=" * 72)

    # restore default
    fft_backend.set_fft_backend("pyfftw")


if __name__ == "__main__":
    run_micro()
