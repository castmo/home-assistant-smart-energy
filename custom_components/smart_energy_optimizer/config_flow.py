"""Config flow and Options flow for Smart Energy & Thermal Optimizer."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_BATTERY_CAPACITY_KWH,
    CONF_BATTERY_POWER_SENSOR,
    CONF_BATTERY_SOC_SENSOR,
    CONF_BIG_CONSUMERS,
    CONF_BOILER_DAILY_HOURS,
    CONF_BOILER_ENTITY,
    CONF_BOILER_POWER_SENSOR,
    CONF_BOILER_RATED_POWER,
    CONF_CONFIGURE_ADVANCED,
    CONF_EFFEKTAVGIFT_PRICE_PER_KW,
    CONF_ENABLE_EFFEKTDIFF,
    CONF_ENERGY_TAX,
    CONF_EV_CHARGER_ENTITY,
    CONF_EV_CHARGER_POWER_SENSOR,
    CONF_GRID_FEE_HIGH_LOAD,
    CONF_GRID_FEE_LOW_LOAD,
    CONF_HEAT_PUMP_CLIMATE,
    CONF_HEAT_PUMP_ENERGY_SENSOR,
    CONF_HEAT_PUMP_MAX_POWER,
    CONF_HEAT_PUMP_POWER_SENSOR,
    CONF_INDOOR_TEMP_SENSOR,
    CONF_OUTDOOR_TEMP_SENSOR,
    CONF_PEAK_LIMIT_KW,
    CONF_PRICE_SENSOR,
    CONF_SOLAR_FORECAST_ENTITY,
    CONF_SOLAR_POWER_SENSOR,
    CONF_SPOT_PRICE_INCLUDES_VAT,
    CONF_SURCHARGE,
    CONF_TARIFF_TYPE,
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
    OPTIMIZATION_MODES,
)
from .price_calculator import (
    TARIFF_CUSTOM,
    TARIFF_FLAT,
    TARIFF_GOTEBORG_ENKELTARIFF,
    TARIFF_GOTEBORG_TIDSTARIFF,
)

_LOGGER = logging.getLogger(__name__)


class SmartEnergyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Smart Energy & Thermal Optimizer."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize config flow."""
        self._data: Dict[str, Any] = {}

    def _create_optimizer_entry(self) -> config_entries.ConfigFlowResult:
        """Create entry with Göteborg Energi & thermal optimizer standard defaults."""
        climate_entity = self._data.get(CONF_HEAT_PUMP_CLIMATE)
        if climate_entity:
            prefix = climate_entity.replace("climate.", "")
            if not self._data.get(CONF_HEAT_PUMP_ENERGY_SENSOR):
                for candidate in [f"sensor.{prefix}_energy_consumed", f"sensor.{prefix}_energy"]:
                    if self.hass.states.get(candidate):
                        self._data[CONF_HEAT_PUMP_ENERGY_SENSOR] = candidate
                        break
            if not self._data.get(CONF_OUTDOOR_TEMP_SENSOR):
                candidate = f"sensor.{prefix}_outdoor_temperature"
                if self.hass.states.get(candidate):
                    self._data[CONF_OUTDOOR_TEMP_SENSOR] = candidate

        # Auto-detect weather if missing
        if not self._data.get(CONF_WEATHER_ENTITY):
            for candidate in ["weather.forecast_home", "weather.home"]:
                if self.hass.states.get(candidate):
                    self._data[CONF_WEATHER_ENTITY] = candidate
                    break
            if not self._data.get(CONF_WEATHER_ENTITY):
                for s in self.hass.states.async_all():
                    if s.entity_id.startswith("weather."):
                        self._data[CONF_WEATHER_ENTITY] = s.entity_id
                        break

        # Standard Göteborg Energi & system defaults
        self._data.setdefault(CONF_HEAT_PUMP_MAX_POWER, 3.5)
        self._data.setdefault(CONF_BOILER_RATED_POWER, 2.0)
        self._data.setdefault(CONF_BOILER_DAILY_HOURS, 2.5)
        self._data.setdefault(CONF_TARIFF_TYPE, TARIFF_GOTEBORG_TIDSTARIFF)
        self._data.setdefault(CONF_GRID_FEE_HIGH_LOAD, 0.38)
        self._data.setdefault(CONF_GRID_FEE_LOW_LOAD, 0.16)
        self._data.setdefault(CONF_ENERGY_TAX, 0.445)
        self._data.setdefault(CONF_SURCHARGE, 0.05)
        self._data.setdefault(CONF_VAT_PERCENT, 25.0)
        self._data.setdefault(CONF_SPOT_PRICE_INCLUDES_VAT, False)
        self._data.setdefault(CONF_ENABLE_EFFEKTDIFF, DEFAULT_ENABLE_EFFEKTDIFF)
        self._data.setdefault(CONF_PEAK_LIMIT_KW, DEFAULT_PEAK_LIMIT_KW)
        self._data.setdefault(CONF_EFFEKTAVGIFT_PRICE_PER_KW, DEFAULT_EFFEKTAVGIFT_PRICE_PER_KW)

        return self.async_create_entry(
            title="Smart Energy Optimizer",
            data=self._data,
            options={
                "mode": DEFAULT_MODE,
                "target_comfort_temp": DEFAULT_TARGET_TEMP,
                "allowed_drift": DEFAULT_ALLOWED_DRIFT,
                "preheat_boost": DEFAULT_MAX_PREHEAT,
                "master_enabled": True,
                "boiler_control_enabled": True,
                "learning_enabled": True,
                CONF_TARIFF_TYPE: self._data.get(CONF_TARIFF_TYPE, TARIFF_GOTEBORG_TIDSTARIFF),
                CONF_GRID_FEE_HIGH_LOAD: self._data.get(CONF_GRID_FEE_HIGH_LOAD, 0.38),
                CONF_GRID_FEE_LOW_LOAD: self._data.get(CONF_GRID_FEE_LOW_LOAD, 0.16),
                CONF_ENERGY_TAX: self._data.get(CONF_ENERGY_TAX, 0.445),
                CONF_SURCHARGE: self._data.get(CONF_SURCHARGE, 0.05),
                CONF_VAT_PERCENT: self._data.get(CONF_VAT_PERCENT, 25.0),
                CONF_SPOT_PRICE_INCLUDES_VAT: self._data.get(CONF_SPOT_PRICE_INCLUDES_VAT, False),
            },
        )

    async def async_step_user(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """Step 1: Quick Setup - Core Heat Pump & Electricity Price setup."""
        errors: Dict[str, str] = {}

        if user_input is not None:
            self._data.update(user_input)
            if not user_input.get(CONF_CONFIGURE_ADVANCED, False):
                return self._create_optimizer_entry()
            return await self.async_step_advanced_heat_pump()

        # Intelligent auto-discovery of default entities in Home Assistant
        default_climate = None
        default_price = None
        default_weather = None

        try:
            states = self.hass.states.async_all()
            climate_entities = [s.entity_id for s in states if s.entity_id.startswith("climate.")]
            if len(climate_entities) == 1:
                default_climate = climate_entities[0]
            else:
                for c in climate_entities:
                    if any(k in c.lower() for k in ["wf_rac", "mitsubishi", "heatpump", "varmepump", "ac", "pump"]):
                        default_climate = c
                        break

            price_entities = [
                s.entity_id for s in states
                if s.entity_id.startswith("sensor.") and any(
                    k in s.entity_id.lower()
                    for k in ["nordpool", "tibber", "electricity_price", "spot_price", "strompris", "elpris"]
                )
            ]
            if price_entities:
                default_price = price_entities[0]

            weather_entities = [s.entity_id for s in states if s.entity_id.startswith("weather.")]
            if "weather.forecast_home" in weather_entities:
                default_weather = "weather.forecast_home"
            elif "weather.home" in weather_entities:
                default_weather = "weather.home"
            elif weather_entities:
                default_weather = weather_entities[0]
        except Exception:
            pass

        schema_dict: Dict[Any, Any] = {}

        if default_climate:
            schema_dict[vol.Required(CONF_HEAT_PUMP_CLIMATE, default=default_climate)] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="climate")
            )
        else:
            schema_dict[vol.Required(CONF_HEAT_PUMP_CLIMATE)] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="climate")
            )

        if default_price:
            schema_dict[vol.Required(CONF_PRICE_SENSOR, default=default_price)] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            )
        else:
            schema_dict[vol.Required(CONF_PRICE_SENSOR)] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            )

        if default_weather:
            schema_dict[vol.Optional(CONF_WEATHER_ENTITY, default=default_weather)] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="weather")
            )
        else:
            schema_dict[vol.Optional(CONF_WEATHER_ENTITY)] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="weather")
            )

        schema_dict[vol.Optional(CONF_CONFIGURE_ADVANCED, default=False)] = selector.BooleanSelector()

        return self.async_show_form(step_id="user", data_schema=vol.Schema(schema_dict), errors=errors)

    async def async_step_advanced_heat_pump(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """Step 2 (Advanced): Water Boiler & Heat Pump Sensor Overrides."""
        errors: Dict[str, str] = {}

        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_tariff()

        schema = vol.Schema(
            {
                vol.Optional(CONF_HEAT_PUMP_MAX_POWER, default=3.5): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0.5, max=15.0, step=0.1, unit_of_measurement="kW")
                ),
                vol.Optional(CONF_HEAT_PUMP_ENERGY_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="energy")
                ),
                vol.Optional(CONF_HEAT_PUMP_POWER_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="power")
                ),
                vol.Optional(CONF_INDOOR_TEMP_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
                ),
                vol.Optional(CONF_OUTDOOR_TEMP_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
                ),
                vol.Optional(CONF_BOILER_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["switch", "water_heater"])
                ),
                vol.Optional(CONF_BOILER_POWER_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="power")
                ),
                vol.Optional(CONF_BOILER_RATED_POWER, default=2.0): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0.5, max=9.0, step=0.1, unit_of_measurement="kW")
                ),
                vol.Optional(CONF_BOILER_DAILY_HOURS, default=2.5): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0.5, max=8.0, step=0.5, unit_of_measurement="h")
                ),
            }
        )

        return self.async_show_form(step_id="advanced_heat_pump", data_schema=schema, errors=errors)

    async def async_step_tariff(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """Step 3 (Advanced): Electricity Tariff, Göteborg Energi Grid Fees, Energy Tax & VAT."""
        errors: Dict[str, str] = {}

        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_subsystems()

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_TARIFF_TYPE,
                    default=TARIFF_GOTEBORG_TIDSTARIFF,
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(
                                value=TARIFF_GOTEBORG_TIDSTARIFF,
                                label="Göteborg Energi Tidstariff (Winter High/Low Load)",
                            ),
                            selector.SelectOptionDict(
                                value=TARIFF_GOTEBORG_ENKELTARIFF,
                                label="Göteborg Energi Enkeltariff (Flat Transmission)",
                            ),
                            selector.SelectOptionDict(
                                value=TARIFF_FLAT,
                                label="Flat Grid Fee",
                            ),
                            selector.SelectOptionDict(
                                value=TARIFF_CUSTOM,
                                label="Custom Grid Tariff",
                            ),
                        ]
                    )
                ),
                vol.Required(CONF_GRID_FEE_HIGH_LOAD, default=0.38): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0.0, max=2.0, step=0.01, unit_of_measurement="SEK/kWh")
                ),
                vol.Required(CONF_GRID_FEE_LOW_LOAD, default=0.16): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0.0, max=2.0, step=0.01, unit_of_measurement="SEK/kWh")
                ),
                vol.Required(CONF_ENERGY_TAX, default=0.445): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0.0, max=2.0, step=0.005, unit_of_measurement="SEK/kWh")
                ),
                vol.Required(CONF_SURCHARGE, default=0.05): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0.0, max=1.0, step=0.005, unit_of_measurement="SEK/kWh")
                ),
                vol.Required(CONF_VAT_PERCENT, default=25.0): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0.0, max=30.0, step=0.5, unit_of_measurement="%")
                ),
                vol.Required(CONF_SPOT_PRICE_INCLUDES_VAT, default=False): selector.BooleanSelector(),
            }
        )

        return self.async_show_form(step_id="tariff", data_schema=schema, errors=errors)

    async def async_step_subsystems(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """Step 4 (Advanced): Big Consumers, Solar, Battery, and EV Charger extensions."""
        errors: Dict[str, str] = {}

        if user_input is not None:
            self._data.update(user_input)
            return self._create_optimizer_entry()

        schema = vol.Schema(
            {
                vol.Optional(CONF_BIG_CONSUMERS): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="power", multiple=True)
                ),
                vol.Optional(CONF_SOLAR_POWER_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="power")
                ),
                vol.Optional(CONF_SOLAR_FORECAST_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional(CONF_BATTERY_SOC_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="battery")
                ),
                vol.Optional(CONF_BATTERY_POWER_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="power")
                ),
                vol.Optional(CONF_BATTERY_CAPACITY_KWH, default=10.0): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=1.0, max=50.0, step=0.5, unit_of_measurement="kWh")
                ),
                vol.Optional(CONF_EV_CHARGER_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["switch", "sensor"])
                ),
                vol.Optional(CONF_EV_CHARGER_POWER_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="power")
                ),
            }
        )

        return self.async_show_form(step_id="subsystems", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Get options flow handler."""
        return SmartEnergyOptionsFlow(config_entry)


class SmartEnergyOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow to update runtime preferences and comfort limits."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """Manage runtime optimization settings and Göteborg Energi tariffs."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        opts = self.config_entry.options

        schema = vol.Schema(
            {
                vol.Required(
                    "mode",
                    default=opts.get("mode", DEFAULT_MODE),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(value=MODE_PRICE_OPTIMIZED, label="Price-Optimized (Max Savings)"),
                            selector.SelectOptionDict(value=MODE_BALANCED, label="Balanced (Comfort & Savings)"),
                            selector.SelectOptionDict(value=MODE_STABLE_TEMP, label="Stable Temperature (Max Comfort)"),
                        ]
                    )
                ),
                vol.Required(
                    "target_comfort_temp",
                    default=opts.get("target_comfort_temp", DEFAULT_TARGET_TEMP),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=16.0, max=26.0, step=0.5, unit_of_measurement="°C")
                ),
                vol.Required(
                    "allowed_drift",
                    default=opts.get("allowed_drift", DEFAULT_ALLOWED_DRIFT),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0.2, max=3.0, step=0.1, unit_of_measurement="°C")
                ),
                vol.Required(
                    "preheat_boost",
                    default=opts.get("preheat_boost", DEFAULT_MAX_PREHEAT),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0.0, max=3.5, step=0.1, unit_of_measurement="°C")
                ),
                vol.Required(
                    CONF_TARIFF_TYPE,
                    default=opts.get(CONF_TARIFF_TYPE, TARIFF_GOTEBORG_TIDSTARIFF),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(
                                value=TARIFF_GOTEBORG_TIDSTARIFF,
                                label="Göteborg Energi Tidstariff (Winter High/Low Load)",
                            ),
                            selector.SelectOptionDict(
                                value=TARIFF_GOTEBORG_ENKELTARIFF,
                                label="Göteborg Energi Enkeltariff (Flat Transmission)",
                            ),
                            selector.SelectOptionDict(
                                value=TARIFF_FLAT,
                                label="Flat Grid Fee",
                            ),
                            selector.SelectOptionDict(
                                value=TARIFF_CUSTOM,
                                label="Custom Grid Tariff",
                            ),
                        ]
                    )
                ),
                vol.Required(
                    CONF_GRID_FEE_HIGH_LOAD,
                    default=opts.get(CONF_GRID_FEE_HIGH_LOAD, 0.38),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0.0, max=2.0, step=0.01, unit_of_measurement="SEK/kWh")
                ),
                vol.Required(
                    CONF_GRID_FEE_LOW_LOAD,
                    default=opts.get(CONF_GRID_FEE_LOW_LOAD, 0.16),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0.0, max=2.0, step=0.01, unit_of_measurement="SEK/kWh")
                ),
                vol.Required(
                    CONF_ENERGY_TAX,
                    default=opts.get(CONF_ENERGY_TAX, 0.445),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0.0, max=2.0, step=0.005, unit_of_measurement="SEK/kWh")
                ),
                vol.Required(
                    CONF_SURCHARGE,
                    default=opts.get(CONF_SURCHARGE, 0.05),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0.0, max=1.0, step=0.005, unit_of_measurement="SEK/kWh")
                ),
                vol.Required(
                    CONF_VAT_PERCENT,
                    default=opts.get(CONF_VAT_PERCENT, 25.0),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0.0, max=30.0, step=0.5, unit_of_measurement="%")
                ),
                vol.Required(
                    "master_enabled",
                    default=opts.get("master_enabled", True),
                ): selector.BooleanSelector(),
                vol.Required(
                    "boiler_control_enabled",
                    default=opts.get("boiler_control_enabled", True),
                ): selector.BooleanSelector(),
                vol.Required(
                    "learning_enabled",
                    default=opts.get("learning_enabled", True),
                ): selector.BooleanSelector(),
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
