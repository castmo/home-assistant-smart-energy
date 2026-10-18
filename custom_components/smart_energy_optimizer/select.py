"""Select platform for Smart Energy & Thermal Optimizer."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    MODE_BALANCED,
    MODE_PRICE_OPTIMIZED,
    MODE_STABLE_TEMP,
    OPTIMIZATION_MODES,
)
from .coordinator import SmartEnergyCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the select platform."""
    coordinator: SmartEnergyCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([SmartEnergyModeSelect(coordinator, entry)])


class SmartEnergyModeSelect(CoordinatorEntity[SmartEnergyCoordinator], SelectEntity):
    """Select entity for optimization mode (Price-Optimized vs Stable Temperature)."""

    def __init__(self, coordinator: SmartEnergyCoordinator, entry: ConfigEntry) -> None:
        """Initialize the select entity."""
        super().__init__(coordinator)
        self.entry = entry
        self._attr_name = "Smart Energy Optimization Mode"
        self._attr_unique_id = f"{entry.entry_id}_optimization_mode"
        self._attr_options = OPTIMIZATION_MODES
        self._attr_icon = "mdi:tune-vertical"

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
    def current_option(self) -> str:
        """Return the current optimization mode."""
        return self.coordinator.mode

    async def async_select_option(self, option: str) -> None:
        """Change the optimization mode."""
        if option in OPTIMIZATION_MODES:
            self.coordinator.mode = option
            new_opts = dict(self.entry.options)
            new_opts["mode"] = option
            self.hass.config_entries.async_update_entry(self.entry, options=new_opts)
            await self.coordinator.async_request_refresh()
