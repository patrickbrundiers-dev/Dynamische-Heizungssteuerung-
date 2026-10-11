// Room card for the Dynamische Heizungssteuerung integration.
// Add it from the card picker ("Dynamische Heizung"); only the room's
// "Betriebsart" select is needed, everything else is found on its device.

const MODES = ["Automatik", "Komfort", "Eco", "Boost", "Aus"];
const SUFFIXES = {
  status: "_status",
  room: "_raumtemperatur",
  target: "_berechnete_solltemperatur",
  duration: "_betriebsart_dauer",
  enabled: "_regelung_aktiv",
  heatingProblem: "_heizproblem",
  thermostatProblem: "_thermostat_problem",
  demand: "_warmebedarf",
};

function number(value, digits = 1) {
  const parsed = Number(value);
  return Number.isFinite(parsed)
    ? parsed.toLocaleString("de-DE", { minimumFractionDigits: digits, maximumFractionDigits: digits })
    : "–";
}

function time(value) {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
}

function escape(text) {
  return String(text ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

class DynamicHeatingCard extends HTMLElement {
  static getStubConfig(hass) {
    const entity = Object.keys(hass.states).find(
      (id) => id.startsWith("select.") && id.endsWith("_betriebsart")
        && hass.entities?.[id]?.platform === "dynamic_heating",
    );
    return { entity: entity || "select.dynamische_heizungssteuerung_betriebsart" };
  }

  setConfig(config) {
    if (!config || !config.entity) {
      throw new Error("Bitte die Betriebsart-Entität des Raums angeben (entity).");
    }
    this._config = config;
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
      this.shadowRoot.addEventListener("click", (event) => this._click(event));
    }
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  getCardSize() {
    return 5;
  }

  _related() {
    const hass = this._hass;
    const select = this._config.entity;
    const deviceId = hass.entities?.[select]?.device_id;
    const found = {};
    const candidates = Object.keys(hass.states).filter(
      (id) => !deviceId || hass.entities?.[id]?.device_id === deviceId,
    );
    for (const [key, suffix] of Object.entries(SUFFIXES)) {
      found[key] = candidates.find((id) => id.endsWith(suffix)
        && (key !== "status" || id.startsWith("sensor."))
        && (key !== "duration" || id.startsWith("select.")));
    }
    let name = this._config.name;
    if (!name && deviceId) {
      const areaId = hass.entities?.[select]?.area_id || hass.devices?.[deviceId]?.area_id;
      name = areaId ? hass.areas?.[areaId]?.name : null;
    }
    found.name = name || "Heizung";
    return found;
  }

  _call(domain, service, data) {
    this._hass.callService(domain, service, data);
  }

  _click(event) {
    const button = event.target.closest("[data-action]");
    if (!button) return;
    const { action, value } = button.dataset;
    const related = this._related();
    if (action === "mode") {
      this._call("select", "select_option", { entity_id: this._config.entity, option: value });
    } else if (action === "duration" && related.duration) {
      this._call("select", "select_option", { entity_id: related.duration, option: value });
    } else if (action === "toggle" && related.enabled) {
      this._call("switch", "toggle", { entity_id: related.enabled });
    } else if (action === "more") {
      const moreInfo = new Event("hass-more-info", { bubbles: true, composed: true });
      moreInfo.detail = { entityId: value };
      this.dispatchEvent(moreInfo);
    }
  }

  _render() {
    if (!this._hass || !this._config || !this.shadowRoot) return;
    const hass = this._hass;
    const select = hass.states[this._config.entity];
    if (!select) {
      this.shadowRoot.innerHTML = `<ha-card><div class="missing">Entität ${escape(this._config.entity)} nicht gefunden.</div></ha-card>`;
      return;
    }
    const related = this._related();
    const state = (id) => (id ? hass.states[id] : undefined);
    const status = state(related.status);
    const attributes = status?.attributes || {};
    const room = state(related.room)?.state;
    const target = state(related.target)?.state ?? attributes.target_temperature;
    const demand = state(related.demand)?.state;
    const duration = state(related.duration);
    const enabled = state(related.enabled)?.state === "on";
    const problem = state(related.heatingProblem)?.state === "on"
      || state(related.thermostatProblem)?.state === "on";
    const until = time(select.attributes.until);
    const next = time(attributes.next_event);
    const valves = Object.entries(attributes.thermostat_setpoints || {});

    const modeButtons = MODES.map((mode) => `
      <button data-action="mode" data-value="${mode}" class="${select.state === mode ? "active" : ""}">${mode}</button>`).join("");
    const durationButtons = (duration?.attributes.options || []).map((option) => `
      <button data-action="duration" data-value="${escape(option)}" class="chip ${duration.state === option ? "active" : ""}">${escape(option)}</button>`).join("");
    const valveRows = valves.map(([id, setpoint]) => {
      const valve = hass.states[id];
      const label = valve?.attributes.friendly_name || id;
      return `<div class="valve" data-action="more" data-value="${escape(id)}">
        <span>${escape(label)}</span>
        <span>${number(valve?.attributes.current_temperature)} °C → ${number(setpoint)} °C</span>
      </div>`;
    }).join("");

    this.shadowRoot.innerHTML = `
      <style>
        ha-card { padding: 16px; }
        .head { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
        .name { font-size: 1.2em; font-weight: 500; }
        .badge { color: var(--error-color, #db4437); font-size: 0.9em; cursor: pointer; }
        .temps { display: flex; align-items: baseline; gap: 12px; margin: 12px 0 4px; }
        .now { font-size: 2.4em; font-weight: 300; }
        .target { color: var(--secondary-text-color); font-size: 1.1em; }
        .status { color: var(--secondary-text-color); margin-bottom: 12px; cursor: pointer; }
        .row { display: flex; flex-wrap: wrap; gap: 6px; margin: 8px 0; }
        button { flex: 1 1 auto; border: 1px solid var(--divider-color); border-radius: 8px;
          background: var(--card-background-color); color: var(--primary-text-color);
          padding: 8px 6px; font: inherit; cursor: pointer; }
        button.active { background: var(--primary-color); color: var(--text-primary-color, #fff); border-color: var(--primary-color); }
        button.chip { flex: 0 1 auto; font-size: 0.85em; padding: 4px 10px; border-radius: 16px; }
        .valve { display: flex; justify-content: space-between; font-size: 0.9em; padding: 4px 0;
          border-top: 1px solid var(--divider-color); cursor: pointer; }
        .foot { display: flex; justify-content: space-between; align-items: center; margin-top: 8px;
          color: var(--secondary-text-color); font-size: 0.9em; }
        .toggle { flex: 0 0 auto; }
        .missing { padding: 8px; }
      </style>
      <ha-card>
        <div class="head">
          <div class="name">${escape(related.name)}</div>
          ${problem ? `<div class="badge" data-action="more" data-value="${escape(related.heatingProblem || related.thermostatProblem)}">⚠ Problem</div>` : ""}
        </div>
        <div class="temps">
          <span class="now">${number(room)} °C</span>
          <span class="target">Soll ${number(target)} °C</span>
        </div>
        <div class="status" data-action="more" data-value="${escape(related.status || "")}">
          ${escape(status?.state || "")}${until ? ` · bis ${until} Uhr` : ""}
        </div>
        <div class="row">${modeButtons}</div>
        ${durationButtons ? `<div class="row">${durationButtons}</div>` : ""}
        ${valveRows}
        <div class="foot">
          <span>${next ? `Nächster Wechsel ${next} Uhr` : ""}${demand !== undefined ? ` · Wärmebedarf ${number(demand, 0)} %` : ""}</span>
          ${related.enabled ? `<button class="toggle chip ${enabled ? "active" : ""}" data-action="toggle">${enabled ? "Regelung an" : "Regelung aus"}</button>` : ""}
        </div>
      </ha-card>`;
  }
}

if (!customElements.get("dynamic-heating-card")) {
  customElements.define("dynamic-heating-card", DynamicHeatingCard);
}
window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === "dynamic-heating-card")) {
  window.customCards.push({
    type: "dynamic-heating-card",
    name: "Dynamische Heizung",
    description: "Raumkarte mit Ist/Soll, Betriebsart, Dauer, Ventilen und Regelung.",
  });
}
