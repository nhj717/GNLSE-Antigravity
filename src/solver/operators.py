"""Linear and nonlinear operators, filters, and conservation integrators for GNLSE.

Implements the master computational equation operators:
- Linear dispersion operator D(Omega) (Taylor series via Horner's method or spline interpolation)
- Self-steepening shock factor (1 + Omega / omega_0) with DC clamping safeguard
- Nonlinear operator N(A) with Raman convolution and shock factor
- Anti-aliasing super-Gaussian frequency filter
- Pulse energy and photon number conservation integrators
"""

from __future__ import annotations

import os
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

        omega_data, beta_data = _load_dispersion_file(path, dispersion)

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


def _load_dispersion_file(path: Path, dispersion=None) -> tuple[np.ndarray, np.ndarray]:
    """Load dispersion curve from CSV or HDF5 and return (omega_sorted, beta_sorted).

    Handles:
    - Direct beta(omega) or beta(lambda) in [rad/m]
    - GVD beta_2(lambda) or beta_2(omega) in [s^2/m] (integrated twice to beta)
    - Dispersion parameter D(lambda) in [ps/(nm·km)]
      converted via beta_2(lambda) = - (lambda^2 / (2 * pi * c)) * D_SI
      and integrated twice to beta(omega).
    - Effective index n_eff(omega) converted via beta(omega) = omega/c * Re(n_eff).
    """
    suffix = path.suffix.lower()
    y_type = "auto"
    if dispersion and hasattr(dispersion, "data_type"):
        y_type = dispersion.data_type

    y_name = ""
    x_name = ""

    if suffix in (".csv", ".txt", ".dat"):
        header_line = ""
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    stripped = line.strip()
                    if stripped.startswith("#") or any(c.isalpha() for c in stripped):
                        header_line = stripped.lower()
                        break
        except Exception:
            pass

        # Auto-detect delimiters
        for delimiter in (",", None, "\t", ";"):
            try:
                data = np.loadtxt(path, delimiter=delimiter, skiprows=0)
                if data.ndim == 2 and data.shape[1] >= 2:
                    break
            except Exception:
                continue
        else:
            import pandas as pd
            df = pd.read_csv(path)
            data = df.values

        x = np.asarray(data[:, 0], dtype=float)
        y = np.asarray(data[:, 1], dtype=float)

        if "beta2" in header_line or "b2" in header_line:
            y_name = "beta2"
        elif "d_" in header_line or ",d" in header_line or "disp" in header_line:
            y_name = "d"
        elif "beta" in header_line:
            y_name = "beta"

    elif suffix in (".h5", ".hdf5"):
        import h5py
        with h5py.File(path, "r") as f:
            if dispersion and dispersion.h5_group and dispersion.h5_dataset_x and dispersion.h5_dataset_y:
                g = dispersion.h5_group
                group = f if g == "/" else f[g.rstrip("/")]
                x = np.asarray(group[dispersion.h5_dataset_x], dtype=float)
                raw_y = np.asarray(group[dispersion.h5_dataset_y])
                y = np.real(raw_y) if np.iscomplexobj(raw_y) else np.asarray(raw_y, dtype=float)
                x_name = dispersion.h5_dataset_x.lower()
                y_name = dispersion.h5_dataset_y.lower()
            else:
                if "omega" in f and "beta" in f:
                    x = np.asarray(f["omega"], dtype=float)
                    y = np.asarray(f["beta"], dtype=float)
                    y_name = "beta"
                elif "wavelength" in f and "beta" in f:
                    x = np.asarray(f["wavelength"], dtype=float)
                    y = np.asarray(f["beta"], dtype=float)
                    y_name = "beta"
                elif "data" in f:
                    d = np.asarray(f["data"], dtype=float)
                    x = d[:, 0]
                    y = d[:, 1]
                else:
                    keys = list(f.keys())
                    if len(keys) >= 2:
                        x = np.asarray(f[keys[0]], dtype=float)
                        raw_y = np.asarray(f[keys[1]])
                        y = np.real(raw_y) if np.iscomplexobj(raw_y) else np.asarray(raw_y, dtype=float)
                        x_name = keys[0].lower()
                        y_name = keys[1].lower()
                    else:
                        raise ValueError(f"HDF5 file must contain at least 2 datasets, found: {keys}")
    else:
        raise ValueError(f"Unsupported file format: {suffix}. Must be .csv or .h5")

    # 1. Determine wavelength [m] and angular frequency omega [rad/s]
    # Optical frequencies omega are typically ~ 1e14 - 1e16 rad/s (x > 1e9).
    # Wavelength in nm is typically ~ 100 - 50000 nm (x > 10.0 or x_name contains 'nm').
    # Wavelength in um is typically ~ 0.1 - 20 um ('um' in x_name or 0.001 < x < 10.0).
    # Wavelength in meters is typically ~ 1e-7 - 1e-4 m (x < 1e-3).
    if np.all(x > 1e9) or "omega" in x_name or "freq" in x_name:
        omega_arr = x
        wl_m = 2.0 * math.pi * C_CONST / np.maximum(omega_arr, 1e-10)
    elif "um" in x_name or (np.all(x > 0.01) and np.all(x < 50.0)):
        # Micrometers [um]
        wl_m = x * 1e-6
        omega_arr = 2.0 * math.pi * C_CONST / wl_m
    elif np.all(x > 50.0) or "nm" in x_name:
        # Nanometers [nm]
        wl_m = x * 1e-9
        omega_arr = 2.0 * math.pi * C_CONST / wl_m
    elif np.all(x < 1e-3):
        # Meters [m]
        wl_m = x
        omega_arr = 2.0 * math.pi * C_CONST / wl_m
    else:
        omega_arr = x
        wl_m = 2.0 * math.pi * C_CONST / np.maximum(omega_arr, 1e-10)

    # 2. Identify physical nature of y (Dispersion D, beta_2, beta_0, or n_eff)
    # Check explicit data_type or infer from names / magnitudes
    is_d = (y_type == "D") or (y_name in ("d", "disp", "dispersion", "d_ps_nm_km"))
    is_beta2 = (y_type == "beta2") or (y_name in ("beta2", "b2"))
    is_neff = (y_type == "n_eff") or (y_name in ("n", "n_eff", "neff"))
    is_beta0 = (y_type == "beta") or (y_name in ("beta", "beta0", "b0"))

    if not (is_d or is_beta2 or is_neff or is_beta0):
        # Auto-detect by magnitude
        y_abs_max = float(np.max(np.abs(y)))
        if 1e-30 < y_abs_max < 1e-20:
            is_beta2 = True
        elif 0.8 <= y_abs_max <= 5.0 and "n" in y_name:
            is_neff = True
        elif y_abs_max > 1e4 and not is_d:
            is_beta0 = True
        else:
            # Default to dispersion parameter D [ps/(nm·km)]
            is_d = True

    # Sort strictly ascending by angular frequency omega
    sort_idx = np.argsort(omega_arr)
    w_sorted = omega_arr[sort_idx]
    y_sorted = y[sort_idx]
    wl_sorted = wl_m[sort_idx]

    if is_d:
        # Convert D [ps/(nm·km)] to beta_2 [s^2/m]
        # Formula: beta_2(lambda) = - (lambda^2 / (2 * pi * c)) * D_SI
        # where D_SI = D * 1e-6 s/m^2
        d_si = y_sorted * 1e-6
        beta2_arr = - (wl_sorted ** 2 / (2.0 * math.pi * C_CONST)) * d_si
        cs_b2 = CubicSpline(w_sorted, beta2_arr)
        cs_beta = cs_b2.antiderivative(2)
        beta_sorted = cs_beta(w_sorted)
    elif is_beta2:
        # Integrate beta_2(omega) twice to obtain beta(omega)
        cs_b2 = CubicSpline(w_sorted, y_sorted)
        cs_beta = cs_b2.antiderivative(2)
        beta_sorted = cs_beta(w_sorted)
    elif is_neff:
        # beta(omega) = omega/c * Re(n_eff)
        beta_sorted = (w_sorted / C_CONST) * y_sorted
    else:
        # Direct propagation constant beta(omega) [rad/m]
        beta_sorted = y_sorted

    return w_sorted, beta_sorted


def evaluate_taylor_betas(
    omega_data: np.ndarray,
    beta_data: np.ndarray,
    omega0: float,
    max_order: int = 7,
) -> list[float]:
    """Evaluate Taylor dispersion coefficients beta_2 through beta_max at carrier omega0.

    Parameters:
    - omega_data: 1D array of angular frequencies [rad/s] (ascending)
    - beta_data: 1D array of propagation constants beta(omega) [rad/m]
    - omega0: Carrier angular frequency [rad/s]
    - max_order: Maximum Taylor expansion order (default 7)

    Returns:
    - List of floats [beta2, beta3, ..., beta_max] in SI units [s^k / m].
    """
    spline = CubicSpline(omega_data, beta_data)
    betas = []
    for k in range(2, max_order + 1):
        try:
            val = float(spline.derivative(k)(omega0))
        except Exception:
            val = 0.0
        betas.append(val)
    return betas


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
    dt: float = 1.0,
) -> np.ndarray:
    """Compute frequency-domain nonlinear operator N_hat[A] per Spec §2.5:

        Step 1: I(T) = |A(T)|^2
        Step 2: Raman convolution via FFT: h_R * I
        Step 3: Total nonlinear response B(T) = A(T) * [(1 - f_R) * I + f_R * (h_R * I)]
        Step 4: N_hat = i * gamma * (1 + Omega / omega_0) * IFFT(B)

    Parameters:
    - a_t: Complex field envelope array in time domain A(T) [sqrt(W)]
    - gamma: Fiber nonlinear coefficient [W^-1 m^-1]
    - shock_factor: 1D real array (1 + Omega/omega0), or None if self-steepening is OFF
    - raman_fft: Precomputed FFT of discrete Raman kernel from prepare_raman_fft
    - raman_fr: Fractional Raman contribution (0.0 if Raman is OFF)
    - dt: Sampling interval Delta T [s] (default 1.0)

    Returns:
    - N_hat: 1D complex array of length N in frequency domain [sqrt(W) / m]
    """
    intensity = np.abs(a_t) ** 2

    if raman_fr > 0.0 and raman_fft is not None:
        i_conv = raman_convolution(intensity, raman_fft, dt)
        b_t = a_t * ((1.0 - raman_fr) * intensity + raman_fr * i_conv)
    else:
        b_t = a_t * intensity

    b_w = np.fft.ifft(b_t)

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

        N_ph = dt * sum_{k: omega_0 + Omega_k > 0} (|A_tilde_k|^2 / (omega_0 + Omega_k))

    Includes DC singularity guard: excludes frequencies where omega_0 + Omega_k <= 0.
    """
    w_total = omega0 + omega
    valid_mask = w_total > 0.0
    if not np.any(valid_mask):
        return 0.0

    integrand = (np.abs(a_w[valid_mask]) ** 2) / w_total[valid_mask]
    return float(dt * np.sum(integrand))


def relative_error(current: float, initial: float) -> float:
    """Compute relative conservation drift |current - initial| / |initial|."""
    denom = abs(initial)
    if denom == 0.0:
        return abs(current - initial)
    return abs(current - initial) / denom


def compute_gamma_from_aeff(
    a_eff_m2: float,
    wl_m: float,
    n2: float = 2.6e-20,
) -> tuple[float, float]:
    """Calculate nonlinear coefficient gamma from effective mode area A_eff.

    Formula:
        gamma_si = (2 * pi * n2) / (lambda_0 * A_eff)   [W^-1 m^-1]
        gamma_w_km = gamma_si * 1e3                     [W^-1 km^-1]

    Parameters:
    - a_eff_m2: Effective mode area in m^2
    - wl_m: Carrier wavelength in meters
    - n2: Nonlinear refractive index [m^2/W] (default fused silica 2.6e-20)

    Returns:
    - Tuple (gamma_si [W^-1 m^-1], gamma_w_km [W^-1 km^-1])
    """
    if a_eff_m2 <= 0.0 or wl_m <= 0.0:
        raise ValueError(f"a_eff_m2 and wl_m must be positive, got A_eff={a_eff_m2}, wl={wl_m}")
    gamma_si = (2.0 * math.pi * n2) / (wl_m * a_eff_m2)
    gamma_w_km = gamma_si * 1e3
    return float(gamma_si), float(gamma_w_km)


def extract_h5_aeff(
    file_path: str,
    group_path: str = "/",
    carrier_wl_m: float = 850e-9,
) -> Optional[float]:
    """Extract and interpolate effective mode area A_eff [m^2] at carrier_wl_m from an HDF5 group.

    Parameters:
    - file_path: Path to .h5 or .hdf5 file
    - group_path: Group path inside HDF5 file (e.g. '/' or '/20230330_4_ideal')
    - carrier_wl_m: Optical carrier wavelength in meters (default 850 nm)

    Returns:
    - a_eff_m2: Effective mode area in m^2, or None if dataset not found.
    """
    if not file_path or not os.path.exists(file_path):
        return None

    try:
        import h5py
        with h5py.File(file_path, "r") as f:
            if group_path == "/" or not group_path:
                grp = f
            else:
                grp = f[group_path.rstrip("/")]

            # Look for A_eff dataset candidate
            aeff_key = None
            for candidate in ("A_eff", "Aeff", "a_eff", "aeff", "area_eff"):
                if candidate in grp and isinstance(grp[candidate], h5py.Dataset):
                    aeff_key = candidate
                    break

            if aeff_key is None:
                return None

            raw_aeff = np.array(grp[aeff_key], dtype=float)
            if raw_aeff.size == 0:
                return None

            # Handle scalar A_eff
            if raw_aeff.ndim == 0 or raw_aeff.size == 1:
                val = float(raw_aeff.item())
                if val > 1e-4:
                    val = val * 1e-12
                return val

            # Array of A_eff: Find corresponding wavelength / frequency coordinate
            wl_key = None
            for candidate in ("wl_um", "wavelength_um", "wavelength_nm", "wavelength", "wl", "lambda", "omega", "freq"):
                if candidate in grp and isinstance(grp[candidate], h5py.Dataset):
                    wl_key = candidate
                    break

            if wl_key is None:
                val = float(raw_aeff.mean())
                if val > 1e-4:
                    val = val * 1e-12
                return val

            raw_coord = np.array(grp[wl_key], dtype=float)

            # Determine wavelength in meters
            if "freq" in wl_key.lower():
                wl_m = C_CONST / np.maximum(raw_coord, 1e-10)
            elif "omega" in wl_key.lower() or np.all(raw_coord > 1e9):
                wl_m = 2.0 * math.pi * C_CONST / np.maximum(raw_coord, 1e-10)
            elif "um" in wl_key.lower() or (np.all(raw_coord > 0.01) and np.all(raw_coord < 50.0)):
                wl_m = raw_coord * 1e-6
            elif "nm" in wl_key.lower() or np.all(raw_coord > 50.0):
                wl_m = raw_coord * 1e-9
            elif np.all(raw_coord < 1e-3):
                wl_m = raw_coord
            else:
                wl_m = raw_coord * 1e-6

            # Sort ascending by wavelength for robust interpolation
            sort_idx = np.argsort(wl_m)
            wl_sorted = wl_m[sort_idx]
            aeff_sorted = raw_aeff[sort_idx]

            interp_val = float(np.interp(carrier_wl_m, wl_sorted, aeff_sorted))

            # Unit sanity check: if A_eff > 1e-4, it was stored in um^2 -> convert to m^2
            if interp_val > 1e-4:
                interp_val = interp_val * 1e-12

            return interp_val
    except Exception:
        return None


