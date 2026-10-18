"""Sensor platform for Smart Energy & Thermal Optimizer."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
)
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
    """Set up the sensor platform."""
    coordinator: SmartEnergyCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = [
        SmartEnergyScheduleSensor(coordinator, entry),
        SmartEnergyIndoorForecastSensor(coordinator, entry),
        SmartEnergyAllInPriceSensor(coordinator, entry),
        SmartEnergyTauSensor(coordinator, entry),
        SmartEnergyCapacitySensor(coordinator, entry),
        SmartEnergyResistanceSensor(coordinator, entry),
        SmartEnergyCopSensor(coordinator, entry),
        SmartEnergySavingsSensor(coordinator, entry),
        SmartEnergyBigConsumersSensor(coordinator, entry),
        SmartEnergyPeakPowerSensor(coordinator, entry),
        SmartEnergyEffektavgiftSavingsSensor(coordinator, entry),
    ]

    async_add_entities(entities)


class BaseSmartEnergySensor(CoordinatorEntity[SmartEnergyCoordinator], SensorEntity):
    """Base class for smart energy sensors."""

    def __init__(
        self,
        coordinator: SmartEnergyCoordinator,
        entry: ConfigEntry,
        key: str,
        name: str,
    ) -> None:
        """Initialize the base sensor."""
        super().__init__(coordinator)
        self.entry = entry
        self._key = key
        self._attr_name = f"Smart Energy {name}"
        self._attr_unique_id = f"{entry.entry_id}_{key}"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device registry info."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.entry.entry_id)},
            name="Smart Energy & Thermal Optimizer",
            manufacturer="castmo",
            model="MPC Thermal Building Controller",
            sw_version="2.0.1",
        )


class SmartEnergyScheduleSensor(BaseSmartEnergySensor):
    """Sensor reporting current heat pump action and full scheduled horizon."""

    def __init__(self, coordinator: SmartEnergyCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "current_action", "Current Action")
        self._attr_icon = "mdi:heat-pump"

    @property
    def native_value(self) -> str:
        """Return the current action (e.g. boost, eco, normal)."""
        return self.coordinator.data.get("current_action", "normal")

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return the complete 24-48h optimization schedule in attributes."""
        return {
            "schedule": self.coordinator.data.get("schedule", []),
            "mode": self.coordinator.data.get("mode"),
            "recommended_setpoint": self.coordinator.data.get("recommended_setpoint"),
            "recommended_boiler_state": self.coordinator.data.get("recommended_boiler_state"),
        }


class SmartEnergyIndoorForecastSensor(BaseSmartEnergySensor):
    """Sensor reporting projected indoor temperature with timeline attributes."""

    def __init__(self, coordinator: SmartEnergyCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "projected_indoor_temp", "Projected Indoor Temp")
        self._attr_device_class = SensorDeviceClass.TEMPERATURE
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:home-thermometer"

    @property
    def native_value(self) -> Optional[float]:
        """Return projected indoor temperature at end of current hour."""
        schedule = self.coordinator.data.get("schedule", [])
        if schedule:
            return schedule[0].get("predicted_temp")
        return self.coordinator.data.get("current_indoor_temp")

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Attributes for ApexCharts or Lovelace card."""
        schedule = self.coordinator.data.get("schedule", [])
        return {
            "forecast_temps": [
                {"time": item["time"], "temp": item["predicted_temp"], "price": item["price"]}
                for item in schedule
            ],
            "target_comfort_temp": self.coordinator.data.get("target_comfort_temp"),
            "allowed_drift": self.coordinator.data.get("allowed_drift"),
            "preheat_boost": self.coordinator.data.get("preheat_boost"),
        }


class SmartEnergyTauSensor(BaseSmartEnergySensor):
    """Learned building thermal time constant (tau = R * C) in hours."""

    def __init__(self, coordinator: SmartEnergyCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "thermal_time_constant", "Building Thermal Time Constant")
        self._attr_native_unit_of_measurement = UnitOfTime.HOURS
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:timer-sand"

    @property
    def native_value(self) -> Optional[float]:
        return self.coordinator.data.get("building_time_constant_tau")

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        return {
            "samples_learned": self.coordinator.data.get("learning_samples", 0),
            "internal_gains_kw": self.coordinator.data.get("building_internal_gains_kw", 0.0),
        }


class SmartEnergyCapacitySensor(BaseSmartEnergySensor):
    """Learned building thermal capacitance (C_th) in kWh/°C."""

    def __init__(self, coordinator: SmartEnergyCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "thermal_capacity", "Building Thermal Capacity")
        self._attr_native_unit_of_measurement = "kWh/°C"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:shield-home"

    @property
    def native_value(self) -> Optional[float]:
        return self.coordinator.data.get("building_thermal_capacity_cth")


class SmartEnergyResistanceSensor(BaseSmartEnergySensor):
    """Learned building thermal resistance (R_th) in °C/kW."""

    def __init__(self, coordinator: SmartEnergyCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "thermal_resistance", "Building Thermal Resistance")
        self._attr_native_unit_of_measurement = "°C/kW"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:wall"

    @property
    def native_value(self) -> Optional[float]:
        return self.coordinator.data.get("building_thermal_resistance_rth")


class SmartEnergyCopSensor(BaseSmartEnergySensor):
    """Current estimated heat pump Coefficient of Performance (COP)."""

    def __init__(self, coordinator: SmartEnergyCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "heat_pump_cop", "Heat Pump Estimated COP")
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:gauge"

    @property
    def native_value(self) -> Optional[float]:
        return self.coordinator.data.get("current_cop")


class SmartEnergySavingsSensor(BaseSmartEnergySensor):
    """Today's estimated optimization cost savings (%)."""

    def __init__(self, coordinator: SmartEnergyCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "savings_today", "Estimated Savings Today")
        self._attr_native_unit_of_measurement = PERCENTAGE
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:piggy-bank-outline"

    @property
    def native_value(self) -> Optional[float]:
        return self.coordinator.data.get("savings_percent", 0.0)

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        return {
            "savings_currency": self.coordinator.data.get("savings_currency", 0.0),
            "total_optimized_cost": self.coordinator.data.get("total_optimized_cost", 0.0),
            "total_baseline_cost": self.coordinator.data.get("total_baseline_cost", 0.0),
        }


class SmartEnergyBigConsumersSensor(BaseSmartEnergySensor):
    """Total active power of all monitored big consumers."""

    def __init__(self, coordinator: SmartEnergyCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "big_consumers_power", "Big Consumers Total Power")
        self._attr_device_class = SensorDeviceClass.POWER
        self._attr_native_unit_of_measurement = UnitOfPower.KILO_WATT
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:lightning-bolt"

    @property
    def native_value(self) -> float:
        consumers = self.coordinator.data.get("big_consumers", [])
        total_kw = sum(c.get("power_kw", 0.0) for c in consumers)
        return round(total_kw, 2)

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        return {
            "consumers": self.coordinator.data.get("big_consumers", []),
        }


class SmartEnergyAllInPriceSensor(BaseSmartEnergySensor):
    """Sensor reporting the total all-in electricity price (spot + Göteborg Energi grid fee + energy tax + VAT)."""

    def __init__(self, coordinator: SmartEnergyCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "all_in_electricity_price", "Total Electricity Price")
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:cash-multiple"
        curr = coordinator.tariff_calculator.currency
        self._attr_native_unit_of_measurement = f"{curr}/kWh"

    @property
    def native_value(self) -> Optional[float]:
        schedule = self.coordinator.data.get("schedule", [])
        if schedule:
            return schedule[0].get("price")
        return None

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        schedule = self.coordinator.data.get("schedule", [])
        first = schedule[0] if schedule else {}
        return {
            "spot_price": first.get("spot_price"),
            "grid_transmission_fee": first.get("grid_fee"),
            "energy_tax": first.get("energy_tax"),
            "is_high_load": first.get("is_high_load", False),
            "tariff_profile": self.coordinator.tariff_calculator.tariff_type,
            "vat_percent": self.coordinator.tariff_calculator.vat_percent,
        }


class SmartEnergyPeakPowerSensor(BaseSmartEnergySensor):
    """Sensor reporting the projected peak hourly demand (kW) over the optimization horizon."""

    def __init__(self, coordinator: SmartEnergyCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "projected_peak_power", "Projected Peak Power")
        self._attr_device_class = SensorDeviceClass.POWER
        self._attr_native_unit_of_measurement = UnitOfPower.KILO_WATT
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:gauge-full"

    @property
    def native_value(self) -> Optional[float]:
        return self.coordinator.data.get("predicted_peak_power_kw")

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        return {
            "peak_limit_kw": self.coordinator.data.get("peak_limit_kw"),
            "peak_shaving_active": self.coordinator.data.get("peak_shaving_active", False),
        }


class SmartEnergyEffektavgiftSavingsSensor(BaseSmartEnergySensor):
    """Sensor reporting estimated monthly savings from effekttariff / peak shaving."""

    def __init__(self, coordinator: SmartEnergyCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "effektavgift_savings", "Effekttariff Monthly Savings")
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:cash-check"
        curr = coordinator.tariff_calculator.currency
        self._attr_native_unit_of_measurement = f"{curr}/month"

    @property
    def native_value(self) -> Optional[float]:
        return self.coordinator.data.get("effektavgift_monthly_savings", 0.0)

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        return {
            "peak_limit_kw": self.coordinator.data.get("peak_limit_kw"),
            "effektavgift_price_per_kw": self.coordinator.optimizer.effektavgift_price_per_kw,
        }


