"""Unit test suite for Energy Disaggregation Engine."""

import sys
import time
from unittest.mock import MagicMock
import unittest

# Mock homeassistant package in sys.modules for standalone testing
for mod in [
    "voluptuous",
    "homeassistant",
    "homeassistant.config_entries",
    "homeassistant.const",
    "homeassistant.core",
    "homeassistant.helpers",
    "homeassistant.helpers.config_validation",
    "homeassistant.helpers.entity",
    "homeassistant.helpers.entity_platform",
    "homeassistant.helpers.event",
    "homeassistant.helpers.selector",
    "homeassistant.helpers.storage",
    "homeassistant.helpers.update_coordinator",
    "homeassistant.components",
    "homeassistant.components.sensor",
    "homeassistant.components.binary_sensor",
    "homeassistant.components.select",
    "homeassistant.components.button",
]:
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()

class MockConfigFlow:
    """Mock base class for ConfigFlow."""
    def __init_subclass__(cls, **kwargs):
        pass

class MockDataUpdateCoordinator:
    """Mock base class for DataUpdateCoordinator."""
    def __init__(self, hass, logger, name=None, update_interval=None):
        self.hass = hass
        self.logger = logger
        self.name = name
        self.data = {}
    def async_set_updated_data(self, data):
        self.data = data
    @classmethod
    def __class_getitem__(cls, item):
        return cls

class MockCoordinatorEntity:
    """Mock base class for CoordinatorEntity."""
    def __init__(self, coordinator):
        self.coordinator = coordinator
    @classmethod
    def __class_getitem__(cls, item):
        return cls

class MockEntity:
    """Mock base entity."""
    @property
    def name(self):
        return getattr(self, "_attr_name", None)

sys.modules["homeassistant"].config_entries = sys.modules["homeassistant.config_entries"]
sys.modules["homeassistant.config_entries"].ConfigFlow = MockConfigFlow
sys.modules["homeassistant.helpers.update_coordinator"].DataUpdateCoordinator = MockDataUpdateCoordinator
sys.modules["homeassistant.helpers.update_coordinator"].CoordinatorEntity = MockCoordinatorEntity
sys.modules["homeassistant.components.sensor"].SensorEntity = MockEntity
sys.modules["homeassistant.components.binary_sensor"].BinarySensorEntity = MockEntity
sys.modules["homeassistant.components.select"].SelectEntity = MockEntity
sys.modules["homeassistant.components.button"].ButtonEntity = MockEntity

from custom_components.energy_disaggregator.const import (
    CONSUMER_BOILER,
    CONSUMER_CAR_CHARGER,
    CONSUMER_OVEN,
    CONSUMER_STOVE,
    CONSUMER_UNKNOWN,
    CONSUMER_WASHER,
    DOMAIN,
)
from custom_components.energy_disaggregator.engine import (
    ConsumerProfile,
    DisaggregationEngine,
    StepEdge,
)
from custom_components.energy_disaggregator.coordinator import EnergyDisaggregatorCoordinator
from custom_components.energy_disaggregator.sensor import (
    ConsumerPowerSensor,
    ConsumerEnergySensor,
    TotalDisaggregatedPowerSensor,
    UnassignedPowerSensor,
    TotalDisaggregatedEnergySensor,
    PendingEventSensor,
)
from custom_components.energy_disaggregator.binary_sensor import (
    ConsumerActiveBinarySensor,
    AwaitingConfirmationBinarySensor,
)
from custom_components.energy_disaggregator.select import PendingConsumerSelect
from custom_components.energy_disaggregator.button import (
    ConfirmProposalButton,
    MarkUnknownButton,
    ResetLearningButton,
)


class TestDisaggregationEngine(unittest.TestCase):
    """Test cases for NILM power step detection, classification, and active learning."""

    def setUp(self):
        """Create a fresh engine for each test."""
        self.engine = DisaggregationEngine(min_step_watts=400, auto_confirm_threshold=0)

    def test_consumer_profile_initialization_and_serialization(self):
        """Test consumer profile creation, update, and dictionary export."""
        boiler = ConsumerProfile(
            consumer_id="boiler",
            name="Water Boiler",
            phase_type="3_phase",
            nominal_power=3000.0,
            nominal_l1=1000.0,
            nominal_l2=1000.0,
            nominal_l3=1000.0,
        )
        self.assertEqual(boiler.id, "boiler")
        self.assertEqual(boiler.mean_total, 3000.0)

        data = boiler.to_dict()
        self.assertIn("nominal_power", data)
        self.assertIn("mean_l1", data)

        restored = ConsumerProfile.from_dict(data)
        self.assertEqual(restored.mean_total, 3000.0)
        self.assertEqual(restored.name, "Water Boiler")

    def test_car_charger_3phase_detection(self):
        """Test identification of an 11 kW 3-phase EV car charger."""
        # Baseline readings (~200W on each phase)
        t = 1000.0
        for _ in range(5):
            self.engine.add_reading(200.0, 200.0, 200.0, 600.0, timestamp=t)
            t += 1.0

        # Car charger turns on (16A 3-phase ≈ 3680W per phase, total ~11040W)
        t += 4.0
        self.engine.add_reading(3880.0, 3880.0, 3880.0, 11640.0, timestamp=t)
        t += 1.0
        event = self.engine.add_reading(3880.0, 3880.0, 3880.0, 11640.0, timestamp=t)

        self.assertIsNotNone(event, "An event should be triggered for 11kW step")
        self.assertEqual(event.proposed_consumer, CONSUMER_CAR_CHARGER)
        self.assertGreater(event.confidence, 70.0)
        self.assertEqual(event.edge.phase_pattern, "3_phase_balanced")

    def test_boiler_3phase_detection(self):
        """Test identification of a 3000W 3-phase water boiler."""
        t = 1000.0
        for _ in range(5):
            self.engine.add_reading(100.0, 100.0, 100.0, 300.0, timestamp=t)
            t += 1.0

        # Boiler turns on: +1000W on each phase (total +3000W)
        t += 4.0
        self.engine.add_reading(1100.0, 1100.0, 1100.0, 3300.0, timestamp=t)
        t += 1.0
        event = self.engine.add_reading(1100.0, 1100.0, 1100.0, 3300.0, timestamp=t)

        self.assertIsNotNone(event)
        self.assertEqual(event.proposed_consumer, CONSUMER_BOILER)
        self.assertEqual(event.edge.phase_pattern, "3_phase_balanced")

    def test_stove_2phase_detection(self):
        """Test identification of a 2-phase induction cooktop/stove."""
        t = 1000.0
        for _ in range(5):
            self.engine.add_reading(150.0, 150.0, 150.0, 450.0, timestamp=t)
            t += 1.0

        # Stove turns on on L1 and L2 (1400W each, L3 unchanged)
        t += 4.0
        self.engine.add_reading(1550.0, 1550.0, 150.0, 3250.0, timestamp=t)
        t += 1.0
        event = self.engine.add_reading(1550.0, 1550.0, 150.0, 3250.0, timestamp=t)

        self.assertIsNotNone(event)
        self.assertEqual(event.proposed_consumer, CONSUMER_STOVE)
        self.assertIn("2_phase", event.edge.phase_pattern)

    def test_active_learning_and_user_override(self):
        """Test user confirming or changing the default proposal, updating learned signature."""
        t = 1000.0
        for _ in range(5):
            self.engine.add_reading(100.0, 100.0, 100.0, 300.0, timestamp=t)
            t += 1.0

        # Step of 2100W on L2 (e.g. Washing machine heating element)
        t += 4.0
        self.engine.add_reading(100.0, 2200.0, 100.0, 2400.0, timestamp=t)
        t += 1.0
        event = self.engine.add_reading(100.0, 2200.0, 100.0, 2400.0, timestamp=t)

        self.assertIsNotNone(event)
        # Even if proposal was Oven or Washer, user can confirm it as Washing Machine:
        success = self.engine.confirm_event(
            event_id=event.event_id,
            selected_consumer=CONSUMER_WASHER,
            now_ts=t,
        )
        self.assertTrue(success)

        washer = self.engine.consumers[CONSUMER_WASHER]
        self.assertTrue(washer.is_active)
        self.assertEqual(washer.confirmations, 1)
        self.assertEqual(washer.active_phase, "l2")
        self.assertAlmostEqual(washer.mean_l2, 2100.0, delta=150.0)

    def test_user_selecting_unknown(self):
        """Test user choosing 'unknown' option."""
        t = 1000.0
        for _ in range(5):
            self.engine.add_reading(100.0, 100.0, 100.0, 300.0, timestamp=t)
            t += 1.0

        t += 4.0
        self.engine.add_reading(600.0, 100.0, 100.0, 800.0, timestamp=t)
        t += 1.0
        event = self.engine.add_reading(600.0, 100.0, 100.0, 800.0, timestamp=t)

        self.assertIsNotNone(event)
        # User marks as unknown
        success = self.engine.mark_unknown(event.event_id)
        self.assertTrue(success)
        self.assertIsNone(self.engine.pending_event)
        self.assertEqual(len(self.engine.unknown_events_log), 1)

    def test_energy_accumulation_and_turn_off(self):
        """Test energy Riemann sum integration and negative turn-off step."""
        t = 1000.0
        for _ in range(5):
            self.engine.add_reading(100.0, 100.0, 100.0, 300.0, timestamp=t)
            t += 1.0

        # Turn on boiler (3000W)
        t += 4.0
        self.engine.add_reading(1100.0, 1100.0, 1100.0, 3300.0, timestamp=t)
        t += 1.0
        event = self.engine.add_reading(1100.0, 1100.0, 1100.0, 3300.0, timestamp=t)
        self.engine.confirm_event(event.event_id, CONSUMER_BOILER, now_ts=t)

        boiler = self.engine.consumers[CONSUMER_BOILER]
        self.assertTrue(boiler.is_active)
        self.assertAlmostEqual(boiler.current_power, 3000.0, delta=100.0)

        # Simulate running for 1 hour in intervals
        for _ in range(12):
            t += 300.0
            self.engine.add_reading(1100.0, 1100.0, 1100.0, 3300.0, timestamp=t)

        # Should have accumulated ~3.0 kWh
        self.assertAlmostEqual(boiler.session_energy_kwh, 3.0, delta=0.1)

        # Turn off boiler (power drops by 3000W)
        t += 4.0
        self.engine.add_reading(100.0, 100.0, 100.0, 300.0, timestamp=t)
        t += 1.0
        self.engine.add_reading(100.0, 100.0, 100.0, 300.0, timestamp=t)

        # Boiler should now be inactive and current power 0W
        self.assertFalse(boiler.is_active)
        self.assertEqual(boiler.current_power, 0.0)
        self.assertGreaterEqual(boiler.lifetime_energy_kwh, 3.0)

    def test_engine_state_persistence(self):
        """Test full engine serialization and restoration."""
        self.engine.min_step_watts = 550
        self.engine.consumers[CONSUMER_BOILER].confirmations = 5
        self.engine.consumers[CONSUMER_BOILER].lifetime_energy_kwh = 125.4

        state = self.engine.to_dict()
        self.assertEqual(state["min_step_watts"], 550)

        new_engine = DisaggregationEngine()
        new_engine.from_dict(state)

        self.assertEqual(new_engine.min_step_watts, 550)
        self.assertEqual(new_engine.consumers[CONSUMER_BOILER].confirmations, 5)
        self.assertAlmostEqual(
            new_engine.consumers[CONSUMER_BOILER].lifetime_energy_kwh, 125.4
        )

    def test_concurrent_appliances_handling(self):
        """Test multiple appliances running at the same time: Boiler + Stove."""
        t = 1000.0
        for _ in range(5):
            self.engine.add_reading(100.0, 100.0, 100.0, 300.0, timestamp=t)
            t += 1.0

        # 1. Boiler turns on (+1000W on each phase)
        t += 4.0
        self.engine.add_reading(1100.0, 1100.0, 1100.0, 3300.0, timestamp=t)
        t += 1.0
        ev1 = self.engine.add_reading(1100.0, 1100.0, 1100.0, 3300.0, timestamp=t)
        self.assertIsNotNone(ev1)
        self.assertEqual(ev1.proposed_consumer, CONSUMER_BOILER)
        self.engine.confirm_event(ev1.event_id, CONSUMER_BOILER, now_ts=t)
        self.assertTrue(self.engine.consumers[CONSUMER_BOILER].is_active)

        # Let boiler run for a few seconds so baseline settles
        for _ in range(5):
            t += 1.0
            self.engine.add_reading(1100.0, 1100.0, 1100.0, 3300.0, timestamp=t)

        # 2. Stove turns on while Boiler is running (+1400W on L1 & L2)
        # Power is now: L1 = 1100+1400 = 2500, L2 = 1100+1400 = 2500, L3 = 1100 (total = 6100)
        t += 4.0
        self.engine.add_reading(2500.0, 2500.0, 1100.0, 6100.0, timestamp=t)
        t += 1.0
        ev2 = self.engine.add_reading(2500.0, 2500.0, 1100.0, 6100.0, timestamp=t)
        self.assertIsNotNone(ev2)
        self.assertEqual(ev2.proposed_consumer, CONSUMER_STOVE)
        self.engine.confirm_event(ev2.event_id, CONSUMER_STOVE, now_ts=t)
        self.assertTrue(self.engine.consumers[CONSUMER_STOVE].is_active)
        self.assertTrue(self.engine.consumers[CONSUMER_BOILER].is_active)

        # Let both run for a few seconds so baseline settles at 6100W
        for _ in range(5):
            t += 1.0
            self.engine.add_reading(2500.0, 2500.0, 1100.0, 6100.0, timestamp=t)

        # 3. Boiler turns off (-1000W on all 3 phases). Stove still running!
        # Power drops to: L1 = 1500, L2 = 1500, L3 = 100 (total = 3100)
        t += 4.0
        self.engine.add_reading(1500.0, 1500.0, 100.0, 3100.0, timestamp=t)
        t += 1.0
        self.engine.add_reading(1500.0, 1500.0, 100.0, 3100.0, timestamp=t)

        # Boiler should be deactivated, Stove should still be active!
        self.assertFalse(self.engine.consumers[CONSUMER_BOILER].is_active)
        self.assertTrue(self.engine.consumers[CONSUMER_STOVE].is_active)

    def test_auto_confirm_threshold(self):
        """Test auto-confirming when confidence and confirmation count are high."""
        self.engine.auto_confirm_threshold = 2
        boiler = self.engine.consumers[CONSUMER_BOILER]
        boiler.confirmations = 3  # already confirmed 3 times

        t = 1000.0
        for _ in range(5):
            self.engine.add_reading(100.0, 100.0, 100.0, 300.0, timestamp=t)
            t += 1.0

        # Step matching boiler (3000W 3-phase)
        t += 4.0
        self.engine.add_reading(1100.0, 1100.0, 1100.0, 3300.0, timestamp=t)
        t += 1.0
        ev = self.engine.add_reading(1100.0, 1100.0, 1100.0, 3300.0, timestamp=t)

        self.assertIsNotNone(ev)
        self.assertEqual(ev.status, "auto_confirmed")
        # Should be activated automatically without user prompt
        self.assertTrue(boiler.is_active)
        self.assertEqual(boiler.confirmations, 4)

    def test_home_assistant_entities_creation(self):
        """Test instantiation and property lookups of all HA sensors, binary sensors, selects, buttons."""
        mock_hass = MagicMock()
        mock_entry = MagicMock()
        mock_entry.entry_id = "test_entry_123"
        mock_entry.title = "Test P1 Disaggregator"
        mock_entry.data = {
            "phase_l1_sensor": "sensor.p1_meter_active_power_l1",
            "phase_l2_sensor": "sensor.p1_meter_active_power_l2",
            "phase_l3_sensor": "sensor.p1_meter_active_power_l3",
        }
        mock_entry.options = {}

        coordinator = EnergyDisaggregatorCoordinator(mock_hass, mock_entry)
        self.assertEqual(coordinator.name, "Energy Disaggregator (Test P1 Disaggregator)")

        # Create sensors
        power_sensor = ConsumerPowerSensor(coordinator, mock_entry, CONSUMER_BOILER)
        energy_sensor = ConsumerEnergySensor(coordinator, mock_entry, CONSUMER_BOILER)
        total_p_sensor = TotalDisaggregatedPowerSensor(coordinator, mock_entry)
        unassigned_sensor = UnassignedPowerSensor(coordinator, mock_entry)
        total_e_sensor = TotalDisaggregatedEnergySensor(coordinator, mock_entry)
        pending_sensor = PendingEventSensor(coordinator, mock_entry)

        self.assertEqual(power_sensor.native_value, 0.0)
        self.assertEqual(energy_sensor.native_value, 0.0)
        self.assertEqual(total_p_sensor.native_value, 0.0)
        self.assertEqual(unassigned_sensor.native_value, 0.0)
        self.assertEqual(pending_sensor.native_value, "Idle")

        # Create binary sensors
        active_sensor = ConsumerActiveBinarySensor(coordinator, mock_entry, CONSUMER_BOILER)
        awaiting_sensor = AwaitingConfirmationBinarySensor(coordinator, mock_entry)
        self.assertFalse(active_sensor.is_on)
        self.assertFalse(awaiting_sensor.is_on)

        # Create select
        sel = PendingConsumerSelect(coordinator, mock_entry)
        self.assertIn("Water Boiler", sel.options)
        self.assertIn("Unknown / Ignore", sel.options)
        self.assertEqual(sel.current_option, "Unknown / Ignore")

        # Create buttons
        btn_confirm = ConfirmProposalButton(coordinator, mock_entry)
        btn_unknown = MarkUnknownButton(coordinator, mock_entry)
        btn_reset = ResetLearningButton(coordinator, mock_entry)
        self.assertEqual(btn_confirm.name, "Confirm Consumer Assignment")
        self.assertEqual(btn_unknown.name, "Mark as Unknown / Ignore")
        self.assertEqual(btn_reset.name, "Reset Learning & Profiles")


if __name__ == "__main__":
    unittest.main()
