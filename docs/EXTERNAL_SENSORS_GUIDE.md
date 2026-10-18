# External Sensors & Setup Guide
### Smart Energy & Thermal Optimizer for Home Assistant

Integrating home energy management can feel overwhelming when there are too many unfamiliar entity pickers. 

The good news is: **If you have a Mitsubishi WF-RAC heat pump, you already have almost everything built-in!** You only need **one** external integration (for electricity prices).

---

## ⚡ Quick Summary: What Do I Actually Need?

| Asset / Sensor | Where does it come from? | Do I need to buy hardware? | Auto-detected? |
|---|---|---|---|
| **Heat Pump Control** | `climate.<device>` (Mitsubishi WF-RAC) | No, uses your existing Wi-Fi heat pump | **Yes (Select in Setup)** |
| **Indoor Room Temp** | `climate.<device>.attributes.current_temperature` | No, built into the indoor unit | **Yes! Automatic** |
| **Outdoor Temp** | `climate.<device>.attributes.outdoor_temperature` | No, built into the outdoor unit | **Yes! Automatic** |
| **Heat Pump Energy** | `sensor.<device>_energy_consumed` | No, logged internally by WF-RAC | **Yes! Automatic** |
| **Weather Forecast** | `weather.forecast_home` (Met.no or SMHI) | No, built into Home Assistant | **Yes! Automatic** |
| **Electricity Spot Price** | `sensor.nordpool_...` or `sensor.electricity_price_...` | No, free software integration (Nordpool/Tibber) | **Required in Setup** |
| **Water Boiler** | `switch.boiler` (Shelly / smart switch) | Optional (only if you have a smart relay) | Optional |
| **Solar / Battery / EV** | Solar inverter, battery, car charger | Optional | Optional |

> 💡 **Key Takeaway:** If you just want to optimize your heat pump, you only need to select **your Mitsubishi climate entity** and **your Nordpool or Tibber price sensor**. Everything else is handled automatically!

---

## 1. Setting Up the Electricity Spot Price Sensor

Our integration needs hourly spot prices (today and tomorrow's upcoming 24 hours) to forecast and plan thermal pre-heating.

### Option A: Nordpool Integration (Recommended for Sweden & Gothenburg)

The Nordpool integration is the Swedish standard for spot electricity prices. It fetches day-ahead prices directly from Nord Pool Spot.

#### Step 1: Install Nordpool via HACS
1. In Home Assistant, open **HACS** -> **Integrations**.
2. Click the **+ Explore & Download Repositories** button.
3. Search for **Nordpool** and click **Download**.
4. Restart Home Assistant.

#### Step 2: Add the Nordpool Integration
1. Go to **Settings** -> **Devices & Services** -> **Add Integration**.
2. Search for **Nordpool**.
3. Fill in the settings:
   - **Region:** `SE3` *(Gothenburg, Stockholm, and central Sweden are all in Bidding Zone SE3)*.
   - **Currency:** `SEK`.
   - **VAT (Moms):** **Leave UNCHECKED (Off)**. *(Our Smart Energy Optimizer calculates the true all-in cost with Göteborg Energi grid fees, energiskatt, and VAT dynamically).*
   - **Precision:** `3` or `4`.
   - **Low price:** Default.
4. Click **Submit**.

Home Assistant will create an entity named:
```text
sensor.nordpool_kwh_se3_sek_3_10_025
```
*(The exact numbers at the end depend on your chosen precision/surcharge settings).*

#### How it works:
* Every day around **13:00–13:15 CET**, Nord Pool publishes tomorrow's 24 hours of electricity prices.
* The Nordpool sensor automatically populates the `raw_today` and `raw_tomorrow` attributes, allowing the optimizer to plan ahead up to 36 hours.

---

### Option B: Tibber Integration

If you have an electricity contract with **Tibber**, you can use the official Home Assistant Tibber integration:

1. Go to **Settings** -> **Devices & Services** -> **Add Integration** -> **Tibber**.
2. Log in with your Tibber API token.
3. Tibber creates the entity:
   ```text
   sensor.electricity_price_home
   ```
4. In our setup, simply select `sensor.electricity_price_home` as your **Electricity Spot Price Sensor**.
5. Check the box **"Spot Price Sensor Already Includes VAT"** during tariff setup (since Tibber includes moms).

---

### Option C: Entso-e / Energi Data Service

If you use the official ENTSO-e Transparency platform integration or Energi Data Service:
* Select the main price sensor. As long as it has `today`/`tomorrow` or `prices` list in attributes, our integration will parse it automatically.

---

## 2. Mitsubishi WF-RAC Heat Pump (Built-in Sensors)

If you use the **Mitsubishi WF-RAC** integration in Home Assistant (which connects to your heat pump via the WF-RAC Wi-Fi adapter), you **do NOT need any extra temperature sensors or energy meters**!

### How Entities Map Automatically:

1. **Thermostat Climate Entity:**
   - Entity: `climate.<your_heat_pump_name>` (e.g., `climate.living_room_ac`).
   - Used by the optimizer to modulate target temperature in 0.5°C increments.
2. **Indoor Room Temperature:**
   - Automatically read from `climate.<your_heat_pump_name>.attributes.current_temperature`.
   - No Zigbee or Bluetooth room sensor needed.
3. **Outdoor Temperature:**
   - Automatically read from `climate.<your_heat_pump_name>.attributes.outdoor_temperature` or `sensor.<your_heat_pump_name>_outdoor_temperature`.
   - This uses the thermistor mounted directly on your outdoor compressor unit.
4. **Energy Consumption & Power:**
   - Automatically read from `sensor.<your_heat_pump_name>_energy_consumed`.
   - The Mitsubishi inverter motherboard logs cumulative kWh. Our coordinator measures the difference over time ($\Delta \text{kWh}/\Delta t$) to compute active power in kW.

---

## 3. Weather Forecast Entity (Outdoor Forecast)

The optimizer needs to know tomorrow's outdoor temperature to calculate how much heat your house will lose through its walls and windows ($Q_{\text{loss}} = \frac{T_{\text{in}} - T_{\text{out}}}{R_{\text{th}}}$).

### Using the Built-In Home Assistant Weather:
* Every Home Assistant system has a default weather integration pre-installed (Meteorologisk Institutt / Met.no).
* Look under **Developer Tools** -> **States** for:
  ```text
  weather.forecast_home
  ```
  *(or `weather.home`)*
* Our optimizer automatically detects and uses this entity by default. You do not need to install or configure anything!

### Optional: SMHI (Sveriges Meteorologiska och Hydrologiska Institut)
If you prefer official Swedish weather data:
1. Go to **Settings** -> **Devices & Services** -> **Add Integration** -> **SMHI**.
2. Enter your home coordinates.
3. Select the created `weather.smhi_...` entity.

---

## 4. Water Boiler / Varmvattenberedare (Optional)

The domestic hot water (DHW) boiler is typically a 2.0–3.0 kW resistive element that heats water for 2–3 hours a day.

### How to Make Your Boiler Smart:
1. Have a certified electrician install a smart relay capable of continuous resistive loads, such as:
   - **Shelly Plus 1PM** (16A, Wi-Fi)
   - **Shelly Pro 1PM** (DIN-rail mounted in your breaker panel)
   - **Sonoff POW Elite** (16A/20A)
2. In Home Assistant, this creates:
   - A switch: `switch.varmvattenberedare`
   - A power sensor: `sensor.varmvattenberedare_power`
3. In **Smart Energy Optimizer**, configure:
   - **Boiler Entity:** `switch.varmvattenberedare`
   - **Boiler Rated Power:** `2.0` kW (or check your boiler's nameplate rating)
   - **Target Run Hours Per Day:** `2.5` hours
4. **How the optimizer controls it:**
   - The optimizer identifies the cheapest electricity hours of the day (often 02:00–05:00 at night or 13:00–15:00 midday).
   - It turns the boiler ON during those hours and OFF during expensive morning/evening peaks.
   - **Effekttariff Protection:** If your heat pump is boosting, the boiler is automatically delayed to an adjacent hour so the two never run simultaneously!

---

## 5. Real-Time Household Power & Göteborg Energi HAN/P1 Port (Optional)

In Gothenburg, all electricity meters (Kamstrup / Aidon / Landis+Gyr) installed by Göteborg Energi Elnät have a **customer interface port (RJ12 HAN / P1)**.

### Why Connect to the HAN Port?
* Gives you sub-second real-time household power consumption (W and kW).
* Lets the optimizer track your actual total villa power against Göteborg Energi's **Effekttariff limit** (e.g. 4.5 kW).

### How to Set It Up:
1. **Activate the Port (Free):**
   - Log in to **Göteborg Energi Mina Sidor** (goteborgenergi.se).
   - Go to your electricity contract and click **Aktivera HAN-porten** (customer port RJ12). It usually activates within 24–48 hours.
2. **Choose a P1 Hardware Reader:**
   - **Tibber Pulse P1:** Plugs directly into the RJ12 port; integrates seamlessly into Home Assistant via the Tibber integration.
   - **HomeWizard Wi-Fi P1 Meter:** Plugs into the RJ12 port; has a local Home Assistant integration with zero cloud dependency.
   - **SlimmeLezer+ / Pow-K (ESPHome):** Open-source Wi-Fi P1 dongle that talks directly to Home Assistant.
3. In Home Assistant, you get:
   - `sensor.power_production_p1` / `sensor.household_active_power`
4. Add this sensor under **Big Consumers** in the optimizer to display your total villa load on your dashboard!

---

## 6. Solar PV, Home Battery & EV Charger (Optional)

If your home has solar panels, battery storage, or an electric vehicle charger:

### Solar Generation Forecast:
* Install the **Solcast PV Forecast** or **Forecast.Solar** integration from HACS.
* Select `sensor.solcast_pv_forecast_power_now` as your **Solar Production Forecast Entity**.
* The optimizer will delay pre-heating if free solar power is expected in the afternoon!

### Home Battery:
* Works with **Huawei FusionSolar**, **Growatt**, **Fronius**, **SolarEdge**, or **Victron**.
* Select:
  - Usable Battery Capacity: e.g. `10.0` kWh
  - State of Charge (SOC): `sensor.battery_state_of_charge` (%)
  - Power: `sensor.battery_charge_discharge_power` (W or kW)

### EV Charger:
* Works with **Easee**, **Zaptec**, **Wallbox**, or **go-eCharger**.
* Select your charger switch entity (`switch.charger_enabled`) and active power sensor (`sensor.charger_power`).
* The optimizer automatically ensures the car charges during lowest-cost hours and pauses charging if the heat pump pre-heats, avoiding effekttariff spikes.

---

## Need Help?

If you ever need to adjust your settings, you do not need to re-install! Simply go to:
**Settings** -> **Devices & Services** -> **Smart Energy & Thermal Optimizer** -> **Configure**.
