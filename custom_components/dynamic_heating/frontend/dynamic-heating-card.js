// Room card for the Dynamische Heizungssteuerung integration.
// Add it from the card picker ("Dynamische Heizung"); only the room's
// "Betriebsart" select is needed, everything else is found on its device.
// The schedule editor ("Dynamische Heizung – Zeitplan", also inside the room
// card) edits the room's schedule helpers as a graph: blocks are comfort
// times, a block's temperature goes into its additional data.

// Fallback when the select does not list its options (older versions).
const MODES = ["Automatik", "Komfort", "Eco", "Boost", "Aus"];
// Icons of the mode buttons, as on the room's button entities.
const ICONS = {
  Automatik: "mdi:calendar-clock",
  Komfort: "mdi:sofa",
  Zuhause: "mdi:home",
  "Aktivität": "mdi:run",
  Eco: "mdi:leaf",
  Schlafen: "mdi:bed",
  Abwesend: "mdi:home-export-outline",
  Boost: "mdi:fire",
  Aus: "mdi:snowflake",
};
const SUFFIXES = {
  status: "_status",
  room: "_raumtemperatur",
  target: "_berechnete_solltemperatur",
  duration: "_betriebsart_dauer",
  enabled: "_regelung_aktiv",
  heatingProblem: "_heizproblem",
  thermostatProblem: "_thermostat_problem",
  demand: "_warmebedarf",
  comfort: "_komforttemperatur",
  eco: "_eco_temperatur",
  energy: "_warmemenge",
};
// Spar-Rechner: how much later (or earlier) comfort may start.
const SHIFTS = [-30, -15, 0, 15, 30, 60];
const DAYS = [
  ["monday", "Mo"], ["tuesday", "Di"], ["wednesday", "Mi"], ["thursday", "Do"],
  ["friday", "Fr"], ["saturday", "Sa"], ["sunday", "So"],
];
const DAY_NAMES = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"];
// Minutes a block snaps to, the shortest block and a new block's length.
const STEP = 15;
const NEW_BLOCK = 120;
const TEMP_STEP = 0.5;
const TEMP_MIN = 5;
const TEMP_MAX = 30;

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

// "07:30:00" -> 450; "24:00:00" -> 1440.
function toMinutes(value) {
  const [hours, minutes] = String(value).split(":").map(Number);
  return (hours || 0) * 60 + (minutes || 0);
}

function toTime(minutes) {
  const pad = (n) => String(n).padStart(2, "0");
  return `${pad(Math.floor(minutes / 60))}:${pad(minutes % 60)}:00`;
}

function clock(minutes) {
  return toTime(minutes).slice(0, 5);
}

function snap(value, step) {
  return Math.round(value / step) * step;
}

function clamp(value, low, high) {
  return Math.min(high, Math.max(low, value));
}

// The room's entities, found on the device of its "Betriebsart" select.
function findRelated(hass, config) {
  const select = config.entity;
  const deviceId = hass.entities?.[select]?.device_id;
  const found = {};
  const candidates = Object.keys(hass.states).filter(
    (id) => !deviceId || hass.entities?.[id]?.device_id === deviceId,
  );
  for (const [key, suffix] of Object.entries(SUFFIXES)) {
    found[key] = candidates.find((id) => id.endsWith(suffix)
      && (key !== "status" || id.startsWith("sensor."))
      && (key !== "duration" || id.startsWith("select."))
      && (!["comfort", "eco"].includes(key) || id.startsWith("number."))
      && (key !== "energy" || id.startsWith("sensor.")));
  }
  let name = config.name;
  if (!name && deviceId) {
    const areaId = hass.entities?.[select]?.area_id || hass.devices?.[deviceId]?.area_id;
    name = areaId ? hass.areas?.[areaId]?.name : null;
  }
  found.name = name || "Heizung";
  return found;
}

function stubEntity(hass) {
  return Object.keys(hass.states).find(
    (id) => id.startsWith("select.") && id.endsWith("_betriebsart")
      && hass.entities?.[id]?.platform === "dynamic_heating",
  ) || "select.dynamische_heizungssteuerung_betriebsart";
}

const SCHEDULE_STYLE = `
  :host { display: block; }
  ha-card { padding: 16px; }
  .title { font-size: 1.2em; font-weight: 500; margin-bottom: 8px; }
  .row { display: flex; flex-wrap: wrap; gap: 6px; margin: 8px 0; align-items: center; }
  button { border: 1px solid var(--divider-color); border-radius: 8px;
    background: var(--card-background-color); color: var(--primary-text-color);
    padding: 6px 10px; font: inherit; cursor: pointer; }
  button.chip { font-size: 0.85em; padding: 4px 10px; border-radius: 16px; }
  button.day { flex: 1 1 0; min-width: 36px; padding: 6px 0; }
  button.active { background: var(--primary-color); color: var(--text-primary-color, #fff); border-color: var(--primary-color); }
  button.primary { background: var(--primary-color); color: var(--text-primary-color, #fff); border-color: var(--primary-color); }
  button:disabled { opacity: 0.45; cursor: default; }
  .dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%;
    background: var(--success-color, #43a047); margin-left: 4px; vertical-align: middle; }
  svg { width: 100%; height: auto; display: block; touch-action: none; user-select: none;
    -webkit-user-select: none; margin: 4px 0; }
  .grid { stroke: var(--divider-color); stroke-width: 1; }
  .axis { fill: var(--secondary-text-color); font-size: 11px; }
  .eco { stroke: var(--secondary-text-color); stroke-width: 2; stroke-dasharray: 6 4; fill: none; }
  .block { fill: var(--dh-block, #ff9800); fill-opacity: 0.22; cursor: grab; }
  .block.sel { fill-opacity: 0.38; }
  .top { stroke: var(--dh-block, #ff9800); stroke-width: 3; }
  .handle { fill: transparent; cursor: ew-resize; }
  .grip { fill: var(--dh-block, #ff9800); }
  .label { fill: var(--primary-text-color); font-size: 12px; font-weight: 500; pointer-events: none; }
  .history { stroke: var(--dh-history, #2196f3); stroke-width: 2; fill: none; pointer-events: none; }
  .now { stroke: var(--success-color, #43a047); stroke-width: 1.5; stroke-dasharray: 3 3; }
  .legend { color: var(--secondary-text-color); font-size: 0.8em; }
  .legend span { white-space: nowrap; margin-right: 10px; }
  .swatch { display: inline-block; width: 12px; height: 3px; vertical-align: middle; margin-right: 4px; }
  .panel { border-top: 1px solid var(--divider-color); padding-top: 8px; margin-top: 4px; }
  .panel label { color: var(--secondary-text-color); font-size: 0.9em; }
  select { font: inherit; padding: 4px; border-radius: 6px; border: 1px solid var(--divider-color);
    background: var(--card-background-color); color: var(--primary-text-color); }
  .temp { min-width: 64px; text-align: center; font-size: 1.1em; }
  .hint { color: var(--secondary-text-color); font-size: 0.85em; }
  .error { color: var(--error-color, #db4437); font-size: 0.9em; }
  .spacer { flex: 1 1 auto; }
`;

// Graph geometry in SVG units; one unit is one pixel of the card's width, so
// labels keep their size on a phone.
const H = 220;
const PAD = { left: 34, right: 8, top: 18, bottom: 22 };
const PLOT_H = H - PAD.top - PAD.bottom;

class DynamicHeatingScheduleCard extends HTMLElement {
  static getStubConfig(hass) {
    return { entity: stubEntity(hass) };
  }

  setConfig(config) {
    if (!config || !config.entity) {
      throw new Error("Bitte die Betriebsart-Entität des Raums angeben (entity).");
    }
    this._config = config;
    this._day = (new Date().getDay() + 6) % 7;
    this._historyCache = {};
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
      const wrapper = config.embedded ? "div" : "ha-card";
      this.shadowRoot.innerHTML = `<style>${SCHEDULE_STYLE}</style>
        <${wrapper} class="wrap">
          ${config.embedded ? "" : '<div class="title"></div>'}
          <div class="top-controls"></div>
          <svg viewBox="0 0 720 ${H}" role="img" aria-label="Zeitplan"></svg>
          <div class="legend"></div>
          <div class="panel-area"></div>
        </${wrapper}>`;
      const root = this.shadowRoot;
      this._svg = root.querySelector("svg");
      root.addEventListener("click", (event) => this._click(event));
      root.addEventListener("change", (event) => this._change(event));
      this._svg.addEventListener("pointerdown", (event) => this._pointerDown(event));
      this._svg.addEventListener("pointermove", (event) => this._pointerMove(event));
      this._svg.addEventListener("pointerup", (event) => this._pointerUp(event));
      this._svg.addEventListener("pointercancel", () => this._pointerCancel());
      this._width = 720;
      if (window.ResizeObserver) {
        new ResizeObserver(() => {
          if (!this._drag && this._measure()) this._renderGraph();
        }).observe(this._svg);
      }
    }
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._config) return;
    const related = findRelated(hass, this._config);
    const attributes = hass.states[related.status]?.attributes || {};
    const info = {
      name: related.name,
      roomSensor: related.room,
      schedules: attributes.schedules || [],
      active: attributes.active_schedule || null,
      comfort: Number(attributes.comfort_temperature),
      eco: Number(attributes.eco_temperature),
    };
    const key = JSON.stringify(info);
    if (key === this._infoKey) return;
    this._infoKey = key;
    this._info = info;
    if (!this._selected || !info.schedules.some((s) => s.entity_id === this._selected)) {
      const first = info.active || info.schedules[0]?.entity_id;
      if (first && first !== this._selected && !this._dirty) {
        this._selected = first;
        this._load();
      }
    }
    if (!this._drag) this._renderAll();
  }

  getCardSize() {
    return 6;
  }

  // ---- loading and saving -------------------------------------------------

  async _load() {
    const hass = this._hass;
    const entityId = this._selected;
    if (!hass || !entityId) return;
    this._loading = true;
    this._error = null;
    this._message = null;
    this._item = null;
    this._draft = null;
    this._dirty = false;
    this._block = null;
    this._renderAll();
    let item = null;
    try {
      const entry = await hass.callWS({ type: "config/entity_registry/get", entity_id: entityId });
      const items = await hass.callWS({ type: "schedule/list" });
      item = items.find((candidate) => candidate.id === entry.unique_id) || null;
    } catch (_err) {
      item = null;
    }
    let days = item;
    if (!days) {
      // A schedule from YAML: shown, but it can only be changed in YAML.
      try {
        const result = await hass.callService(
          "schedule", "get_schedule", { entity_id: entityId }, undefined, false, true,
        );
        days = result?.response?.[entityId];
      } catch (err) {
        this._error = `Zeitplan konnte nicht gelesen werden: ${err?.message || err}`;
      }
    }
    if (entityId !== this._selected) return;
    this._item = item;
    this._draft = days ? this._toDraft(days) : null;
    this._readonly = !item
      ? "Dieser Zeitplan steht in der YAML-Konfiguration und lässt sich hier nur ansehen."
      : !hass.user?.is_admin
        ? "Ändern dürfen nur Administratoren, der Zeitplan wird nur angezeigt."
        : null;
    this._loading = false;
    this._renderAll();
    this._loadHistory();
  }

  _toDraft(days) {
    const draft = {};
    for (const [day] of DAYS) {
      draft[day] = (days[day] || [])
        .map((block) => ({
          from: toMinutes(block.from),
          to: toMinutes(block.to) || 1440,
          data: { ...(block.data || {}) },
        }))
        .sort((a, b) => a.from - b.from);
    }
    return draft;
  }

  async _save() {
    if (!this._item || !this._draft || this._readonly) return;
    const payload = { type: "schedule/update", schedule_id: this._item.id, name: this._item.name };
    if (this._item.icon) payload.icon = this._item.icon;
    for (const [day] of DAYS) {
      payload[day] = this._draft[day].map((block) => {
        const out = { from: toTime(block.from), to: toTime(block.to) };
        if (Object.keys(block.data).length) out.data = block.data;
        return out;
      });
    }
    this._saving = true;
    this._error = null;
    this._renderControls();
    try {
      this._item = await this._hass.callWS(payload);
      this._dirty = false;
      this._message = "Gespeichert. Die Heizung richtet sich ab jetzt danach.";
    } catch (err) {
      this._error = `Speichern fehlgeschlagen: ${err?.message || err}`;
    }
    this._saving = false;
    this._renderAll();
  }

  async _loadHistory() {
    const hass = this._hass;
    const sensor = this._info?.roomSensor;
    if (!hass || !sensor) return;
    const start = this._dayStart(this._day);
    const key = `${sensor}|${start.toISOString()}`;
    if (this._historyCache[key] && start.toDateString() !== new Date().toDateString()) {
      this._history = this._historyCache[key];
      this._renderGraph();
      return;
    }
    const end = new Date(Math.min(Date.now(), start.getTime() + 86400000));
    try {
      const result = await hass.callWS({
        type: "history/history_during_period",
        start_time: start.toISOString(),
        end_time: end.toISOString(),
        entity_ids: [sensor],
        minimal_response: true,
        no_attributes: true,
        significant_changes_only: false,
      });
      const points = (result?.[sensor] || [])
        .map((row) => [
          ((row.lu ?? row.last_updated) * 1000 - start.getTime()) / 60000,
          Number(row.s ?? row.state),
        ])
        .map(([minute, value]) => [Math.max(0, minute), value])
        .filter(([minute, value]) => Number.isFinite(value) && minute <= 1440);
      this._historyCache[key] = points;
      if (start.getTime() === this._dayStart(this._day).getTime()) {
        this._history = points;
        this._renderGraph();
        this._renderLegend();
      }
    } catch (_err) {
      this._history = [];
    }
  }

  // Midnight of the latest date (today or earlier) that falls on this weekday.
  _dayStart(dayIndex) {
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const back = ((today.getDay() + 6) % 7 - dayIndex + 7) % 7;
    return new Date(today.getFullYear(), today.getMonth(), today.getDate() - back);
  }

  // ---- editing --------------------------------------------------------------

  _blocks() {
    return this._draft?.[DAYS[this._day][0]] || [];
  }

  _blockTemperature(block) {
    const own = Number(block.data?.temperature);
    return Number.isFinite(own) ? own : this._info?.comfort;
  }

  _touch() {
    this._dirty = true;
    this._message = null;
    this._error = null;
  }

  _limits(index) {
    const blocks = this._blocks();
    return {
      low: index > 0 ? blocks[index - 1].to : 0,
      high: index < blocks.length - 1 ? blocks[index + 1].from : 1440,
    };
  }

  _addAt(minute) {
    const blocks = this._blocks();
    let low = 0;
    let high = 1440;
    for (const block of blocks) {
      if (block.to <= minute) low = Math.max(low, block.to);
      if (block.from > minute) high = Math.min(high, block.from);
      if (block.from <= minute && minute < block.to) return;
    }
    if (high - low < STEP * 2) return;
    let from = snap(minute - NEW_BLOCK / 2, STEP);
    from = clamp(from, low, high - STEP * 2);
    const to = Math.min(high, from + NEW_BLOCK);
    blocks.push({ from, to, data: {} });
    blocks.sort((a, b) => a.from - b.from);
    this._block = blocks.findIndex((block) => block.from === from);
    this._touch();
  }

  _copyTo(targets) {
    const source = this._blocks();
    for (const index of targets) {
      if (index === this._day) continue;
      this._draft[DAYS[index][0]] = source.map((block) => ({ ...block, data: { ...block.data } }));
    }
    this._touch();
    this._message = "Kopiert. Zum Übernehmen noch speichern.";
  }

  _toggleSavings(related) {
    this._showSavings = !this._showSavings;
    this._savingsAnswer = null;
    if (!this._showSavings) {
      this._savingsBox.innerHTML = "";
      this._render();
      return;
    }
    const value = (id) => {
      const state = id ? this._hass.states[id] : undefined;
      return state && !isNaN(Number(state.state)) ? Number(state.state) : "";
    };
    this._savingsBox.innerHTML = `
      <div class="hint">Spar-Rechner: rechnet die nächsten 7 Tage mit dem gelernten Raummodell durch. Es wird nichts geändert, bis du auf „Übernehmen“ tippst.</div>
      <label>Eco-Temperatur <input type="number" step="0.5" min="5" max="30" name="eco" value="${value(related.eco)}"></label>
      <label>Komforttemperatur <input type="number" step="0.5" min="5" max="30" name="comfort" value="${value(related.comfort)}"></label>
      <label>Komfortbeginn <select name="shift">${SHIFTS.map((minutes) => `
        <option value="${minutes}" ${minutes === 0 ? "selected" : ""}>${minutes === 0 ? "wie im Zeitplan" : `${Math.abs(minutes)} min ${minutes > 0 ? "später" : "früher"}`}</option>`).join("")}
      </select></label>
      <div class="row"><button data-action="savings-run">Rechnen</button></div>
      <div class="answer"></div>`;
    this._render();
  }

  _savingsInput() {
    const read = (name) => this._savingsBox.querySelector(`[name="${name}"]`)?.value;
    const data = { shift_minutes: Number(read("shift") || 0) };
    if (read("eco") !== "") data.eco_temperature = Number(read("eco"));
    if (read("comfort") !== "") data.comfort_temperature = Number(read("comfort"));
    return data;
  }

  async _runSavings(related) {
    const box = this._savingsBox.querySelector(".answer");
    if (!box) return;
    box.textContent = "Wird gerechnet …";
    const input = this._savingsInput();
    try {
      const result = await this._hass.callWS({
        type: "call_service",
        domain: "dynamic_heating",
        service: "estimate_savings",
        service_data: { entity_id: this._config.entity, ...input },
        return_response: true,
      });
      this._savingsAnswer = { input, response: result.response };
      const response = result.response || {};
      const changed = (response.new_eco !== response.eco || response.new_comfort !== response.comfort)
        && related.eco && related.comfort;
      box.innerHTML = `<div>${escape(response.text || "Keine Antwort.")}</div>
        ${changed ? '<div class="row"><button data-action="savings-apply">Übernehmen</button></div>' : ""}
        ${input.shift_minutes ? '<div class="hint">Die Zeiten änderst du im Zeitplan.</div>' : ""}`;
    } catch (err) {
      box.textContent = `Rechnen ging nicht: ${err?.message || err}`;
    }
  }

  async _applySavings(related) {
    const answer = this._savingsAnswer?.response;
    if (!answer) return;
    const box = this._savingsBox.querySelector(".answer");
    try {
      // Lower eco first and raise comfort last, so eco stays below comfort.
      const steps = [];
      if (answer.new_eco !== answer.eco) steps.push([related.eco, answer.new_eco]);
      if (answer.new_comfort !== answer.comfort) steps.push([related.comfort, answer.new_comfort]);
      if (answer.new_eco > answer.eco) steps.reverse();
      for (const [entity, value] of steps) {
        await this._hass.callService("number", "set_value", { entity_id: entity, value });
      }
      if (box) box.innerHTML = '<div>Übernommen.</div>';
      this._savingsAnswer = null;
    } catch (err) {
      if (box) box.textContent = `Übernehmen ging nicht: ${err?.message || err}`;
    }
  }

  _click(event) {
    const button = event.target.closest("[data-action]");
    if (!button || button.disabled) return;
    const { action, value } = button.dataset;
    const blocks = this._blocks();
    const block = this._block !== null ? blocks[this._block] : null;
    if (action === "schedule") {
      if (value === this._selected) return;
      if (this._dirty && !window.confirm("Ungespeicherte Änderungen verwerfen?")) return;
      this._selected = value;
      this._dirty = false;
      this._load();
      return;
    }
    if (action === "day") {
      this._day = Number(value);
      this._block = null;
      this._history = [];
      this._loadHistory();
    } else if (action === "copy") {
      const targets = value === "weekdays" ? [0, 1, 2, 3, 4]
        : value === "weekend" ? [5, 6] : [0, 1, 2, 3, 4, 5, 6];
      this._copyTo(targets);
    } else if (action === "save") {
      this._save();
      return;
    } else if (action === "discard") {
      this._load();
      return;
    } else if (action === "reload") {
      this._load();
      return;
    } else if (block && action === "temp") {
      const current = this._blockTemperature(block) ?? 20;
      block.data.temperature = clamp(snap(current + Number(value), TEMP_STEP), TEMP_MIN, TEMP_MAX);
      this._touch();
    } else if (block && action === "comfort") {
      delete block.data.temperature;
      this._touch();
    } else if (block && action === "delete") {
      blocks.splice(this._block, 1);
      this._block = null;
      this._touch();
    } else if (action === "close") {
      this._block = null;
    }
    this._renderAll();
  }

  _change(event) {
    const field = event.target.closest("[data-field]");
    if (!field || this._block === null) return;
    const block = this._blocks()[this._block];
    const { low, high } = this._limits(this._block);
    const value = Number(field.value);
    const from = field.dataset.field === "from" ? value : block.from;
    const to = field.dataset.field === "to" ? value : block.to;
    if (from >= to) {
      this._error = "Das Ende muss nach dem Anfang liegen.";
    } else if (from < low || to > high) {
      this._error = `Überschneidet sich mit einem anderen Block (frei von ${clock(low)} bis ${clock(high)}).`;
    } else {
      block.from = from;
      block.to = to;
      this._touch();
    }
    this._renderAll();
  }

  // ---- pointer handling on the graph ---------------------------------------

  _point(event) {
    const matrix = this._svg.getScreenCTM();
    if (!matrix) return { x: 0, y: 0 };
    const point = new DOMPoint(event.clientX, event.clientY).matrixTransform(matrix.inverse());
    return { x: point.x, y: point.y };
  }

  get _plotW() {
    return this._width - PAD.left - PAD.right;
  }

  // Follow the card's width; true when it changed.
  _measure() {
    const measured = Math.round(this._svg.getBoundingClientRect().width);
    const width = measured ? clamp(measured, 300, 1400) : this._width;
    if (width === this._width) return false;
    this._width = width;
    return true;
  }

  _minuteAt(x) {
    return clamp(((x - PAD.left) / this._plotW) * 1440, 0, 1440);
  }

  _pointerDown(event) {
    if (!this._draft || this._readonly || event.button > 0) return;
    const target = event.target.closest("[data-role]");
    const point = this._point(event);
    const index = target ? Number(target.dataset.index) : null;
    const block = index !== null ? this._blocks()[index] : null;
    this._drag = {
      role: target?.dataset.role || "background",
      index,
      start: point,
      origin: block ? { from: block.from, to: block.to, temp: this._blockTemperature(block) ?? 20 } : null,
      moved: false,
      axis: null,
    };
    this._svg.setPointerCapture(event.pointerId);
    event.preventDefault();
  }

  _pointerMove(event) {
    const drag = this._drag;
    if (!drag) return;
    const point = this._point(event);
    const dx = point.x - drag.start.x;
    const dy = point.y - drag.start.y;
    if (!drag.moved && Math.hypot(dx, dy) < 6) return;
    drag.moved = true;
    if (drag.index === null) return;
    const block = this._blocks()[drag.index];
    const { low, high } = this._limits(drag.index);
    const minutes = (dx / this._plotW) * 1440;
    const [tMin, tMax] = this._range;
    if (drag.role === "left") {
      block.from = clamp(snap(drag.origin.from + minutes, STEP), low, block.to - STEP);
    } else if (drag.role === "right") {
      block.to = clamp(snap(drag.origin.to + minutes, STEP), block.from + STEP, high);
    } else {
      // A block moves sideways or changes its temperature, whichever way the
      // finger went first.
      drag.axis = drag.axis || (Math.abs(dx) >= Math.abs(dy) ? "x" : "y");
      if (drag.axis === "x") {
        const length = drag.origin.to - drag.origin.from;
        const from = clamp(snap(drag.origin.from + minutes, STEP), low, high - length);
        block.from = from;
        block.to = from + length;
      } else {
        const degrees = (-dy / PLOT_H) * (tMax - tMin);
        block.data.temperature = clamp(snap(drag.origin.temp + degrees, TEMP_STEP), TEMP_MIN, TEMP_MAX);
      }
    }
    this._block = drag.index;
    this._touch();
    this._renderGraph();
    this._renderPanel();
  }

  _pointerUp(event) {
    const drag = this._drag;
    this._drag = null;
    if (!drag) return;
    if (!drag.moved) {
      if (drag.index !== null) {
        this._block = drag.index;
      } else {
        this._addAt(this._minuteAt(this._point(event).x));
      }
    }
    this._renderAll();
  }

  _pointerCancel() {
    this._drag = null;
    this._renderAll();
  }

  // ---- rendering ------------------------------------------------------------

  _computeRange() {
    const values = [this._info?.eco, this._info?.comfort];
    for (const block of this._blocks()) values.push(this._blockTemperature(block));
    for (const [, value] of this._history || []) values.push(value);
    const finite = values.filter(Number.isFinite);
    const low = Math.floor(Math.min(16, ...finite) - 1);
    const high = Math.ceil(Math.max(23, ...finite) + 1);
    this._range = [low, high];
  }

  _renderAll() {
    if (!this.shadowRoot || !this._info) return;
    const title = this.shadowRoot.querySelector(".title");
    if (title) title.textContent = `Zeitplan ${this._info.name}`;
    this._renderControls();
    this._renderGraph();
    this._renderLegend();
    this._renderPanel();
  }

  _renderControls() {
    const box = this.shadowRoot.querySelector(".top-controls");
    const info = this._info;
    if (!info.schedules.length) {
      box.innerHTML = '<div class="hint">Für diesen Raum ist kein Zeitplan eingerichtet (Einstellungen der Integration).</div>';
      return;
    }
    const schedules = info.schedules.length > 1 ? `<div class="row">${info.schedules.map((s) => `
      <button class="chip ${s.entity_id === this._selected ? "active" : ""}" data-action="schedule" data-value="${escape(s.entity_id)}">
        ${escape(s.name)}${s.entity_id === info.active ? '<span class="dot" title="gerade aktiv"></span>' : ""}
      </button>`).join("")}</div>` : "";
    const days = DAYS.map(([, label], index) => `
      <button class="day ${index === this._day ? "active" : ""}" data-action="day" data-value="${index}">${label}</button>`).join("");
    const editable = this._draft && !this._readonly;
    const busy = this._saving || this._loading;
    box.innerHTML = `
      ${schedules}
      <div class="row">${days}</div>
      ${this._readonly ? `<div class="hint">${escape(this._readonly)}</div>` : ""}
      ${this._loading ? '<div class="hint">Zeitplan wird geladen …</div>' : ""}
      ${this._error ? `<div class="error">${escape(this._error)}</div>` : ""}
      ${this._message ? `<div class="hint">${escape(this._message)}</div>` : ""}
      ${editable ? `<div class="row">
        <span class="hint">${escape(DAY_NAMES[this._day])} kopieren auf</span>
        <button class="chip" data-action="copy" data-value="weekdays">Mo–Fr</button>
        <button class="chip" data-action="copy" data-value="weekend">Sa–So</button>
        <button class="chip" data-action="copy" data-value="all">alle Tage</button>
        <span class="spacer"></span>
        <button data-action="discard" ${this._dirty && !busy ? "" : "disabled"}>Verwerfen</button>
        <button class="primary" data-action="save" ${this._dirty && !busy ? "" : "disabled"}>${this._saving ? "Speichert …" : "Speichern"}</button>
      </div>` : ""}`;
  }

  _renderGraph() {
    const svg = this._svg;
    if (!svg) return;
    if (!this._draft) {
      svg.innerHTML = "";
      return;
    }
    if (!this._drag) {
      this._computeRange();
      this._measure();
    }
    svg.setAttribute("viewBox", `0 0 ${this._width} ${H}`);
    const PLOT_W = this._plotW;
    const [tMin, tMax] = this._range;
    const x = (minute) => PAD.left + (minute / 1440) * PLOT_W;
    const y = (temp) => PAD.top + ((tMax - clamp(temp, tMin, tMax)) / (tMax - tMin)) * PLOT_H;
    const parts = [];
    // Background catches taps that add a block.
    parts.push(`<rect x="${PAD.left}" y="${PAD.top}" width="${PLOT_W}" height="${PLOT_H}" fill="transparent"/>`);
    for (let hour = 0; hour <= 24; hour += 3) {
      parts.push(`<line class="grid" x1="${x(hour * 60)}" x2="${x(hour * 60)}" y1="${PAD.top}" y2="${PAD.top + PLOT_H}"/>`);
      parts.push(`<text class="axis" x="${x(hour * 60)}" y="${H - 6}" text-anchor="middle">${String(hour).padStart(2, "0")}</text>`);
    }
    const stepT = tMax - tMin > 12 ? 4 : 2;
    for (let temp = Math.ceil(tMin / stepT) * stepT; temp <= tMax; temp += stepT) {
      parts.push(`<line class="grid" x1="${PAD.left}" x2="${PAD.left + PLOT_W}" y1="${y(temp)}" y2="${y(temp)}"/>`);
      parts.push(`<text class="axis" x="${PAD.left - 6}" y="${y(temp) + 4}" text-anchor="end">${temp}°</text>`);
    }
    const blocks = this._blocks();
    const eco = this._info.eco;
    if (Number.isFinite(eco)) {
      // Eco between the blocks.
      let cursor = 0;
      const segments = [];
      for (const block of blocks) {
        if (block.from > cursor) segments.push([cursor, block.from]);
        cursor = Math.max(cursor, block.to);
      }
      if (cursor < 1440) segments.push([cursor, 1440]);
      for (const [from, to] of segments) {
        parts.push(`<line class="eco" x1="${x(from)}" x2="${x(to)}" y1="${y(eco)}" y2="${y(eco)}"/>`);
      }
    }
    const base = Number.isFinite(eco) ? y(eco) : PAD.top + PLOT_H;
    blocks.forEach((block, index) => {
      const temp = this._blockTemperature(block);
      const top = Number.isFinite(temp) ? y(temp) : PAD.top + PLOT_H / 3;
      const left = x(block.from);
      const right = x(block.to);
      const height = Math.max(4, Math.abs(base - top));
      const yTop = Math.min(base, top);
      const selected = index === this._block;
      parts.push(`<rect class="block ${selected ? "sel" : ""}" data-role="block" data-index="${index}"
        x="${left}" y="${yTop}" width="${Math.max(2, right - left)}" height="${height}"/>`);
      parts.push(`<line class="top" x1="${left}" x2="${right}" y1="${top}" y2="${top}" pointer-events="none"/>`);
      const own = Number.isFinite(Number(block.data?.temperature));
      parts.push(`<text class="label" x="${(left + right) / 2}" y="${top - 5}" text-anchor="middle">${number(temp)}°${own ? "" : " K"}</text>`);
      if (!this._readonly) {
        for (const [role, edge] of [["left", left], ["right", right]]) {
          parts.push(`<rect class="grip" x="${edge - 2}" y="${top - 7}" width="4" height="14" rx="2" pointer-events="none"/>`);
          parts.push(`<rect class="handle" data-role="${role}" data-index="${index}" x="${edge - 9}" y="${yTop - 10}" width="18" height="${height + 20}"/>`);
        }
      }
    });
    const history = this._history || [];
    if (history.length) {
      // Step line: a sensor keeps its value until the next reading.
      let path = "";
      history.forEach(([minute, value], i) => {
        const px = x(minute).toFixed(1);
        const py = y(value).toFixed(1);
        path += i === 0 ? `M${px},${py}` : `H${px}V${py}`;
      });
      const start = this._dayStart(this._day);
      const end = Math.min(1440, (Date.now() - start.getTime()) / 60000);
      path += `H${x(end).toFixed(1)}`;
      parts.push(`<path class="history" d="${path}"/>`);
    }
    if (this._day === (new Date().getDay() + 6) % 7) {
      const now = new Date();
      const minute = now.getHours() * 60 + now.getMinutes();
      parts.push(`<line class="now" x1="${x(minute)}" x2="${x(minute)}" y1="${PAD.top}" y2="${PAD.top + PLOT_H}" pointer-events="none"/>`);
    }
    svg.innerHTML = parts.join("");
  }

  _renderLegend() {
    const box = this.shadowRoot.querySelector(".legend");
    if (!this._draft) {
      box.innerHTML = "";
      return;
    }
    const start = this._dayStart(this._day);
    const today = start.toDateString() === new Date().toDateString();
    const date = today ? "heute" : `am ${start.toLocaleDateString("de-DE", { day: "numeric", month: "numeric" })}`;
    box.innerHTML = `
      <span><span class="swatch" style="background: var(--dh-block, #ff9800)"></span>Komfort laut Zeitplan (K = Komforttemperatur des Raums)</span>
      <span><span class="swatch" style="background: var(--secondary-text-color)"></span>Eco ${number(this._info.eco)} °C</span>
      ${this._history?.length ? `<span><span class="swatch" style="background: var(--dh-history, #2196f3)"></span>Raumtemperatur ${date}</span>` : ""}
      ${this._readonly ? "" : '<div class="hint">Tippen auf eine freie Stelle legt einen Block an. Block seitlich ziehen verschiebt ihn, hoch oder runter ändert die Temperatur, die Ränder ändern Anfang und Ende.</div>'}`;
  }

  _renderPanel() {
    const box = this.shadowRoot.querySelector(".panel-area");
    const block = this._block !== null ? this._blocks()[this._block] : null;
    if (!block || this._readonly) {
      box.innerHTML = "";
      return;
    }
    const { low, high } = this._limits(this._block);
    // The 15-minute grid plus the ends and the block's own time, so times like
    // 05:10 from the helper editor show as they are.
    const options = (from, to, selected) => {
      const minutes = new Set([from, to, selected]);
      for (let minute = Math.ceil(from / STEP) * STEP; minute <= to; minute += STEP) {
        minutes.add(minute);
      }
      return [...minutes].sort((a, b) => a - b).map((minute) => `
        <option value="${minute}" ${minute === selected ? "selected" : ""}>${clock(minute)}</option>`).join("");
    };
    const own = Number.isFinite(Number(block.data?.temperature));
    box.innerHTML = `
      <div class="panel">
        <div class="row">
          <label>Von</label>
          <select data-field="from">${options(low, block.to - STEP, block.from)}</select>
          <label>bis</label>
          <select data-field="to">${options(block.from + STEP, high, block.to)}</select>
        </div>
        <div class="row">
          <button data-action="temp" data-value="-${TEMP_STEP}">−</button>
          <span class="temp">${number(this._blockTemperature(block))} °C</span>
          <button data-action="temp" data-value="${TEMP_STEP}">+</button>
          <button class="chip ${own ? "" : "active"}" data-action="comfort">Komforttemperatur</button>
          <span class="spacer"></span>
          <button data-action="delete">Löschen</button>
          <button data-action="close">Fertig</button>
        </div>
      </div>`;
  }
}

class DynamicHeatingCard extends HTMLElement {
  static getStubConfig(hass) {
    return { entity: stubEntity(hass) };
  }

  setConfig(config) {
    if (!config || !config.entity) {
      throw new Error("Bitte die Betriebsart-Entität des Raums angeben (entity).");
    }
    this._config = config;
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
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
          .modes { display: grid; grid-template-columns: repeat(auto-fill, minmax(72px, 1fr)); gap: 6px; margin: 8px 0; }
          button.mode { display: flex; flex-direction: column; align-items: center; gap: 2px; font-size: 0.85em; }
          button.mode ha-icon { --mdc-icon-size: 22px; }
          button.active { background: var(--primary-color); color: var(--text-primary-color, #fff); border-color: var(--primary-color); }
          button.chip { flex: 0 1 auto; font-size: 0.85em; padding: 4px 10px; border-radius: 16px; }
          .valve { display: flex; justify-content: space-between; font-size: 0.9em; padding: 4px 0;
            border-top: 1px solid var(--divider-color); cursor: pointer; }
          .foot { display: flex; justify-content: space-between; align-items: center; gap: 6px; margin-top: 8px;
            color: var(--secondary-text-color); font-size: 0.9em; }
          .foot .info { flex: 1 1 auto; }
          .toggle { flex: 0 0 auto; }
          .missing { padding: 8px; }
          .schedule:not(:empty), .savings:not(:empty) { border-top: 1px solid var(--divider-color); margin-top: 12px; padding-top: 8px; }
          .savings label { display: flex; justify-content: space-between; align-items: center; gap: 8px; margin: 6px 0; }
          .savings input, .savings select { width: 7em; font: inherit; padding: 4px 6px; border-radius: 6px;
            border: 1px solid var(--divider-color); background: var(--card-background-color); color: var(--primary-text-color); }
          .savings .answer { margin: 8px 0; line-height: 1.4; }
          .savings .hint { color: var(--secondary-text-color); font-size: 0.85em; }
        </style>
        <ha-card><div class="main"></div><div class="savings"></div><div class="schedule"></div></ha-card>`;
      this._main = this.shadowRoot.querySelector(".main");
      this._savingsBox = this.shadowRoot.querySelector(".savings");
      this._scheduleBox = this.shadowRoot.querySelector(".schedule");
      this.shadowRoot.addEventListener("click", (event) => this._click(event));
    }
    if (this._editor) this._editor.setConfig({ entity: config.entity, name: config.name, embedded: true });
  }

  set hass(hass) {
    this._hass = hass;
    if (this._editor) this._editor.hass = hass;
    this._render();
  }

  getCardSize() {
    return this._showSchedule ? 12 : 6;
  }

  _call(domain, service, data) {
    this._hass.callService(domain, service, data);
  }

  _toggleSchedule() {
    this._showSchedule = !this._showSchedule;
    if (this._showSchedule) {
      if (!this._editor) {
        this._editor = document.createElement("dynamic-heating-schedule-card");
        this._editor.setConfig({ entity: this._config.entity, name: this._config.name, embedded: true });
      }
      this._scheduleBox.appendChild(this._editor);
      this._editor.hass = this._hass;
    } else if (this._editor) {
      this._editor.remove();
    }
    this._render();
  }

  _toggleSavings(related) {
    this._showSavings = !this._showSavings;
    this._savingsAnswer = null;
    if (!this._showSavings) {
      this._savingsBox.innerHTML = "";
      this._render();
      return;
    }
    const value = (id) => {
      const state = id ? this._hass.states[id] : undefined;
      return state && !isNaN(Number(state.state)) ? Number(state.state) : "";
    };
    this._savingsBox.innerHTML = `
      <div class="hint">Spar-Rechner: rechnet die nächsten 7 Tage mit dem gelernten Raummodell durch. Es wird nichts geändert, bis du auf „Übernehmen“ tippst.</div>
      <label>Eco-Temperatur <input type="number" step="0.5" min="5" max="30" name="eco" value="${value(related.eco)}"></label>
      <label>Komforttemperatur <input type="number" step="0.5" min="5" max="30" name="comfort" value="${value(related.comfort)}"></label>
      <label>Komfortbeginn <select name="shift">${SHIFTS.map((minutes) => `
        <option value="${minutes}" ${minutes === 0 ? "selected" : ""}>${minutes === 0 ? "wie im Zeitplan" : `${Math.abs(minutes)} min ${minutes > 0 ? "später" : "früher"}`}</option>`).join("")}
      </select></label>
      <div class="row"><button data-action="savings-run">Rechnen</button></div>
      <div class="answer"></div>`;
    this._render();
  }

  _savingsInput() {
    const read = (name) => this._savingsBox.querySelector(`[name="${name}"]`)?.value;
    const data = { shift_minutes: Number(read("shift") || 0) };
    if (read("eco") !== "") data.eco_temperature = Number(read("eco"));
    if (read("comfort") !== "") data.comfort_temperature = Number(read("comfort"));
    return data;
  }

  async _runSavings(related) {
    const box = this._savingsBox.querySelector(".answer");
    if (!box) return;
    box.textContent = "Wird gerechnet …";
    const input = this._savingsInput();
    try {
      const result = await this._hass.callWS({
        type: "call_service",
        domain: "dynamic_heating",
        service: "estimate_savings",
        service_data: { entity_id: this._config.entity, ...input },
        return_response: true,
      });
      this._savingsAnswer = { input, response: result.response };
      const response = result.response || {};
      const changed = (response.new_eco !== response.eco || response.new_comfort !== response.comfort)
        && related.eco && related.comfort;
      box.innerHTML = `<div>${escape(response.text || "Keine Antwort.")}</div>
        ${changed ? '<div class="row"><button data-action="savings-apply">Übernehmen</button></div>' : ""}
        ${input.shift_minutes ? '<div class="hint">Die Zeiten änderst du im Zeitplan.</div>' : ""}`;
    } catch (err) {
      box.textContent = `Rechnen ging nicht: ${err?.message || err}`;
    }
  }

  async _applySavings(related) {
    const answer = this._savingsAnswer?.response;
    if (!answer) return;
    const box = this._savingsBox.querySelector(".answer");
    try {
      // Lower eco first and raise comfort last, so eco stays below comfort.
      const steps = [];
      if (answer.new_eco !== answer.eco) steps.push([related.eco, answer.new_eco]);
      if (answer.new_comfort !== answer.comfort) steps.push([related.comfort, answer.new_comfort]);
      if (answer.new_eco > answer.eco) steps.reverse();
      for (const [entity, value] of steps) {
        await this._hass.callService("number", "set_value", { entity_id: entity, value });
      }
      if (box) box.innerHTML = '<div>Übernommen.</div>';
      this._savingsAnswer = null;
    } catch (err) {
      if (box) box.textContent = `Übernehmen ging nicht: ${err?.message || err}`;
    }
  }

  _click(event) {
    // Clicks inside the schedule editor are handled there.
    if (this._editor && event.composedPath().includes(this._editor)) return;
    const button = event.target.closest("[data-action]");
    if (!button) return;
    const { action, value } = button.dataset;
    const related = findRelated(this._hass, this._config);
    if (action === "mode") {
      this._call("select", "select_option", { entity_id: this._config.entity, option: value });
    } else if (action === "duration" && related.duration) {
      this._call("select", "select_option", { entity_id: related.duration, option: value });
    } else if (action === "toggle" && related.enabled) {
      this._call("switch", "toggle", { entity_id: related.enabled });
    } else if (action === "schedule") {
      this._toggleSchedule();
    } else if (action === "savings") {
      this._toggleSavings(related);
    } else if (action === "savings-run") {
      this._runSavings(related);
    } else if (action === "savings-apply") {
      this._applySavings(related);
    } else if (action === "more") {
      const moreInfo = new Event("hass-more-info", { bubbles: true, composed: true });
      moreInfo.detail = { entityId: value };
      this.dispatchEvent(moreInfo);
    }
  }

  _render() {
    if (!this._hass || !this._config || !this._main) return;
    const hass = this._hass;
    const select = hass.states[this._config.entity];
    if (!select) {
      this._main.innerHTML = `<div class="missing">Entität ${escape(this._config.entity)} nicht gefunden.</div>`;
      return;
    }
    const related = findRelated(hass, this._config);
    const state = (id) => (id ? hass.states[id] : undefined);
    const status = state(related.status);
    const attributes = status?.attributes || {};
    const room = state(related.room)?.state;
    const target = state(related.target)?.state ?? attributes.target_temperature;
    const demand = state(related.demand)?.state;
    const energy = state(related.energy)?.attributes?.today_kwh;
    const duration = state(related.duration);
    const enabled = state(related.enabled)?.state === "on";
    const problem = state(related.heatingProblem)?.state === "on"
      || state(related.thermostatProblem)?.state === "on";
    const until = time(select.attributes.until);
    const next = time(attributes.next_event);
    const valves = Object.entries(attributes.thermostat_setpoints || {});
    const scheduleButton = this._config.schedule_editor !== false && attributes.schedules?.length;

    // Manuell is set through the temperature, not picked as a button.
    const modes = (this._config.modes || select.attributes.options || MODES)
      .filter((mode) => mode !== "Manuell");
    const modeButtons = modes.map((mode) => `
      <button data-action="mode" data-value="${escape(mode)}" class="mode ${select.state === mode ? "active" : ""}">
        ${ICONS[mode] ? `<ha-icon icon="${ICONS[mode]}"></ha-icon>` : ""}<span>${escape(mode)}</span>
      </button>`).join("");
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

    this._main.innerHTML = `
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
      <div class="modes">${modeButtons}</div>
      ${durationButtons ? `<div class="row">${durationButtons}</div>` : ""}
      ${valveRows}
      <div class="foot">
        <span class="info">${next ? `Nächster Wechsel ${next} Uhr` : ""}${demand !== undefined ? ` · Wärmebedarf ${number(demand, 0)} %` : ""}${energy !== undefined && energy !== null ? ` · heute ca. ${number(energy)} kWh` : ""}</span>
        ${related.eco ? `<button class="toggle chip ${this._showSavings ? "active" : ""}" data-action="savings">Sparen?</button>` : ""}
        ${scheduleButton ? `<button class="toggle chip ${this._showSchedule ? "active" : ""}" data-action="schedule">Zeitplan</button>` : ""}
        ${related.enabled ? `<button class="toggle chip ${enabled ? "active" : ""}" data-action="toggle">${enabled ? "Regelung an" : "Regelung aus"}</button>` : ""}
      </div>`;
  }
}

if (!customElements.get("dynamic-heating-schedule-card")) {
  customElements.define("dynamic-heating-schedule-card", DynamicHeatingScheduleCard);
}
if (!customElements.get("dynamic-heating-card")) {
  customElements.define("dynamic-heating-card", DynamicHeatingCard);
}
window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === "dynamic-heating-card")) {
  window.customCards.push({
    type: "dynamic-heating-card",
    name: "Dynamische Heizung",
    description: "Raumkarte mit Ist/Soll, Betriebsart, Dauer, Ventilen, Regelung, Zeitplan und Spar-Rechner.",
  });
}
if (!window.customCards.some((card) => card.type === "dynamic-heating-schedule-card")) {
  window.customCards.push({
    type: "dynamic-heating-schedule-card",
    name: "Dynamische Heizung – Zeitplan",
    description: "Zeitplan des Raums als Graph: Blöcke ziehen, Temperatur je Block, Raumtemperatur darüber.",
  });
}
