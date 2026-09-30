"""Hardware-aware Signal Throttling Filter for GNLSE Concurrency Bridge.

Ensures real-time GUI animation does not saturate the Qt event loop,
enforcing a maximum frame rate cap (nominally <= 60 FPS, interval >= 16.6 ms)
and supporting a full-speed Turbo Mode bypass when live display is disabled.
"""

from __future__ import annotations

import time
from typing import Callable, Optional
from src.solver.config import SimulationState


class SignalThrottler:
    """Filters high-frequency numerical solver states to a stable GUI frame rate.
    
    Attributes:
        max_fps: Maximum visual update rate in frames per second (default 60.0).
        display_live: When False (Turbo Mode), drops all intermediate visual frames
                      to eliminate UI rendering latency, emitting only progress.
    """

    def __init__(self, max_fps: float = 60.0, display_live: bool = True) -> None:
        self.max_fps = max(1.0, min(float(max_fps), 120.0))
        self.min_interval = 1.0 / self.max_fps
        self.display_live = display_live
        self._last_emit_time = 0.0
        self._dropped_frames = 0
        self._emitted_frames = 0

    def reset(self) -> None:
        """Reset internal frame counters and timers."""
        self._last_emit_time = 0.0
        self._dropped_frames = 0
        self._emitted_frames = 0

    def should_emit(self, now: Optional[float] = None) -> bool:
        """Evaluate whether an incoming state frame should be forwarded to the GUI.
        
        Args:
            now: Current timestamp in seconds (defaults to time.perf_counter()).
            
        Returns:
            True if the frame should be rendered, False if it should be dropped.
        """
        if not self.display_live:
            self._dropped_frames += 1
            return False

        if now is None:
            now = time.perf_counter()

        elapsed = now - self._last_emit_time
        if elapsed >= self.min_interval:
            self._last_emit_time = now
            self._emitted_frames += 1
            return True
        else:
            self._dropped_frames += 1
            return False

    @property
    def dropped_count(self) -> int:
        """Total number of visual frames suppressed to protect the event loop."""
        return self._dropped_frames

    @property
    def emitted_count(self) -> int:
        """Total number of visual frames passed to the rendering canvas."""
        return self._emitted_frames
