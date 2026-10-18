/**
 * Smart Energy & Thermal Optimizer Lovelace Card
 *
 * Visual showcase of Heat Pump (Mitsubishi WF-RAC), Water Boiler,
 * Electricity Prices (accounting for Göteborg Energi grid transmission tariffs,
 * Swedish energy taxes, supplier surcharges, and VAT), Big Consumers Breakdown,
 * and Quick Optimization Mode Controls.
 */

class SmartEnergyOptimizerCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._selectedHourIndex = null;
  }

  setConfig(config) {
    this._config = {
      title: "Smart Energy & Thermal Optimizer",
      schedule_sensor: "sensor.smart_energy_current_action",
      forecast_sensor: "sensor.smart_energy_projected_indoor_temp",
      price_sensor: "sensor.smart_energy_total_electricity_price",
      big_consumers_sensor: "sensor.smart_energy_big_consumers_total_power",
      climate_entity: "climate.smart_energy_heat_pump_controller",
      mode_select: "select.smart_energy_optimization_mode",
      savings_sensor: "sensor.smart_energy_estimated_savings_today",
      tau_sensor: "sensor.smart_energy_building_thermal_time_constant",
      cop_sensor: "sensor.smart_energy_heat_pump_estimated_cop",
      ...config,
    };
  }

  set hass(hass) {
    this._hass = hass;
    this.render();
  }

  getCardSize() {
    return 6;
  }

  _callService(domain, service, data) {
    if (this._hass) {
      this._hass.callService(domain, service, data);
    }
  }

  _setMode(mode) {
    const selectEntity = this._config.mode_select;
    if (selectEntity && this._hass.states[selectEntity]) {
      this._callService("select", "select_option", {
        entity_id: selectEntity,
        option: mode,
      });
    }
  }

  _adjustTemp(delta) {
    const climateEntity = this._config.climate_entity;
    const stateObj = this._hass.states[climateEntity];
    if (stateObj && stateObj.attributes.temperature !== undefined) {
      const newTemp = Math.round((stateObj.attributes.temperature + delta) * 2) / 2;
      this._callService("climate", "set_temperature", {
        entity_id: climateEntity,
        temperature: newTemp,
      });
    }
  }

  render() {
    if (!this._hass || !this._config) return;

    const scheduleState = this._hass.states[this._config.schedule_sensor];
    const savingsState = this._hass.states[this._config.savings_sensor];
    const climateState = this._hass.states[this._config.climate_entity];
    const consumersState = this._hass.states[this._config.big_consumers_sensor];
    const tauState = this._hass.states[this._config.tau_sensor];
    const copState = this._hass.states[this._config.cop_sensor];
    const modeState = this._hass.states[this._config.mode_select];

    const currentMode = modeState ? modeState.state : "balanced";
    const currentAction = scheduleState ? scheduleState.state : "normal";
    const currentTemp = climateState ? climateState.attributes.current_temperature || "--" : "--";
    const targetTemp = climateState ? climateState.attributes.temperature || 21.0 : 21.0;
    const savingsPct = savingsState ? savingsState.state : "0";
    const tauVal = tauState ? tauState.state : "--";
    const copVal = copState ? copState.state : "3.5";

    const schedule = (scheduleState && scheduleState.attributes && scheduleState.attributes.schedule) || [];
    const consumers = (consumersState && consumersState.attributes && consumersState.attributes.consumers) || [];

    // Current hour values
    const currentHour = schedule.length > 0 ? schedule[0] : null;
    const currentPrice = currentHour ? currentHour.price : 0.20;
    const currentOutdoor = currentHour ? currentHour.outdoor_temp : "--";
    const hpPower = currentHour ? currentHour.hp_power_kw : 0.0;
    const boilerPower = currentHour ? currentHour.boiler_power_kw : 0.0;
    const boilerAction = currentHour ? currentHour.boiler_action : "off";
    const spotPrice = currentHour && currentHour.spot_price !== undefined ? currentHour.spot_price : currentPrice;
    const gridFee = currentHour && currentHour.grid_fee !== undefined ? currentHour.grid_fee : 0.0;
    const energyTax = currentHour && currentHour.energy_tax !== undefined ? currentHour.energy_tax : 0.0;
    const isHighLoad = currentHour ? Boolean(currentHour.is_high_load) : false;
    const targetSetpoint = currentHour && currentHour.target_setpoint ? currentHour.target_setpoint : targetTemp;

    // Build SVG chart data for 24h price & action timeline
    const chartHtml = this._renderTimelineChart(schedule);

    // Build Big consumers list
    const consumersHtml = this._renderConsumers(consumers, hpPower, boilerPower);

    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
        }
        ha-card {
          padding: 16px;
          border-radius: 16px;
          background: var(--ha-card-background, var(--card-background-color, #1e1e24));
          color: var(--primary-text-color, #ffffff);
          box-shadow: var(--ha-card-box-shadow, 0 4px 14px rgba(0,0,0,0.25));
          font-family: var(--paper-font-body1_-_font-family, system-ui, -apple-system, sans-serif);
        }
        .header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 14px;
        }
        .title-row {
          display: flex;
          align-items: center;
          gap: 10px;
        }
        .title {
          font-size: 1.15rem;
          font-weight: 600;
        }
        .savings-badge {
          background: linear-gradient(135deg, #10b981, #059669);
          color: #ffffff;
          padding: 4px 10px;
          border-radius: 20px;
          font-size: 0.8rem;
          font-weight: 700;
          display: flex;
          align-items: center;
          gap: 4px;
        }
        .action-banner {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 10px 14px;
          border-radius: 12px;
          background: rgba(255, 255, 255, 0.05);
          margin-bottom: 16px;
          border-left: 4px solid var(--state-color, #3b82f6);
        }
        .action-banner.boost {
          border-left-color: #f59e0b;
          background: rgba(245, 158, 11, 0.12);
        }
        .action-banner.eco {
          border-left-color: #06b6d4;
          background: rgba(6, 182, 212, 0.12);
        }
        .action-banner.normal {
          border-left-color: #3b82f6;
        }
        .action-text {
          font-weight: 600;
          font-size: 0.95rem;
          text-transform: capitalize;
        }
        .temp-display {
          display: flex;
          align-items: baseline;
          gap: 6px;
        }
        .temp-val {
          font-size: 1.4rem;
          font-weight: 700;
        }
        .temp-sub {
          font-size: 0.85rem;
          opacity: 0.7;
        }

        /* Mode Selection Pills */
        .mode-selector {
          display: flex;
          gap: 8px;
          margin-bottom: 16px;
          background: rgba(0, 0, 0, 0.2);
          padding: 4px;
          border-radius: 12px;
        }
        .mode-btn {
          flex: 1;
          padding: 8px 4px;
          border: none;
          border-radius: 8px;
          background: transparent;
          color: var(--primary-text-color, #fff);
          font-size: 0.78rem;
          font-weight: 600;
          cursor: pointer;
          transition: all 0.2s ease;
          text-align: center;
        }
        .mode-btn:hover {
          background: rgba(255, 255, 255, 0.08);
        }
        .mode-btn.active {
          background: var(--primary-color, #3b82f6);
          color: #fff;
          box-shadow: 0 2px 8px rgba(59, 130, 246, 0.4);
        }

        /* Quick Temp Control */
        .temp-control-row {
          display: flex;
          align-items: center;
          justify-content: space-between;
          background: rgba(255, 255, 255, 0.03);
          border-radius: 12px;
          padding: 8px 14px;
          margin-bottom: 16px;
        }
        .btn-circle {
          width: 32px;
          height: 32px;
          border-radius: 50%;
          border: none;
          background: rgba(255, 255, 255, 0.1);
          color: #fff;
          font-size: 1.2rem;
          cursor: pointer;
          display: flex;
          align-items: center;
          justify-content: center;
          transition: background 0.2s;
        }
        .btn-circle:hover {
          background: rgba(255, 255, 255, 0.2);
        }

        /* Asset Grid: Heat Pump & Boiler */
        .assets-grid {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 12px;
          margin-bottom: 16px;
        }
        .asset-card {
          background: rgba(255, 255, 255, 0.04);
          border-radius: 12px;
          padding: 12px;
          display: flex;
          flex-direction: column;
          gap: 6px;
          border: 1px solid rgba(255, 255, 255, 0.06);
        }
        .asset-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          font-size: 0.85rem;
          opacity: 0.8;
        }
        .asset-val {
          font-size: 1.3rem;
          font-weight: 700;
        }
        .asset-meta {
          font-size: 0.75rem;
          opacity: 0.7;
          display: flex;
          justify-content: space-between;
        }

        /* Timeline Section */
        .section-title {
          font-size: 0.85rem;
          font-weight: 600;
          text-transform: uppercase;
          letter-spacing: 0.5px;
          opacity: 0.7;
          margin-bottom: 8px;
          display: flex;
          justify-content: space-between;
        }
        .chart-container {
          background: rgba(0, 0, 0, 0.25);
          border-radius: 12px;
          padding: 10px;
          margin-bottom: 16px;
          overflow-x: auto;
        }
        .chart-legend {
          display: flex;
          gap: 12px;
          font-size: 0.72rem;
          opacity: 0.8;
          margin-top: 6px;
          justify-content: flex-end;
          flex-wrap: wrap;
        }
        .legend-item {
          display: flex;
          align-items: center;
          gap: 4px;
        }
        .legend-dot {
          width: 8px;
          height: 8px;
          border-radius: 2px;
        }

        /* Consumers Breakdown */
        .consumers-box {
          background: rgba(255, 255, 255, 0.03);
          border-radius: 12px;
          padding: 12px;
          margin-bottom: 16px;
        }
        .consumer-row {
          display: flex;
          align-items: center;
          justify-content: space-between;
          margin-bottom: 8px;
          font-size: 0.85rem;
        }
        .progress-bar-bg {
          height: 6px;
          background: rgba(255, 255, 255, 0.1);
          border-radius: 3px;
          overflow: hidden;
          margin-top: 3px;
        }
        .progress-bar-fill {
          height: 100%;
          border-radius: 3px;
          background: var(--primary-color, #3b82f6);
        }

        /* Thermal Intelligence Footer */
        .intel-row {
          display: grid;
          grid-template-columns: repeat(3, 1fr);
          gap: 8px;
          font-size: 0.75rem;
          background: rgba(0, 0, 0, 0.2);
          border-radius: 10px;
          padding: 10px;
          text-align: center;
        }
        .intel-metric {
          font-size: 1.05rem;
          font-weight: 700;
          color: #60a5fa;
        }
        .intel-label {
          opacity: 0.7;
          margin-top: 2px;
        }
      </style>

      <ha-card>
        <!-- Header -->
        <div class="header">
          <div class="title-row">
            <span class="title">${this._config.title}</span>
          </div>
          <div class="savings-badge">
            ⚡ ${savingsPct}% Savings Today
          </div>
        </div>

        <!-- Action & Status Banner -->
        <div class="action-banner ${currentAction}">
          <div>
            <div class="action-text">Status: ${currentAction === "boost" ? "Pre-Heat Boost (Low Tariff)" : currentAction === "eco" ? "Eco Coasting (Peak Tariff)" : "Optimal Heating"}</div>
            <div style="font-size:0.75rem; opacity:0.85; margin-top:3px; display:flex; align-items:center; gap:8px;">
              <span>Total: <b>${currentPrice.toFixed(2)} SEK/kWh</b></span>
              <span style="background:${isHighLoad ? 'rgba(239, 68, 68, 0.2)' : 'rgba(16, 185, 129, 0.2)'}; color:${isHighLoad ? '#f87171' : '#34d399'}; padding:1px 6px; border-radius:6px; font-weight:600; font-size:0.7rem;">
                ${isHighLoad ? '⚡ Göteborg Energi Höglast' : '🌱 Göteborg Energi Låglast'}
              </span>
            </div>
            <div style="font-size:0.68rem; opacity:0.65; margin-top:2px;">
              Spot: ${(spotPrice).toFixed(2)} | Nät: ${(gridFee).toFixed(2)} | Skatt: ${(energyTax).toFixed(2)} | Outdoor: ${currentOutdoor}°C
            </div>
          </div>
          <div class="temp-display">
            <span class="temp-val">${currentTemp}°C</span>
            <span class="temp-sub">/ ${targetTemp}°C</span>
          </div>
        </div>

        <!-- Mode Selector -->
        <div class="mode-selector">
          <button class="mode-btn ${currentMode === "price_optimized" ? "active" : ""}" id="btn-mode-price">
            💰 Price Optimized
          </button>
          <button class="mode-btn ${currentMode === "balanced" ? "active" : ""}" id="btn-mode-balanced">
            ⚖️ Balanced
          </button>
          <button class="mode-btn ${currentMode === "stable_temperature" ? "active" : ""}" id="btn-mode-stable">
            🌡️ Stable Temp
          </button>
        </div>

        <!-- Quick Temp Adjustment -->
        <div class="temp-control-row">
          <span style="font-size:0.85rem; opacity:0.8;">Target Comfort Temperature</span>
          <div style="display:flex; align-items:center; gap:10px;">
            <button class="btn-circle" id="btn-temp-minus">-</button>
            <span style="font-weight:700; font-size:1.1rem;">${targetTemp} °C</span>
            <button class="btn-circle" id="btn-temp-plus">+</button>
          </div>
        </div>

        <!-- Heat Pump & Boiler Tiles -->
        <div class="assets-grid">
          <div class="asset-card">
            <div class="asset-header">
              <span>🔥 Heat Pump (Mitsubishi WF-RAC)</span>
              <span style="color:${hpPower > 0.05 ? "#10b981" : "#94a3b8"}">${hpPower > 0.05 ? "ACTIVE" : "STANDBY"}</span>
            </div>
            <div class="asset-val">${hpPower.toFixed(2)} <span style="font-size:0.8rem; font-weight:normal;">kW</span></div>
            <div class="asset-meta">
              <span>Set: <b>${targetSetpoint}°C</b></span>
              <span>COP: <b>${copVal}</b> (${(hpPower * parseFloat(copVal || 3.0)).toFixed(1)} kW th)</span>
            </div>
          </div>

          <div class="asset-card">
            <div class="asset-header">
              <span>💧 Water Boiler</span>
              <span style="color:${boilerAction === "heating" ? "#f59e0b" : "#94a3b8"}">${boilerAction === "heating" ? "HEATING" : "IDLE"}</span>
            </div>
            <div class="asset-val">${boilerPower.toFixed(2)} <span style="font-size:0.8rem; font-weight:normal;">kW</span></div>
            <div class="asset-meta">
              <span>Dispatch: <b>${boilerAction === "heating" ? "Scheduled Low" : "Standby"}</b></span>
            </div>
          </div>
        </div>

        <!-- 24h Interactive Timeline Chart -->
        <div class="section-title">
          <span>24-Hour Price & Scheduled Action Timeline</span>
        </div>
        <div class="chart-container">
          ${chartHtml}
          <div class="chart-legend">
            <div class="legend-item"><div class="legend-dot" style="background:#10b981;"></div> Low Price</div>
            <div class="legend-item"><div class="legend-dot" style="background:#ef4444;"></div> Peak Price</div>
            <div class="legend-item"><div class="legend-dot" style="background:#f59e0b;"></div> HP Boost</div>
            <div class="legend-item"><div class="legend-dot" style="background:#06b6d4;"></div> Boiler Active</div>
          </div>
        </div>

        <!-- Big Consumers Breakdown -->
        <div class="section-title">
          <span>Live Big Consumers Breakdown</span>
        </div>
        <div class="consumers-box">
          ${consumersHtml}
        </div>

        <!-- Thermal Building Intelligence -->
        <div class="section-title">
          <span>Self-Learning Building Thermal Intelligence</span>
        </div>
        <div class="intel-row">
          <div>
            <div class="intel-metric">${tauVal} h</div>
            <div class="intel-label">Building Inertia (τ)</div>
          </div>
          <div>
            <div class="intel-metric">${copVal}</div>
            <div class="intel-label">Active COP</div>
          </div>
          <div>
            <div class="intel-metric">Adaptive</div>
            <div class="intel-label">RLS Estimator</div>
          </div>
        </div>
      </ha-card>
    `;

    // Event listeners
    this.shadowRoot.getElementById("btn-mode-price")?.addEventListener("click", () => this._setMode("price_optimized"));
    this.shadowRoot.getElementById("btn-mode-balanced")?.addEventListener("click", () => this._setMode("balanced"));
    this.shadowRoot.getElementById("btn-mode-stable")?.addEventListener("click", () => this._setMode("stable_temperature"));

    this.shadowRoot.getElementById("btn-temp-minus")?.addEventListener("click", () => this._adjustTemp(-0.5));
    this.shadowRoot.getElementById("btn-temp-plus")?.addEventListener("click", () => this._adjustTemp(0.5));
  }

  _renderTimelineChart(schedule) {
    if (!schedule || schedule.length === 0) {
      return `<div style="text-align:center; padding:20px; opacity:0.6;">Awaiting schedule forecast...</div>`;
    }

    const items = schedule.slice(0, 24);
    const maxPrice = Math.max(...items.map((i) => i.price), 0.1);
    const minPrice = Math.min(...items.map((i) => i.price), 0.0);
    const priceRange = maxPrice - minPrice || 0.1;

    const width = 480;
    const height = 110;
    const barWidth = width / items.length;

    let bars = "";
    items.forEach((item, idx) => {
      const x = idx * barWidth;
      const normalizedPrice = (item.price - minPrice) / priceRange;
      const barHeight = Math.max(12, normalizedPrice * 60);
      const y = height - barHeight - 20;

      // Color based on price percentile
      let color = "#10b981"; // green
      if (normalizedPrice > 0.7) color = "#ef4444"; // red
      else if (normalizedPrice > 0.4) color = "#f59e0b"; // yellow/orange

      // Indicator bar for action
      let actionIndicator = "";
      if (item.action === "boost") {
        actionIndicator = `<rect x="${x + 1}" y="${height - 18}" width="${barWidth - 2}" height="5" fill="#f59e0b" rx="2" />`;
      } else if (item.action === "eco") {
        actionIndicator = `<rect x="${x + 1}" y="${height - 18}" width="${barWidth - 2}" height="3" fill="#06b6d4" rx="1" />`;
      }

      // Boiler indicator
      let boilerDot = "";
      if (item.boiler_action === "heating") {
        boilerDot = `<circle cx="${x + barWidth / 2}" cy="10" r="3.5" fill="#06b6d4" />`;
      }

      const timeLabel = new Date(item.time).getHours() + "h";
      const showLabel = idx % 3 === 0;
      const tooltip = `${timeLabel}: ${item.price.toFixed(2)} SEK/kWh (Spot: ${(item.spot_price || 0).toFixed(2)} + Nät: ${(item.grid_fee || 0).toFixed(2)}${item.is_high_load ? ' [Höglast]' : ' [Låglast]'} + Skatt: ${(item.energy_tax || 0).toFixed(2)}) | Action: ${item.action} | Outdoor: ${item.outdoor_temp}°C`;

      bars += `
        <g>
          <title>${tooltip}</title>
          <rect x="${x + 2}" y="${y}" width="${barWidth - 4}" height="${barHeight}" fill="${color}" opacity="0.85" rx="3" />
          ${actionIndicator}
          ${boilerDot}
          ${showLabel ? `<text x="${x + barWidth / 2}" y="${height - 2}" font-size="9" fill="#94a3b8" text-anchor="middle">${timeLabel}</text>` : ""}
        </g>
      `;
    });

    return `
      <svg viewBox="0 0 ${width} ${height}" style="width:100%; height:auto; overflow:visible;">
        ${bars}
      </svg>
    `;
  }

  _renderConsumers(consumers, hpPower, boilerPower) {
    const list = [...consumers];

    // Ensure heat pump and boiler are shown even if not in arbitrary list
    if (!list.find((c) => c.name.toLowerCase().includes("heat pump"))) {
      list.unshift({ name: "Heat Pump", power_kw: hpPower });
    }
    if (!list.find((c) => c.name.toLowerCase().includes("boiler"))) {
      list.push({ name: "Water Boiler", power_kw: boilerPower });
    }

    const totalKw = list.reduce((acc, c) => acc + (c.power_kw || 0), 0);
    const maxKw = Math.max(totalKw, 3.0);

    return list
      .map((c) => {
        const pct = maxKw > 0 ? Math.min(100, Math.round((c.power_kw / maxKw) * 100)) : 0;
        return `
        <div style="margin-bottom:8px;">
          <div class="consumer-row">
            <span>${c.name}</span>
            <span style="font-weight:600;">${(c.power_kw || 0).toFixed(2)} kW</span>
          </div>
          <div class="progress-bar-bg">
            <div class="progress-bar-fill" style="width:${pct}%;"></div>
          </div>
        </div>
      `;
      })
      .join("");
  }
}

customElements.define("smart-energy-optimizer-card", SmartEnergyOptimizerCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "smart-energy-optimizer-card",
  name: "Smart Energy & Thermal Optimizer Card",
  preview: true,
  description: "Visual showcase and control for Heat Pump, Boiler, Electricity Prices, and Big Consumers.",
});
