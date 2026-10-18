"""Select platform for Energy Disaggregator."""

from __future__ import annotations

from typing import Any, Dict, List

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONSUMER_UNKNOWN, DOMAIN
from .coordinator import EnergyDisaggregatorCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the select platform."""
    coordinator: EnergyDisaggregatorCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities([PendingConsumerSelect(coordinator, entry)])


class PendingConsumerSelect(
    CoordinatorEntity[EnergyDisaggregatorCoordinator], SelectEntity
):
    """Dropdown allowing user to confirm or change the proposed consumer."""

    def __init__(
        self, coordinator: EnergyDisaggregatorCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self.entry = entry
        self._attr_name = "Assigned Consumer"
        self._attr_unique_id = f"{entry.entry_id}_pending_consumer_select"
        self._attr_icon = "mdi:format-list-bulleted"

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
    def options(self) -> List[str]:
        """Return list of selectable consumer names + Unknown."""
        opts: List[str] = [
            c.name for c in self.coordinator.engine.consumers.values()
        ]
        opts.append("Unknown / Ignore")
        return opts

    @property
    def current_option(self) -> str:
        """Return currently selected consumer in the UI."""
        sel_id = self.coordinator.selected_pending_consumer
        if sel_id == CONSUMER_UNKNOWN or not sel_id:
            return "Unknown / Ignore"

        consumer = self.coordinator.engine.consumers.get(sel_id)
        return consumer.name if consumer else sel_id.title()

    async def async_select_option(self, option: str) -> None:
        """Change selected consumer."""
        if option == "Unknown / Ignore":
            self.coordinator.set_selected_pending_consumer(CONSUMER_UNKNOWN)
            return

        for cid, consumer in self.coordinator.engine.consumers.items():
            if consumer.name == option:
                self.coordinator.set_selected_pending_consumer(cid)
                return

        self.coordinator.set_selected_pending_consumer(option.lower())
