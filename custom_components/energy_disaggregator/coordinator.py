"""DataUpdateCoordinator for Energy Disaggregator and NILM Monitor."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
import time
from typing import Any, Dict, List, Optional

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    ACTION_CHANGE_PREFIX,
    ACTION_CONFIRM_PREFIX,
    ACTION_UNKNOWN_PREFIX,
    CONF_AUTO_CONFIRM_THRESHOLD,
    CONF_AUTO_LEARN,
    CONF_ENABLE_NOTIFICATIONS,
    CONF_MIN_STEP_WATTS,
    CONF_NOTIFY_SERVICE,
    CONF_PHASE_L1_SENSOR,
    CONF_PHASE_L2_SENSOR,
    CONF_PHASE_L3_SENSOR,
    CONF_TOTAL_POWER_SENSOR,
    CONSUMER_UNKNOWN,
    DEFAULT_AUTO_CONFIRM_THRESHOLD,
    DEFAULT_AUTO_LEARN,
    DEFAULT_ENABLE_NOTIFICATIONS,
    DEFAULT_MIN_STEP_WATTS,
    DEFAULT_STORAGE_KEY,
    DEFAULT_STORAGE_VERSION,
    DOMAIN,
    EVENT_CONSUMER_CONFIRMED,
    EVENT_POWER_STEP_DETECTED,
)
from .engine import DisaggregationEngine, PendingEvent

_LOGGER = logging.getLogger(__name__)


class EnergyDisaggregatorCoordinator(DataUpdateCoordinator[Dict[str, Any]]):
    """Coordinates reading 3-phase HomeWizard data, step detection, and active learning."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"Energy Disaggregator ({entry.title})",
            update_interval=timedelta(seconds=2),
        )
        self.entry = entry

        # Configuration options
        min_step = entry.options.get(
            CONF_MIN_STEP_WATTS,
            entry.data.get(CONF_MIN_STEP_WATTS, DEFAULT_MIN_STEP_WATTS),
        )
        auto_thresh = entry.options.get(
            CONF_AUTO_CONFIRM_THRESHOLD,
            entry.data.get(CONF_AUTO_CONFIRM_THRESHOLD, DEFAULT_AUTO_CONFIRM_THRESHOLD),
        )

        self.engine = DisaggregationEngine(
            min_step_watts=min_step,
            auto_confirm_threshold=auto_thresh,
        )

        self._store = Store(
            hass,
            DEFAULT_STORAGE_VERSION,
            f"{DEFAULT_STORAGE_KEY}_{entry.entry_id}",
        )

        # Real-time state
        self.current_p1: float = 0.0
        self.current_p2: float = 0.0
        self.current_p3: float = 0.0
        self.current_total_power: float = 0.0

        # UI state for pending confirmation
        self.selected_pending_consumer: str = CONSUMER_UNKNOWN

        # Tracked listeners
        self._unsub_state_change: Optional[callback] = None
        self._unsub_interval: Optional[callback] = None
        self._unsub_notification_action: Optional[callback] = None

    async def async_init(self) -> None:
        """Restore learned profiles from storage and set up listeners."""
        await self._async_load_storage()

        # Listen to 3-phase HomeWizard power sensor changes
        sensor_l1 = self.entry.data.get(CONF_PHASE_L1_SENSOR)
        sensor_l2 = self.entry.data.get(CONF_PHASE_L2_SENSOR)
        sensor_l3 = self.entry.data.get(CONF_PHASE_L3_SENSOR)
        sensor_tot = self.entry.data.get(CONF_TOTAL_POWER_SENSOR)

        monitored_sensors = [s for s in [sensor_l1, sensor_l2, sensor_l3, sensor_tot] if s]
        if monitored_sensors:
            self._unsub_state_change = async_track_state_change_event(
                self.hass,
                monitored_sensors,
                self._async_handle_sensor_change,
            )

        # Periodic timer (1 sec) for continuous energy integration & smooth reporting
        self._unsub_interval = async_track_time_interval(
            self.hass,
            self._async_tick,
            timedelta(seconds=1),
        )

        # Listen for Mobile App Actionable Notification actions
        self._unsub_notification_action = self.hass.bus.async_listen(
            "mobile_app_notification_action",
            self._async_handle_notification_action,
        )

        # Read initial states
        self._read_current_sensor_states()

    async def _async_load_storage(self) -> None:
        """Load persistent learned knowledge and cumulative energy."""
        try:
            data = await self._store.async_load()
            if data and isinstance(data, dict):
                self.engine.from_dict(data)
                _LOGGER.info(
                    "Restored %d consumer profiles from persistent storage",
                    len(self.engine.consumers),
                )
        except Exception as err:
            _LOGGER.error("Failed to load disaggregator storage: %s", err)

    async def async_save_storage(self) -> None:
        """Save persistent learned knowledge and cumulative energy."""
        try:
            data = self.engine.to_dict()
            await self._store.async_save(data)
        except Exception as err:
            _LOGGER.error("Failed to save disaggregator storage: %s", err)

    def _read_current_sensor_states(self) -> None:
        """Read sensor values directly from Home Assistant state machine."""
        s1 = self._parse_float_state(self.entry.data.get(CONF_PHASE_L1_SENSOR))
        s2 = self._parse_float_state(self.entry.data.get(CONF_PHASE_L2_SENSOR))
        s3 = self._parse_float_state(self.entry.data.get(CONF_PHASE_L3_SENSOR))
        tot = self._parse_float_state(self.entry.data.get(CONF_TOTAL_POWER_SENSOR))

        if s1 is not None:
            self.current_p1 = s1
        if s2 is not None:
            self.current_p2 = s2
        if s3 is not None:
            self.current_p3 = s3

        if tot is not None:
            self.current_total_power = tot
        else:
            self.current_total_power = self.current_p1 + self.current_p2 + self.current_p3

    def _parse_float_state(self, entity_id: Optional[str]) -> Optional[float]:
        """Safely extract float value from entity state."""
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return None
        try:
            return float(state.state)
        except (ValueError, TypeError):
            return None

    @callback
    def _async_handle_sensor_change(self, event: Event) -> None:
        """Handle real-time state change from HomeWizard 3-phase sensors."""
        self._read_current_sensor_states()
        self._process_reading()

    @callback
    def _async_tick(self, _now: Any) -> None:
        """Periodic clock tick: integrates Riemann energy and refreshes UI."""
        self._read_current_sensor_states()
        self._process_reading()

    def _process_reading(self) -> None:
        """Feed current 3-phase reading to disaggregation engine."""
        now_ts = time.time()
        pending_event = self.engine.add_reading(
            p1=self.current_p1,
            p2=self.current_p2,
            p3=self.current_p3,
            total=self.current_total_power,
            timestamp=now_ts,
        )

        if pending_event is not None and pending_event.status == "pending":
            # Set UI selector default to the proposed consumer
            self.selected_pending_consumer = pending_event.proposed_consumer

            # Fire HA event
            self.hass.bus.async_fire(
                EVENT_POWER_STEP_DETECTED,
                pending_event.to_dict(),
            )

            # Send Notification to user
            enable_notify = self.entry.options.get(
                CONF_ENABLE_NOTIFICATIONS,
                self.entry.data.get(CONF_ENABLE_NOTIFICATIONS, DEFAULT_ENABLE_NOTIFICATIONS),
            )
            if enable_notify:
                self.hass.async_create_task(
                    self._async_send_learning_notification(pending_event)
                )

        # Notify entity platforms of new state
        self.async_set_updated_data(self._build_coordinator_data())

    async def _async_send_learning_notification(self, pending: PendingEvent) -> None:
        """Send mobile actionable notification and persistent notification."""
        event_id = pending.event_id
        proposed_cid = pending.proposed_consumer
        consumer = self.engine.consumers.get(proposed_cid)
        proposed_name = consumer.name if consumer else proposed_cid.title()

        edge = pending.edge
        p1, p2, p3 = edge.delta_l1, edge.delta_l2, edge.delta_l3
        total_w = edge.delta_total

        title = f"⚡ New Load Detected (+{total_w:.0f} W)"
        msg = (
            f"Power step detected across phases (L1: {p1:+.0f}W, L2: {p2:+.0f}W, L3: {p3:+.0f}W).\n\n"
            f"Most likely: **{proposed_name}** ({pending.confidence:.0f}% confidence).\n"
            f"Confirm below or pick another appliance in Home Assistant."
        )

        # 1. Create Persistent Notification in Home Assistant
        await self.hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "notification_id": f"energy_disagg_{event_id}",
                "title": title,
                "message": msg,
            },
        )

        # 2. Send Mobile App Actionable Notification
        notify_service = self.entry.options.get(
            CONF_NOTIFY_SERVICE,
            self.entry.data.get(CONF_NOTIFY_SERVICE, "notify.notify"),
        )

        if notify_service and "." in notify_service:
            domain, service_name = notify_service.split(".", 1)
            actions = [
                {
                    "action": f"{ACTION_CONFIRM_PREFIX}{event_id}",
                    "title": f"✅ Confirm: {proposed_name}",
                },
                {
                    "action": f"{ACTION_UNKNOWN_PREFIX}{event_id}",
                    "title": "❓ Unknown / Ignore",
                },
                {
                    "action": f"{ACTION_CHANGE_PREFIX}{event_id}",
                    "title": "✏️ Change Device",
                },
            ]

            try:
                await self.hass.services.async_call(
                    domain,
                    service_name,
                    {
                        "title": title,
                        "message": f"Is this the {proposed_name}? (+{total_w:.0f} W detected)",
                        "data": {
                            "tag": f"energy_disagg_{event_id}",
                            "actions": actions,
                        },
                    },
                )
            except Exception as err:
                _LOGGER.debug("Could not dispatch mobile app notification via %s: %s", notify_service, err)

    @callback
    def _async_handle_notification_action(self, event: Event) -> None:
        """Handle actionable notification button clicks from user's phone."""
        action = event.data.get("action", "")

        if action.startswith(ACTION_CONFIRM_PREFIX):
            event_id = action[len(ACTION_CONFIRM_PREFIX):]
            _LOGGER.info("User confirmed proposal via mobile notification for event %s", event_id)
            self.hass.async_create_task(
                self.async_confirm_proposal(event_id=event_id)
            )

        elif action.startswith(ACTION_UNKNOWN_PREFIX):
            event_id = action[len(ACTION_UNKNOWN_PREFIX):]
            _LOGGER.info("User selected Unknown via mobile notification for event %s", event_id)
            self.hass.async_create_task(
                self.async_mark_unknown(event_id=event_id)
            )

        elif action.startswith(ACTION_CHANGE_PREFIX):
            _LOGGER.info("User requested to change device for event; opened Home Assistant controls")

    async def async_confirm_proposal(
        self,
        event_id: Optional[str] = None,
        consumer_id: Optional[str] = None,
    ) -> bool:
        """Confirm the event with chosen consumer (or default dropdown selection)."""
        target_consumer = consumer_id or self.selected_pending_consumer
        if not target_consumer:
            target_consumer = (
                self.engine.pending_event.proposed_consumer
                if self.engine.pending_event
                else CONSUMER_UNKNOWN
            )

        success = self.engine.confirm_event(
            event_id=event_id,
            selected_consumer=target_consumer,
        )

        if success:
            # Dismiss persistent notification
            ev_id = event_id or (self.engine.pending_event.event_id if self.engine.pending_event else "")
            if ev_id:
                await self.hass.services.async_call(
                    "persistent_notification",
                    "dismiss",
                    {"notification_id": f"energy_disagg_{ev_id}"},
                )

            # Fire confirmation event
            self.hass.bus.async_fire(
                EVENT_CONSUMER_CONFIRMED,
                {
                    "event_id": ev_id,
                    "consumer": target_consumer,
                },
            )

            # Persist learned data
            await self.async_save_storage()
            self.async_set_updated_data(self._build_coordinator_data())

        return success

    async def async_mark_unknown(self, event_id: Optional[str] = None) -> bool:
        """Mark event as unknown / ignore."""
        return await self.async_confirm_proposal(
            event_id=event_id,
            consumer_id=CONSUMER_UNKNOWN,
        )

    def set_selected_pending_consumer(self, consumer_id: str) -> None:
        """Update selected consumer option from UI select entity."""
        self.selected_pending_consumer = consumer_id
        self.async_set_updated_data(self._build_coordinator_data())

    async def async_teach_consumer(
        self,
        consumer_id: str,
        nominal_power: float,
        phase_type: str = "any",
        nominal_l1: float = 0.0,
        nominal_l2: float = 0.0,
        nominal_l3: float = 0.0,
    ) -> None:
        """Calibrate consumer signature manually."""
        self.engine.teach_consumer(
            consumer_id=consumer_id,
            nominal_power=nominal_power,
            phase_type=phase_type,
            nominal_l1=nominal_l1,
            nominal_l2=nominal_l2,
            nominal_l3=nominal_l3,
        )
        await self.async_save_storage()
        self.async_set_updated_data(self._build_coordinator_data())

    async def async_reset_learning(self) -> None:
        """Reset all learned profiles."""
        self.engine.reset_learning()
        await self.async_save_storage()
        self.async_set_updated_data(self._build_coordinator_data())

    def _build_coordinator_data(self) -> Dict[str, Any]:
        """Aggregate data for all entity platforms."""
        total_disaggregated = sum(
            c.current_power for c in self.engine.consumers.values() if c.is_active
        )
        unassigned = max(0.0, self.current_total_power - total_disaggregated)

        total_disaggregated_energy = sum(
            c.lifetime_energy_kwh for c in self.engine.consumers.values()
        )

        return {
            "current_p1": round(self.current_p1, 1),
            "current_p2": round(self.current_p2, 1),
            "current_p3": round(self.current_p3, 1),
            "total_power": round(self.current_total_power, 1),
            "total_disaggregated_power": round(total_disaggregated, 1),
            "unassigned_power": round(unassigned, 1),
            "total_disaggregated_energy": round(total_disaggregated_energy, 3),
            "consumers": {cid: c.to_dict() for cid, c in self.engine.consumers.items()},
            "pending_event": self.engine.pending_event.to_dict() if self.engine.pending_event else None,
            "selected_pending_consumer": self.selected_pending_consumer,
        }

    async def async_update_data(self) -> Dict[str, Any]:
        """Standard update coordinator fetch."""
        self._read_current_sensor_states()
        self._process_reading()
        return self._build_coordinator_data()

    async def async_unload(self) -> None:
        """Clean up all listeners and save state."""
        if self._unsub_state_change:
            self._unsub_state_change()
        if self._unsub_interval:
            self._unsub_interval()
        if self._unsub_notification_action:
            self._unsub_notification_action()
        await self.async_save_storage()
