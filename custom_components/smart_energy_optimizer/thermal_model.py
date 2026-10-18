"""Self-learning Building Thermal Model (1R1C Equivalent Thermal Network).

This module implements a physical lumped-capacitance thermal dynamic model
and continuous online learning via Recursive Least Squares (RLS).

Thermal Physics:
  C_th * (dT_in / dt) = (T_out - T_in) / R_th + Q_hp + Q_internal

Discrete Formulation (per delta_t hours):
  delta_T / delta_t = (1 / tau) * (T_out - T_in) + (1 / C_th) * Q_hp + (Q_internal / C_th)
  y = theta_1 * (T_out - T_in) + theta_2 * Q_hp + theta_3

From learned theta:
  C_th = 1 / theta_2           (kWh / °C)
  tau = 1 / theta_1            (hours, thermal time constant)
  R_th = tau / C_th            (°C / kW, building thermal envelope resistance)
  Q_internal = theta_3 / theta_2 (kW, baseline internal gains)
"""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional, Tuple

from .const import (
    DEFAULT_COP_ALPHA,
    DEFAULT_INTERNAL_GAINS,
    DEFAULT_NOMINAL_COP,
    DEFAULT_THERMAL_CAPACITY,
    DEFAULT_THERMAL_RESISTANCE,
)

_LOGGER = logging.getLogger(__name__)


class BuildingThermalModel:
    """Self-learning lumped-capacitance 1R1C building thermal model."""

    def __init__(
        self,
        c_th: float = DEFAULT_THERMAL_CAPACITY,
        r_th: float = DEFAULT_THERMAL_RESISTANCE,
        q_internal: float = DEFAULT_INTERNAL_GAINS,
        nominal_cop: float = DEFAULT_NOMINAL_COP,
        cop_alpha: float = DEFAULT_COP_ALPHA,
        forgetting_factor: float = 0.998,
    ) -> None:
        """Initialize the thermal model with initial priors."""
        # Physical parameters
        self.c_th = max(1.0, min(float(c_th), 50.0))  # kWh/°C
        self.r_th = max(0.5, min(float(r_th), 30.0))  # °C/kW
        self.q_internal = max(0.05, min(float(q_internal), 3.0))  # kW
        self.nominal_cop = float(nominal_cop)
        self.cop_alpha = float(cop_alpha)
        self.forgetting_factor = float(forgetting_factor)

        # Derived time constant tau = R * C (hours)
        self.tau = self.r_th * self.c_th

        # Total learning iterations and confidence metrics
        self.sample_count: int = 0
        self.total_heat_energy_kwh: float = 0.0

        # RLS State Vector: theta = [theta_1, theta_2, theta_3]^T
        # theta_1 = 1 / tau
        # theta_2 = 1 / C_th
        # theta_3 = Q_internal / C_th
        theta_1 = 1.0 / self.tau
        theta_2 = 1.0 / self.c_th
        theta_3 = self.q_internal / self.c_th
        self.theta: List[float] = [theta_1, theta_2, theta_3]

        # RLS Covariance Matrix P (3x3 symmetric matrix)
        # Initialized with moderate diagonal uncertainty
        p_diag = 0.01
        self.cov: List[List[float]] = [
            [p_diag, 0.0, 0.0],
            [0.0, p_diag, 0.0],
            [0.0, 0.0, p_diag],
        ]

        # Keep last observed data point for delta calculations
        self._last_t_in: Optional[float] = None
        self._last_t_out: Optional[float] = None
        self._last_q_hp: Optional[float] = None
        self._last_timestamp: Optional[float] = None

    def estimate_cop(self, outdoor_temp: float) -> float:
        """Calculate Heat Pump Coefficient of Performance (COP) as function of outdoor temperature.

        COP increases with warmer outdoor air:
        COP(T_out) = nominal_cop + cop_alpha * (T_out - 7.0)
        Bounded between 1.2 and 6.5.
        """
        raw_cop = self.nominal_cop + self.cop_alpha * (outdoor_temp - 7.0)
        return max(1.2, min(raw_cop, 6.5))

    def forecast_heat_pump_consumption(
        self,
        t_set: float,
        t_in: float,
        t_out: float,
        max_power_kw: float = 3.0,
        min_power_kw: float = 0.25,
    ) -> Tuple[float, float]:
        """Forecast the electrical power draw and delivered thermal heat of the heat pump.

        Takes setpoint, current indoor temp, and outdoor temp into account.
        Optimized for modulating inverter heat pumps like Mitsubishi Heavy Industries (WF-RAC).

        Returns:
            Tuple of (electrical_power_kw, delivered_thermal_kw).
        """
        cop = self.estimate_cop(t_out)

        # If setpoint is lower than indoor temp, compressor idles
        if t_set <= t_in - 0.5:
            return 0.0, 0.0

        # Steady-state heat loss of envelope at target setpoint
        q_loss = max(0.0, (t_set - t_out) / self.r_th - self.q_internal)

        # Transient boost when temperature is below setpoint
        temp_gap = max(0.0, t_set - t_in)
        q_boost = temp_gap * (self.c_th / 1.5)

        q_thermal_desired = q_loss + q_boost
        max_thermal = max_power_kw * cop
        q_thermal = min(max_thermal, max(0.0, q_thermal_desired))

        if q_thermal <= 0.05:
            p_elec = 0.0
        else:
            p_elec = max(min_power_kw, q_thermal / max(cop, 0.1))
            p_elec = min(p_elec, max_power_kw)

        return round(p_elec, 2), round(q_thermal, 2)

    def update_measurement(
        self,
        t_in: float,
        t_out: float,
        heat_pump_power_kw: float,
        delta_hours: float,
    ) -> bool:
        """Feed a new measurement observation into the online RLS estimator.

        Args:
            t_in: Current measured indoor temperature (°C)
            t_out: Current measured outdoor temperature (°C)
            heat_pump_power_kw: Average electrical power of heat pump in this interval (kW)
            delta_hours: Elapsed time since previous measurement (hours)

        Returns:
            True if model parameters were successfully updated.
        """
        # Sanity check elapsed time (should be between 0.05h [3 min] and 4.0h)
        if delta_hours <= 0.05 or delta_hours > 4.0:
            _LOGGER.debug(
                "Skipping thermal model update: delta_hours %.2f outside valid range",
                delta_hours,
            )
            self._last_t_in = t_in
            self._last_t_out = t_out
            self._last_q_hp = heat_pump_power_kw * self.estimate_cop(t_out)
            return False

        if self._last_t_in is None:
            self._last_t_in = t_in
            self._last_t_out = t_out
            self._last_q_hp = heat_pump_power_kw * self.estimate_cop(t_out)
            return False

        # Heat delivered: thermal kW = electrical kW * COP
        cop = self.estimate_cop(t_out)
        q_hp = heat_pump_power_kw * cop

        # Target variable: y = delta T_in / delta_t (°C / hour)
        delta_t_in = t_in - self._last_t_in
        rate_of_change = delta_t_in / delta_hours

        # Outlier rejection: if temp changed faster than 3.0°C/hour, likely a window/door open or sensor glitch
        if abs(rate_of_change) > 3.0:
            _LOGGER.warning(
                "Thermal model outlier rejected: rate of change %.2f °C/h exceeds physical threshold",
                rate_of_change,
            )
            self._last_t_in = t_in
            self._last_t_out = t_out
            self._last_q_hp = q_hp
            return False

        # Average conditions during the interval
        avg_t_in = 0.5 * (t_in + self._last_t_in)
        avg_t_out = 0.5 * (t_out + (self._last_t_out if self._last_t_out is not None else t_out))
        avg_q_hp = 0.5 * (q_hp + (self._last_q_hp if self._last_q_hp is not None else q_hp))

        # Regressor vector: x = [(T_out - T_in), Q_hp, 1.0]
        x = [avg_t_out - avg_t_in, avg_q_hp, 1.0]

        # Execute Recursive Least Squares (RLS) step
        success = self._rls_step(x=x, y=rate_of_change)

        if success:
            self.sample_count += 1
            self.total_heat_energy_kwh += avg_q_hp * delta_hours

        # Store for next iteration
        self._last_t_in = t_in
        self._last_t_out = t_out
        self._last_q_hp = q_hp
        return success

    def _rls_step(self, x: List[float], y: float) -> bool:
        """Perform one Recursive Least Squares iteration with forgetting factor."""
        lam = self.forgetting_factor

        # 1. Prediction error: e = y - x^T * theta
        pred = sum(x[i] * self.theta[i] for i in range(3))
        err = y - pred

        # 2. Compute P * x (vector length 3)
        px = [
            sum(self.cov[i][j] * x[j] for j in range(3))
            for i in range(3)
        ]

        # 3. Scalar denominator: denom = lambda + x^T * P * x
        x_px = sum(x[i] * px[i] for i in range(3))
        denom = lam + x_px
        if abs(denom) < 1e-9:
            return False

        # 4. Kalman gain: K = (P * x) / denom
        k = [px[i] / denom for i in range(3)]

        # 5. Candidate new theta: theta_new = theta + K * err
        new_theta = [self.theta[i] + k[i] * err for i in range(3)]

        # 6. Physical constraints & projection
        # theta_1 = 1 / tau. Tau must be between 6h and 100h => theta_1 in [0.01, 0.166]
        # theta_2 = 1 / C_th. C_th must be between 1.5 and 40 kWh/°C => theta_2 in [0.025, 0.667]
        # theta_3 = Q_internal / C_th. Must be >= 0 => theta_3 in [0.0, 0.4]
        clamped_theta_1 = max(0.01, min(new_theta[0], 0.166))
        clamped_theta_2 = max(0.025, min(new_theta[1], 0.667))
        clamped_theta_3 = max(0.0, min(new_theta[2], 0.4))

        self.theta = [clamped_theta_1, clamped_theta_2, clamped_theta_3]

        # 7. Update covariance matrix: P = (1 / lambda) * (P - K * x^T * P)
        # Note: x^T * P = px^T (since P is symmetric)
        new_cov = [[0.0] * 3 for _ in range(3)]
        for i in range(3):
            for j in range(3):
                new_cov[i][j] = (self.cov[i][j] - k[i] * px[j]) / lam

        # Ensure diagonal values don't explode or collapse
        for i in range(3):
            new_cov[i][i] = max(1e-6, min(new_cov[i][i], 1.0))
            for j in range(i + 1, 3):
                # Enforce symmetry
                sym = 0.5 * (new_cov[i][j] + new_cov[j][i])
                new_cov[i][j] = sym
                new_cov[j][i] = sym

        self.cov = new_cov

        # 8. Recompute physical metrics
        self.c_th = 1.0 / self.theta[1]
        self.tau = 1.0 / self.theta[0]
        self.r_th = self.tau / self.c_th
        self.q_internal = self.theta[2] * self.c_th

        _LOGGER.debug(
            "Thermal model updated: C_th=%.2f kWh/°C, R_th=%.2f °C/kW, Tau=%.1fh, Q_int=%.2f kW (samples=%d)",
            self.c_th,
            self.r_th,
            self.tau,
            self.q_internal,
            self.sample_count,
        )
        return True

    def predict_next_temperature(
        self,
        current_t_in: float,
        outdoor_temp: float,
        heat_thermal_kw: float,
        step_hours: float = 1.0,
    ) -> float:
        """Simulate forward one discrete step using the learned model.

        dT_in / dt = (T_out - T_in) / (R_th * C_th) + (Q_heat + Q_internal) / C_th
        """
        # Exact analytical solution for linear 1st order ODE with constant inputs over step:
        # T_in(t+h) = T_in(t) * exp(-h / tau) + (T_out + R_th*(Q_heat + Q_internal)) * (1 - exp(-h / tau))
        decay = math.exp(-step_hours / self.tau)
        t_asymptote = outdoor_temp + self.r_th * (heat_thermal_kw + self.q_internal)
        next_t_in = current_t_in * decay + t_asymptote * (1.0 - decay)
        return next_t_in

    def simulate_trajectory(
        self,
        initial_t_in: float,
        outdoor_temps: List[float],
        heat_inputs_thermal_kw: List[float],
        step_hours: float = 1.0,
    ) -> List[float]:
        """Simulate indoor temperature trajectory given outdoor temperature forecast and planned heat inputs."""
        trajectory = [initial_t_in]
        t_current = initial_t_in

        for t_out, q_heat in zip(outdoor_temps, heat_inputs_thermal_kw):
            t_current = self.predict_next_temperature(
                current_t_in=t_current,
                outdoor_temp=t_out,
                heat_thermal_kw=q_heat,
                step_hours=step_hours,
            )
            trajectory.append(round(t_current, 2))

        return trajectory

    def to_dict(self) -> Dict[str, Any]:
        """Serialize state for persistent storage in Home Assistant."""
        return {
            "c_th": round(self.c_th, 4),
            "r_th": round(self.r_th, 4),
            "q_internal": round(self.q_internal, 4),
            "nominal_cop": self.nominal_cop,
            "cop_alpha": self.cop_alpha,
            "sample_count": self.sample_count,
            "total_heat_energy_kwh": round(self.total_heat_energy_kwh, 2),
            "theta": [round(x, 6) for x in self.theta],
            "cov": [[round(x, 6) for x in row] for row in self.cov],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BuildingThermalModel":
        """Reconstruct model from stored dictionary."""
        model = cls(
            c_th=data.get("c_th", DEFAULT_THERMAL_CAPACITY),
            r_th=data.get("r_th", DEFAULT_THERMAL_RESISTANCE),
            q_internal=data.get("q_internal", DEFAULT_INTERNAL_GAINS),
            nominal_cop=data.get("nominal_cop", DEFAULT_NOMINAL_COP),
            cop_alpha=data.get("cop_alpha", DEFAULT_COP_ALPHA),
        )
        model.sample_count = data.get("sample_count", 0)
        model.total_heat_energy_kwh = data.get("total_heat_energy_kwh", 0.0)
        if "theta" in data and len(data["theta"]) == 3:
            model.theta = [float(x) for x in data["theta"]]
        if "cov" in data and len(data["cov"]) == 3:
            model.cov = [[float(x) for x in row] for row in data["cov"]]
        # Recalculate derived
        model.tau = model.r_th * model.c_th
        return model
