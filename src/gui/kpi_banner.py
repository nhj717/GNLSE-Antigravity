"""KPI Summary Banner Widget for GNLSE Workstation.

Displays 5 real-time diagnostic cards:
1. Soliton Dynamics N (Soliton Order & Regime)
2. Characteristic Scales (Dispersion Length L_D, Nonlinear Length L_NL, Soliton Period z_sol)
3. Output Spectral Bandwidth (e.g. -20 dB Bandwidth Δλ)
4. SSFS Raman Shift (Soliton Self-Frequency Shift Δλ_Raman)
5. Residual Conservation Error (Relative Energy Error |ΔE/E₀|)
"""

from __future__ import annotations

import math
from typing import Optional
import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QFrame
)

from src.gui.theme import (
    SURFACE_LOW, SURFACE, SURFACE_HIGH, BORDER_SUBTLE, BORDER_COLOR,
    CYAN_ACCENT, CYAN_LIGHT, PINK_ACCENT, PURPLE_ACCENT, GREEN_SUCCESS,
    TEXT_PRIMARY, TEXT_MUTED
)
from src.solver.config import PulseConfig, FiberConfig, SimulationState


class KpiCard(QFrame):
    """Individual Cyberpunk Telemetry Metric Card."""

    def __init__(
        self,
        title: str,
        initial_value: str = "--",
        unit: str = "",
        accent_color: str = CYAN_ACCENT,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.accent_color = accent_color
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(f"""
            KpiCard {{
                background-color: {SURFACE_LOW};
                border: 1px solid {BORDER_SUBTLE};
                border-top: 2px solid {accent_color};
                border-radius: 6px;
                padding: 6px 10px;
            }}
            KpiCard:hover {{
                border-color: {accent_color};
                background-color: {SURFACE};
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        # Title / Label
        self.lbl_title = QLabel(title.upper())
        self.lbl_title.setStyleSheet(f"""
            color: {TEXT_MUTED};
            font-size: 9px;
            font-weight: 700;
            letter-spacing: 0.5px;
        """)
        layout.addWidget(self.lbl_title)

        # Value + Unit row
        val_layout = QHBoxLayout()
        val_layout.setContentsMargins(0, 0, 0, 0)
        val_layout.setSpacing(4)

        self.lbl_value = QLabel(initial_value)
        self.lbl_value.setStyleSheet(f"""
            color: {TEXT_PRIMARY};
            font-size: 15px;
            font-weight: 800;
            font-family: 'JetBrains Mono', monospace;
        """)

        self.lbl_unit = QLabel(unit)
        self.lbl_unit.setStyleSheet(f"""
            color: {accent_color};
            font-size: 10px;
            font-weight: 600;
        """)

        val_layout.addWidget(self.lbl_value)
        val_layout.addWidget(self.lbl_unit)
        val_layout.addStretch()
        layout.addLayout(val_layout)

        # Subtitle / Details
        self.lbl_detail = QLabel("")
        self.lbl_detail.setStyleSheet(f"""
            color: {TEXT_MUTED};
            font-size: 9px;
            font-weight: 400;
        """)
        layout.addWidget(self.lbl_detail)

    def set_data(self, value: str, unit: Optional[str] = None, detail: Optional[str] = None) -> None:
        self.lbl_value.setText(value)
        if unit is not None:
            self.lbl_unit.setText(unit)
        if detail is not None:
            self.lbl_detail.setText(detail)


class KpiBannerWidget(QWidget):
    """Horizontal 5-Card Diagnostic Strip."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # 1. Soliton Dynamics N
        self.card_n = KpiCard(
            title="Soliton Dynamics",
            initial_value="N = --",
            unit="",
            accent_color=CYAN_ACCENT,
        )

        # 2. Characteristic Scales L_D / L_NL
        self.card_scales = KpiCard(
            title="Characteristic Scales",
            initial_value="L_D / L_NL",
            unit="",
            accent_color=PURPLE_ACCENT,
        )

        # 3. Output Bandwidth
        self.card_bw = KpiCard(
            title="Output Bandwidth",
            initial_value="--",
            unit="nm",
            accent_color=PINK_ACCENT,
        )

        # 4. SSFS Raman Shift
        self.card_ssfs = KpiCard(
            title="SSFS Raman Shift",
            initial_value="--",
            unit="nm",
            accent_color=CYAN_ACCENT,
        )

        # 5. Residual Energy Conservation
        self.card_err = KpiCard(
            title="Residual Error",
            initial_value="--",
            unit="|ΔE/E₀|",
            accent_color=GREEN_SUCCESS,
        )

        layout.addWidget(self.card_n, 1)
        layout.addWidget(self.card_scales, 1)
        layout.addWidget(self.card_bw, 1)
        layout.addWidget(self.card_ssfs, 1)
        layout.addWidget(self.card_err, 1)

    def update_from_configs(
        self,
        pulse: PulseConfig,
        fiber: FiberConfig,
        state: Optional[SimulationState] = None,
    ) -> None:
        """Calculate and update KPI metrics based on pulse, fiber, and state."""
        try:
            t0 = pulse.t0
            p0 = pulse.p_peak
            gamma = fiber.gamma
            beta2 = fiber.dispersion.beta2

            # 1. Soliton Order N = sqrt(gamma * P0 * T0^2 / |beta2|)
            if abs(beta2) > 1e-35 and p0 > 0 and gamma > 0:
                l_d = (t0 ** 2) / abs(beta2)
                l_nl = 1.0 / (gamma * p0)
                n_sol = math.sqrt(l_d / l_nl)
                z_sol = (math.pi / 2.0) * l_d

                if n_sol < 1.3:
                    n_regime = "Fundamental Soliton (N≈1)"
                elif n_sol < 3.0:
                    n_regime = f"Low-Order Soliton (N={n_sol:.1f})"
                else:
                    n_regime = f"High-Order Fission (N={n_sol:.1f})"

                self.card_n.set_data(f"N = {n_sol:.2f}", "", n_regime)

                # Format L_D and L_NL
                def fmt_len(val_m: float) -> str:
                    if val_m >= 1.0:
                        return f"{val_m:.2f} m"
                    elif val_m >= 1e-2:
                        return f"{val_m * 1e2:.2f} cm"
                    elif val_m >= 1e-3:
                        return f"{val_m * 1e3:.2f} mm"
                    else:
                        return f"{val_m * 1e6:.1f} μm"

                self.card_scales.set_data(
                    f"{fmt_len(l_d)} / {fmt_len(l_nl)}",
                    "",
                    f"z_sol = {fmt_len(z_sol)}",
                )
            else:
                self.card_n.set_data("N = N/A", "", "Zero or normal dispersion")
                self.card_scales.set_data("Linear / CW", "", "No soliton formation")

            # If simulation state is available, compute spectrum metrics and conservation
            if state is not None:
                # 3. Output Bandwidth & 4. Raman Shift
                c_light = 299792458.0
                omega0 = pulse.omega_0
                omega_tot = omega0 + state.omega
                pos_mask = (omega_tot > 0)
                if np.any(pos_mask):
                    wl_nm = (2.0 * math.pi * c_light / omega_tot[pos_mask]) * 1e9
                    psd = np.abs(state.a_w[pos_mask]) ** 2 * (2.0 * math.pi * c_light / ((wl_nm * 1e-9) ** 2))
                    sort_i = np.argsort(wl_nm)
                    wl_nm = wl_nm[sort_i]
                    psd = psd[sort_i]

                    psd_max = np.max(psd)
                    if psd_max > 0:
                        # -20 dB bandwidth
                        threshold = psd_max * 0.01  # -20 dB
                        above = np.where(psd >= threshold)[0]
                        if len(above) > 1:
                            bw_20db = float(wl_nm[above[-1]] - wl_nm[above[0]])
                            self.card_bw.set_data(f"Δλ = {bw_20db:.1f}", "nm", f"[{wl_nm[above[0]]:.0f} – {wl_nm[above[-1]]:.0f} nm]")
                        else:
                            self.card_bw.set_data("< 1.0", "nm", "Narrowband pump")

                        # Raman SSFS: Peak wavelength of longest-wavelength peak
                        peak_idx = int(np.argmax(psd))
                        lambda_peak = float(wl_nm[peak_idx])
                        carrier_nm = pulse.center_wavelength * 1e9
                        raman_shift = lambda_peak - carrier_nm
                        if raman_shift >= 0:
                            self.card_ssfs.set_data(f"+{raman_shift:.1f}", "nm", f"Peak at {lambda_peak:.1f} nm")
                        else:
                            self.card_ssfs.set_data(f"{raman_shift:.1f}", "nm", f"Peak at {lambda_peak:.1f} nm")

                # 5. Residual Conservation Error
                rel_err = state.rel_energy_err
                if rel_err < 1e-6:
                    err_str = f"{rel_err:.2e}"
                    err_status = "Excellent (<1e-6)"
                elif rel_err < 1e-4:
                    err_str = f"{rel_err:.2e}"
                    err_status = "Acceptable (<1e-4)"
                else:
                    err_str = f"{rel_err:.2e}"
                    err_status = "Dissipative / High Loss"
                self.card_err.set_data(err_str, "|ΔE/E₀|", err_status)

        except Exception as e:
            pass

    def reset(self) -> None:
        """Reset cards to idle state."""
        self.card_n.set_data("N = --", "", "Awaiting simulation")
        self.card_scales.set_data("L_D / L_NL", "", "--")
        self.card_bw.set_data("--", "nm", "--")
        self.card_ssfs.set_data("--", "nm", "--")
        self.card_err.set_data("--", "|ΔE/E₀|", "Idle")
