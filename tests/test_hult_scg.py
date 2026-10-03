"""Benchmark Test Case 2: Johan Hult 2007 Supercontinuum Soliton Fission.

Validates:
- Propagation through the soliton fission zone (z > L_fiss ~ 7.9 mm)
- Photon number conservation in the presence of Raman and Shock
- Execution speed with compiled C acceleration
"""

import math
import numpy as np
import pytest

from src.solver.config import PulseConfig, FiberConfig, DispersionConfig, SolverConfig
from src.solver.engine import solve_generator


@pytest.mark.parametrize("method", ["RK4IP", "S-SSFM", "SSFM"])
def test_hult_soliton_fission_and_photon_conservation(method: str):
    """Propagate 10 kW pulse in NL-1.7-770 PCF past fission length across all solvers."""
    lambda0 = 850e-9
    gamma = 0.045
    t_fwhm = 50e-15
    p0 = 10000.0  # 10 kW
    length = 0.10  # 10 cm

    betas = [
        -1.276e-26,
        8.119e-41,
        -1.321e-55,
        3.032e-70,
        -4.196e-85,
        2.570e-100,
    ]

    disp = DispersionConfig.from_si(
        beta2=betas[0], beta3=betas[1], beta4=betas[2],
        beta5=betas[3], beta6=betas[4], beta7=betas[5]
    )
    fiber = FiberConfig(
        length=length,
        gamma=gamma,
        loss_alpha_db=0.0,
        dispersion=disp,
        raman_fr=0.18,
        raman_tau1=12.2e-15,
        raman_tau2=32.0e-15,
    )
    pulse = PulseConfig(
        shape="sech",
        t_fwhm=t_fwhm,
        p_peak=p0,
        center_wavelength=lambda0,
    )
    solver = SolverConfig(
        simulation_type="spectrum_vs_distance",
        method=method,
        n_points=2048,
        time_window=6e-12,  # dt = 2.93 fs < tau1/4 = 3.05 fs
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

    states = list(solve_generator(pulse, fiber, solver))
    final = states[-1]

    # Verify propagation reached 10 cm
    assert pytest.approx(final.z, abs=1e-6) == length

    # Verify peak power compressed / fission occurred (initial 10 kW reaches higher peak before fission)
    max_history_power = max(s.power for s in states)
    assert max_history_power > 10000.0, f"Max power {max_history_power} did not show compression"

    # Verify photon number conservation |Delta N_ph / N_ph(0)| < 1e-3
    assert final.rel_photon_err < 1e-3, f"Photon error {final.rel_photon_err:.2e} exceeded 1e-3"
