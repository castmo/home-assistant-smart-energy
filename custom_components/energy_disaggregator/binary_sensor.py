"""Binary sensor platform for Energy Disaggregator."""

from __future__ import annotations

from typing import Any, Dict

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import EnergyDisaggregatorCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up binary sensors."""
    coordinator: EnergyDisaggregatorCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[BinarySensorEntity] = []

    # Active running state for each consumer
    for cid, consumer in coordinator.engine.consumers.items():
        entities.append(ConsumerActiveBinarySensor(coordinator, entry, cid))

    # Global notification/confirmation pending binary sensor
    entities.append(AwaitingConfirmationBinarySensor(coordinator, entry))

    async_add_entities(entities)


class ConsumerActiveBinarySensor(
    CoordinatorEntity[EnergyDisaggregatorCoordinator], BinarySensorEntity
):
    """Indicates whether an identified consumer is currently drawing power."""

    _attr_device_class = BinarySensorDeviceClass.RUNNING

    def __init__(
        self,
        coordinator: EnergyDisaggregatorCoordinator,
        entry: ConfigEntry,
        consumer_id: str,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self.entry = entry
        self.consumer_id = consumer_id
        consumer = coordinator.engine.consumers[consumer_id]
        self._attr_name = f"{consumer.name} Active"
        self._attr_unique_id = f"{entry.entry_id}_{consumer_id}_active"
        self._attr_icon = consumer.icon

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.entry.entry_id)},
            name="Energy Disaggregator & Power Monitor",
            manufacturer="Home Assistant Community",
            model="NILM Active Learning Disaggregator",
            sw_version="1.0.0",
        )

    @property
    def is_on(self) -> bool:
        """Return True if consumer is active."""
        consumer = self.coordinator.engine.consumers.get(self.consumer_id)
        return consumer.is_active if consumer else False

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return running duration and current power."""
        consumer = self.coordinator.engine.consumers.get(self.consumer_id)
        if not consumer:
            return {}
        return {
            "current_power_watts": consumer.current_power,
            "session_start_time": consumer.session_start_time,
            "session_energy_kwh": round(consumer.session_energy_kwh, 3),
        }


class AwaitingConfirmationBinarySensor(
    CoordinatorEntity[EnergyDisaggregatorCoordinator], BinarySensorEntity
):
    """Indicates whether the integration is currently waiting for user confirmation."""

    def __init__(
        self, coordinator: EnergyDisaggregatorCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self.entry = entry
        self._attr_name = "Awaiting Confirmation"
        self._attr_unique_id = f"{entry.entry_id}_awaiting_confirmation"
        self._attr_icon = "mdi:bell-alert"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.entry.entry_id)},
            name="Energy Disaggregator & Power Monitor",
            manufacturer="Home Assistant Community",
            model="NILM Active Learning Disaggregator",
            sw_version="1.0.0",
        )

    @property
    def is_on(self) -> bool:
        """Return True if pending event is awaiting user confirmation."""
        return self.coordinator.data.get("pending_event") is not None
