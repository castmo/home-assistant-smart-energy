"""DataUpdateCoordinator for Smart Energy & Thermal Optimizer."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from homeassistant.components.climate import (
    ATTR_HVAC_MODE,
    ATTR_TEMPERATURE,
    SERVICE_SET_HVAC_MODE,
    SERVICE_SET_TEMPERATURE,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_BATTERY_CAPACITY_KWH,
    CONF_BATTERY_POWER_SENSOR,
    CONF_BATTERY_SOC_SENSOR,
    CONF_BIG_CONSUMERS,
    CONF_BOILER_DAILY_HOURS,
    CONF_BOILER_RUN_HOURS_PER_DAY,
    CONF_BOILER_ENTITY,
    CONF_BOILER_POWER_SENSOR,
    CONF_BOILER_RATED_POWER,
    CONF_EV_CHARGER_ENTITY,
    CONF_EV_CHARGER_POWER_SENSOR,
    CONF_ENERGY_TAX,
    CONF_ENABLE_EFFEKTDIFF,
    CONF_EFFEKTAVGIFT_PRICE_PER_KW,
    CONF_GRID_FEE_HIGH_LOAD,
    CONF_GRID_FEE_LOW_LOAD,
    CONF_HEAT_PUMP_CLIMATE,
    CONF_HEAT_PUMP_ENERGY_SENSOR,
    CONF_HEAT_PUMP_MAX_POWER,
    CONF_HEAT_PUMP_POWER_SENSOR,
    CONF_INDOOR_TEMP_SENSOR,
    CONF_OUTDOOR_TEMP_SENSOR,
    CONF_PEAK_LIMIT_KW,
    CONF_PRICE_CURRENCY,
    CONF_PRICE_SENSOR,
    CONF_SOLAR_FORECAST_ENTITY,
    CONF_SOLAR_POWER_SENSOR,
    CONF_SPOT_PRICE_INCLUDES_VAT,
    CONF_SURCHARGE,
    CONF_TARIFF_TYPE,
    CONF_USE_WF_RAC_SENSORS,
    CONF_VAT_PERCENT,
    CONF_WEATHER_ENTITY,
    DEFAULT_ALLOWED_DRIFT,
    DEFAULT_EFFEKTAVGIFT_PRICE_PER_KW,
    DEFAULT_ENABLE_EFFEKTDIFF,
    DEFAULT_MAX_PREHEAT,
    DEFAULT_MODE,
    DEFAULT_PEAK_LIMIT_KW,
    DEFAULT_TARGET_TEMP,
    DOMAIN,
    MODE_BALANCED,
    MODE_PRICE_OPTIMIZED,
    MODE_STABLE_TEMP,
    SCAN_INTERVAL_MINUTES,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .optimizer import EnergyOptimizer, OptimizationResult
from .price_calculator import (
    ElectricityTariffCalculator,
    PriceBreakdown,
    TARIFF_GOTEBORG_TIDSTARIFF,
)
from .thermal_model import BuildingThermalModel

_LOGGER = logging.getLogger(__name__)


class SmartEnergyCoordinator(DataUpdateCoordinator[Dict[str, Any]]):
    """Coordinator to manage polling, model learning, MPC optimization, and dispatch."""

    def __init__(self, hass: HomeAssistant, config_entry: Any) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=SCAN_INTERVAL_MINUTES),
        )
        self.entry = config_entry
        self.store = Store(hass, STORAGE_VERSION, STORAGE_KEY)

        # Settings and Preferences (can be modified at runtime via number/select entities)
        self.mode = config_entry.options.get("mode", DEFAULT_MODE)
        self.target_comfort_temp = float(
            config_entry.options.get("target_comfort_temp", DEFAULT_TARGET_TEMP)
        )
        self.allowed_drift = float(
            config_entry.options.get("allowed_drift", DEFAULT_ALLOWED_DRIFT)
        )
        self.preheat_boost = float(
            config_entry.options.get("preheat_boost", DEFAULT_MAX_PREHEAT)
        )
        self.master_enabled = config_entry.options.get("master_enabled", True)
        self.boiler_control_enabled = config_entry.options.get("boiler_control_enabled", True)
        self.learning_enabled = config_entry.options.get("learning_enabled", True)

        # Thermal Model and Optimizer
        self.thermal_model = BuildingThermalModel()
        max_hp_kw = float(config_entry.data.get(CONF_HEAT_PUMP_MAX_POWER, 3.5))
        boiler_kw = float(config_entry.data.get(CONF_BOILER_RATED_POWER, 2.0))
        boiler_hours = float(config_entry.data.get(CONF_BOILER_RUN_HOURS_PER_DAY, 2.5))
        peak_limit = float(
            config_entry.options.get(CONF_PEAK_LIMIT_KW, config_entry.data.get(CONF_PEAK_LIMIT_KW, DEFAULT_PEAK_LIMIT_KW))
        )
        enable_effekt = config_entry.options.get(
            CONF_ENABLE_EFFEKTDIFF, config_entry.data.get(CONF_ENABLE_EFFEKTDIFF, DEFAULT_ENABLE_EFFEKTDIFF)
        )
        effekt_price = float(
            config_entry.options.get(
                CONF_EFFEKTAVGIFT_PRICE_PER_KW,
                config_entry.data.get(CONF_EFFEKTAVGIFT_PRICE_PER_KW, DEFAULT_EFFEKTAVGIFT_PRICE_PER_KW),
            )
        )
        self.optimizer = EnergyOptimizer(
            thermal_model=self.thermal_model,
            max_hp_power_kw=max_hp_kw,
            boiler_rated_kw=boiler_kw,
            boiler_daily_hours=boiler_hours,
            peak_limit_kw=peak_limit,
            enable_effekttariff=enable_effekt,
            effektavgift_price_per_kw=effekt_price,
        )

        # Electricity Tariff Calculator (Göteborg Energi and taxes)
        tariff_type = config_entry.options.get(
            CONF_TARIFF_TYPE, config_entry.data.get(CONF_TARIFF_TYPE, TARIFF_GOTEBORG_TIDSTARIFF)
        )
        surcharge = float(config_entry.options.get(CONF_SURCHARGE, config_entry.data.get(CONF_SURCHARGE, 0.05)))
        energy_tax = float(config_entry.options.get(CONF_ENERGY_TAX, config_entry.data.get(CONF_ENERGY_TAX, 0.445)))
        grid_high = float(
            config_entry.options.get(CONF_GRID_FEE_HIGH_LOAD, config_entry.data.get(CONF_GRID_FEE_HIGH_LOAD, 0.38))
        )
        grid_low = float(
            config_entry.options.get(CONF_GRID_FEE_LOW_LOAD, config_entry.data.get(CONF_GRID_FEE_LOW_LOAD, 0.16))
        )
        vat_pct = float(config_entry.options.get(CONF_VAT_PERCENT, config_entry.data.get(CONF_VAT_PERCENT, 25.0)))
        spot_incl_vat = config_entry.options.get(
            CONF_SPOT_PRICE_INCLUDES_VAT, config_entry.data.get(CONF_SPOT_PRICE_INCLUDES_VAT, False)
        )
        currency = config_entry.data.get(CONF_PRICE_CURRENCY, "SEK")

        self.tariff_calculator = ElectricityTariffCalculator(
            tariff_type=tariff_type,
            surcharge=surcharge,
            energy_tax=energy_tax,
            grid_fee_high_load=grid_high,
            grid_fee_low_load=grid_low,
            vat_percent=vat_pct,
            spot_price_includes_vat=spot_incl_vat,
            currency=currency,
        )

        self.last_optimization_result: Optional[OptimizationResult] = None
        self._last_measurement_time: Optional[float] = None
        self._last_hp_energy_kwh: Optional[float] = None
        self._latest_price_breakdowns: Dict[str, PriceBreakdown] = {}

    async def async_init(self) -> None:
        """Load stored thermal model weights and initial state."""
        stored_data = await self.store.async_load()
        if stored_data and isinstance(stored_data, dict):
            try:
                self.thermal_model = BuildingThermalModel.from_dict(stored_data)
                self.optimizer.thermal_model = self.thermal_model
                _LOGGER.info(
                    "Restored building thermal model from storage (Tau=%.1fh, C_th=%.2f, R_th=%.2f, samples=%d)",
                    self.thermal_model.tau,
                    self.thermal_model.c_th,
                    self.thermal_model.r_th,
                    self.thermal_model.sample_count,
                )
            except Exception as err:
                _LOGGER.warning("Could not restore stored thermal model, starting fresh: %s", err)

    async def async_save_model(self) -> None:
        """Persist current thermal model parameters to disk."""
        try:
            await self.store.async_save(self.thermal_model.to_dict())
            _LOGGER.debug("Saved thermal model weights to storage")
        except Exception as err:
            _LOGGER.error("Failed to save thermal model weights: %s", err)

    async def _async_update_data(self) -> Dict[str, Any]:
        """Fetch sensor values, learn thermal model parameters, and solve MPC plan."""
        now_ts = time.time()

        # 1. Read Current Sensors & Check Mitsubishi WF-RAC Climate
        climate_entity = self.entry.data.get(CONF_HEAT_PUMP_CLIMATE)
        climate_state = self.hass.states.get(climate_entity) if climate_entity else None

        indoor_temp = self._get_float_state(self.entry.data.get(CONF_INDOOR_TEMP_SENSOR))
        outdoor_temp = self._get_float_state(self.entry.data.get(CONF_OUTDOOR_TEMP_SENSOR))
        hp_power_kw = self._get_float_state(self.entry.data.get(CONF_HEAT_PUMP_POWER_SENSOR))
        hp_energy_kwh = self._get_float_state(self.entry.data.get(CONF_HEAT_PUMP_ENERGY_SENSOR))
        boiler_power_kw = self._get_float_state(self.entry.data.get(CONF_BOILER_POWER_SENSOR), default=0.0)

        # Mitsubishi WF-RAC Native Auto-Detection & Fallbacks:
        if climate_state:
            # Auto-read indoor temp from WF-RAC climate attributes if not explicitly configured
            if indoor_temp is None and "current_temperature" in climate_state.attributes:
                indoor_temp = float(climate_state.attributes["current_temperature"])
            # Auto-read outdoor temp from WF-RAC climate attributes if available
            if outdoor_temp is None and "outdoor_temperature" in climate_state.attributes:
                try:
                    outdoor_temp = float(climate_state.attributes["outdoor_temperature"])
                except (ValueError, TypeError):
                    pass
            # Check corresponding WF-RAC sensors by naming convention if needed
            if outdoor_temp is None:
                prefix = climate_entity.replace("climate.", "")
                outdoor_temp = self._get_float_state(f"sensor.{prefix}_outdoor_temperature")
            if hp_energy_kwh is None:
                prefix = climate_entity.replace("climate.", "")
                hp_energy_kwh = self._get_float_state(f"sensor.{prefix}_energy_consumed")

        # Fallback outdoor temp from weather entity if outdoor sensor unavailable
        if outdoor_temp is None:
            outdoor_temp = self._get_weather_current_temp()

        # Fallback indoor temp if missing
        if indoor_temp is None:
            indoor_temp = self.target_comfort_temp

        if outdoor_temp is None:
            outdoor_temp = 5.0

        # Calculate HP power from cumulative energy (e.g. Mitsubishi WF-RAC energy_consumed)
        if (hp_power_kw is None or hp_power_kw == 0.0) and hp_energy_kwh is not None:
            if self._last_hp_energy_kwh is not None and self._last_measurement_time is not None:
                delta_energy = max(0.0, hp_energy_kwh - self._last_hp_energy_kwh)
                delta_hours = (now_ts - self._last_measurement_time) / 3600.0
                if delta_hours > 0.005:
                    hp_power_kw = delta_energy / delta_hours
            self._last_hp_energy_kwh = hp_energy_kwh

        if hp_power_kw is None:
            hp_power_kw = 0.0

        # Convert power from W to kW if sensor value is large (e.g. > 100 W)
        if hp_power_kw > 100.0:
            hp_power_kw /= 1000.0
        if boiler_power_kw > 100.0:
            boiler_power_kw /= 1000.0

        # 2. Self-Learning Update (RLS)
        if self.learning_enabled and self._last_measurement_time is not None:
            delta_hours = (now_ts - self._last_measurement_time) / 3600.0
            updated = self.thermal_model.update_measurement(
                t_in=indoor_temp,
                t_out=outdoor_temp,
                heat_pump_power_kw=hp_power_kw,
                delta_hours=delta_hours,
            )
            if updated and self.thermal_model.sample_count % 10 == 0:
                await self.async_save_model()

        self._last_measurement_time = now_ts

        # 3. Read Future Prices & Weather Forecast
        prices = await self._async_get_electricity_prices()
        weather_forecast = await self._async_get_weather_forecast()
        solar_forecast = await self._async_get_solar_forecast()

        # 4. Run Optimizer
        result = self.optimizer.solve(
            current_indoor_temp=indoor_temp,
            target_comfort_temp=self.target_comfort_temp,
            allowed_drift=self.allowed_drift,
            preheat_boost=self.preheat_boost,
            mode=self.mode,
            prices=prices,
            outdoor_forecast=weather_forecast,
            solar_forecast=solar_forecast,
        )
        self.last_optimization_result = result

        # 5. Execute Dispatch Commands to Devices if master is enabled
        if self.master_enabled:
            await self._async_dispatch_commands(result)

        # 6. Read Big Consumers Live Breakdown
        big_consumers_data = self._read_big_consumers()

        # 7. Package Data Payload for Home Assistant Entities & Lovelace Card
        return {
            "current_indoor_temp": round(indoor_temp, 2),
            "current_outdoor_temp": round(outdoor_temp, 2),
            "current_hp_power_kw": round(hp_power_kw, 2),
            "current_boiler_power_kw": round(boiler_power_kw, 2),
            "current_cop": round(self.thermal_model.estimate_cop(outdoor_temp), 2),
            "mode": self.mode,
            "target_comfort_temp": self.target_comfort_temp,
            "allowed_drift": self.allowed_drift,
            "preheat_boost": self.preheat_boost,
            "recommended_setpoint": result.recommended_setpoint,
            "recommended_boiler_state": result.recommended_boiler_state,
            "current_action": result.current_action,
            "savings_percent": result.savings_percent,
            "savings_currency": result.savings_currency,
            "total_optimized_cost": result.total_optimized_cost,
            "total_baseline_cost": result.total_baseline_cost,
            "predicted_peak_power_kw": result.predicted_peak_power_kw,
            "peak_shaving_active": result.peak_shaving_active,
            "effektavgift_monthly_savings": result.effektavgift_monthly_savings,
            "peak_limit_kw": self.optimizer.peak_limit_kw,
            "building_time_constant_tau": round(self.thermal_model.tau, 1),
            "building_thermal_capacity_cth": round(self.thermal_model.c_th, 2),
            "building_thermal_resistance_rth": round(self.thermal_model.r_th, 2),
            "building_internal_gains_kw": round(self.thermal_model.q_internal, 2),
            "learning_samples": self.thermal_model.sample_count,
            "big_consumers": big_consumers_data,
            "current_spot_price": round(self._latest_price_breakdowns.get(result.intervals[0].timestamp.isoformat()).spot_price, 4) if (result.intervals and result.intervals[0].timestamp.isoformat() in self._latest_price_breakdowns) else 0.0,
            "current_grid_fee": round(self._latest_price_breakdowns.get(result.intervals[0].timestamp.isoformat()).grid_transmission_fee, 4) if (result.intervals and result.intervals[0].timestamp.isoformat() in self._latest_price_breakdowns) else 0.0,
            "current_energy_tax": round(self._latest_price_breakdowns.get(result.intervals[0].timestamp.isoformat()).energy_tax, 4) if (result.intervals and result.intervals[0].timestamp.isoformat() in self._latest_price_breakdowns) else 0.0,
            "is_high_load": self._latest_price_breakdowns.get(result.intervals[0].timestamp.isoformat()).is_high_load if (result.intervals and result.intervals[0].timestamp.isoformat() in self._latest_price_breakdowns) else False,
            "tariff_currency": self.tariff_calculator.currency,
            "consumer_score": result.current_consumer_score,
            "consumer_rating": result.current_consumer_rating,
            "shower_score": result.current_shower_score,
            "shower_rating": result.current_shower_rating,
            "shower_reheat_window": result.current_shower_reheat_window,
            "shower_effective_price": result.current_shower_effective_price,
            "best_consumer_hours": result.best_consumer_hours,
            "best_shower_hours": result.best_shower_hours,
            "schedule": [
                {
                    "time": inv.timestamp.isoformat(),
                    "price": round(inv.price, 4),
                    "spot_price": round(self._latest_price_breakdowns.get(inv.timestamp.isoformat(), PriceBreakdown(inv.price, 0, 0, 0, 0, inv.price, False)).spot_price, 4),
                    "grid_fee": round(self._latest_price_breakdowns.get(inv.timestamp.isoformat(), PriceBreakdown(0, 0, 0, 0, 0, 0, False)).grid_transmission_fee, 4),
                    "energy_tax": round(self._latest_price_breakdowns.get(inv.timestamp.isoformat(), PriceBreakdown(0, 0, 0, 0, 0, 0, False)).energy_tax, 4),
                    "is_high_load": self._latest_price_breakdowns.get(inv.timestamp.isoformat(), PriceBreakdown(0, 0, 0, 0, 0, 0, False)).is_high_load,
                    "outdoor_temp": round(inv.outdoor_temp, 1),
                    "cop": round(inv.cop, 2),
                    "action": inv.heat_pump_action,
                    "target_setpoint": inv.heat_pump_target_setpoint,
                    "hp_power_kw": inv.heat_pump_power_kw,
                    "predicted_temp": inv.predicted_indoor_temp,
                    "boiler_action": inv.boiler_action,
                    "boiler_power_kw": inv.boiler_power_kw,
                    "solar_kw": inv.solar_generation_kw,
                    "net_grid_kw": inv.net_grid_power_kw,
                    "cost": inv.cost,
                    "consumer_score": inv.consumer_score,
                    "consumer_rating": inv.consumer_rating,
                    "shower_score": inv.shower_score,
                    "shower_rating": inv.shower_rating,
                    "shower_effective_price": inv.shower_effective_price,
                    "shower_reheat_window": inv.shower_reheat_window,
                    "shower_reheat_cost_sek": inv.shower_reheat_cost_sek,
                }
                for inv in result.intervals
            ],
        }

    async def _async_dispatch_commands(self, result: OptimizationResult) -> None:
        """Send target setpoint to heat pump and switch commands to boiler."""
        # 1. Dispatch to Heat Pump Climate (e.g. Mitsubishi WF-RAC)
        climate_entity = self.entry.data.get(CONF_HEAT_PUMP_CLIMATE)
        if climate_entity and self.hass.states.get(climate_entity):
            # Mitsubishi WF-RAC uses 0.5°C step resolution and bounds between 16°C and 30°C
            raw_target = result.recommended_setpoint
            target_setpoint = round(raw_target * 2.0) / 2.0
            target_setpoint = max(16.0, min(30.0, target_setpoint))

            try:
                current_state = self.hass.states.get(climate_entity)
                current_target = current_state.attributes.get(ATTR_TEMPERATURE)

                # Ensure HVAC mode is heat if device is off or idle and action is active
                current_mode = current_state.state
                if current_mode in (HVACMode.OFF, "off") and result.current_action != "idle":
                    await self.hass.services.async_call(
                        "climate",
                        SERVICE_SET_HVAC_MODE,
                        {
                            ATTR_ENTITY_ID: climate_entity,
                            ATTR_HVAC_MODE: HVACMode.HEAT,
                        },
                        blocking=False,
                    )

                # Only issue service call if setpoint difference >= 0.2°C to prevent excessive Wi-Fi calls
                if current_target is None or abs(float(current_target) - target_setpoint) >= 0.2:
                    _LOGGER.info(
                        "Dispatching setpoint %.1f°C to Heat Pump (Mitsubishi WF-RAC) %s (was %s)",
                        target_setpoint,
                        climate_entity,
                        current_target,
                    )
                    await self.hass.services.async_call(
                        "climate",
                        SERVICE_SET_TEMPERATURE,
                        {
                            ATTR_ENTITY_ID: climate_entity,
                            ATTR_TEMPERATURE: target_setpoint,
                        },
                        blocking=False,
                    )
            except Exception as err:
                _LOGGER.error("Failed to set heat pump temperature: %s", err)

        # 2. Dispatch to Boiler Entity
        boiler_entity = self.entry.data.get(CONF_BOILER_ENTITY)
        if self.boiler_control_enabled and boiler_entity and self.hass.states.get(boiler_entity):
            should_run = result.recommended_boiler_state
            try:
                boiler_state = self.hass.states.get(boiler_entity)
                domain = boiler_entity.split(".")[0]
                is_currently_on = boiler_state.state in (STATE_ON, "heat", "performance")

                if should_run and not is_currently_on:
                    _LOGGER.info("Boiler scheduled ON during cheap electricity hour: %s", boiler_entity)
                    await self.hass.services.async_call(
                        domain,
                        SERVICE_TURN_ON,
                        {ATTR_ENTITY_ID: boiler_entity},
                        blocking=False,
                    )
                elif not should_run and is_currently_on:
                    _LOGGER.info("Boiler scheduled OFF during high electricity hour: %s", boiler_entity)
                    await self.hass.services.async_call(
                        domain,
                        SERVICE_TURN_OFF,
                        {ATTR_ENTITY_ID: boiler_entity},
                        blocking=False,
                    )
            except Exception as err:
                _LOGGER.error("Failed to dispatch boiler command: %s", err)

    def _read_big_consumers(self) -> List[Dict[str, Any]]:
        """Read live power and state from configured big consumers."""
        consumers: List[Dict[str, Any]] = []

        # Heat pump
        hp_sensor = self.entry.data.get(CONF_HEAT_PUMP_POWER_SENSOR)
        if hp_sensor:
            val = self._get_float_state(hp_sensor, 0.0)
            if val > 100.0:
                val /= 1000.0
            consumers.append({"name": "Heat Pump", "power_kw": round(val, 2), "entity_id": hp_sensor})

        # Boiler
        boiler_sensor = self.entry.data.get(CONF_BOILER_POWER_SENSOR)
        if boiler_sensor:
            val = self._get_float_state(boiler_sensor, 0.0)
            if val > 100.0:
                val /= 1000.0
            consumers.append({"name": "Water Boiler", "power_kw": round(val, 2), "entity_id": boiler_sensor})

        # EV Charger
        ev_sensor = self.entry.data.get(CONF_EV_CHARGER_POWER_SENSOR)
        if ev_sensor:
            val = self._get_float_state(ev_sensor, 0.0)
            if val > 100.0:
                val /= 1000.0
            consumers.append({"name": "EV Charger", "power_kw": round(val, 2), "entity_id": ev_sensor})

        # Arbitrary big consumers list
        extra_sensors = self.entry.data.get(CONF_BIG_CONSUMERS, [])
        for entity_id in extra_sensors:
            state = self.hass.states.get(entity_id)
            if state and state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                try:
                    val = float(state.state)
                    if val > 100.0:
                        val /= 1000.0
                    friendly_name = state.attributes.get("friendly_name", entity_id)
                    consumers.append({"name": friendly_name, "power_kw": round(val, 2), "entity_id": entity_id})
                except (ValueError, TypeError):
                    pass

        return consumers

    async def _async_get_electricity_prices(self) -> List[Tuple[datetime, float]]:
        """Extract hourly electricity spot prices and calculate all-in end-user price with tariffs & taxes."""
        price_entity = self.entry.data.get(CONF_PRICE_SENSOR)
        now = datetime.now().replace(minute=0, second=0, microsecond=0)
        default_prices = [(now + timedelta(hours=i), 0.20) for i in range(24)]

        if not price_entity:
            raw_prices = default_prices
        else:
            state = self.hass.states.get(price_entity)
            if not state:
                raw_prices = default_prices
            else:
                raw_prices = []
                raw_entries: List[Any] = []
                attrs = state.attributes

                if "raw_today" in attrs:
                    raw_entries.extend(attrs.get("raw_today") or [])
                    raw_entries.extend(attrs.get("raw_tomorrow") or [])
                elif "prices" in attrs:
                    raw_entries.extend(attrs.get("prices") or [])
                elif "today" in attrs:
                    raw_entries.extend(attrs.get("today") or [])
                    raw_entries.extend(attrs.get("tomorrow") or [])

                for entry in raw_entries:
                    try:
                        if isinstance(entry, dict):
                            ts_str = entry.get("start") or entry.get("time") or entry.get("timestamp")
                            price_val = entry.get("value") or entry.get("total") or entry.get("price")
                            if ts_str and price_val is not None:
                                if isinstance(ts_str, datetime):
                                    ts = ts_str
                                else:
                                    ts = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))
                                raw_prices.append((ts, float(price_val)))
                    except Exception:
                        continue

                if not raw_prices:
                    try:
                        current_price = float(state.state)
                        raw_prices = [(now + timedelta(hours=i), current_price) for i in range(24)]
                    except (ValueError, TypeError):
                        raw_prices = default_prices

        # Calculate all-in total price for each hour including Göteborg Energi tariffs, taxes, and VAT
        all_in_prices: List[Tuple[datetime, float]] = []
        self._latest_price_breakdowns = {}

        for ts, spot in sorted(raw_prices, key=lambda x: x[0]):
            bd = self.tariff_calculator.calculate_total_price(raw_spot_price=spot, dt=ts)
            all_in_prices.append((ts, bd.total_price))
            self._latest_price_breakdowns[ts.isoformat()] = bd

        return all_in_prices

    async def _async_get_weather_forecast(self) -> List[Tuple[datetime, float]]:
        """Extract hourly outdoor temperature forecast from weather or sensor entity."""
        now = datetime.now().replace(minute=0, second=0, microsecond=0)
        default_temps = [(now + timedelta(hours=i), 6.0) for i in range(24)]

        weather_entity = self.entry.data.get(CONF_WEATHER_ENTITY)
        if not weather_entity:
            for candidate in ["weather.forecast_home", "weather.home"]:
                if self.hass.states.get(candidate):
                    weather_entity = candidate
                    break
            if not weather_entity:
                for s in self.hass.states.async_all():
                    if s.entity_id.startswith("weather."):
                        weather_entity = s.entity_id
                        break
        if not weather_entity:
            return default_temps

        # In modern HA (2023.12+), weather forecast is fetched via service weather.get_forecasts
        try:
            resp = await self.hass.services.async_call(
                "weather",
                "get_forecasts",
                {ATTR_ENTITY_ID: weather_entity, "type": "hourly"},
                blocking=True,
                return_response=True,
            )
            forecast_items = resp.get(weather_entity, {}).get("forecast", [])
            results: List[Tuple[datetime, float]] = []
            for item in forecast_items:
                ts_str = item.get("datetime")
                temp = item.get("temperature")
                if ts_str and temp is not None:
                    ts = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))
                    results.append((ts, float(temp)))
            if results:
                return sorted(results, key=lambda x: x[0])
        except Exception:
            pass

        # Fallback to weather state attributes if service call is not supported
        state = self.hass.states.get(weather_entity)
        if state and "forecast" in state.attributes:
            try:
                results = []
                for item in state.attributes["forecast"]:
                    ts_str = item.get("datetime")
                    temp = item.get("temperature")
                    if ts_str and temp is not None:
                        ts = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))
                        results.append((ts, float(temp)))
                if results:
                    return sorted(results, key=lambda x: x[0])
            except Exception:
                pass

        return default_temps

    async def _async_get_solar_forecast(self) -> List[Tuple[datetime, float]]:
        """Read solar PV generation forecast if configured (Solcast / Forecast.Solar)."""
        solar_entity = self.entry.data.get(CONF_SOLAR_FORECAST_ENTITY)
        if not solar_entity:
            return []

        state = self.hass.states.get(solar_entity)
        if not state:
            return []

        # Parse forecast attribute if present
        results: List[Tuple[datetime, float]] = []
        if "forecast" in state.attributes:
            for item in state.attributes["forecast"]:
                try:
                    ts = datetime.fromisoformat(str(item["datetime"]).replace("Z", "+00:00"))
                    val = float(item.get("power", item.get("watts", 0.0)))
                    if val > 100.0:
                        val /= 1000.0  # W to kW
                    results.append((ts, val))
                except Exception:
                    continue
        return results

    def _get_float_state(self, entity_id: Optional[str], default: Optional[float] = None) -> Optional[float]:
        """Safely extract float value from state."""
        if not entity_id:
            return default
        state = self.hass.states.get(entity_id)
        if not state or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return default
        try:
            return float(state.state)
        except (ValueError, TypeError):
            return default

    def _get_weather_current_temp(self) -> Optional[float]:
        """Get temperature attribute from weather entity."""
        weather_entity = self.entry.data.get(CONF_WEATHER_ENTITY)
        if not weather_entity:
            return None
        state = self.hass.states.get(weather_entity)
        if state and "temperature" in state.attributes:
            try:
                return float(state.attributes["temperature"])
            except (ValueError, TypeError):
                pass
        return None
