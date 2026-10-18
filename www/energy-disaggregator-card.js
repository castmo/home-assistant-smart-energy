/**
 * Energy Disaggregator & Power Signature Monitor Lovelace Card
 *
 * Real-time 3-phase grid power monitoring from HomeWizard P1 meter,
 * interactive human-in-the-loop load confirmation banner, and
 * disaggregated power & energy breakdown for large household consumers.
 */

class EnergyDisaggregatorCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._selectedConsumerOverride = null;
  }

  setConfig(config) {
    this._config = {
      title: "Energy Disaggregator & Load Monitor",
      phase_l1_sensor: "sensor.p1_meter_active_power_l1",
      phase_l2_sensor: "sensor.p1_meter_active_power_l2",
      phase_l3_sensor: "sensor.p1_meter_active_power_l3",
      total_power_sensor: "sensor.p1_meter_active_power",
      pending_event_sensor: "sensor.energy_disaggregator_pending_event",
      awaiting_confirmation_sensor: "binary_sensor.energy_disaggregator_awaiting_confirmation",
      pending_select_entity: "select.energy_disaggregator_assigned_consumer",
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

  _confirmEvent(consumerId) {
    this._callService("energy_disaggregator", "confirm_event", {
      consumer: consumerId,
    });
  }

  _markUnknown() {
    this._callService("energy_disaggregator", "mark_unknown", {});
  }

  _getState(entityId, defaultVal = 0) {
    if (!this._hass || !entityId) return defaultVal;
    const stateObj = this._hass.states[entityId];
    if (!stateObj || isNaN(parseFloat(stateObj.state))) return defaultVal;
    return parseFloat(stateObj.state);
  }

  _findConsumers() {
    if (!this._hass) return [];
    const consumers = [];
    const states = this._hass.states;

    const consumerKeys = [
      { id: "boiler", name: "Water Boiler", icon: "mdi:water-boiler" },
      { id: "stove", name: "Stove / Induction", icon: "mdi:stove" },
      { id: "oven", name: "Oven", icon: "mdi:toaster-oven" },
      { id: "car_charger", name: "EV Car Charger", icon: "mdi:ev-station" },
      { id: "washer", name: "Washing Machine", icon: "mdi:washing-machine" },
      { id: "dryer", name: "Tumble Dryer", icon: "mdi:tumble-dryer" },
      { id: "dishwasher", name: "Dishwasher", icon: "mdi:dishwasher" },
      { id: "heat_pump", name: "Heat Pump", icon: "mdi:heat-pump" },
    ];

    for (const c of consumerKeys) {
      // Find power sensor
      let pSensor = null;
      let eSensor = null;
      let aSensor = null;

      for (const [eid, stateObj] of Object.entries(states)) {
        if (eid.includes(c.id)) {
          if (eid.endsWith("_power")) pSensor = stateObj;
          else if (eid.endsWith("_energy")) eSensor = stateObj;
          else if (eid.endsWith("_active")) aSensor = stateObj;
        }
      }

      const power = pSensor ? parseFloat(pSensor.state) || 0 : 0;
      const energy = eSensor ? parseFloat(eSensor.state) || 0 : 0;
      const isActive = aSensor ? aSensor.state === "on" : power > 50;

      consumers.push({
        id: c.id,
        name: c.name,
        icon: c.icon,
        power,
        energy,
        isActive,
      });
    }

    return consumers;
  }

  render() {
    if (!this._hass) return;

    // 3-Phase readings
    const p1 = this._getState(this._config.phase_l1_sensor, 0);
    const p2 = this._getState(this._config.phase_l2_sensor, 0);
    const p3 = this._getState(this._config.phase_l3_sensor, 0);
    let totalP = this._getState(this._config.total_power_sensor, null);
    if (totalP === null || totalP === 0) {
      totalP = p1 + p2 + p3;
    }

    // Pending event
    let pendingEvent = null;
    let isAwaiting = false;

    // Check awaiting binary sensor or pending sensor
    for (const [eid, stateObj] of Object.entries(this._hass.states)) {
      if (eid.includes("awaiting_confirmation") && stateObj.state === "on") {
        isAwaiting = true;
      }
      if (eid.includes("pending_event") && stateObj.attributes && stateObj.attributes.event_id) {
        pendingEvent = stateObj.attributes;
      }
    }

    const consumers = this._findConsumers();
    const disaggregatedTotal = consumers.reduce(
      (acc, c) => acc + (c.isActive ? c.power : 0),
      0
    );
    const unassignedPower = Math.max(0, totalP - disaggregatedTotal);

    const maxPhase = Math.max(p1, p2, p3, 2000);
    const p1Percent = Math.min(100, Math.round((p1 / maxPhase) * 100));
    const p2Percent = Math.min(100, Math.round((p2 / maxPhase) * 100));
    const p3Percent = Math.min(100, Math.round((p3 / maxPhase) * 100));

    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
        }
        ha-card {
          padding: 18px 20px 22px 20px;
          border-radius: 16px;
          background: var(--card-background-color, #1e1e24);
          box-shadow: 0 8px 24px rgba(0, 0, 0, 0.25);
          color: var(--primary-text-color, #ffffff);
          font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        }
        .header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 16px;
        }
        .header h2 {
          margin: 0;
          font-size: 1.25rem;
          font-weight: 600;
          display: flex;
          align-items: center;
          gap: 8px;
        }
        .grid-total {
          font-size: 1.35rem;
          font-weight: 700;
          color: #ffb74d;
        }
        .phase-bars {
          display: grid;
          grid-template-columns: repeat(3, 1fr);
          gap: 12px;
          margin-bottom: 20px;
          background: rgba(255, 255, 255, 0.04);
          padding: 14px;
          border-radius: 12px;
        }
        .phase-col {
          display: flex;
          flex-direction: column;
          gap: 6px;
        }
        .phase-title {
          font-size: 0.8rem;
          color: var(--secondary-text-color, #9e9e9e);
          text-transform: uppercase;
          font-weight: 600;
        }
        .phase-val {
          font-size: 1.1rem;
          font-weight: 700;
        }
        .bar-bg {
          height: 6px;
          border-radius: 4px;
          background: rgba(255, 255, 255, 0.1);
          overflow: hidden;
        }
        .bar-fill {
          height: 100%;
          border-radius: 4px;
          transition: width 0.4s ease;
        }
        .p1-bar { background: #42a5f5; }
        .p2-bar { background: #66bb6a; }
        .p3-bar { background: #ab47bc; }

        /* Notification Banner */
        .notification-banner {
          background: linear-gradient(135deg, rgba(255, 167, 38, 0.2), rgba(239, 83, 80, 0.2));
          border: 1px solid rgba(255, 167, 38, 0.5);
          border-radius: 14px;
          padding: 16px;
          margin-bottom: 20px;
          animation: pulseBanner 2.5s infinite;
        }
        @keyframes pulseBanner {
          0% { box-shadow: 0 0 0 0 rgba(255, 167, 38, 0.4); }
          70% { box-shadow: 0 0 0 10px rgba(255, 167, 38, 0); }
          100% { box-shadow: 0 0 0 0 rgba(255, 167, 38, 0); }
        }
        .banner-header {
          display: flex;
          align-items: center;
          gap: 10px;
          font-weight: 700;
          font-size: 1.05rem;
          margin-bottom: 8px;
          color: #ffa726;
        }
        .banner-details {
          font-size: 0.88rem;
          line-height: 1.4;
          margin-bottom: 14px;
          color: var(--primary-text-color, #fff);
        }
        .banner-actions {
          display: flex;
          flex-wrap: wrap;
          gap: 10px;
          align-items: center;
        }
        button.action-btn {
          border: none;
          padding: 8px 16px;
          border-radius: 8px;
          font-size: 0.88rem;
          font-weight: 600;
          cursor: pointer;
          transition: all 0.2s ease;
          display: flex;
          align-items: center;
          gap: 6px;
        }
        .btn-confirm {
          background: #4caf50;
          color: #ffffff;
        }
        .btn-confirm:hover {
          background: #43a047;
          transform: translateY(-1px);
        }
        .btn-unknown {
          background: rgba(255, 255, 255, 0.12);
          color: #eeeeee;
        }
        .btn-unknown:hover {
          background: rgba(255, 255, 255, 0.2);
        }
        select.consumer-select {
          background: rgba(0, 0, 0, 0.35);
          border: 1px solid rgba(255, 255, 255, 0.2);
          color: #fff;
          padding: 8px 12px;
          border-radius: 8px;
          font-size: 0.88rem;
          outline: none;
          cursor: pointer;
        }

        /* Consumer Grid */
        .consumers-title {
          font-size: 0.95rem;
          font-weight: 600;
          margin-bottom: 12px;
          color: var(--secondary-text-color, #9e9e9e);
          display: flex;
          justify-content: space-between;
        }
        .consumers-grid {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
          gap: 12px;
        }
        .consumer-tile {
          background: rgba(255, 255, 255, 0.03);
          border: 1px solid rgba(255, 255, 255, 0.08);
          border-radius: 12px;
          padding: 12px 14px;
          display: flex;
          flex-direction: column;
          gap: 6px;
          position: relative;
          transition: all 0.2s ease;
        }
        .consumer-tile.active {
          border-color: rgba(76, 175, 80, 0.6);
          background: rgba(76, 175, 80, 0.08);
        }
        .c-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
        }
        .c-name {
          font-size: 0.88rem;
          font-weight: 600;
          display: flex;
          align-items: center;
          gap: 6px;
        }
        .status-dot {
          width: 8px;
          height: 8px;
          border-radius: 50%;
          background: #757575;
        }
        .status-dot.active {
          background: #4caf50;
          box-shadow: 0 0 8px #4caf50;
          animation: pulseDot 1.5s infinite;
        }
        @keyframes pulseDot {
          0% { transform: scale(0.9); opacity: 0.8; }
          50% { transform: scale(1.2); opacity: 1; }
          100% { transform: scale(0.9); opacity: 0.8; }
        }
        .c-power {
          font-size: 1.15rem;
          font-weight: 700;
        }
        .c-energy {
          font-size: 0.78rem;
          color: var(--secondary-text-color, #9e9e9e);
        }

        /* Footer breakdown */
        .footer-breakdown {
          margin-top: 18px;
          padding-top: 14px;
          border-top: 1px solid rgba(255, 255, 255, 0.08);
          display: flex;
          justify-content: space-between;
          font-size: 0.85rem;
          color: var(--secondary-text-color, #9e9e9e);
        }
        .footer-breakdown strong {
          color: var(--primary-text-color, #ffffff);
        }
      </style>

      <ha-card>
        <div class="header">
          <h2>
            <ha-icon icon="mdi:flash"></ha-icon>
            ${this._config.title}
          </h2>
          <div class="grid-total">${Math.round(totalP)} W</div>
        </div>

        <!-- 3-Phase Grid Meter -->
        <div class="phase-bars">
          <div class="phase-col">
            <div class="phase-title">Phase L1</div>
            <div class="phase-val" style="color: #42a5f5;">${Math.round(p1)} W</div>
            <div class="bar-bg">
              <div class="bar-fill p1-bar" style="width: ${p1Percent}%;"></div>
            </div>
          </div>
          <div class="phase-col">
            <div class="phase-title">Phase L2</div>
            <div class="phase-val" style="color: #66bb6a;">${Math.round(p2)} W</div>
            <div class="bar-bg">
              <div class="bar-fill p2-bar" style="width: ${p2Percent}%;"></div>
            </div>
          </div>
          <div class="phase-col">
            <div class="phase-title">Phase L3</div>
            <div class="phase-val" style="color: #ab47bc;">${Math.round(p3)} W</div>
            <div class="bar-bg">
              <div class="bar-fill p3-bar" style="width: ${p3Percent}%;"></div>
            </div>
          </div>
        </div>

        <!-- Interactive Notification & Confirmation Banner -->
        ${
          (isAwaiting || pendingEvent)
            ? `
          <div class="notification-banner">
            <div class="banner-header">
              <ha-icon icon="mdi:bell-ring"></ha-icon>
              New Power Load Detected (${pendingEvent && pendingEvent.edge ? `+${Math.round(pendingEvent.edge.delta_total)} W` : "Step Trigger"})
            </div>
            <div class="banner-details">
              Pattern: <strong>${pendingEvent && pendingEvent.edge ? pendingEvent.edge.phase_pattern : "3-phase"}</strong>
              ${
                pendingEvent && pendingEvent.edge
                  ? `(L1: ${Math.round(pendingEvent.edge.delta_l1)}W, L2: ${Math.round(pendingEvent.edge.delta_l2)}W, L3: ${Math.round(pendingEvent.edge.delta_l3)}W)`
                  : ""
              }<br/>
              Proposed Appliance: <strong>${
                pendingEvent ? pendingEvent.proposed_consumer.replace("_", " ").toUpperCase() : "Unknown"
              }</strong>
              ${pendingEvent ? `(${Math.round(pendingEvent.confidence)}% confidence)` : ""}
            </div>
            <div class="banner-actions">
              <button class="action-btn btn-confirm" id="btn-confirm-proposal">
                <ha-icon icon="mdi:check"></ha-icon>
                Confirm ${pendingEvent ? pendingEvent.proposed_consumer.replace("_", " ").toUpperCase() : "Default"}
              </button>

              <select class="consumer-select" id="consumer-override-select">
                <option value="">-- Change Device --</option>
                ${consumers
                  .map(
                    (c) =>
                      `<option value="${c.id}">${c.name}</option>`
                  )
                  .join("")}
                <option value="unknown">Unknown / Ignore</option>
              </select>

              <button class="action-btn btn-unknown" id="btn-mark-unknown">
                <ha-icon icon="mdi:close"></ha-icon>
                Unknown
              </button>
            </div>
          </div>
        `
            : ""
        }

        <!-- Tracked Consumers Grid -->
        <div class="consumers-title">
          <span>Identified Consumers</span>
          <span>${Math.round(disaggregatedTotal)} W active</span>
        </div>

        <div class="consumers-grid">
          ${consumers
            .map(
              (c) => `
            <div class="consumer-tile ${c.isActive ? "active" : ""}">
              <div class="c-header">
                <span class="c-name">
                  <ha-icon icon="${c.icon}"></ha-icon>
                  ${c.name}
                </span>
                <span class="status-dot ${c.isActive ? "active" : ""}"></span>
              </div>
              <div class="c-power" style="color: ${c.isActive ? "#81c784" : "inherit"};">
                ${Math.round(c.power)} W
              </div>
              <div class="c-energy">${c.energy.toFixed(2)} kWh</div>
            </div>
          `
            )
            .join("")}
        </div>

        <!-- Footer Breakdown -->
        <div class="footer-breakdown">
          <div>
            Disaggregated: <strong>${Math.round(disaggregatedTotal)} W</strong>
          </div>
          <div>
            Unassigned Load: <strong>${Math.round(unassignedPower)} W</strong>
          </div>
        </div>
      </ha-card>
    `;

    // Attach event listeners
    const confirmBtn = this.shadowRoot.getElementById("btn-confirm-proposal");
    if (confirmBtn) {
      confirmBtn.addEventListener("click", () => {
        const selectElem = this.shadowRoot.getElementById("consumer-override-select");
        const chosen = selectElem && selectElem.value ? selectElem.value : (pendingEvent ? pendingEvent.proposed_consumer : "unknown");
        this._confirmEvent(chosen);
      });
    }

    const selectElem = this.shadowRoot.getElementById("consumer-override-select");
    if (selectElem) {
      selectElem.addEventListener("change", (e) => {
        if (e.target.value) {
          this._confirmEvent(e.target.value);
        }
      });
    }

    const unknownBtn = this.shadowRoot.getElementById("btn-mark-unknown");
    if (unknownBtn) {
      unknownBtn.addEventListener("click", () => {
        this._markUnknown();
      });
    }
  }
}

customElements.define("energy-disaggregator-card", EnergyDisaggregatorCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "energy-disaggregator-card",
  name: "Energy Disaggregator Card",
  preview: true,
  description: "Live 3-phase HomeWizard NILM monitor and interactive active learning card",
});
