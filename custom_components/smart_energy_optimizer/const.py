"""Constants for the Smart Energy & Thermal Optimizer integration."""

DOMAIN = "smart_energy_optimizer"
VERSION = "2.1.0"

# Configuration Keys
CONF_INDOOR_TEMP_SENSOR = "indoor_temp_sensor"
CONF_OUTDOOR_TEMP_SENSOR = "outdoor_temp_sensor"
CONF_WEATHER_ENTITY = "weather_entity"
CONF_PRICE_SENSOR = "price_sensor"
CONF_PRICE_CURRENCY = "price_currency"

# Heat Pump Controls
CONF_HEAT_PUMP_CLIMATE = "heat_pump_climate"
CONF_HEAT_PUMP_POWER_SENSOR = "heat_pump_power_sensor"
CONF_HEAT_PUMP_ENERGY_SENSOR = "heat_pump_energy_sensor"  # e.g. Mitsubishi WF-RAC energy_consumed (kWh)
CONF_HEAT_PUMP_MAX_POWER = "heat_pump_max_power"
CONF_HEAT_PUMP_MIN_TEMP = "heat_pump_min_temp"
CONF_HEAT_PUMP_MAX_TEMP = "heat_pump_max_temp"
CONF_USE_WF_RAC_SENSORS = "use_wf_rac_sensors"  # Auto-read indoor/outdoor/energy from Mitsubishi WF-RAC
CONF_CONFIGURE_ADVANCED = "configure_advanced"

# Tariff and Grid Fees (Göteborg Energi & Swedish taxes)
CONF_TARIFF_TYPE = "tariff_type"
CONF_ENERGY_TAX = "energy_tax"
CONF_SURCHARGE = "surcharge"
CONF_GRID_FEE_HIGH_LOAD = "grid_fee_high_load"
CONF_GRID_FEE_LOW_LOAD = "grid_fee_low_load"
CONF_VAT_PERCENT = "vat_percent"
CONF_SPOT_PRICE_INCLUDES_VAT = "spot_price_includes_vat"

# Göteborg Energi Effekttariff (Peak Power Shaving)
CONF_ENABLE_EFFEKTDIFF = "enable_effekttariff"
CONF_PEAK_LIMIT_KW = "peak_limit_kw"
CONF_EFFEKTAVGIFT_PRICE_PER_KW = "effektavgift_price_per_kw"
DEFAULT_ENABLE_EFFEKTDIFF = True
DEFAULT_PEAK_LIMIT_KW = 4.5  # Max target kW peak for household
DEFAULT_EFFEKTAVGIFT_PRICE_PER_KW = 48.0  # Approx SEK/kW/month for Göteborg Energi villa

# Boiler / DHW Controls
CONF_BOILER_ENTITY = "boiler_entity"
CONF_BOILER_POWER_SENSOR = "boiler_power_sensor"
CONF_BOILER_RATED_POWER = "boiler_rated_power"
CONF_BOILER_RUN_HOURS_PER_DAY = "boiler_run_hours_per_day"
CONF_BOILER_DAILY_HOURS = CONF_BOILER_RUN_HOURS_PER_DAY

# Big Consumers Power Sensors
CONF_BIG_CONSUMERS = "big_consumers"

# Future Extension Configuration Keys
CONF_SOLAR_POWER_SENSOR = "solar_power_sensor"
CONF_SOLAR_FORECAST_ENTITY = "solar_forecast_entity"
CONF_BATTERY_SOC_SENSOR = "battery_soc_sensor"
CONF_BATTERY_POWER_SENSOR = "battery_power_sensor"
CONF_BATTERY_CAPACITY_KWH = "battery_capacity_kwh"
CONF_EV_CHARGER_ENTITY = "ev_charger_entity"
CONF_EV_CHARGER_POWER_SENSOR = "ev_charger_power_sensor"

# Optimization Modes
MODE_PRICE_OPTIMIZED = "price_optimized"
MODE_BALANCED = "balanced"
MODE_STABLE_TEMP = "stable_temperature"

OPTIMIZATION_MODES = [
    MODE_PRICE_OPTIMIZED,
    MODE_BALANCED,
    MODE_STABLE_TEMP,
]

# Defaults
DEFAULT_TARGET_TEMP = 21.5
DEFAULT_ALLOWED_DRIFT = 1.0  # +/- deg C
DEFAULT_MAX_PREHEAT = 1.5    # Max deg C above target before price peaks
DEFAULT_MODE = MODE_BALANCED
DEFAULT_CURRENCY = "EUR"

# Thermal Model Defaults (Initial Priors)
DEFAULT_THERMAL_CAPACITY = 6.0   # kWh / °C (approx typical 120-160 m2 house)
DEFAULT_THERMAL_RESISTANCE = 4.0  # °C / kW
DEFAULT_INTERNAL_GAINS = 0.4     # kW base internal gains (people, electronics)
DEFAULT_NOMINAL_COP = 3.5        # at 7°C outdoor
DEFAULT_COP_ALPHA = 0.07         # COP change per °C outdoor temp change

# Storage Key
STORAGE_KEY = f"{DOMAIN}_model_data"
STORAGE_VERSION = 1

# Update Intervals
SCAN_INTERVAL_MINUTES = 10
