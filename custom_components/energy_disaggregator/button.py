"""Button platform for Energy Disaggregator."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
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
    """Set up the button platform."""
    coordinator: EnergyDisaggregatorCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        [
            ConfirmProposalButton(coordinator, entry),
            MarkUnknownButton(coordinator, entry),
            ResetLearningButton(coordinator, entry),
        ]
    )


class BaseDisaggregatorButton(
    CoordinatorEntity[EnergyDisaggregatorCoordinator], ButtonEntity
):
    """Base button entity for Energy Disaggregator."""

    def __init__(
        self,
        coordinator: EnergyDisaggregatorCoordinator,
        entry: ConfigEntry,
        key: str,
        name: str,
        icon: str,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self.entry = entry
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_icon = icon

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


class ConfirmProposalButton(BaseDisaggregatorButton):
    """Button to confirm the currently proposed/selected consumer."""

    def __init__(
        self, coordinator: EnergyDisaggregatorCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize."""
        super().__init__(
            coordinator,
            entry,
            "confirm_proposal",
            "Confirm Consumer Assignment",
            "mdi:check-circle-outline",
        )

    async def async_press(self) -> None:
        """Handle button press."""
        await self.coordinator.async_confirm_proposal()


class MarkUnknownButton(BaseDisaggregatorButton):
    """Button to mark the pending event as Unknown/Ignore."""

    def __init__(
        self, coordinator: EnergyDisaggregatorCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize."""
        super().__init__(
            coordinator,
            entry,
            "mark_unknown",
            "Mark as Unknown / Ignore",
            "mdi:close-circle-outline",
        )

    async def async_press(self) -> None:
        """Handle button press."""
        await self.coordinator.async_mark_unknown()


class ResetLearningButton(BaseDisaggregatorButton):
    """Button to reset all learned appliance signatures back to factory defaults."""

    def __init__(
        self, coordinator: EnergyDisaggregatorCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize."""
        super().__init__(
            coordinator,
            entry,
            "reset_learning",
            "Reset Learning & Profiles",
            "mdi:restart",
        )

    async def async_press(self) -> None:
        """Handle button press."""
        await self.coordinator.async_reset_learning()
