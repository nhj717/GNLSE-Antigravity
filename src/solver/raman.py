"""Raman response function and convolution operators for silica fibers.

Implements the Blow-Wood model (Blow & Wood, 1989):
    h_R(T) = ((tau1^2 + tau2^2) / (tau1 * tau2^2)) * exp(-T / tau2) * sin(T / tau1) * Theta(T)

Normalized such that:
    integral_0^infinity h_R(T) dT = 1.0
"""

from __future__ import annotations

import numpy as np


def blow_wood_raman_response(
    t: np.ndarray,
    tau1: float = 12.2e-15,
    tau2: float = 32.0e-15,
) -> np.ndarray:
    """Evaluate continuous Blow-Wood Raman response function h_R(T) in [s^-1].

    Parameters:
    - t: Retarded time array [s]
    - tau1: Raman oscillation timescale [s] (default 12.2 fs for silica)
    - tau2: Raman damping timescale [s] (default 32.0 fs for silica)

    Returns:
    - hr: Raman response array [s^-1], with hr(t < 0) = 0
    """
    hr = np.zeros_like(t, dtype=np.float64)
    positive_mask = t > 0.0
    t_pos = t[positive_mask]

    prefactor = (tau1**2 + tau2**2) / (tau1 * (tau2**2))
    hr[positive_mask] = prefactor * np.exp(-t_pos / tau2) * np.sin(t_pos / tau1)
    return hr


def prepare_raman_fft(
    n_points: int,
    dt: float,
    tau1: float = 12.2e-15,
    tau2: float = 32.0e-15,
) -> np.ndarray:
    """Precompute the frequency-domain discrete Raman convolution kernel FFT(h_R * dt).

    As derived in GNLSE Theoretical Spec §2.5 and Amendment 6:
    - Discrete response is causal: h_R[n] = h_R(n * dt) for n = 0, ..., N-1.
    - Since h_R decays with tau2 = 32 fs, it vanishes well before N * dt.
    - Discrete Riemann normalization sum(h_R[n] * dt) is strictly normalized to 1.0.
    - The discrete circular convolution with intensity I_n:
        (h_R * I)_n = IFFT(raman_fft * FFT(I))_n
      directly yields the convolution integral in power units [W].

    Parameters:
    - n_points: Number of grid points N
    - dt: Sampling interval Delta T [s]
    - tau1: Raman oscillation timescale [s]
    - tau2: Raman damping timescale [s]

    Returns:
    - raman_fft: 1D complex array of length N containing FFT(h_R_discrete)
    """
    t_causal = np.arange(n_points, dtype=np.float64) * dt
    hr_continuous = blow_wood_raman_response(t_causal, tau1=tau1, tau2=tau2)

    # Numerical integral for exact discrete normalization:
    hr_integral = float(np.sum(hr_continuous) * dt)
    if hr_integral > 0.0:
        hr_discrete = (hr_continuous * dt) / hr_integral
    else:
        hr_discrete = hr_continuous * dt

    return np.fft.fft(hr_discrete)


def raman_convolution(
    intensity: np.ndarray,
    raman_fft: np.ndarray,
) -> np.ndarray:
    """Compute the Raman convolution integral (h_R * |A|^2)(T) via FFT.

    Parameters:
    - intensity: Optical intensity array |A(T)|^2 [W]
    - raman_fft: Precomputed FFT of discrete Raman kernel from prepare_raman_fft

    Returns:
    - Real-valued convolution array in [W]
    """
    return np.real(np.fft.ifft(raman_fft * np.fft.fft(intensity)))
