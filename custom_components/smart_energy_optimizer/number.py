"""Number platform for Smart Energy & Thermal Optimizer."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
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
    """Set up the number platform."""
    coordinator: SmartEnergyCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = [
        SmartEnergyTargetTempNumber(coordinator, entry),
        SmartEnergyAllowedDriftNumber(coordinator, entry),
        SmartEnergyPreheatBoostNumber(coordinator, entry),
    ]

    async_add_entities(entities)


class BaseSmartEnergyNumber(CoordinatorEntity[SmartEnergyCoordinator], NumberEntity):
    """Base class for smart energy number controls."""

    def __init__(
        self,
        coordinator: SmartEnergyCoordinator,
        entry: ConfigEntry,
        key: str,
        name: str,
        min_value: float,
        max_value: float,
        step: float,
    ) -> None:
        super().__init__(coordinator)
        self.entry = entry
        self._key = key
        self._attr_name = f"Smart Energy {name}"
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_native_min_value = min_value
        self._attr_native_max_value = max_value
        self._attr_native_step = step
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_mode = NumberMode.BOX

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.entry.entry_id)},
            name="Smart Energy & Thermal Optimizer",
            manufacturer="Home Assistant Community",
            model="MPC Thermal Building Controller",
            sw_version="1.0.0",
        )


class SmartEnergyTargetTempNumber(BaseSmartEnergyNumber):
    """Target comfort temperature setting."""

    def __init__(self, coordinator: SmartEnergyCoordinator, entry: ConfigEntry) -> None:
        super().__init__(
            coordinator, entry, "target_comfort_temp", "Comfort Target Temperature", 16.0, 26.0, 0.5
        )
        self._attr_icon = "mdi:thermometer-check"

    @property
    def native_value(self) -> float:
        return self.coordinator.target_comfort_temp

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator.target_comfort_temp = float(value)
        new_opts = dict(self.entry.options)
        new_opts["target_comfort_temp"] = float(value)
        self.hass.config_entries.async_update_entry(self.entry, options=new_opts)
        await self.coordinator.async_request_refresh()


class SmartEnergyAllowedDriftNumber(BaseSmartEnergyNumber):
    """Allowed indoor temperature drift (drop) below comfort target."""

    def __init__(self, coordinator: SmartEnergyCoordinator, entry: ConfigEntry) -> None:
        super().__init__(
            coordinator, entry, "allowed_drift", "Allowed Temperature Drift", 0.2, 3.0, 0.1
        )
        self._attr_icon = "mdi:thermometer-chevron-down"

    @property
    def native_value(self) -> float:
        return self.coordinator.allowed_drift

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator.allowed_drift = float(value)
        new_opts = dict(self.entry.options)
        new_opts["allowed_drift"] = float(value)
        self.hass.config_entries.async_update_entry(self.entry, options=new_opts)
        await self.coordinator.async_request_refresh()


class SmartEnergyPreheatBoostNumber(BaseSmartEnergyNumber):
    """Allowed pre-heat boost temperature above comfort target before price peaks."""

    def __init__(self, coordinator: SmartEnergyCoordinator, entry: ConfigEntry) -> None:
        super().__init__(
            coordinator, entry, "preheat_boost", "Pre-heat Max Boost", 0.0, 3.5, 0.1
        )
        self._attr_icon = "mdi:thermometer-chevron-up"

    @property
    def native_value(self) -> float:
        return self.coordinator.preheat_boost

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator.preheat_boost = float(value)
        new_opts = dict(self.entry.options)
        new_opts["preheat_boost"] = float(value)
        self.hass.config_entries.async_update_entry(self.entry, options=new_opts)
        await self.coordinator.async_request_refresh()
