"""Model Predictive Control (MPC) and Energy Dispatch Optimizer.

Optimizes Heat Pump and Boiler operations over a 24-48 hour rolling horizon,
taking into account spot electricity prices, outdoor temperature forecasts,
and the learned building thermal dynamics.

Designed with modular hooks to seamlessly extend to:
- Solar PV generation forecasts
- Battery storage charge/discharge scheduling
- Electric Vehicle (EV) smart charging
"""

from __future__ import annotations

from dataclasses import dataclass, field
import datetime
import logging
from typing import Any, Dict, List, Optional, Tuple

from .const import (
    MODE_BALANCED,
    MODE_PRICE_OPTIMIZED,
    MODE_STABLE_TEMP,
)
from .thermal_model import BuildingThermalModel

_LOGGER = logging.getLogger(__name__)


@dataclass
class OptimizationInterval:
    """A single discrete time interval (e.g. 1 hour) in the optimization horizon."""

    index: int
    timestamp: datetime.datetime
    price: float  # Currency per kWh
    outdoor_temp: float  # °C
    cop: float  # Estimated Heat Pump COP
    effective_heat_cost: float  # price / cop

    # Optimization Decisions
    heat_pump_action: str = "normal"  # "off", "eco", "normal", "boost"
    heat_pump_target_setpoint: float = 21.0  # °C setpoint commanded to thermostat
    heat_pump_power_kw: float = 0.0  # Electrical power (kW)
    heat_pump_thermal_kw: float = 0.0  # Thermal heat output (kW)
    predicted_indoor_temp: float = 21.0  # Simulated indoor temp at end of interval

    boiler_action: str = "off"  # "off" or "heating"
    boiler_power_kw: float = 0.0  # Electrical power (kW)

    # Future Subsystem Expansion Fields
    solar_generation_kw: float = 0.0
    battery_charge_kw: float = 0.0
    battery_discharge_kw: float = 0.0
    ev_charging_kw: float = 0.0

    # Net Grid Interaction
    net_grid_power_kw: float = 0.0
    cost: float = 0.0


@dataclass
class OptimizationResult:
    """Full schedule and summary metrics produced by the optimizer."""

    intervals: List[OptimizationInterval] = field(default_factory=list)
    mode: str = MODE_BALANCED
    total_optimized_cost: float = 0.0
    total_baseline_cost: float = 0.0
    savings_currency: float = 0.0
    savings_percent: float = 0.0

    # Effekttariff / Peak Power metrics
    predicted_peak_power_kw: float = 0.0
    peak_shaving_active: bool = False
    effektavgift_monthly_savings: float = 0.0

    # Current immediate commands to apply right now
    recommended_setpoint: float = 21.0
    recommended_boiler_state: bool = False
    current_action: str = "normal"


class EnergyOptimizer:
    """Rolling horizon energy optimizer for Heat Pump, Boiler, and home energy assets."""

    def __init__(
        self,
        thermal_model: BuildingThermalModel,
        max_hp_power_kw: float = 3.5,
        boiler_rated_kw: float = 2.0,
        boiler_daily_hours: float = 2.5,
        peak_limit_kw: float = 4.5,
        enable_effekttariff: bool = True,
        effektavgift_price_per_kw: float = 48.0,
    ) -> None:
        """Initialize optimizer."""
        self.thermal_model = thermal_model
        self.max_hp_power_kw = max(0.5, float(max_hp_power_kw))
        self.boiler_rated_kw = max(0.5, float(boiler_rated_kw))
        self.boiler_daily_hours = max(0.5, min(float(boiler_daily_hours), 8.0))
        self.peak_limit_kw = max(1.0, float(peak_limit_kw))
        self.enable_effekttariff = bool(enable_effekttariff)
        self.effektavgift_price_per_kw = float(effektavgift_price_per_kw)

    def solve(
        self,
        current_indoor_temp: float,
        target_comfort_temp: float,
        allowed_drift: float,
        preheat_boost: float,
        mode: str,
        prices: List[Tuple[datetime.datetime, float]],
        outdoor_forecast: List[Tuple[datetime.datetime, float]],
        solar_forecast: Optional[List[Tuple[datetime.datetime, float]]] = None,
    ) -> OptimizationResult:
        """Execute rolling-horizon optimization.

        Args:
            current_indoor_temp: Current indoor temperature (°C).
            target_comfort_temp: User's desired base comfort temperature (°C).
            allowed_drift: Max allowed temp drop below comfort in economy modes (°C).
            preheat_boost: Max allowed temp increase above comfort in pre-heat (°C).
            mode: MODE_PRICE_OPTIMIZED, MODE_BALANCED, or MODE_STABLE_TEMP.
            prices: Chronological list of (timestamp, price_per_kwh).
            outdoor_forecast: Chronological list of (timestamp, outdoor_temp_c).
            solar_forecast: Optional list of (timestamp, pv_generation_kw).

        Returns:
            OptimizationResult containing full timeline and immediate control commands.
        """
        horizon_length = min(len(prices), len(outdoor_forecast))
        if horizon_length == 0:
            _LOGGER.warning("Empty forecast or price data provided to optimizer")
            return OptimizationResult(
                recommended_setpoint=target_comfort_temp,
                recommended_boiler_state=False,
                current_action="fallback",
            )

        # 1. Align time series data
        intervals: List[OptimizationInterval] = []
        solar_dict = {ts: val for ts, val in (solar_forecast or [])}

        for i in range(horizon_length):
            ts, price = prices[i]
            _, t_out = outdoor_forecast[i]
            cop = self.thermal_model.estimate_cop(t_out)
            effective_cost = price / max(cop, 0.1)

            interval = OptimizationInterval(
                index=i,
                timestamp=ts,
                price=price,
                outdoor_temp=t_out,
                cop=cop,
                effective_heat_cost=effective_cost,
                solar_generation_kw=solar_dict.get(ts, 0.0),
            )
            intervals.append(interval)

        # 2. Optimize Heat Pump first based on selected Mode
        if mode == MODE_STABLE_TEMP:
            self._optimize_heat_pump_stable(
                intervals=intervals,
                current_temp=current_indoor_temp,
                target_temp=target_comfort_temp,
            )
        elif mode == MODE_PRICE_OPTIMIZED:
            self._optimize_heat_pump_price(
                intervals=intervals,
                current_temp=current_indoor_temp,
                target_temp=target_comfort_temp,
                max_drift=allowed_drift,
                max_boost=preheat_boost,
            )
        else:  # MODE_BALANCED
            self._optimize_heat_pump_balanced(
                intervals=intervals,
                current_temp=current_indoor_temp,
                target_temp=target_comfort_temp,
                max_drift=min(allowed_drift, 0.5),
                max_boost=min(preheat_boost, 0.8),
            )

        # 3. Optimize Boiler with anti-coincidence peak avoidance (Göteborg Energi Effekttariff)
        self._optimize_boiler(
            intervals=intervals,
            peak_limit_kw=self.peak_limit_kw if self.enable_effekttariff else None,
        )

        # 4. Extensibility: Optimize Battery & EV Charging with peak capping
        self._optimize_battery_storage(intervals)
        self._optimize_ev_charging(
            intervals=intervals,
            peak_limit_kw=self.peak_limit_kw if self.enable_effekttariff else None,
        )

        # 5. Compute Net Energy Balance & Savings Metrics
        result = self._calculate_totals(
            intervals=intervals,
            current_temp=current_indoor_temp,
            target_temp=target_comfort_temp,
            mode=mode,
        )

        return result

    def _optimize_boiler(
        self,
        intervals: List[OptimizationInterval],
        peak_limit_kw: Optional[float] = None,
    ) -> None:
        """Schedule boiler runs during the lowest electricity price intervals.

        With Effekttariff protection enabled, hours where the Heat Pump is drawing high
        power (e.g. pre-heat boost) are penalized so the boiler and heat pump do not create
        an expensive peak together.
        """
        hours_to_schedule = max(1, int(round(self.boiler_daily_hours)))
        horizon_count = len(intervals)

        def boiler_hour_cost(i: int) -> float:
            base_p = intervals[i].price
            if peak_limit_kw is not None:
                combined_p = intervals[i].heat_pump_power_kw + self.boiler_rated_kw
                if combined_p > peak_limit_kw:
                    # Penalize peak violation heavily so boiler shifts to an adjacent non-peak hour
                    return base_p + 10.0 + (combined_p - peak_limit_kw)
            return base_p

        sorted_indices = sorted(range(horizon_count), key=boiler_hour_cost)
        chosen_indices = set(sorted_indices[:hours_to_schedule])

        for i, interval in enumerate(intervals):
            if i in chosen_indices:
                interval.boiler_action = "heating"
                interval.boiler_power_kw = self.boiler_rated_kw
            else:
                interval.boiler_action = "off"
                interval.boiler_power_kw = 0.0

    def _optimize_heat_pump_stable(
        self,
        intervals: List[OptimizationInterval],
        current_temp: float,
        target_temp: float,
    ) -> None:
        """Mode: Stable Temperature.

        Minimizes indoor temperature fluctuation. The heat pump modulates continuously
        to match the building heat loss at each interval, maintaining a flat comfort line.
        """
        t_sim = current_temp

        for interval in intervals:
            # Steady-state required thermal power to maintain target_temp:
            # Q_loss = (T_target - T_out) / R_th - Q_internal
            t_out = interval.outdoor_temp
            q_needed = (target_temp - t_out) / self.thermal_model.r_th - self.thermal_model.q_internal
            # Proportional correction if current temp deviates from target
            temp_error = target_temp - t_sim
            q_correction = (temp_error * self.thermal_model.c_th) / 1.0  # correct within 1h

            desired_q_thermal = max(0.0, q_needed + q_correction)
            # Bound by heat pump max thermal capacity
            max_thermal = self.max_hp_power_kw * interval.cop
            q_thermal = min(desired_q_thermal, max_thermal)
            p_elec = q_thermal / max(interval.cop, 0.1)

            # Thermostat setpoint commanded
            setpoint = target_temp

            interval.heat_pump_action = "normal"
            interval.heat_pump_target_setpoint = round(setpoint, 1)
            interval.heat_pump_power_kw = round(p_elec, 2)
            interval.heat_pump_thermal_kw = round(q_thermal, 2)

            # Advance simulation 1 hour
            t_sim = self.thermal_model.predict_next_temperature(
                current_t_in=t_sim,
                outdoor_temp=t_out,
                heat_thermal_kw=q_thermal,
                step_hours=1.0,
            )
            interval.predicted_indoor_temp = round(t_sim, 2)

    def _optimize_heat_pump_price(
        self,
        intervals: List[OptimizationInterval],
        current_temp: float,
        target_temp: float,
        max_drift: float,
        max_boost: float,
    ) -> None:
        """Mode: Price Optimized (Smart MPC with Pre-Heating).

        Identifies upcoming high electricity price blocks. Pre-heats the building mass
        during low effective cost windows (high COP and/or low spot price), and lets
        the house coast/drift down to (T_target - max_drift) during expensive price spikes.
        """
        min_temp = target_temp - max_drift
        max_temp = target_temp + max_boost

        # Calculate price statistics across the horizon
        effective_costs = [inv.effective_heat_cost for inv in intervals]
        avg_cost = sum(effective_costs) / len(effective_costs)
        p25_cost = sorted(effective_costs)[int(len(effective_costs) * 0.25)]
        p75_cost = sorted(effective_costs)[int(len(effective_costs) * 0.75)]

        t_sim = current_temp
        n = len(intervals)

        for i, interval in enumerate(intervals):
            t_out = interval.outdoor_temp
            cop = interval.cop
            eff_cost = interval.effective_heat_cost

            # Check if an expensive peak is coming in the next 1-4 hours
            peak_ahead = False
            for lookahead in range(1, min(5, n - i)):
                if intervals[i + lookahead].effective_heat_cost >= p75_cost:
                    peak_ahead = True
                    break

            is_cheap_now = eff_cost <= p25_cost or eff_cost < avg_cost * 0.85
            is_expensive_now = eff_cost >= p75_cost or eff_cost > avg_cost * 1.15

            # Decision logic:
            if is_cheap_now and peak_ahead and t_sim < max_temp:
                # PRE-HEAT BOOST: Store cheap heat in thermal building mass
                action = "boost"
                setpoint = max_temp
                desired_t = max_temp
            elif is_expensive_now and t_sim > min_temp:
                # FLOAT / ECO: Coast on building thermal inertia during price spike
                action = "eco"
                setpoint = min_temp
                desired_t = min_temp
            else:
                # NORMAL: Maintain comfortable baseline
                action = "normal"
                setpoint = target_temp
                desired_t = target_temp

            # Calculate required heat to reach or move towards desired_t
            q_loss = (desired_t - t_out) / self.thermal_model.r_th - self.thermal_model.q_internal
            temp_error = desired_t - t_sim
            q_correction = (temp_error * self.thermal_model.c_th) / 1.0
            raw_q = max(0.0, q_loss + q_correction)

            max_thermal = self.max_hp_power_kw * cop

            if action == "boost":
                q_thermal = min(max_thermal, max(raw_q, max_thermal * 0.85))
            elif action == "eco":
                # Coast or minimal baseline to avoid dropping below min_temp
                if t_sim <= min_temp + 0.2:
                    q_thermal = min(max_thermal, max(0.0, raw_q))
                else:
                    q_thermal = 0.0
            else:
                q_thermal = min(max_thermal, max(0.0, raw_q))

            p_elec = q_thermal / max(cop, 0.1)

            interval.heat_pump_action = action
            interval.heat_pump_target_setpoint = round(setpoint, 1)
            interval.heat_pump_power_kw = round(p_elec, 2)
            interval.heat_pump_thermal_kw = round(q_thermal, 2)

            # Advance simulation 1 hour
            t_sim = self.thermal_model.predict_next_temperature(
                current_t_in=t_sim,
                outdoor_temp=t_out,
                heat_thermal_kw=q_thermal,
                step_hours=1.0,
            )
            interval.predicted_indoor_temp = round(t_sim, 2)

    def _optimize_heat_pump_balanced(
        self,
        intervals: List[OptimizationInterval],
        current_temp: float,
        target_temp: float,
        max_drift: float = 0.5,
        max_boost: float = 0.8,
    ) -> None:
        """Mode: Balanced.

        Combines sensible price shifting with strict comfort retention (narrow drift window).
        """
        # Run price optimization with tighter bounds
        self._optimize_heat_pump_price(
            intervals=intervals,
            current_temp=current_temp,
            target_temp=target_temp,
            max_drift=max_drift,
            max_boost=max_boost,
        )

    def _optimize_battery_storage(
        self,
        intervals: List[OptimizationInterval],
        capacity_kwh: float = 10.0,
        max_rate_kw: float = 3.3,
        initial_soc_pct: float = 50.0,
    ) -> None:
        """Extensible Battery Storage Optimization.

        Charges during excess solar production or during the lowest 25% price hours.
        Discharges during the highest 25% price hours to shave peaks.
        """
        prices = [inv.price for inv in intervals]
        if not prices:
            return

        sorted_prices = sorted(prices)
        p25 = sorted_prices[int(len(prices) * 0.25)]
        p75 = sorted_prices[int(len(prices) * 0.75)]

        current_soc_kwh = (initial_soc_pct / 100.0) * capacity_kwh
        min_soc_kwh = capacity_kwh * 0.10  # 10% reserve
        max_soc_kwh = capacity_kwh * 0.95  # 95% max charge

        for inv in intervals:
            # Check solar excess first
            solar_excess = max(0.0, inv.solar_generation_kw - (inv.heat_pump_power_kw + inv.boiler_power_kw))
            charge_kw = 0.0
            discharge_kw = 0.0

            if solar_excess > 0.1:
                # Solar priority charge
                possible_charge = min(solar_excess, max_rate_kw, max_soc_kwh - current_soc_kwh)
                charge_kw = max(0.0, possible_charge)
                current_soc_kwh += charge_kw
            elif inv.price <= p25 and current_soc_kwh < max_soc_kwh:
                # Cheap grid price charge
                possible_charge = min(max_rate_kw, max_soc_kwh - current_soc_kwh)
                charge_kw = max(0.0, possible_charge)
                current_soc_kwh += charge_kw
            elif inv.price >= p75 and current_soc_kwh > min_soc_kwh:
                # High grid price discharge
                demand = inv.heat_pump_power_kw + inv.boiler_power_kw
                possible_discharge = min(demand, max_rate_kw, current_soc_kwh - min_soc_kwh)
                discharge_kw = max(0.0, possible_discharge)
                current_soc_kwh -= discharge_kw

            inv.battery_charge_kw = round(charge_kw, 2)
            inv.battery_discharge_kw = round(discharge_kw, 2)

    def _optimize_ev_charging(
        self,
        intervals: List[OptimizationInterval],
        required_kwh: float = 0.0,
        departure_hour_idx: int = 7,
        max_charge_kw: float = 7.4,
        peak_limit_kw: Optional[float] = None,
    ) -> None:
        """Extensible EV Smart Charging with peak power limit capping."""
        if required_kwh <= 0.0 or departure_hour_idx <= 0:
            return

        window_len = min(departure_hour_idx, len(intervals))
        if window_len <= 0:
            return

        # Sort indices in departure window by price
        indices_by_price = sorted(range(window_len), key=lambda i: intervals[i].price)

        remaining_energy = required_kwh
        for idx in indices_by_price:
            if remaining_energy <= 0.0:
                break
            available_room = max_charge_kw
            if peak_limit_kw is not None:
                current_p = intervals[idx].heat_pump_power_kw + intervals[idx].boiler_power_kw
                available_room = min(available_room, max(0.0, peak_limit_kw - current_p))

            alloc = min(available_room, remaining_energy)
            if alloc > 0.0:
                intervals[idx].ev_charging_kw = round(alloc, 2)
                remaining_energy -= alloc

    def _calculate_totals(
        self,
        intervals: List[OptimizationInterval],
        current_temp: float,
        target_temp: float,
        mode: str,
    ) -> OptimizationResult:
        """Calculate total energy, costs, peak power, and baseline comparison."""
        total_opt_cost = 0.0
        total_base_cost = 0.0

        for interval in intervals:
            # Net grid power: HP power + Boiler + EV + Battery Charge - Battery Discharge - Solar
            gross_p = (
                interval.heat_pump_power_kw
                + interval.boiler_power_kw
                + interval.ev_charging_kw
                + interval.battery_charge_kw
                - interval.battery_discharge_kw
            )
            net_grid_p = max(0.0, gross_p - interval.solar_generation_kw)
            interval.net_grid_power_kw = round(net_grid_p, 2)
            interval.cost = round(net_grid_p * interval.price, 3)
            total_opt_cost += interval.cost

            # Baseline calculation: Flat heating without price shifting
            q_base = max(
                0.0,
                (target_temp - interval.outdoor_temp) / self.thermal_model.r_th
                - self.thermal_model.q_internal,
            )
            p_base_hp = q_base / max(interval.cop, 0.1)
            p_base_boiler = (self.boiler_daily_hours / 24.0) * self.boiler_rated_kw
            p_base_gross = p_base_hp + p_base_boiler + interval.ev_charging_kw
            p_base_net = max(0.0, p_base_gross - interval.solar_generation_kw)
            total_base_cost += p_base_net * interval.price

        savings_curr = max(0.0, total_base_cost - total_opt_cost)
        savings_pct = (
            (savings_curr / total_base_cost * 100.0) if total_base_cost > 0.001 else 0.0
        )

        # Peak power metrics for Effekttariff
        peak_grid_power = max((inv.net_grid_power_kw for inv in intervals), default=0.0)
        uncoordinated_peak = max(
            (inv.heat_pump_power_kw + self.boiler_rated_kw for inv in intervals),
            default=0.0,
        )
        effekt_saved_kw = max(0.0, uncoordinated_peak - peak_grid_power)
        effekt_monthly_savings = round(effekt_saved_kw * self.effektavgift_price_per_kw, 2)
        peak_shaving_active = self.enable_effekttariff and (effekt_saved_kw > 0.1)

        first = intervals[0]
        return OptimizationResult(
            intervals=intervals,
            mode=mode,
            total_optimized_cost=round(total_opt_cost, 2),
            total_baseline_cost=round(total_base_cost, 2),
            savings_currency=round(savings_curr, 2),
            savings_percent=round(savings_pct, 1),
            predicted_peak_power_kw=round(peak_grid_power, 2),
            peak_shaving_active=peak_shaving_active,
            effektavgift_monthly_savings=effekt_monthly_savings,
            recommended_setpoint=first.heat_pump_target_setpoint,
            recommended_boiler_state=(first.boiler_action == "heating"),
            current_action=first.heat_pump_action,
        )

