"""The Energy Disaggregator & Power Signature Monitor Integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import (
    DOMAIN,
    SERVICE_CONFIRM_EVENT,
    SERVICE_MARK_UNKNOWN,
    SERVICE_RESET_LEARNING,
    SERVICE_TEACH_CONSUMER,
)
from .coordinator import EnergyDisaggregatorCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SELECT,
    Platform.BUTTON,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Energy Disaggregator component."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Energy Disaggregator from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    coordinator = EnergyDisaggregatorCoordinator(hass, entry)
    await coordinator.async_init()

    # Initial data refresh
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Forward setup to entity platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Listen for options updates
    entry.async_on_unload(entry.add_update_listener(async_update_options))

    # Register Integration Services
    async def handle_confirm_event(call: ServiceCall) -> None:
        """Confirm a detected event with chosen consumer."""
        event_id = call.data.get("event_id")
        consumer = call.data.get("consumer")
        _LOGGER.info("Service confirm_event called: %s -> %s", event_id, consumer)
        await coordinator.async_confirm_proposal(event_id=event_id, consumer_id=consumer)

    async def handle_mark_unknown(call: ServiceCall) -> None:
        """Mark an event as unknown/ignore."""
        event_id = call.data.get("event_id")
        _LOGGER.info("Service mark_unknown called: %s", event_id)
        await coordinator.async_mark_unknown(event_id=event_id)

    async def handle_teach_consumer(call: ServiceCall) -> None:
        """Manually calibrate or teach an appliance power signature."""
        consumer_id = call.data.get("consumer_id")
        power = float(call.data.get("power", 2000.0))
        phase_type = call.data.get("phase_type", "any")
        p1 = float(call.data.get("power_l1", 0.0))
        p2 = float(call.data.get("power_l2", 0.0))
        p3 = float(call.data.get("power_l3", 0.0))
        await coordinator.async_teach_consumer(
            consumer_id=consumer_id,
            nominal_power=power,
            phase_type=phase_type,
            nominal_l1=p1,
            nominal_l2=p2,
            nominal_l3=p3,
        )

    async def handle_reset_learning(call: ServiceCall) -> None:
        """Reset learned signatures back to defaults."""
        _LOGGER.info("Service reset_learning called")
        await coordinator.async_reset_learning()

    if not hass.services.has(DOMAIN, SERVICE_CONFIRM_EVENT):
        hass.services.async_register(
            DOMAIN,
            SERVICE_CONFIRM_EVENT,
            handle_confirm_event,
        )

    if not hass.services.has(DOMAIN, SERVICE_MARK_UNKNOWN):
        hass.services.async_register(
            DOMAIN,
            SERVICE_MARK_UNKNOWN,
            handle_mark_unknown,
        )

    if not hass.services.has(DOMAIN, SERVICE_TEACH_CONSUMER):
        hass.services.async_register(
            DOMAIN,
            SERVICE_TEACH_CONSUMER,
            handle_teach_consumer,
        )

    if not hass.services.has(DOMAIN, SERVICE_RESET_LEARNING):
        hass.services.async_register(
            DOMAIN,
            SERVICE_RESET_LEARNING,
            handle_reset_learning,
        )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: EnergyDisaggregatorCoordinator = hass.data[DOMAIN].pop(
            entry.entry_id
        )
        await coordinator.async_unload()

    return unload_ok


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload integration when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
