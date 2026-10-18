"""Climate platform providing a smart virtual thermostat for the Heat Pump."""

from __future__ import annotations

from typing import Any, List, Optional

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    MODE_BALANCED,
    MODE_PRICE_OPTIMIZED,
    MODE_STABLE_TEMP,
)
from .coordinator import SmartEnergyCoordinator

PRESET_PRICE_OPTIMIZED = "Price-Optimized"
PRESET_BALANCED = "Balanced"
PRESET_STABLE_TEMP = "Stable Temperature"

PRESET_TO_MODE = {
    PRESET_PRICE_OPTIMIZED: MODE_PRICE_OPTIMIZED,
    PRESET_BALANCED: MODE_BALANCED,
    PRESET_STABLE_TEMP: MODE_STABLE_TEMP,
}
MODE_TO_PRESET = {v: k for k, v in PRESET_TO_MODE.items()}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the climate platform."""
    coordinator: SmartEnergyCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([SmartEnergyThermostat(coordinator, entry)])


class SmartEnergyThermostat(CoordinatorEntity[SmartEnergyCoordinator], ClimateEntity):
    """Smart virtual thermostat representation of the heat pump optimizer."""

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.AUTO, HVACMode.OFF]
    _attr_preset_modes = [PRESET_PRICE_OPTIMIZED, PRESET_BALANCED, PRESET_STABLE_TEMP]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.PRESET_MODE
    )

    def __init__(self, coordinator: SmartEnergyCoordinator, entry: ConfigEntry) -> None:
        """Initialize thermostat."""
        super().__init__(coordinator)
        self.entry = entry
        self._attr_name = "Smart Energy Heat Pump Controller"
        self._attr_unique_id = f"{entry.entry_id}_virtual_thermostat"
        self._attr_min_temp = 16.0
        self._attr_max_temp = 26.0
        self._attr_target_temperature_step = 0.5

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.entry.entry_id)},
            name="Smart Energy & Thermal Optimizer",
            manufacturer="Home Assistant Community",
            model="MPC Thermal Building Controller",
            sw_version="1.0.0",
        )

    @property
    def current_temperature(self) -> Optional[float]:
        return self.coordinator.data.get("current_indoor_temp")

    @property
    def target_temperature(self) -> Optional[float]:
        return self.coordinator.target_comfort_temp

    @property
    def hvac_mode(self) -> HVACMode:
        if not self.coordinator.master_enabled:
            return HVACMode.OFF
        return HVACMode.HEAT

    @property
    def hvac_action(self) -> HVACAction:
        if not self.coordinator.master_enabled:
            return HVACAction.OFF
        action = self.coordinator.data.get("current_action", "normal")
        if action in ("boost", "normal"):
            return HVACAction.HEATING
        return HVACAction.IDLE

    @property
    def preset_mode(self) -> Optional[str]:
        return MODE_TO_PRESET.get(self.coordinator.mode, PRESET_BALANCED)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target comfort temperature."""
        temp = kwargs.get("temperature")
        if temp is not None:
            self.coordinator.target_comfort_temp = float(temp)
            new_opts = dict(self.entry.options)
            new_opts["target_comfort_temp"] = float(temp)
            self.hass.config_entries.async_update_entry(self.entry, options=new_opts)
            await self.coordinator.async_request_refresh()

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set new optimization preset mode."""
        if preset_mode in PRESET_TO_MODE:
            new_mode = PRESET_TO_MODE[preset_mode]
            self.coordinator.mode = new_mode
            new_opts = dict(self.entry.options)
            new_opts["mode"] = new_mode
            self.hass.config_entries.async_update_entry(self.entry, options=new_opts)
            await self.coordinator.async_request_refresh()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Turn on or off master automation."""
        if hvac_mode == HVACMode.OFF:
            self.coordinator.master_enabled = False
        else:
            self.coordinator.master_enabled = True
        new_opts = dict(self.entry.options)
        new_opts["master_enabled"] = self.coordinator.master_enabled
        self.hass.config_entries.async_update_entry(self.entry, options=new_opts)
        await self.coordinator.async_request_refresh()
