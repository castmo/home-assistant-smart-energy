"""Constants for the Energy Disaggregator integration."""

DOMAIN = "energy_disaggregator"

# Configuration keys
CONF_PHASE_L1_SENSOR = "phase_l1_sensor"
CONF_PHASE_L2_SENSOR = "phase_l2_sensor"
CONF_PHASE_L3_SENSOR = "phase_l3_sensor"
CONF_TOTAL_POWER_SENSOR = "total_power_sensor"
CONF_NOTIFY_SERVICE = "notify_service"
CONF_MIN_STEP_WATTS = "min_step_watts"
CONF_ENABLE_NOTIFICATIONS = "enable_notifications"
CONF_AUTO_LEARN = "auto_learn"
CONF_AUTO_CONFIRM_THRESHOLD = "auto_confirm_threshold"
CONF_TRACKED_CONSUMERS = "tracked_consumers"

# Default values
DEFAULT_MIN_STEP_WATTS = 400
DEFAULT_ENABLE_NOTIFICATIONS = True
DEFAULT_AUTO_LEARN = True
DEFAULT_AUTO_CONFIRM_THRESHOLD = 0  # 0 means always ask during learning
DEFAULT_STORAGE_KEY = "energy_disaggregator.knowledge_base"
DEFAULT_STORAGE_VERSION = 1

# Well-known consumer IDs
CONSUMER_BOILER = "boiler"
CONSUMER_STOVE = "stove"
CONSUMER_OVEN = "oven"
CONSUMER_CAR_CHARGER = "car_charger"
CONSUMER_WASHER = "washer"
CONSUMER_DRYER = "dryer"
CONSUMER_DISHWASHER = "dishwasher"
CONSUMER_HEAT_PUMP = "heat_pump"
CONSUMER_UNKNOWN = "unknown"

# Initial physical priors for large household consumers:
# - Boiler: typically 3-phase resistive (3x 1000W) or single-phase 2000-3000W
# - Stove: typically 2-phase split (L1+L2, ~2000-3600W total)
# - Oven: single phase, 2000-2800W
# - Car Charger: 3-phase balanced 11kW (3x 3.6kW), or 7.4kW single phase
# - Washer: 1-phase 2000-2400W heating
# - Dryer: 1-phase 2000-2800W resistive or 600-900W heat pump
# - Dishwasher: 1-phase 1800-2200W heating
# - Heat Pump: 3-phase or 1-phase compressor 1500-3500W
DEFAULT_CONSUMER_CATALOG = {
    CONSUMER_BOILER: {
        "name": "Water Boiler",
        "icon": "mdi:water-boiler",
        "phase_type": "3_phase",  # or any
        "nominal_power": 3000.0,
        "nominal_l1": 1000.0,
        "nominal_l2": 1000.0,
        "nominal_l3": 1000.0,
        "tolerance": 500.0,
    },
    CONSUMER_STOVE: {
        "name": "Stove / Induction Hob",
        "icon": "mdi:stove",
        "phase_type": "2_phase",
        "nominal_power": 2800.0,
        "nominal_l1": 1400.0,
        "nominal_l2": 1400.0,
        "nominal_l3": 0.0,
        "tolerance": 800.0,
    },
    CONSUMER_OVEN: {
        "name": "Oven",
        "icon": "mdi:toaster-oven",
        "phase_type": "1_phase",
        "nominal_power": 2400.0,
        "nominal_l1": 2400.0,
        "nominal_l2": 0.0,
        "nominal_l3": 0.0,
        "tolerance": 500.0,
    },
    CONSUMER_CAR_CHARGER: {
        "name": "EV Car Charger",
        "icon": "mdi:ev-station",
        "phase_type": "3_phase",
        "nominal_power": 11040.0,
        "nominal_l1": 3680.0,
        "nominal_l2": 3680.0,
        "nominal_l3": 3680.0,
        "tolerance": 2500.0,
    },
    CONSUMER_WASHER: {
        "name": "Washing Machine",
        "icon": "mdi:washing-machine",
        "phase_type": "1_phase",
        "nominal_power": 2100.0,
        "nominal_l1": 2100.0,
        "nominal_l2": 0.0,
        "nominal_l3": 0.0,
        "tolerance": 450.0,
    },
    CONSUMER_DRYER: {
        "name": "Tumble Dryer",
        "icon": "mdi:tumble-dryer",
        "phase_type": "1_phase",
        "nominal_power": 2500.0,
        "nominal_l1": 2500.0,
        "nominal_l2": 0.0,
        "nominal_l3": 0.0,
        "tolerance": 600.0,
    },
    CONSUMER_DISHWASHER: {
        "name": "Dishwasher",
        "icon": "mdi:dishwasher",
        "phase_type": "1_phase",
        "nominal_power": 2000.0,
        "nominal_l1": 2000.0,
        "nominal_l2": 0.0,
        "nominal_l3": 0.0,
        "tolerance": 400.0,
    },
    CONSUMER_HEAT_PUMP: {
        "name": "Heat Pump",
        "icon": "mdi:heat-pump",
        "phase_type": "3_phase",
        "nominal_power": 2200.0,
        "nominal_l1": 730.0,
        "nominal_l2": 730.0,
        "nominal_l3": 740.0,
        "tolerance": 800.0,
    },
}

# Actionable notification actions
ACTION_CONFIRM_PREFIX = "DISAGG_CONFIRM_"
ACTION_UNKNOWN_PREFIX = "DISAGG_UNKNOWN_"
ACTION_CHANGE_PREFIX = "DISAGG_CHANGE_"

# Event types fired to HA event bus
EVENT_POWER_STEP_DETECTED = "energy_disaggregator_step_detected"
EVENT_CONSUMER_CONFIRMED = "energy_disaggregator_consumer_confirmed"
EVENT_CONSUMER_STATE_CHANGED = "energy_disaggregator_state_changed"

# Services
SERVICE_CONFIRM_EVENT = "confirm_event"
SERVICE_MARK_UNKNOWN = "mark_unknown"
SERVICE_TEACH_CONSUMER = "teach_consumer"
SERVICE_RESET_LEARNING = "reset_learning"
SERVICE_SET_CONSUMER_STATE = "set_consumer_state"
