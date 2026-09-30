"""Acceleration backend dispatch for GNLSE solver engine.

Provides dynamic dispatch architecture:
- Falls back gracefully to pure NumPy/SciPy when compiled extensions are not present.
- Seamlessly routes stepping operations to compiled Cython/C extensions when available.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

# Flag indicating whether compiled Cython acceleration is available
ACCEL_AVAILABLE: bool = False
_COMPILED_STEPPERS: dict[str, Callable[..., Any]] = {}

try:
    from .c_steppers import (
        step_rk4ip_c,
        step_ssfm_c,
        step_sssfm_c,
    )
    _COMPILED_STEPPERS["RK4IP"] = step_rk4ip_c
    _COMPILED_STEPPERS["S-SSFM"] = step_sssfm_c
    _COMPILED_STEPPERS["SSFM"] = step_ssfm_c
    ACCEL_AVAILABLE = True
except (ImportError, Exception):
    ACCEL_AVAILABLE = False


def is_accel_available() -> bool:
    """Return True if compiled Cython kernels are present and active."""
    return ACCEL_AVAILABLE


def get_accel_stepper(method: str) -> Optional[Callable[..., Any]]:
    """Return the compiled stepper for the specified method, or None if not available."""
    return _COMPILED_STEPPERS.get(method)
