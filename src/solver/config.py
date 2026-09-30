"""Configuration and state dataclasses for GNLSE pulse propagation simulator.

All internal calculations strictly use SI base units:
- Distance z: meters [m]
- Time T: seconds [s]
- Power P: watts [W]
- Dispersion beta_k: s^k / m
- Nonlinear parameter gamma: W^-1 m^-1
- Attenuation alpha: m^-1
- Frequency omega: rad / s
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal, Optional
import numpy as np

# Physical constant
C_CONST: float = 299792458.0  # Speed of light in vacuum [m/s]


@dataclass
class DispersionConfig:
    """Dispersion specification for the optical fiber.

    Supports:
    - "manual" mode: higher-order dispersion coefficients beta_2 through beta_7 (SI: s^k / m)
    - "import" mode: loading beta(omega) or dispersion D(lambda) from .csv or .h5 files
    """

    mode: Literal["manual", "import"] = "manual"
    # betas: [beta2, beta3, beta4, beta5, beta6, beta7] in SI units [s^k / m]
    betas: list[float] = field(default_factory=lambda: [0.0] * 6)
    import_path: Optional[str] = None

    def __post_init__(self) -> None:
        if self.mode not in ("manual", "import"):
            raise ValueError(f"Invalid dispersion mode '{self.mode}', must be 'manual' or 'import'.")
        # Ensure betas list has at least 6 elements
        if len(self.betas) < 6:
            self.betas = list(self.betas) + [0.0] * (6 - len(self.betas))

    @property
    def beta2(self) -> float:
        return self.betas[0]

    @property
    def beta3(self) -> float:
        return self.betas[1]

    @property
    def beta4(self) -> float:
        return self.betas[2]

    @property
    def beta5(self) -> float:
        return self.betas[3]

    @property
    def beta6(self) -> float:
        return self.betas[4]

    @property
    def beta7(self) -> float:
        return self.betas[5]

    @staticmethod
    def ps_km_to_si(order: int, val_ps_km: float) -> float:
        """Convert dispersion coefficient from ps^k / km to SI unit s^k / m.

        Formula: 1 ps^k / km = 10^(-(12*k + 3)) s^k / m.
        """
        if order < 1:
            raise ValueError(f"Dispersion order must be >= 1, got {order}")
        exponent = -(12 * order + 3)
        return float(val_ps_km * (10.0 ** exponent))

    @staticmethod
    def si_to_ps_km(order: int, val_si: float) -> float:
        """Convert dispersion coefficient from SI unit s^k / m to ps^k / km."""
        if order < 1:
            raise ValueError(f"Dispersion order must be >= 1, got {order}")
        exponent = 12 * order + 3
        return float(val_si * (10.0 ** exponent))

    @staticmethod
    def ps_m_to_si(order: int, val_ps_m: float) -> float:
        """Convert dispersion coefficient from ps^k / m to SI unit s^k / m.

        Formula: 1 ps^k / m = 10^(-12*k) s^k / m.
        """
        if order < 1:
            raise ValueError(f"Dispersion order must be >= 1, got {order}")
        return float(val_ps_m * (10.0 ** (-12 * order)))

    @classmethod
    def from_conventional_ps_km(
        cls,
        beta2: float = 0.0,
        beta3: float = 0.0,
        beta4: float = 0.0,
        beta5: float = 0.0,
        beta6: float = 0.0,
        beta7: float = 0.0,
    ) -> "DispersionConfig":
        """Instantiate DispersionConfig from conventional values in ps^k / km."""
        betas_si = [
            cls.ps_km_to_si(2, beta2),
            cls.ps_km_to_si(3, beta3),
            cls.ps_km_to_si(4, beta4),
            cls.ps_km_to_si(5, beta5),
            cls.ps_km_to_si(6, beta6),
            cls.ps_km_to_si(7, beta7),
        ]
        return cls(mode="manual", betas=betas_si)

    @classmethod
    def from_si(
        cls,
        beta2: float = 0.0,
        beta3: float = 0.0,
        beta4: float = 0.0,
        beta5: float = 0.0,
        beta6: float = 0.0,
        beta7: float = 0.0,
    ) -> "DispersionConfig":
        return cls(mode="manual", betas=[beta2, beta3, beta4, beta5, beta6, beta7])
    @classmethod
    def from_import(cls, import_path: str) -> "DispersionConfig":
        """Instantiate DispersionConfig in import mode for a .csv or .h5 file."""
        return cls(mode="import", import_path=import_path)


def ps2_km_to_si(val_ps2_km: float) -> float:
    return DispersionConfig.ps_km_to_si(2, val_ps2_km)


def ps3_km_to_si(val_ps3_km: float) -> float:
    return DispersionConfig.ps_km_to_si(3, val_ps3_km)


def psk_km_to_si(val_psk_km: float, order: int) -> float:
    return DispersionConfig.ps_km_to_si(order, val_psk_km)



@dataclass
class PulseConfig:
    """Input optical pulse configuration.

    Units:
    - t_fwhm: Intensity Full-Width at Half-Maximum [s]
    - p_peak: Peak optical power [W]
    - center_wavelength: Carrier center wavelength [m]
    - chirp: Dimensionless chirp parameter C (phase factor exp(-i * C / 2 * (T/T0)^2))
    """

    shape: Literal["sech", "gaussian", "custom"] = "sech"
    t_fwhm: float = 1.763e-12  # s (default ~1.763 ps)
    p_peak: float = 16.46  # W
    center_wavelength: float = 1550e-9  # m
    chirp: float = 0.0
    custom_field: Optional[np.ndarray] = None
    custom_time: Optional[np.ndarray] = None

    def __post_init__(self) -> None:
        if self.shape not in ("sech", "gaussian", "custom"):
            raise ValueError(f"Invalid pulse shape '{self.shape}', must be 'sech', 'gaussian', or 'custom'.")
        if self.t_fwhm <= 0:
            raise ValueError(f"Pulse t_fwhm must be positive, got {self.t_fwhm}")
        if self.p_peak < 0:
            raise ValueError(f"Pulse p_peak must be non-negative, got {self.p_peak}")
        if self.center_wavelength <= 0:
            raise ValueError(f"center_wavelength must be positive, got {self.center_wavelength}")

    @property
    def t0(self) -> float:
        """Characteristic pulse duration T_0 [s].

        - sech: T_0 = T_FWHM / (2 * ln(1 + sqrt(2))) ≈ T_FWHM / 1.762747174
        - gaussian: T_0 = T_FWHM / (2 * sqrt(ln(2))) ≈ T_FWHM / 1.665109222
        """
        if self.shape == "gaussian":
            return self.t_fwhm / (2.0 * math.sqrt(math.log(2.0)))
        return self.t_fwhm / (2.0 * math.log(1.0 + math.sqrt(2.0)))

    @property
    def frequency_0(self) -> float:
        """Carrier frequency f_0 [Hz]."""
        return C_CONST / self.center_wavelength

    @property
    def omega_0(self) -> float:
        """Carrier angular frequency omega_0 [rad/s]."""
        return 2.0 * math.pi * C_CONST / self.center_wavelength


@dataclass
class FiberConfig:
    """Optical fiber physical parameters.

    Units:
    - length: Fiber propagation length [m]
    - gamma: Nonlinear coefficient [W^-1 m^-1]
    - loss_alpha_db: Attenuation in [dB/km]
    - dispersion: DispersionConfig
    - raman_fr: Fractional Raman contribution (0.18 for fused silica)
    - raman_tau1: Blow-Wood oscillation timescale [s] (12.2 fs for silica)
    - raman_tau2: Blow-Wood damping timescale [s] (32.0 fs for silica)
    """

    length: float = 100.0  # m
    gamma: float = 1.3e-3  # W^-1 m^-1
    loss_alpha_db: float = 0.0  # dB/km
    dispersion: DispersionConfig = field(default_factory=DispersionConfig)
    raman_fr: float = 0.18
    raman_tau1: float = 12.2e-15  # s
    raman_tau2: float = 32.0e-15  # s

    def __post_init__(self) -> None:
        if self.length <= 0:
            raise ValueError(f"Fiber length must be positive, got {self.length}")
        if self.gamma < 0:
            raise ValueError(f"Nonlinear coefficient gamma must be non-negative, got {self.gamma}")
        if self.loss_alpha_db < 0:
            raise ValueError(f"loss_alpha_db must be non-negative, got {self.loss_alpha_db}")
        if not (0.0 <= self.raman_fr <= 1.0):
            raise ValueError(f"raman_fr must be in [0, 1], got {self.raman_fr}")
        if self.raman_tau1 <= 0 or self.raman_tau2 <= 0:
            raise ValueError("Raman timescales tau1 and tau2 must be positive.")

    @property
    def alpha_si(self) -> float:
        """Power attenuation coefficient alpha in SI units [m^-1].

        Conversion: alpha[m^-1] = (alpha_dB / (10 * log10(e))) * 10^(-3)
                                = (alpha_dB * ln(10) / 10) * 10^(-3)
        """
        return float(self.loss_alpha_db * (math.log(10.0) / 10.0) * 1e-3)

    @classmethod
    def from_conventional(
        cls,
        length_m: float,
        gamma_w_km: float,
        loss_alpha_db: float = 0.0,
        dispersion: Optional[DispersionConfig] = None,
        raman_fr: float = 0.18,
        raman_tau1: float = 12.2e-15,
        raman_tau2: float = 32.0e-15,
    ) -> "FiberConfig":
        """Instantiate FiberConfig with gamma in W^-1 km^-1."""
        gamma_si = gamma_w_km * 1e-3
        return cls(
            length=length_m,
            gamma=gamma_si,
            loss_alpha_db=loss_alpha_db,
            dispersion=dispersion or DispersionConfig(),
            raman_fr=raman_fr,
            raman_tau1=raman_tau1,
            raman_tau2=raman_tau2,
        )


@dataclass
class SolverConfig:
    """Numerical solver settings and grid discretization.

    Parameters:
    - simulation_type: "spectrum_vs_distance" (evolve single pulse in z)
                       or "spectrum_vs_power" (sweep input peak power at fixed z=L)
    - method: Integration algorithm ("SSFM", "S-SSFM", "RK4IP")
    - n_points: Temporal/frequency grid size (must be power of 2)
    - time_window: Total temporal calculation window T_max [s]
    - adaptive_step: Enable local error step-doubling adaptive step size
    - initial_step: Initial step size h_0 [m]
    - min_step: Minimum allowable step size [m]
    - max_step: Maximum allowable step size [m]
    - tolerance: Relative local error tolerance epsilon for adaptive control
    - power_min, power_max, power_steps: Power sweep range [W]
    - z_records: Number of intermediate z records to yield (None for every accepted step)
    - filter_alias: Anti-aliasing super-Gaussian frequency filter
    """

    simulation_type: Literal["spectrum_vs_distance", "spectrum_vs_power"] = "spectrum_vs_distance"
    method: Literal["SSFM", "S-SSFM", "RK4IP"] = "RK4IP"
    n_points: int = 1024
    time_window: float = 20.0e-12  # s
    adaptive_step: bool = True
    initial_step: float = 0.01  # m
    min_step: float = 1e-9  # m
    max_step: float = 1.0  # m
    tolerance: float = 1e-6
    power_min: float = 0.0  # W
    power_max: float = 1000.0  # W
    power_steps: int = 50
    z_records: Optional[int] = None
    filter_alias: bool = False
    filter_order: int = 20
    filter_cutoff: float = 0.95
    raman_enabled: bool = True
    shock_enabled: bool = True
    safety_factor: float = 0.8

    def __post_init__(self) -> None:
        if self.simulation_type not in ("spectrum_vs_distance", "spectrum_vs_power"):
            raise ValueError(f"Invalid simulation_type '{self.simulation_type}'")
        if self.method not in ("SSFM", "S-SSFM", "RK4IP"):
            raise ValueError(f"Invalid method '{self.method}', must be 'SSFM', 'S-SSFM', or 'RK4IP'")
        if self.n_points <= 0 or (self.n_points & (self.n_points - 1)) != 0:
            raise ValueError(f"n_points must be a positive power of 2, got {self.n_points}")
        if self.time_window <= 0:
            raise ValueError(f"time_window must be positive, got {self.time_window}")
        if self.initial_step <= 0 or self.min_step <= 0:
            raise ValueError("Steps must be positive.")
        if self.tolerance <= 0:
            raise ValueError("tolerance must be positive.")
        if self.power_min < 0 or self.power_max < self.power_min:
            raise ValueError("Invalid power range.")
        if self.power_steps < 1:
            raise ValueError("power_steps must be at least 1.")

    @property
    def dt(self) -> float:
        """Temporal grid resolution Delta T [s]."""
        return self.time_window / self.n_points

    def check_raman_sampling(self, tau1: float = 12.2e-15) -> tuple[bool, str]:
        """Verify temporal grid resolution satisfies Delta T <= tau1/4 for Raman oscillations."""
        dt = self.dt
        limit = tau1 / 4.0
        if dt > limit:
            return (
                False,
                f"Grid sampling Delta T = {dt * 1e15:.2f} fs exceeds Raman threshold tau1/4 = {limit * 1e15:.2f} fs. "
                "Increase N or reduce Time Window to avoid numerical aliasing.",
            )
        return True, "Temporal grid resolution OK"


@dataclass
class SimulationState:
    """Snapshot of the simulation state yielded during propagation.

    Attributes:
    - step: Step counter (int)
    - z: Current propagation distance [m]
    - power: Peak instantaneous power max(|A(T)|^2) [W]
    - h: Current step size [m]
    - t: Retarded time grid array [s] (length N)
    - omega: Angular frequency offset grid array Omega = omega - omega_0 [rad/s] (length N)
    - a_t: Complex field envelope in time domain A(z, T) [sqrt(W)] (length N, complex128)
    - a_w: Complex field envelope in frequency domain A_tilde(z, Omega) (length N, complex128)
    - rel_energy_err: Relative pulse energy drift |E(z) - E(0)| / E(0)
    - rel_photon_err: Relative photon number drift |N_ph(z) - N_ph(0)| / N_ph(0)
    """

    step: int
    z: float
    power: float
    h: float
    t: np.ndarray
    omega: np.ndarray
    a_t: np.ndarray
    a_w: np.ndarray
    rel_energy_err: float
    rel_photon_err: float

    @property
    def intensity(self) -> np.ndarray:
        """Instantaneous optical power profile |A(z, T)|^2 [W]."""
        return np.abs(self.a_t) ** 2

    @property
    def spectral_power(self) -> np.ndarray:
        """Spectral power |A_tilde(z, Omega)|^2."""
        return np.abs(self.a_w) ** 2
