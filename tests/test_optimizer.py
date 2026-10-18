"""Test suite for thermal model learning and energy optimizer."""

import datetime
import math
import sys
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
    "homeassistant.helpers.event",
    "homeassistant.helpers.selector",
    "homeassistant.helpers.storage",
    "homeassistant.helpers.update_coordinator",
    "homeassistant.components",
    "homeassistant.components.climate",
    "homeassistant.components.sensor",
    "homeassistant.components.select",
    "homeassistant.components.number",
    "homeassistant.components.switch",
]:
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()

class MockConfigFlow:
    """Mock base class for ConfigFlow."""
    def __init_subclass__(cls, **kwargs):
        pass

sys.modules["homeassistant"].config_entries = sys.modules["homeassistant.config_entries"]
sys.modules["homeassistant.config_entries"].ConfigFlow = MockConfigFlow

from custom_components.smart_energy_optimizer.const import (
    MODE_BALANCED,
    MODE_PRICE_OPTIMIZED,
    MODE_STABLE_TEMP,
)
from custom_components.smart_energy_optimizer.optimizer import EnergyOptimizer
from custom_components.smart_energy_optimizer.thermal_model import BuildingThermalModel


class TestThermalModelAndOptimizer(unittest.TestCase):
    """Test cases for thermal physics learning and optimization engine."""

    def test_thermal_model_initialization_and_serialization(self):
        """Test model creation, persistence to dict, and restoration."""
        model = BuildingThermalModel(
            c_th=6.5,
            r_th=4.2,
            q_internal=0.45,
            nominal_cop=3.6,
        )
        self.assertAlmostEqual(model.c_th, 6.5, places=2)
        self.assertAlmostEqual(model.r_th, 4.2, places=2)
        self.assertAlmostEqual(model.tau, 6.5 * 4.2, places=2)

        data = model.to_dict()
        self.assertIn("c_th", data)
        self.assertIn("r_th", data)
        self.assertIn("theta", data)

        restored = BuildingThermalModel.from_dict(data)
        self.assertAlmostEqual(restored.c_th, 6.5, places=2)
        self.assertAlmostEqual(restored.r_th, 4.2, places=2)
        self.assertAlmostEqual(restored.tau, model.tau, places=2)

    def test_cop_estimation(self):
        """Test COP changes with outdoor temperature."""
        model = BuildingThermalModel(nominal_cop=3.5, cop_alpha=0.08)
        cop_at_7 = model.estimate_cop(7.0)
        cop_at_minus_5 = model.estimate_cop(-5.0)
        cop_at_15 = model.estimate_cop(15.0)

        self.assertAlmostEqual(cop_at_7, 3.5, places=2)
        self.assertLess(cop_at_minus_5, cop_at_7)
        self.assertGreater(cop_at_15, cop_at_7)

    def test_online_rls_learning(self):
        """Test that RLS updates building parameters given simulated sensor data."""
        # True simulated house: C_true = 8.0 kWh/°C, R_true = 3.5 °C/kW => tau = 28.0h
        c_true = 8.0
        r_true = 3.5
        q_int_true = 0.5

        # Initialize model with different prior: C = 5.0, R = 5.0
        model = BuildingThermalModel(c_th=5.0, r_th=5.0, q_internal=0.3)

        # Simulate 72 hours of data
        t_in = 20.5
        now = datetime.datetime.now()
        dt_h = 1.0

        for step in range(72):
            hour = step % 24
            # Diurnal outdoor temp: between 0°C at night and 10°C in afternoon
            t_out = 5.0 + 5.0 * math.sin((hour - 8) * math.pi / 12.0)
            # Simulated heat pump cycling
            hp_elec_kw = 1.5 if (hour < 7 or hour > 19) else 0.8
            cop = model.estimate_cop(t_out)
            q_hp = hp_elec_kw * cop

            # True building next temp
            tau_true = r_true * c_true
            decay = math.exp(-dt_h / tau_true)
            t_asymp = t_out + r_true * (q_hp + q_int_true)
            next_t_in = t_in * decay + t_asymp * (1.0 - decay)

            # Feed to learning model
            model.update_measurement(
                t_in=next_t_in,
                t_out=t_out,
                heat_pump_power_kw=hp_elec_kw,
                delta_hours=dt_h,
            )
            t_in = next_t_in

        self.assertGreater(model.sample_count, 50)
        # Check that parameters moved towards the true values
        self.assertGreater(model.c_th, 5.0)  # Prior was 5.0, true is 8.0
        print(f"Learned C_th: {model.c_th:.2f} (True: 8.0), R_th: {model.r_th:.2f} (True: 3.5), Tau: {model.tau:.1f}h")

    def test_optimizer_modes_and_boiler_scheduling(self):
        """Test MPC optimizer in Price-Optimized, Stable-Temp, and Balanced modes."""
        model = BuildingThermalModel(c_th=6.0, r_th=4.0)
        optimizer = EnergyOptimizer(
            thermal_model=model,
            max_hp_power_kw=3.0,
            boiler_rated_kw=2.0,
            boiler_daily_hours=2.0,
        )

        base_time = datetime.datetime(2026, 10, 15, 0, 0)
        # Create 24 hours of prices with a cheap valley at night and afternoon, peak in evening
        prices = []
        outdoor_forecast = []
        for h in range(24):
            ts = base_time + datetime.timedelta(hours=h)
            # Price curve: cheap at 02:00-05:00 (0.10 €/kWh), peak at 17:00-20:00 (0.50 €/kWh)
            if 1 <= h <= 4:
                p = 0.10
            elif 17 <= h <= 20:
                p = 0.50
            else:
                p = 0.25
            prices.append((ts, p))

            # Outdoor temp: cold at night (2°C), warmer at midday (12°C)
            t_out = 7.0 + 5.0 * math.cos((h - 14) * math.pi / 12.0)
            outdoor_forecast.append((ts, t_out))

        # 1. Test Stable Temperature Mode
        res_stable = optimizer.solve(
            current_indoor_temp=21.0,
            target_comfort_temp=21.0,
            allowed_drift=1.0,
            preheat_boost=1.5,
            mode=MODE_STABLE_TEMP,
            prices=prices,
            outdoor_forecast=outdoor_forecast,
        )
        # In stable mode, predicted indoor temp should stay very close to 21.0
        max_indoor = max(inv.predicted_indoor_temp for inv in res_stable.intervals)
        min_indoor = min(inv.predicted_indoor_temp for inv in res_stable.intervals)
        self.assertLess(max_indoor, 21.4)
        self.assertGreater(min_indoor, 20.6)

        # 2. Test Price-Optimized Mode
        res_price = optimizer.solve(
            current_indoor_temp=21.0,
            target_comfort_temp=21.0,
            allowed_drift=1.5,
            preheat_boost=1.5,
            mode=MODE_PRICE_OPTIMIZED,
            prices=prices,
            outdoor_forecast=outdoor_forecast,
        )

        # Cost in Price-Optimized mode must be lower than baseline
        self.assertLess(res_price.total_optimized_cost, res_price.total_baseline_cost)
        self.assertGreater(res_price.savings_percent, 5.0)

        # Test unconstrained boiler scheduling (peak_limit_kw=6.0 allows HP boost + boiler together)
        unconstrained_optimizer = EnergyOptimizer(
            thermal_model=model,
            max_hp_power_kw=3.0,
            boiler_rated_kw=2.0,
            boiler_daily_hours=2.0,
            peak_limit_kw=6.0,
        )
        res_unconstrained = unconstrained_optimizer.solve(
            current_indoor_temp=21.0,
            target_comfort_temp=21.0,
            allowed_drift=1.5,
            preheat_boost=1.5,
            mode=MODE_PRICE_OPTIMIZED,
            prices=prices,
            outdoor_forecast=outdoor_forecast,
        )
        boiler_unconstrained_indices = [
            inv.index for inv in res_unconstrained.intervals if inv.boiler_action == "heating"
        ]
        self.assertEqual(boiler_unconstrained_indices, [1, 2])

        # Test effekttariff anti-coincidence protection (peak_limit_kw=4.5 prevents HP 3.0 kW + Boiler 2.0 kW)
        boiler_constrained_indices = [
            inv.index for inv in res_price.intervals if inv.boiler_action == "heating"
        ]
        self.assertEqual(len(boiler_constrained_indices), 2)
        # Verify that combined heat pump + boiler power never exceeds peak_limit_kw (4.5 kW) in any hour
        for inv in res_price.intervals:
            self.assertLessEqual(inv.heat_pump_power_kw + inv.boiler_power_kw, 4.5)

        print(f"Price-Optimized Cost: {res_price.total_optimized_cost:.2f} € vs Baseline: {res_price.total_baseline_cost:.2f} € (Savings: {res_price.savings_percent}%)")

    def test_solar_and_battery_extension(self):
        """Test solar generation offset and battery peak shaving dispatch."""
        model = BuildingThermalModel(c_th=6.0, r_th=4.0)
        optimizer = EnergyOptimizer(thermal_model=model)

        base_time = datetime.datetime(2026, 10, 15, 0, 0)
        prices = []
        outdoor_forecast = []
        solar_forecast = []

        for h in range(24):
            ts = base_time + datetime.timedelta(hours=h)
            # High price peak at hour 18 (0.60 €/kWh)
            p = 0.60 if 17 <= h <= 20 else 0.15
            prices.append((ts, p))
            outdoor_forecast.append((ts, 5.0))
            # Mid-day solar peak at hours 11 to 14 (up to 4 kW)
            solar_kw = 4.0 if 11 <= h <= 14 else 0.0
            solar_forecast.append((ts, solar_kw))

        res = optimizer.solve(
            current_indoor_temp=21.0,
            target_comfort_temp=21.0,
            allowed_drift=1.0,
            preheat_boost=1.5,
            mode=MODE_PRICE_OPTIMIZED,
            prices=prices,
            outdoor_forecast=outdoor_forecast,
            solar_forecast=solar_forecast,
        )

        # Verify solar generation offset is recorded
        solar_intervals = [inv for inv in res.intervals if inv.solar_generation_kw > 0]
        self.assertEqual(len(solar_intervals), 4)

        # Verify battery charges during solar or cheap hours and discharges during peak
        battery_discharges = [inv for inv in res.intervals if inv.battery_discharge_kw > 0]
        self.assertGreater(len(battery_discharges), 0)

    def test_ev_charging_extension(self):
        """Test EV charging scheduling in the cheapest hours before departure."""
        model = BuildingThermalModel(c_th=6.0, r_th=4.0)
        optimizer = EnergyOptimizer(thermal_model=model)

        base_time = datetime.datetime(2026, 10, 15, 0, 0)
        prices = []
        outdoor_forecast = []

        for h in range(24):
            ts = base_time + datetime.timedelta(hours=h)
            # Cheapest hours are at 02:00, 03:00 (0.08 €/kWh)
            p = 0.08 if h in [2, 3] else 0.30
            prices.append((ts, p))
            outdoor_forecast.append((ts, 5.0))

        intervals = [
            optimizer.solve(
                current_indoor_temp=21.0,
                target_comfort_temp=21.0,
                allowed_drift=1.0,
                preheat_boost=1.5,
                mode=MODE_BALANCED,
                prices=prices,
                outdoor_forecast=outdoor_forecast,
            ).intervals
        ][0]

        # Schedule 14 kWh of EV charging before 07:00 AM (hour 7)
        optimizer._optimize_ev_charging(
            intervals=intervals,
            required_kwh=14.0,
            departure_hour_idx=7,
            max_charge_kw=7.0,
        )

        # Must be allocated to hours 2 and 3
        self.assertEqual(intervals[2].ev_charging_kw, 7.0)
        self.assertEqual(intervals[3].ev_charging_kw, 7.0)
        self.assertEqual(intervals[0].ev_charging_kw, 0.0)

    def test_goteborg_energi_tariff_calculator(self):
        """Test Göteborg Energi winter high-load vs low-load tariff and Swedish taxes."""
        from custom_components.smart_energy_optimizer.price_calculator import (
            ElectricityTariffCalculator,
            TARIFF_GOTEBORG_TIDSTARIFF,
        )

        calc = ElectricityTariffCalculator(
            tariff_type=TARIFF_GOTEBORG_TIDSTARIFF,
            surcharge=0.05,
            energy_tax=0.445,
            grid_fee_high_load=0.38,
            grid_fee_low_load=0.16,
            vat_percent=25.0,
            spot_price_includes_vat=False,
        )

        # Winter weekday at 10:00 (Höglast: Dec 15, 2026, Tuesday 10:00)
        winter_weekday_day = datetime.datetime(2026, 12, 15, 10, 0)
        self.assertTrue(calc.is_goteborg_high_load(winter_weekday_day))
        bd_day = calc.calculate_total_price(raw_spot_price=0.50, dt=winter_weekday_day)
        # Subtotal = 0.50 + 0.05 + 0.445 + 0.38 = 1.375
        # Total with 25% VAT = 1.375 * 1.25 = 1.71875 SEK/kWh
        self.assertAlmostEqual(bd_day.total_price, 1.7188, places=3)
        self.assertTrue(bd_day.is_high_load)

        # Winter weekday at 03:00 (Låglast night: Dec 15, 2026, Tuesday 03:00)
        winter_weekday_night = datetime.datetime(2026, 12, 15, 3, 0)
        self.assertFalse(calc.is_goteborg_high_load(winter_weekday_night))
        bd_night = calc.calculate_total_price(raw_spot_price=0.50, dt=winter_weekday_night)
        # Subtotal = 0.50 + 0.05 + 0.445 + 0.16 = 1.155
        # Total with 25% VAT = 1.155 * 1.25 = 1.44375 SEK/kWh
        self.assertAlmostEqual(bd_night.total_price, 1.4438, places=3)
        self.assertFalse(bd_night.is_high_load)

        # Notice: Transmission fee alone creates a ~0.275 SEK/kWh price difference!
        self.assertGreater(bd_day.total_price, bd_night.total_price)

    def test_heat_pump_consumption_forecaster(self):
        """Test energy forecasting given a target setpoint (compatible with WF-RAC data)."""
        model = BuildingThermalModel(c_th=6.0, r_th=4.0)

        # Room at 20.0°C, outdoor at 0.0°C, target setpoint 22.0°C (ramp up)
        p_elec_boost, q_th_boost = model.forecast_heat_pump_consumption(
            t_set=22.0, t_in=20.0, t_out=0.0
        )
        self.assertGreater(p_elec_boost, 0.5)

        # Room at 22.0°C, target setpoint 20.0°C (setpoint below indoor, should idle)
        p_elec_idle, q_th_idle = model.forecast_heat_pump_consumption(
            t_set=20.0, t_in=22.0, t_out=0.0
        )
        self.assertEqual(p_elec_idle, 0.0)

    def test_simplified_config_flow(self):
        """Test that the simplified 1-step config flow automatically detects WF-RAC entities and applies defaults."""
        import asyncio
        from custom_components.smart_energy_optimizer.config_flow import SmartEnergyConfigFlow
        from custom_components.smart_energy_optimizer.const import (
            CONF_CONFIGURE_ADVANCED,
            CONF_GRID_FEE_HIGH_LOAD,
            CONF_GRID_FEE_LOW_LOAD,
            CONF_HEAT_PUMP_CLIMATE,
            CONF_HEAT_PUMP_ENERGY_SENSOR,
            CONF_PRICE_SENSOR,
            CONF_TARIFF_TYPE,
            CONF_WEATHER_ENTITY,
        )
        from custom_components.smart_energy_optimizer.price_calculator import TARIFF_GOTEBORG_TIDSTARIFF

        flow = SmartEnergyConfigFlow()
        flow.hass = MagicMock()
        flow.async_create_entry = lambda title, data, options: {
            "type": "create_entry",
            "title": title,
            "data": data,
            "options": options,
        }

        # Mock HA states containing WF-RAC climate, Nordpool sensor, and weather forecast
        state_climate = MagicMock(entity_id="climate.living_room_wf_rac")
        state_price = MagicMock(entity_id="sensor.nordpool_kwh_se3_sek_3_10_025")
        state_weather = MagicMock(entity_id="weather.forecast_home")
        state_energy = MagicMock(entity_id="sensor.living_room_wf_rac_energy_consumed")

        flow.hass.states.async_all.return_value = [state_climate, state_price, state_weather, state_energy]
        flow.hass.states.get.side_effect = lambda eid: {
            "climate.living_room_wf_rac": state_climate,
            "sensor.nordpool_kwh_se3_sek_3_10_025": state_price,
            "weather.forecast_home": state_weather,
            "sensor.living_room_wf_rac_energy_consumed": state_energy,
        }.get(eid)

        flow.async_show_form = lambda step_id, data_schema, errors=None: {
            "type": "form",
            "step_id": step_id,
            "errors": errors,
        }

        # 1. Test Initial Form presentation (auto-detects climate, price, weather)
        form_res = asyncio.run(flow.async_step_user(None))
        self.assertEqual(form_res["type"], "form")
        self.assertEqual(form_res["step_id"], "user")

        # 2. Quick Setup (1-step onboarding without advanced configuration)
        res = asyncio.run(flow.async_step_user({
            CONF_HEAT_PUMP_CLIMATE: "climate.living_room_wf_rac",
            CONF_PRICE_SENSOR: "sensor.nordpool_kwh_se3_sek_3_10_025",
            CONF_CONFIGURE_ADVANCED: False,
        }))

        # Assert entry is created immediately without forcing user through multi-page forms
        self.assertEqual(res["type"], "create_entry")
        self.assertEqual(res["title"], "Smart Energy Optimizer")

        # Assert auto-detection of WF-RAC energy sensor and default weather entity
        self.assertEqual(res["data"][CONF_HEAT_PUMP_ENERGY_SENSOR], "sensor.living_room_wf_rac_energy_consumed")
        self.assertEqual(res["data"][CONF_WEATHER_ENTITY], "weather.forecast_home")

        # Assert Göteborg Energi Tidstariff loaded by default
        self.assertEqual(res["data"][CONF_TARIFF_TYPE], TARIFF_GOTEBORG_TIDSTARIFF)
        self.assertEqual(res["data"][CONF_GRID_FEE_HIGH_LOAD], 0.38)
        self.assertEqual(res["data"][CONF_GRID_FEE_LOW_LOAD], 0.16)

        # 3. Test Advanced Setup path
        adv_flow = SmartEnergyConfigFlow()
        adv_flow.hass = flow.hass
        adv_flow.async_show_form = flow.async_show_form
        adv_res = asyncio.run(adv_flow.async_step_user({
            CONF_HEAT_PUMP_CLIMATE: "climate.living_room_wf_rac",
            CONF_PRICE_SENSOR: "sensor.nordpool_kwh_se3_sek_3_10_025",
            CONF_CONFIGURE_ADVANCED: True,
        }))
        self.assertEqual(adv_res["type"], "form")
        self.assertEqual(adv_res["step_id"], "advanced_heat_pump")

    def test_high_consumer_scoring(self):
        """Test flexible consumer scoring (battery charging, EV, appliances)."""
        model = BuildingThermalModel(c_th=6.0, r_th=3.5, q_internal=0.4)
        optimizer = EnergyOptimizer(thermal_model=model)

        now = datetime.datetime(2026, 1, 15, 0, 0)  # Winter weekday
        prices = [
            (now + datetime.timedelta(hours=0), 0.50),  # Cheap night
            (now + datetime.timedelta(hours=1), 0.55),
            (now + datetime.timedelta(hours=7), 2.50),  # Expensive morning peak
            (now + datetime.timedelta(hours=8), 2.80),
        ]
        weather = [(t, 0.0) for t, _ in prices]

        result = optimizer.solve(
            current_indoor_temp=21.0,
            target_comfort_temp=21.0,
            allowed_drift=1.0,
            preheat_boost=1.0,
            mode=MODE_BALANCED,
            prices=prices,
            outdoor_forecast=weather,
        )

        intervals = result.intervals
        # Cheap night intervals should have high score
        self.assertGreaterEqual(intervals[0].consumer_score, 80)
        self.assertEqual(intervals[0].consumer_rating, "optimal")

        # Peak hours should have low score
        self.assertLess(intervals[3].consumer_score, 40)
        self.assertEqual(intervals[3].consumer_rating, "avoid")

        # Best consumer hours should prioritize the cheapest night hours (avoiding morning peaks)
        self.assertEqual(len(result.best_consumer_hours), 3)
        best_times = [h["time"] for h in result.best_consumer_hours]
        self.assertIn("00:00", best_times)
        self.assertIn("01:00", best_times)
        self.assertNotIn("08:00", best_times)

    def test_shower_scoring_with_delayed_reheat(self):
        """Test shower scoring specifically verifying delayed boiler reheating dynamics."""
        model = BuildingThermalModel(c_th=6.0, r_th=3.5, q_internal=0.4)
        optimizer = EnergyOptimizer(thermal_model=model)

        # Scenario:
        # Hour 0 (04:00): cheap (0.50 SEK)
        # Hour 1 (05:00): cheap (0.50 SEK)
        # Hour 2 (06:00): SPIKE to 3.00 SEK (winter morning peak)
        # Hour 3 (07:00): SPIKE to 3.20 SEK
        # Hour 4 (08:00): SPIKE to 3.00 SEK
        # Hour 5 (21:00): expensive (2.00 SEK)
        # Hour 6 (22:00): cheap night drop (0.60 SEK)
        # Hour 7 (23:00): cheap night drop (0.50 SEK)
        now = datetime.datetime(2026, 1, 15, 4, 0)  # 04:00 winter Thursday
        prices = [
            (now + datetime.timedelta(hours=0), 0.50),  # 04:00
            (now + datetime.timedelta(hours=1), 0.50),  # 05:00
            (now + datetime.timedelta(hours=2), 3.00),  # 06:00
            (now + datetime.timedelta(hours=3), 3.20),  # 07:00
            (now + datetime.timedelta(hours=4), 3.00),  # 08:00
        ]
        weather = [(t, 0.0) for t, _ in prices]

        result = optimizer.solve(
            current_indoor_temp=21.0,
            target_comfort_temp=21.0,
            allowed_drift=1.0,
            preheat_boost=1.0,
            mode=MODE_BALANCED,
            prices=prices,
            outdoor_forecast=weather,
        )

        inv_04 = result.intervals[0]  # 04:00
        inv_05 = result.intervals[1]  # 05:00

        # At 05:00, direct spot price is only 0.50 SEK.
        # BUT showering at 05:00 means boiler reheats at 06:00 (3.00 SEK) and 07:00 (3.20 SEK)!
        # Therefore, shower score at 05:00 must be significantly lower than at 04:00.
        self.assertGreater(inv_05.shower_effective_price, inv_04.shower_effective_price)
        self.assertLess(inv_05.shower_score, inv_04.shower_score)
        self.assertIn("05:00 - 07:30", inv_05.shower_reheat_window)


if __name__ == "__main__":
    unittest.main()


