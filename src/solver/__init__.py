"""GNLSE Solver Package.

Numerical engine for solving the Generalized Nonlinear Schrödinger Equation
governing optical pulse propagation in single-mode fibers.
"""

from .config import (
    C_CONST,
    DispersionConfig,
    FiberConfig,
    PulseConfig,
    SimulationState,
    SolverConfig,
)
from .raman import (
    blow_wood_raman_response,
    prepare_raman_fft,
    raman_convolution,
)
from .operators import (
    compute_dispersion_operator,
    compute_energy,
    compute_nonlinear_operator,
    compute_photon_number,
    compute_shock_factor,
    relative_error,
    super_gaussian_filter,
)
from .accel import (
    get_accel_stepper,
    is_accel_available,
)
from .engine import (
    generate_initial_pulse,
    solve_generator,
    step_rk4ip,
    step_ssfm,
    step_sssfm,
)

__all__ = [
    "C_CONST",
    "DispersionConfig",
    "PulseConfig",
    "FiberConfig",
    "SolverConfig",
    "SimulationState",
    "blow_wood_raman_response",
    "prepare_raman_fft",
    "raman_convolution",
    "compute_dispersion_operator",
    "compute_energy",
    "compute_nonlinear_operator",
    "compute_photon_number",
    "compute_shock_factor",
    "relative_error",
    "super_gaussian_filter",
    "get_accel_stepper",
    "is_accel_available",
    "generate_initial_pulse",
    "solve_generator",
    "step_rk4ip",
    "step_ssfm",
    "step_sssfm",
]
