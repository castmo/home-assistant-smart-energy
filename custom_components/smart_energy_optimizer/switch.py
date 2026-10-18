"""Switch platform for Smart Energy & Thermal Optimizer."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SmartEnergyCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the switch platform."""
    coordinator: SmartEnergyCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = [
        SmartEnergyMasterSwitch(coordinator, entry),
        SmartEnergyBoilerSwitch(coordinator, entry),
        SmartEnergyLearningSwitch(coordinator, entry),
    ]

    async_add_entities(entities)


class BaseSmartEnergySwitch(CoordinatorEntity[SmartEnergyCoordinator], SwitchEntity):
    """Base switch class."""

    def __init__(
        self,
        coordinator: SmartEnergyCoordinator,
        entry: ConfigEntry,
        key: str,
        name: str,
    ) -> None:
        super().__init__(coordinator)
        self.entry = entry
        self._key = key
        self._attr_name = f"Smart Energy {name}"
        self._attr_unique_id = f"{entry.entry_id}_{key}"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.entry.entry_id)},
            name="Smart Energy & Thermal Optimizer",
            manufacturer="Home Assistant Community",
            model="MPC Thermal Building Controller",
            sw_version="1.0.0",
        )


class SmartEnergyMasterSwitch(BaseSmartEnergySwitch):
    """Master switch to enable/disable automated dispatch to heat pump and boiler."""

    def __init__(self, coordinator: SmartEnergyCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "master_automation", "Master Automated Dispatch")
        self._attr_icon = "mdi:power"

    @property
    def is_on(self) -> bool:
        return self.coordinator.master_enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.coordinator.master_enabled = True
        new_opts = dict(self.entry.options)
        new_opts["master_enabled"] = True
        self.hass.config_entries.async_update_entry(self.entry, options=new_opts)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.coordinator.master_enabled = False
        new_opts = dict(self.entry.options)
        new_opts["master_enabled"] = False
        self.hass.config_entries.async_update_entry(self.entry, options=new_opts)
        await self.coordinator.async_request_refresh()


class SmartEnergyBoilerSwitch(BaseSmartEnergySwitch):
    """Switch to enable/disable boiler smart dispatch."""

    def __init__(self, coordinator: SmartEnergyCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "boiler_automation", "Boiler Smart Scheduling")
        self._attr_icon = "mdi:water-boiler"

    @property
    def is_on(self) -> bool:
        return self.coordinator.boiler_control_enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.coordinator.boiler_control_enabled = True
        new_opts = dict(self.entry.options)
        new_opts["boiler_control_enabled"] = True
        self.hass.config_entries.async_update_entry(self.entry, options=new_opts)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.coordinator.boiler_control_enabled = False
        new_opts = dict(self.entry.options)
        new_opts["boiler_control_enabled"] = False
        self.hass.config_entries.async_update_entry(self.entry, options=new_opts)
        await self.coordinator.async_request_refresh()


class SmartEnergyLearningSwitch(BaseSmartEnergySwitch):
    """Switch to toggle online continuous thermal learning."""

    def __init__(self, coordinator: SmartEnergyCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "self_learning", "Continuous Model Learning")
        self._attr_icon = "mdi:brain"

    @property
    def is_on(self) -> bool:
        return self.coordinator.learning_enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.coordinator.learning_enabled = True
        new_opts = dict(self.entry.options)
        new_opts["learning_enabled"] = True
        self.hass.config_entries.async_update_entry(self.entry, options=new_opts)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.coordinator.learning_enabled = False
        new_opts = dict(self.entry.options)
        new_opts["learning_enabled"] = False
        self.hass.config_entries.async_update_entry(self.entry, options=new_opts)
        await self.coordinator.async_request_refresh()
