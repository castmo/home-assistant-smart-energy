"""Config flow for Energy Disaggregator & Power Signature Monitor."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_AUTO_CONFIRM_THRESHOLD,
    CONF_AUTO_LEARN,
    CONF_ENABLE_NOTIFICATIONS,
    CONF_MIN_STEP_WATTS,
    CONF_NOTIFY_SERVICE,
    CONF_PHASE_L1_SENSOR,
    CONF_PHASE_L2_SENSOR,
    CONF_PHASE_L3_SENSOR,
    CONF_TOTAL_POWER_SENSOR,
    DEFAULT_AUTO_CONFIRM_THRESHOLD,
    DEFAULT_AUTO_LEARN,
    DEFAULT_ENABLE_NOTIFICATIONS,
    DEFAULT_MIN_STEP_WATTS,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class EnergyDisaggregatorConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Energy Disaggregator."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize config flow."""
        self._data: Dict[str, Any] = {}

    async def async_step_user(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """Step 1: Configure HomeWizard 3-Phase Sensors & Notifications."""
        errors: Dict[str, str] = {}

        if user_input is not None:
            self._data.update(user_input)
            return self.async_create_entry(
                title="HomeWizard Energy Disaggregator",
                data=self._data,
                options={
                    CONF_MIN_STEP_WATTS: user_input.get(
                        CONF_MIN_STEP_WATTS, DEFAULT_MIN_STEP_WATTS
                    ),
                    CONF_ENABLE_NOTIFICATIONS: user_input.get(
                        CONF_ENABLE_NOTIFICATIONS, DEFAULT_ENABLE_NOTIFICATIONS
                    ),
                    CONF_AUTO_CONFIRM_THRESHOLD: user_input.get(
                        CONF_AUTO_CONFIRM_THRESHOLD, DEFAULT_AUTO_CONFIRM_THRESHOLD
                    ),
                    CONF_NOTIFY_SERVICE: user_input.get(
                        CONF_NOTIFY_SERVICE, "notify.notify"
                    ),
                },
            )

        # Smart Auto-Detection of HomeWizard P1 meter entities
        default_l1 = None
        default_l2 = None
        default_l3 = None
        default_tot = None
        default_notify = "notify.notify"

        try:
            states = self.hass.states.async_all()
            for s in states:
                eid = s.entity_id.lower()
                if "power" in eid or "active_power" in eid:
                    if "l1" in eid or "phase_1" in eid:
                        default_l1 = default_l1 or s.entity_id
                    elif "l2" in eid or "phase_2" in eid:
                        default_l2 = default_l2 or s.entity_id
                    elif "l3" in eid or "phase_3" in eid:
                        default_l3 = default_l3 or s.entity_id
                    elif (
                        "total" in eid
                        or eid.endswith("active_power")
                        or "p1_meter_active_power" in eid
                    ):
                        default_tot = default_tot or s.entity_id
        except Exception:
            pass

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_PHASE_L1_SENSOR,
                    default=default_l1 or vol.UNDEFINED,
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Required(
                    CONF_PHASE_L2_SENSOR,
                    default=default_l2 or vol.UNDEFINED,
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Required(
                    CONF_PHASE_L3_SENSOR,
                    default=default_l3 or vol.UNDEFINED,
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional(
                    CONF_TOTAL_POWER_SENSOR,
                    description={"suggested_value": default_tot},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional(
                    CONF_NOTIFY_SERVICE,
                    default=default_notify,
                ): selector.TextSelector(selector.TextSelectorConfig()),
                vol.Optional(
                    CONF_MIN_STEP_WATTS,
                    default=DEFAULT_MIN_STEP_WATTS,
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=150,
                        max=3000,
                        step=50,
                        unit_of_measurement="W",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Optional(
                    CONF_ENABLE_NOTIFICATIONS,
                    default=DEFAULT_ENABLE_NOTIFICATIONS,
                ): selector.BooleanSelector(),
                vol.Optional(
                    CONF_AUTO_CONFIRM_THRESHOLD,
                    default=DEFAULT_AUTO_CONFIRM_THRESHOLD,
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0,
                        max=20,
                        step=1,
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Get the options flow for this handler."""
        return EnergyDisaggregatorOptionsFlowHandler(config_entry)


class EnergyDisaggregatorOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options for Energy Disaggregator."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """Manage configuration options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_min_step = self.config_entry.options.get(
            CONF_MIN_STEP_WATTS,
            self.config_entry.data.get(CONF_MIN_STEP_WATTS, DEFAULT_MIN_STEP_WATTS),
        )
        current_notify = self.config_entry.options.get(
            CONF_NOTIFY_SERVICE,
            self.config_entry.data.get(CONF_NOTIFY_SERVICE, "notify.notify"),
        )
        current_enable_notify = self.config_entry.options.get(
            CONF_ENABLE_NOTIFICATIONS,
            self.config_entry.data.get(CONF_ENABLE_NOTIFICATIONS, DEFAULT_ENABLE_NOTIFICATIONS),
        )
        current_auto_confirm = self.config_entry.options.get(
            CONF_AUTO_CONFIRM_THRESHOLD,
            self.config_entry.data.get(CONF_AUTO_CONFIRM_THRESHOLD, DEFAULT_AUTO_CONFIRM_THRESHOLD),
        )

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_MIN_STEP_WATTS,
                    default=current_min_step,
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=150,
                        max=3000,
                        step=50,
                        unit_of_measurement="W",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Optional(
                    CONF_ENABLE_NOTIFICATIONS,
                    default=current_enable_notify,
                ): selector.BooleanSelector(),
                vol.Optional(
                    CONF_NOTIFY_SERVICE,
                    default=current_notify,
                ): selector.TextSelector(selector.TextSelectorConfig()),
                vol.Optional(
                    CONF_AUTO_CONFIRM_THRESHOLD,
                    default=current_auto_confirm,
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0,
                        max=20,
                        step=1,
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
