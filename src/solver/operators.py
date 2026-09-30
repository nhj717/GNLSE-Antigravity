"""Linear and nonlinear operators, filters, and conservation integrators for GNLSE.

Implements the master computational equation operators:
- Linear dispersion operator D(Omega) (Taylor series via Horner's method or spline interpolation)
- Self-steepening shock factor (1 + Omega / omega_0) with DC clamping safeguard
- Nonlinear operator N(A) with Raman convolution and shock factor
- Anti-aliasing super-Gaussian frequency filter
- Pulse energy and photon number conservation integrators
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Optional
import numpy as np
from scipy.interpolate import CubicSpline

from .config import DispersionConfig, C_CONST
from .raman import raman_convolution


def compute_dispersion_operator(
    omega: np.ndarray,
    dispersion: DispersionConfig,
    alpha_si: float = 0.0,
    omega0: float = 0.0,
) -> np.ndarray:
    """Evaluate linear dispersion operator D(Omega) in the frequency domain [m^-1].

    Formula:
        D(Omega) = -alpha / 2 + i * phi(Omega)

    In manual mode (Taylor series via Horner's scheme):
        phi(Omega) = sum_{k=2}^7 (beta_k / k!) * Omega^k

    In import mode:
        phi(Omega) = beta(omega_0 + Omega) - beta(omega_0) - beta_1 * Omega
    using cubic spline interpolation of imported beta(omega).

    Parameters:
    - omega: Angular frequency offset grid Omega = omega - omega_0 [rad/s]
    - dispersion: DispersionConfig specifying mode and parameters
    - alpha_si: Power attenuation coefficient in [m^-1]
    - omega0: Carrier angular frequency [rad/s] (required for import mode)

    Returns:
    - Complex 1D array D(Omega) of length N [m^-1]
    """
    if dispersion.mode == "manual":
        # Betas: beta_2 .. beta_7
        b = dispersion.betas
        b2 = b[0] if len(b) > 0 else 0.0
        b3 = b[1] if len(b) > 1 else 0.0
        b4 = b[2] if len(b) > 2 else 0.0
        b5 = b[3] if len(b) > 3 else 0.0
        b6 = b[4] if len(b) > 4 else 0.0
        b7 = b[5] if len(b) > 5 else 0.0

        # Horner's method evaluation for numerical stability:
        # phi(Omega) = Omega^2 * (b2/2 + Omega * (b3/6 + Omega * (b4/24 + Omega * (b5/120 + Omega * (b6/720 + Omega * b7/5040)))))
        term = b7 / 5040.0
        term = b6 / 720.0 + omega * term
        term = b5 / 120.0 + omega * term
        term = b4 / 24.0 + omega * term
        term = b3 / 6.0 + omega * term
        term = b2 / 2.0 + omega * term
        phi = (omega**2) * term

        return (-0.5 * alpha_si) + 1j * phi

    elif dispersion.mode == "import":
        if not dispersion.import_path:
            raise ValueError("Import path must be provided when dispersion mode is 'import'.")
        path = Path(dispersion.import_path)
        if not path.is_file():
            raise FileNotFoundError(f"Dispersion import file not found: {path}")

        omega_data, beta_data = _load_dispersion_file(path)

        # Build cubic spline
        spline = CubicSpline(omega_data, beta_data)
        if omega0 <= 0.0:
            raise ValueError(f"omega0 must be positive for imported dispersion, got {omega0}")

        beta_0 = float(spline(omega0))
        beta_1 = float(spline(omega0, nu=1))  # First derivative dbeta/domega at omega_0

        w_grid = omega0 + omega
        beta_eval = spline(w_grid)
        phi = beta_eval - beta_0 - beta_1 * omega

        return (-0.5 * alpha_si) + 1j * phi

    else:
        raise ValueError(f"Unknown dispersion mode: {dispersion.mode}")


def _load_dispersion_file(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Load dispersion curve from CSV or HDF5."""
    suffix = path.suffix.lower()
    if suffix in (".csv", ".txt", ".dat"):
        # Auto-detect delimiters
        for delimiter in (",", None, "\t", ";"):
            try:
                data = np.loadtxt(path, delimiter=delimiter, skiprows=0)
                if data.ndim == 2 and data.shape[1] >= 2:
                    break
            except Exception:
                continue
        else:
            # Fallback to pandas
            import pandas as pd
            df = pd.read_csv(path)
            data = df.values

        x = data[:, 0]
        y = data[:, 1]

    elif suffix in (".h5", ".hdf5"):
        import h5py
        with h5py.File(path, "r") as f:
            if "omega" in f and "beta" in f:
                x = np.asarray(f["omega"])
                y = np.asarray(f["beta"])
            elif "wavelength" in f and "beta" in f:
                x = np.asarray(f["wavelength"])
                y = np.asarray(f["beta"])
            elif "data" in f:
                d = np.asarray(f["data"])
                x = d[:, 0]
                y = d[:, 1]
            else:
                # pick first two datasets
                keys = list(f.keys())
                if len(keys) >= 2:
                    x = np.asarray(f[keys[0]])
                    y = np.asarray(f[keys[1]])
                else:
                    raise ValueError(f"HDF5 file must contain at least 2 datasets, found: {keys}")
    else:
        raise ValueError(f"Unsupported file format: {suffix}. Must be .csv or .h5")

    # Determine whether x is wavelength (m or nm) or angular frequency (rad/s)
    # Optical angular frequencies omega are typically ~ 1e14 - 1e16 rad/s (omega > 1e10).
    # Wavelengths in nm are typically ~ 200 - 5000 nm (10 <= x <= 1e5).
    # Wavelengths in meters are typically ~ 1e-7 - 5e-6 m (x < 1e-3).
    if np.all(x > 1e9):
        # Angular frequency in rad/s
        omega_arr = x
    elif np.all(x > 10.0):
        # Wavelength in nm
        wavelength_m = x * 1e-9
        omega_arr = 2.0 * math.pi * C_CONST / wavelength_m
    elif np.all(x < 1e-3):
        # Wavelength in meters
        omega_arr = 2.0 * math.pi * C_CONST / x
    else:
        # Default: assumed angular frequency
        omega_arr = x

    # Ensure omega is strictly ascending for CubicSpline
    sort_idx = np.argsort(omega_arr)
    omega_sorted = omega_arr[sort_idx]
    beta_sorted = y[sort_idx]

    return omega_sorted, beta_sorted


def compute_shock_factor(
    omega: np.ndarray,
    omega0: float,
    enabled: bool = True,
) -> np.ndarray:
    """Compute convention-independent self-steepening factor (1 + Omega / omega_0).

    Safeguard: clamps at 0 to prevent unphysical negative values near DC (Omega -> -omega_0).
    """
    if not enabled or omega0 <= 0.0:
        return np.ones_like(omega, dtype=np.float64)
    factor = 1.0 + (omega / omega0)
    return np.maximum(0.0, factor)


def super_gaussian_filter(
    omega: np.ndarray,
    cutoff_fraction: float = 0.95,
    order: int = 20,
) -> np.ndarray:
    """Construct anti-aliasing super-Gaussian frequency window.

    W(Omega) = exp( - (|Omega| / (cutoff * Omega_max))^(2 * order) )
    """
    omega_max = float(np.max(np.abs(omega)))
    if omega_max <= 0.0 or cutoff_fraction <= 0.0:
        return np.ones_like(omega, dtype=np.float64)

    ratio = np.abs(omega) / (cutoff_fraction * omega_max)
    # Clip ratio to avoid floating point overflow in power
    ratio_clipped = np.clip(ratio, 0.0, 3.0)
    exponent = -(ratio_clipped ** (2 * order))
    return np.exp(exponent)


def compute_nonlinear_operator(
    a_t: np.ndarray,
    gamma: float,
    shock_factor: Optional[np.ndarray] = None,
    raman_fft: Optional[np.ndarray] = None,
    raman_fr: float = 0.0,
) -> np.ndarray:
    """Compute frequency-domain nonlinear operator N_hat[A] per Spec §2.5:

        Step 1: I(T) = |A(T)|^2
        Step 2: Raman convolution via FFT: h_R * I
        Step 3: Total nonlinear response B(T) = A(T) * [(1 - f_R) * I + f_R * (h_R * I)]
        Step 4: N_hat = i * gamma * (1 + Omega / omega_0) * FFT(B)

    Parameters:
    - a_t: Complex field envelope array in time domain A(T) [sqrt(W)]
    - gamma: Fiber nonlinear coefficient [W^-1 m^-1]
    - shock_factor: 1D real array (1 + Omega/omega0), or None if self-steepening is OFF
    - raman_fft: Precomputed FFT of discrete Raman kernel from prepare_raman_fft
    - raman_fr: Fractional Raman contribution (0.0 if Raman is OFF)

    Returns:
    - N_hat: 1D complex array of length N in frequency domain [sqrt(W) / m]
    """
    intensity = np.abs(a_t) ** 2

    if raman_fr > 0.0 and raman_fft is not None:
        i_conv = raman_convolution(intensity, raman_fft)
        b_t = a_t * ((1.0 - raman_fr) * intensity + raman_fr * i_conv)
    else:
        b_t = a_t * intensity

    b_w = np.fft.fft(b_t)

    if shock_factor is not None:
        return 1j * gamma * shock_factor * b_w
    return 1j * gamma * b_w


def compute_energy(a_t: np.ndarray, dt: float) -> float:
    """Compute total optical pulse energy E(z) [Joules] via discrete Riemann integral.

    E = dt * sum_{n=0}^{N-1} |A_n|^2
    """
    return float(dt * np.sum(np.abs(a_t) ** 2))


def compute_photon_number(
    a_w: np.ndarray,
    omega: np.ndarray,
    omega0: float,
    dt: float,
) -> float:
    """Compute photon number N_ph(z) [photons, arbitrary units] per Spec §2.9 & Amendment 9:

        N_ph = (dt^2 / N) * sum_{k: omega_0 + Omega_k > 0} (|A_tilde_k|^2 / (omega_0 + Omega_k))

    Includes DC singularity guard: excludes frequencies where omega_0 + Omega_k <= 0.
    """
    w_total = omega0 + omega
    valid_mask = w_total > 0.0
    if not np.any(valid_mask):
        return 0.0

    n_points = len(a_w)
    integrand = (np.abs(a_w[valid_mask]) ** 2) / w_total[valid_mask]
    return float((dt**2 / n_points) * np.sum(integrand))


def relative_error(current: float, initial: float) -> float:
    """Compute relative conservation drift |current - initial| / |initial|."""
    denom = abs(initial)
    if denom < 1e-30:
        return abs(current - initial)
    return abs(current - initial) / denom
