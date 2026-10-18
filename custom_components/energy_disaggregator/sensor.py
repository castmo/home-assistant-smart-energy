"""Sensor platform for Energy Disaggregator."""

from __future__ import annotations

from typing import Any, Dict, Optional

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy, UnitOfPower
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
    """Set up Energy Disaggregator sensor entities."""
    coordinator: EnergyDisaggregatorCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[SensorEntity] = []

    # 1. Per-consumer Power & Energy sensors
    for cid, consumer in coordinator.engine.consumers.items():
        entities.append(ConsumerPowerSensor(coordinator, entry, cid))
        entities.append(ConsumerEnergySensor(coordinator, entry, cid))

    # 2. System aggregate & monitoring sensors
    entities.extend(
        [
            TotalDisaggregatedPowerSensor(coordinator, entry),
            UnassignedPowerSensor(coordinator, entry),
            TotalDisaggregatedEnergySensor(coordinator, entry),
            PendingEventSensor(coordinator, entry),
        ]
    )

    async_add_entities(entities)


class BaseDisaggregatorSensor(CoordinatorEntity[EnergyDisaggregatorCoordinator], SensorEntity):
    """Base sensor entity for Energy Disaggregator."""

    def __init__(
        self,
        coordinator: EnergyDisaggregatorCoordinator,
        entry: ConfigEntry,
        key: str,
        name: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entry = entry
        self._key = key
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}_{key}"

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


class ConsumerPowerSensor(BaseDisaggregatorSensor):
    """Measures real-time power (W) consumed by an identified consumer."""

    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT

    def __init__(
        self,
        coordinator: EnergyDisaggregatorCoordinator,
        entry: ConfigEntry,
        consumer_id: str,
    ) -> None:
        """Initialize consumer power sensor."""
        consumer = coordinator.engine.consumers[consumer_id]
        super().__init__(
            coordinator,
            entry,
            f"{consumer_id}_power",
            f"{consumer.name} Power",
        )
        self.consumer_id = consumer_id
        self._attr_icon = consumer.icon

    @property
    def native_value(self) -> Optional[float]:
        """Return current power consumption."""
        consumer = self.coordinator.engine.consumers.get(self.consumer_id)
        if consumer:
            return round(consumer.current_power, 1)
        return 0.0

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return diagnostic consumer attributes."""
        consumer = self.coordinator.engine.consumers.get(self.consumer_id)
        if not consumer:
            return {}
        return {
            "is_active": consumer.is_active,
            "learned_mean_watts": round(consumer.mean_total, 1),
            "learned_l1_watts": round(consumer.mean_l1, 1),
            "learned_l2_watts": round(consumer.mean_l2, 1),
            "learned_l3_watts": round(consumer.mean_l3, 1),
            "phase_type": consumer.phase_type,
            "active_phase": consumer.active_phase,
            "confirmations_count": consumer.confirmations,
            "current_l1": round(consumer.current_l1, 1),
            "current_l2": round(consumer.current_l2, 1),
            "current_l3": round(consumer.current_l3, 1),
        }


class ConsumerEnergySensor(BaseDisaggregatorSensor):
    """Measures cumulative energy (kWh) consumed by an identified consumer."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR

    def __init__(
        self,
        coordinator: EnergyDisaggregatorCoordinator,
        entry: ConfigEntry,
        consumer_id: str,
    ) -> None:
        """Initialize consumer energy sensor."""
        consumer = coordinator.engine.consumers[consumer_id]
        super().__init__(
            coordinator,
            entry,
            f"{consumer_id}_energy",
            f"{consumer.name} Energy",
        )
        self.consumer_id = consumer_id
        self._attr_icon = consumer.icon

    @property
    def native_value(self) -> Optional[float]:
        """Return cumulative lifetime energy in kWh."""
        consumer = self.coordinator.engine.consumers.get(self.consumer_id)
        if consumer:
            return round(consumer.lifetime_energy_kwh, 3)
        return 0.0

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return session energy and timestamps."""
        consumer = self.coordinator.engine.consumers.get(self.consumer_id)
        if not consumer:
            return {}
        return {
            "session_energy_kwh": round(consumer.session_energy_kwh, 3),
            "last_turned_on": consumer.last_turned_on,
            "last_turned_off": consumer.last_turned_off,
        }


class TotalDisaggregatedPowerSensor(BaseDisaggregatorSensor):
    """Total power of all currently identified running consumers."""

    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_icon = "mdi:lightning-bolt"

    def __init__(
        self, coordinator: EnergyDisaggregatorCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize."""
        super().__init__(
            coordinator,
            entry,
            "total_disaggregated_power",
            "Total Disaggregated Power",
        )

    @property
    def native_value(self) -> Optional[float]:
        """Return total active disaggregated power."""
        return self.coordinator.data.get("total_disaggregated_power", 0.0)


class UnassignedPowerSensor(BaseDisaggregatorSensor):
    """Grid power not yet assigned to any recognized large consumer."""

    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_icon = "mdi:help-rhombus-outline"

    def __init__(
        self, coordinator: EnergyDisaggregatorCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize."""
        super().__init__(
            coordinator,
            entry,
            "unassigned_power",
            "Unassigned Grid Power",
        )

    @property
    def native_value(self) -> Optional[float]:
        """Return unassigned power in Watts."""
        return self.coordinator.data.get("unassigned_power", 0.0)


class TotalDisaggregatedEnergySensor(BaseDisaggregatorSensor):
    """Total cumulative energy of all tracked consumers."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_icon = "mdi:chart-bell-curve-cumulative"

    def __init__(
        self, coordinator: EnergyDisaggregatorCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize."""
        super().__init__(
            coordinator,
            entry,
            "total_disaggregated_energy",
            "Total Disaggregated Energy",
        )

    @property
    def native_value(self) -> Optional[float]:
        """Return total disaggregated cumulative energy."""
        return self.coordinator.data.get("total_disaggregated_energy", 0.0)


class PendingEventSensor(BaseDisaggregatorSensor):
    """Displays latest detected load change event and proposal."""

    _attr_icon = "mdi:radar"

    def __init__(
        self, coordinator: EnergyDisaggregatorCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize."""
        super().__init__(
            coordinator,
            entry,
            "pending_event",
            "Last Detected Load Event",
        )

    @property
    def native_value(self) -> str:
        """Return proposed consumer or Idle."""
        pending = self.coordinator.data.get("pending_event")
        if pending:
            cid = pending.get("proposed_consumer", "unknown")
            consumer = self.coordinator.engine.consumers.get(cid)
            name = consumer.name if consumer else cid.title()
            conf = pending.get("confidence", 0.0)
            return f"{name} ({conf:.0f}%)"
        return "Idle"

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return full details of the pending event."""
        pending = self.coordinator.data.get("pending_event")
        if not pending:
            return {"status": "idle"}
        return pending
