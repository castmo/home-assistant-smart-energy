"""The Smart Energy & Thermal Optimizer Integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN
from .coordinator import SmartEnergyCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.CLIMATE,
    Platform.SELECT,
    Platform.NUMBER,
    Platform.SWITCH,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Smart Energy & Thermal Optimizer from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    coordinator = SmartEnergyCoordinator(hass, entry)
    await coordinator.async_init()

    # Initial data refresh
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Forward setup to all entity platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Listen for options updates
    entry.async_on_unload(entry.add_update_listener(async_update_options))

    # Register Integration Services
    async def handle_recalculate_plan(call: ServiceCall) -> None:
        """Force immediate recalculation of optimization schedule."""
        _LOGGER.info("Service called: recalculate_plan")
        await coordinator.async_request_refresh()

    async def handle_reset_learning_model(call: ServiceCall) -> None:
        """Reset thermal model parameters back to default priors."""
        _LOGGER.info("Service called: reset_learning_model")
        from .thermal_model import BuildingThermalModel
        coordinator.thermal_model = BuildingThermalModel()
        coordinator.optimizer.thermal_model = coordinator.thermal_model
        await coordinator.async_save_model()
        await coordinator.async_request_refresh()

    hass.services.async_register(
        DOMAIN, "recalculate_plan", handle_recalculate_plan
    )
    hass.services.async_register(
        DOMAIN, "reset_learning_model", handle_reset_learning_model
    )

    return True


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    coordinator: SmartEnergyCoordinator = hass.data[DOMAIN][entry.entry_id]
    coordinator.mode = entry.options.get("mode", coordinator.mode)
    coordinator.target_comfort_temp = float(
        entry.options.get("target_comfort_temp", coordinator.target_comfort_temp)
    )
    coordinator.allowed_drift = float(
        entry.options.get("allowed_drift", coordinator.allowed_drift)
    )
    coordinator.preheat_boost = float(
        entry.options.get("preheat_boost", coordinator.preheat_boost)
    )
    coordinator.master_enabled = entry.options.get(
        "master_enabled", coordinator.master_enabled
    )
    coordinator.boiler_control_enabled = entry.options.get(
        "boiler_control_enabled", coordinator.boiler_control_enabled
    )
    coordinator.learning_enabled = entry.options.get(
        "learning_enabled", coordinator.learning_enabled
    )

    # Reload tariff calculator preferences if changed
    from .const import (
        CONF_ENERGY_TAX,
        CONF_GRID_FEE_HIGH_LOAD,
        CONF_GRID_FEE_LOW_LOAD,
        CONF_PRICE_CURRENCY,
        CONF_SPOT_PRICE_INCLUDES_VAT,
        CONF_SURCHARGE,
        CONF_TARIFF_TYPE,
        CONF_VAT_PERCENT,
    )
    from .price_calculator import ElectricityTariffCalculator, TARIFF_GOTEBORG_TIDSTARIFF

    coordinator.tariff_calculator = ElectricityTariffCalculator(
        tariff_type=entry.options.get(
            CONF_TARIFF_TYPE, entry.data.get(CONF_TARIFF_TYPE, TARIFF_GOTEBORG_TIDSTARIFF)
        ),
        surcharge=float(entry.options.get(CONF_SURCHARGE, entry.data.get(CONF_SURCHARGE, 0.05))),
        energy_tax=float(entry.options.get(CONF_ENERGY_TAX, entry.data.get(CONF_ENERGY_TAX, 0.445))),
        grid_fee_high_load=float(
            entry.options.get(CONF_GRID_FEE_HIGH_LOAD, entry.data.get(CONF_GRID_FEE_HIGH_LOAD, 0.38))
        ),
        grid_fee_low_load=float(
            entry.options.get(CONF_GRID_FEE_LOW_LOAD, entry.data.get(CONF_GRID_FEE_LOW_LOAD, 0.16))
        ),
        vat_percent=float(entry.options.get(CONF_VAT_PERCENT, entry.data.get(CONF_VAT_PERCENT, 25.0))),
        spot_price_includes_vat=entry.options.get(
            CONF_SPOT_PRICE_INCLUDES_VAT, entry.data.get(CONF_SPOT_PRICE_INCLUDES_VAT, False)
        ),
        currency=entry.data.get(CONF_PRICE_CURRENCY, "SEK"),
    )

    await coordinator.async_request_refresh()


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    coordinator: SmartEnergyCoordinator = hass.data[DOMAIN].get(entry.entry_id)
    if coordinator:
        await coordinator.async_save_model()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
