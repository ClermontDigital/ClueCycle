/* Clue Cycle card - a Clue-style cycle tracker for Home Assistant.
 * Unofficial; not affiliated with Clue or BioWink GmbH.
 * Buildless: plain JS custom element, served by the clue_cycle integration.
 */
const CC_VERSION = "0.4.1";

const COL = {
  bg: "#1C1B19", surface: "#262422", surface2: "#2F2D2A", line: "#3B3936",
  text: "#F4EFE7", muted: "#B3ABA0", faint: "#7E776E",
  red: "#E8473F", redLight: "#F26B63", redDark: "#B52A2A", redDeep: "#8B1A1A",
  blue: "#5582C9", blueDark: "#2E5089", blueLight: "#BFD3F5",
  grey: "#4A4845", orange: "#F07B3F", brownBtn: "#6B3410", green: "#3C9B76",
};
const FLOW_COL = { light: COL.redLight, medium: "#D9453F", heavy: COL.redDark, super_heavy: COL.redDeep, spotting: "#F2A09B" };
const FLOW_LABEL = { light: "Light", medium: "Medium", heavy: "Heavy", super_heavy: "Super heavy" };
const FLOW_LEVEL = { light: 1, medium: 2, heavy: 3, super_heavy: 4 };
const KIND_COL = {
  period: COL.red, period_predicted: "rgba(232,71,63,0.35)", fertile: COL.blue,
  fertile_peak: COL.blueDark, ovulation: COL.blueDark, normal: COL.grey,
};
// Fertility treatment colours, and the days drawn as a marker on the ring: [fill, centre, run underneath].
const TX = { stim: "#E8A33D", tww: "#7E62C9", trigger: "#E8A33D", collection: "#2BA6A0", transfer: "#3C9B76", test: "#E0679A" };
Object.assign(KIND_COL, { stim: TX.stim, tww: TX.tww, trigger: TX.trigger, collection: TX.collection,
  collection_expected: TX.collection, transfer: TX.transfer, test: TX.test });
const MARKERS = {
  ovulation: [COL.blueLight, COL.blueDark, "fertile_peak"], trigger: ["#FFE3B8", TX.trigger, "stim"],
  collection: ["#BFEDE9", TX.collection, "normal"], collection_expected: [null, TX.collection, "normal"],
  transfer: ["#C8F0DA", TX.transfer, "tww"], test: ["#F8C9DA", TX.test, "tww"],
};
const DAY_BG = {
  period: COL.red, period_predicted: "rgba(232,71,63,0.22)", fertile: COL.blue, fertile_peak: COL.blueDark,
  ovulation: COL.blueDark, stim: "rgba(232,163,61,0.75)", tww: "rgba(126,98,201,0.6)", trigger: TX.trigger,
  collection: TX.collection, collection_expected: "rgba(43,166,160,0.35)", transfer: TX.transfer, test: TX.test,
};
const fmtNum = (n) => (n == null || n === "" ? "" : Number.isInteger(+n) ? String(+n) : String(+(+n).toFixed(2)));
const hhmm = (d) => `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const parse = (s) => { const [y, m, d] = s.split("-").map(Number); return new Date(y, m - 1, d); };
const addDays = (d, n) => { const x = new Date(d); x.setDate(x.getDate() + n); return x; };
const fmtDay = (s) => { const d = parse(s); return `${d.getDate()} ${MONTHS[d.getMonth()]}`; };
const fmtLong = (s) => { const d = parse(s); return `${WEEKDAYS[d.getDay()]} ${d.getDate()} ${MONTHS[d.getMonth()]}`; };
const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;
const tint = (hex, a) => { const n = parseInt(hex.slice(1), 16); return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${a})`; };

function arcPath(cx, cy, r, a0, a1) {
  const rad = (a) => (a * Math.PI) / 180;
  const x0 = cx + r * Math.cos(rad(a0)), y0 = cy + r * Math.sin(rad(a0));
  const x1 = cx + r * Math.cos(rad(a1)), y1 = cy + r * Math.sin(rad(a1));
  const large = a1 - a0 > 180 ? 1 : 0;
  return `M${x0.toFixed(2)} ${y0.toFixed(2)} A${r} ${r} 0 ${large} 1 ${x1.toFixed(2)} ${y1.toFixed(2)}`;
}
const polar = (cx, cy, r, a) => [cx + r * Math.cos((a * Math.PI) / 180), cy + r * Math.sin((a * Math.PI) / 180)];

class ClueCycleCard extends HTMLElement {
  setConfig(config) {
    this._config = config || {};
    this._view = this._config.view === "track" ? "log" : (this._config.view || "today");
    // view: mini is a compact widget (ring + headline) for other dashboards; tap opens navigation_path.
    this._mini = this._view === "mini";
  }

  static getStubConfig() { return {}; }
  getCardSize() { return this._mini ? 2 : 14; }
  getGridOptions() { return { columns: "full", rows: "auto" }; }

  set hass(hass) {
    this._hass = hass;
    if (!this._started) { this._started = true; this._init(); }
  }

  connectedCallback() {
    if (this._started && this._entryId && !this._unsub) this._subscribe();
  }

  disconnectedCallback() {
    if (this._unsub) { this._unsub.then((u) => u && u()).catch(() => {}); this._unsub = null; }
  }

  /* ---------- data ---------- */

  async _ws(msg) { return this._hass.callWS(msg); }

  async _init() {
    this._root = document.createElement("ha-card");
    if (this._mini) {
      this._root.classList.add("cc-mini", `theme-${this._config.theme || "clue"}`);
      this._root.innerHTML = `<style>${this._miniCss()}</style><div class="cc-main"></div>`;
    } else {
      this._root.innerHTML = `<style>${this._css()}</style><div class="cc"><div class="cc-main">Loading…</div></div>`;
    }
    this.appendChild(this._root);
    this._main = this._root.querySelector(".cc-main");
    this._root.addEventListener("click", (e) => this._onClick(e));
    this._root.addEventListener("change", (e) => this._onChange(e));
    this._today = iso(new Date());
    this._selected = this._today;
    this._month = parse(this._today); this._month.setDate(1);
    this._tipsOpen = false;
    try {
      const [cats, trackers] = await Promise.all([this._ws({ type: "clue_cycle/categories" }), this._ws({ type: "clue_cycle/trackers" })]);
      this._cats = cats.categories;
      this._catById = Object.fromEntries(this._cats.map((c) => [c.id, c]));
      this._trackers = trackers;
      if (!trackers.length) {
        if (this._mini) { this._main.innerHTML = `<div class="mini-empty">No cycle tracker shared with you</div>`; return; }
        this._main.innerHTML = `<div class="empty"><ha-icon icon="mdi:lock-outline"></ha-icon><p>No cycle tracker is shared with you yet.</p>
          <p class="muted">Add one under Settings → Devices &amp; services → Clue Cycle, or ask its owner to share it with you.</p></div>`;
        return;
      }
      const wanted = this._config.entry_id && trackers.find((t) => t.entry_id === this._config.entry_id);
      this._tracker = wanted || trackers[0];
      this._entryId = this._tracker.entry_id;
      this._subscribe();
      await this._reload();
    } catch (err) {
      this._main.innerHTML = `<div class="empty"><p>Couldn't load Clue Cycle.</p><p class="muted">${esc(err.message || err)}</p></div>`;
    }
  }

  _subscribe() {
    if (!this._hass || !this._entryId) return;
    this._unsub = this._hass.connection.subscribeMessage(
      () => this._scheduleReload(), { type: "clue_cycle/subscribe", entry_id: this._entryId },
    ).catch(() => null);
  }

  _scheduleReload() {
    clearTimeout(this._reloadTimer);
    this._reloadTimer = setTimeout(() => this._reload(), 300);
  }

  _range() {
    if (this._view === "calendar") {
      const lo = addDays(this._month, -7), hi = new Date(this._month.getFullYear(), this._month.getMonth() + 1, 7);
      return [iso(lo), iso(hi)];
    }
    const sel = parse(this._selected);
    return [iso(addDays(sel, -24)), iso(addDays(sel, 14))];
  }

  async _reload() {
    if (!this._entryId) return;
    const now = iso(new Date());
    if (now !== this._today) {
      // Past midnight: move "today" along, and the selection with it if it was on today.
      if (this._selected === this._today) this._selected = now;
      this._today = now;
    }
    if (this._mini) {
      this._ov = await this._ws({ type: "clue_cycle/overview", entry_id: this._entryId, date: this._today });
      this._renderMini();
      return;
    }
    const [start, end] = this._range();
    const base = { entry_id: this._entryId, date: this._today };
    const [ov, cal, days] = await Promise.all([
      this._ws({ type: "clue_cycle/overview", ...base }),
      this._ws({ type: "clue_cycle/calendar", ...base, start, end }),
      this._ws({ type: "clue_cycle/days", entry_id: this._entryId, start, end }),
    ]);
    this._ov = ov; this._cal = cal; this._days = days;
    this._tracker = ov.tracker;
    if (this._view === "analysis") this._analysis = await this._ws({ type: "clue_cycle/analysis", ...base });
    if (this._view === "settings" && this._tracker.role === "owner" && !this._sharing) {
      this._sharing = await this._ws({ type: "clue_cycle/sharing", entry_id: this._entryId });
    }
    if (ov.treatment_tracking) {
      const [info, summary] = await Promise.all([
        this._ws({ type: "clue_cycle/treatment_info", entry_id: this._entryId }),
        this._view === "treatment" ? this._ws({ type: "clue_cycle/treatment_summary", ...base }) : Promise.resolve(this._summary),
      ]);
      this._tx = info;
      this._txMeds = Object.fromEntries(info.meds.map((m) => [m.id, m]));
      this._summary = summary;
    } else if (this._view === "treatment") {
      this._view = "today";
    }
    // Reminders and the phones they can go to (also used by the phase notification settings).
    const wantSched = this._canEdit && (this._view === "treatment" || (this._view === "settings" && this._tracker.role === "owner"));
    if (wantSched) this._sched = await this._ws({ type: "clue_cycle/schedules", entry_id: this._entryId });
    this._render();
  }

  get _canEdit() { return this._tracker && (this._tracker.role === "owner" || this._tracker.role === "edit"); }

  /* ---------- rendering ---------- */

  _render() {
    const views = [["today", "Today", "mdi:circle-double"], ["log", "Track", "mdi:plus-circle-outline"],
      ["calendar", "Calendar", "mdi:calendar-month-outline"], ["analysis", "Analysis", "mdi:chart-box-outline"]];
    if (this._ov.treatment_tracking) views.push(["treatment", "Treatment", "mdi:needle"]);
    views.push(["settings", "Settings", "mdi:cog-outline"]);
    const picker = this._trackers.length > 1
      ? `<select class="tracker" data-change="tracker">${this._trackers.map((t) => `<option value="${t.entry_id}" ${t.entry_id === this._entryId ? "selected" : ""}>${esc(t.name)}</option>`).join("")}</select>`
      : `<div class="tracker-name">${esc(this._tracker.name)}</div>`;
    const role = this._tracker.role === "view" ? `<span class="badge">View only</span>` : this._tracker.role === "edit" ? `<span class="badge">Shared with you</span>` : "";
    const body = { today: () => this._today_(), log: () => this._log(), calendar: () => this._calendarView(),
      analysis: () => this._analysisView(), treatment: () => this._treatmentView(),
      settings: () => this._settings() }[this._view]();
    this._main.innerHTML = `
      <div class="top">${picker}${role}</div>
      <div class="body">${body}</div>
      <nav class="tabs">${views.map(([id, label, icon]) => `<button class="tab ${this._view === id ? "on" : ""}" data-action="view" data-view="${id}"><ha-icon icon="${icon}"></ha-icon><span>${label}</span></button>`).join("")}</nav>`;
    if (this._view === "log") {
      const sel = this._main.querySelector(".strip .day.sel");
      if (sel) sel.scrollIntoView({ block: "nearest", inline: "center" });
    }
  }

  _renderMini() {
    const ov = this._ov, ring = ov.ring || [], t = ov.treatment, p = ov.prediction, st = ov.status;
    const n = ring.length, cx = 50, cy = 50, R = 40, SW = 9, gap = 10, span = 360 - gap, per = n ? span / n : 0, a0 = -90 + gap / 2;
    const ang = (i) => a0 + i * per;
    let svg = `<path d="${arcPath(cx, cy, R, a0, a0 + span)}" stroke="var(--mini-track)" stroke-width="${SW}" fill="none" stroke-linecap="round"/>`;
    const runs = [];
    ring.forEach((d, i) => {
      const k = MARKERS[d.kind] ? MARKERS[d.kind][2] : d.kind;
      if (runs.length && runs[runs.length - 1].k === k) runs[runs.length - 1].end = i; else runs.push({ k, start: i, end: i });
    });
    for (const k of ["fertile", "fertile_peak", "stim", "tww", "period_predicted", "period"]) {
      for (const r of runs.filter((x) => x.k === k)) {
        const s0 = ang(r.start) + 0.6, e0 = Math.max(s0 + 0.5, ang(r.end + 1) - 0.6);
        svg += `<path d="${arcPath(cx, cy, R, s0, e0)}" stroke="${k === "period_predicted" ? COL.redLight : KIND_COL[k]}" stroke-opacity="${k === "period_predicted" ? 0.45 : 1}" stroke-width="${SW}" fill="none"/>`;
      }
    }
    ring.forEach((d, i) => {
      const m = MARKERS[d.kind];
      if (!m) return;
      const [x, y] = polar(cx, cy, R, ang(i) + per / 2);
      svg += `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="3.6" fill="${m[0] || "var(--mini-bg)"}" stroke="${m[1]}" stroke-width="1.6"/>`;
    });
    const ti = ring.findIndex((d) => d.date === this._today);
    if (ti >= 0) {
      const [x, y] = polar(cx, cy, R, ang(ti) + per / 2);
      svg += `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="6.5" fill="var(--mini-bg)" stroke="var(--mini-text)" stroke-width="2.4"/>`;
    }
    const day = ti >= 0 ? ring[ti].day : (p.cycle_day || "");
    svg += `<text x="50" y="45" text-anchor="middle" font-size="11" fill="var(--mini-muted)">Day</text>
      <text x="50" y="63" text-anchor="middle" font-size="22" font-weight="700" fill="var(--mini-text)">${day}</text>`;
    let next = "";
    if (t) {
      const nd = ov.next_dose, ahead = (dd) => dd && dd >= this._today;
      const m = [["Egg collection", ahead(t.collection) ? t.collection : ahead(t.expected_collection) ? t.expected_collection : null],
        ["Transfer", ahead(t.transfer) ? t.transfer : null], ["Blood test", ahead(t.test_date) ? t.test_date : null]].find(([, dd]) => dd);
      next = nd ? `Next dose ${nd.time} · ${nd.name}` : m ? `${m[0]} ${fmtDay(m[1])}` : t.type_label;
    } else if (p.next_period) {
      // Don't repeat the ring's sub-line: when it already talks about the period, show the fertile window.
      const said = /period/i.test(st.sub || "") || /period/i.test(st.headline || "");
      if (!said) next = p.late_days ? `Period ${plural(p.late_days, "day")} late` : `Next period ${fmtDay(p.next_period)}`;
      else if (p.fertile_end && p.fertile_start <= this._today && this._today <= p.fertile_end) next = `Fertile until ${fmtDay(p.fertile_end)}`;
      else if (p.fertile_start && p.fertile_start > this._today) next = `Fertile from ${fmtDay(p.fertile_start)}`;
      else next = `Period due ${fmtDay(p.next_period)}`;
    }
    const nav = this._config.navigation_path ? `data-action="open" role="button" tabindex="0"` : "";
    this._main.innerHTML = `<div class="mini ${nav ? "nav" : ""}" ${nav}>
      <svg viewBox="0 0 100 100" class="mini-ring">${svg}</svg>
      <div class="mini-t"><div class="mini-k">${esc(this._config.title || "Cycle")}</div>
        <div class="mini-h">${esc(st.headline)}</div><div class="mini-s">${esc(st.sub)}</div>
        ${next ? `<div class="mini-n">${esc(next)}</div>` : ""}</div></div>`;
  }

  _miniCss() {
    return `
    ha-card.cc-mini { --mini-bg: ${COL.bg}; --mini-text: ${COL.text}; --mini-muted: ${COL.muted}; --mini-track: ${COL.grey};
      --mini-accent: ${COL.blueLight}; background: var(--mini-bg); color: var(--mini-text); border-radius: 14px; overflow: hidden;
      font-family: var(--paper-font-body1_-_font-family, Roboto, system-ui, sans-serif); }
    /* glass: dark navy with a cyan edge, to sit with tron-style dashboards */
    ha-card.cc-mini.theme-glass { --mini-bg: rgba(4,16,26,.9); --mini-text: #e0fbff; --mini-muted: rgba(224,251,255,.65);
      --mini-track: rgba(224,251,255,.14); --mini-accent: #5fd3ff; border: 1px solid rgba(0,168,255,.35); border-radius: 4px;
      box-shadow: 0 0 10px rgba(0,168,255,.12); }
    .mini { display: flex; align-items: center; gap: 10px; padding: 7px 10px 7px 7px; }
    .mini.nav { cursor: pointer; }
    .mini-ring { width: 72px; height: 72px; flex: 0 0 auto; }
    .mini-t { min-width: 0; text-align: left; font-family: var(--paper-font-body1_-_font-family, Roboto, system-ui, sans-serif); }
    .mini-k { font-size: 10px; letter-spacing: .5px; text-transform: uppercase; color: var(--mini-muted); }
    .mini-h { font-size: 14px; font-weight: 700; line-height: 1.2; margin-top: 1px; }
    .mini-s { font-size: 11px; color: var(--mini-muted); line-height: 1.3; }
    .mini-n { font-size: 11px; color: var(--mini-accent); line-height: 1.3; margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .mini-empty { padding: 10px 12px; font-size: 12px; color: var(--mini-muted); }`;
  }

  _ringSvg() {
    const ring = this._ov.ring || [];
    const n = ring.length;
    if (!n) return "";
    const cx = 200, cy = 200, R = 158, SW = 30, gapTop = 7;
    const span = 360 - gapTop, per = span / n, a0 = -90 + gapTop / 2;
    const cap = ((SW / 2) / R) * (180 / Math.PI);
    const ang = (i) => a0 + i * per;
    let svg = `<path d="${arcPath(cx, cy, R, a0, a0 + span)}" stroke="${COL.grey}" stroke-width="${SW}" fill="none" stroke-linecap="round"/>`;
    // Coloured runs: consecutive days of the same kind, with rounded ends that sit on the day edges.
    const runs = [];
    ring.forEach((d, i) => {
      const k = MARKERS[d.kind] ? MARKERS[d.kind][2] : d.kind;
      if (runs.length && runs[runs.length - 1].k === k) runs[runs.length - 1].end = i;
      else runs.push({ k, start: i, end: i });
    });
    const order = ["fertile", "fertile_peak", "stim", "tww", "period_predicted", "period"];
    for (const k of order) {
      for (const r of runs.filter((x) => x.k === k)) {
        let s = ang(r.start) + cap, e = ang(r.end + 1) - cap;
        if (e < s) { const m = (s + e) / 2; s = m - 0.01; e = m + 0.01; }
        const col = k === "period_predicted" ? COL.redLight : KIND_COL[k];
        const op = k === "period_predicted" ? 0.4 : 1;
        svg += `<path d="${arcPath(cx, cy, R, s, e)}" stroke="${col}" stroke-opacity="${op}" stroke-width="${SW}" fill="none" stroke-linecap="round"/>`;
      }
    }
    // Logged-category dots, stacked inward.
    ring.forEach((d, i) => {
      (d.dots || []).slice(0, 5).forEach((c, j) => {
        const [x, y] = polar(cx, cy, R - SW / 2 - 12 - j * 9, ang(i) + per / 2);
        svg += `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="3.2" fill="${c}"/>`;
      });
    });
    // Markers: ovulation, and the trigger, egg collection, transfer and test day in a treatment cycle.
    ring.forEach((d, i) => {
      const m = MARKERS[d.kind];
      if (!m) return;
      const [x, y] = polar(cx, cy, R, ang(i) + per / 2);
      svg += m[0]
        ? `<circle cx="${x}" cy="${y}" r="11" fill="${m[0]}"/><circle cx="${x}" cy="${y}" r="3.6" fill="${m[1]}"/>`
        : `<circle cx="${x}" cy="${y}" r="10" fill="${COL.bg}" stroke="${m[1]}" stroke-width="3" stroke-dasharray="4 3"/>`;
    });
    // Period drop at the start and the arrow back into the next cycle.
    const [dx, dy] = polar(cx, cy, R + SW / 2 + 16, -90 - 1);
    svg += `<path transform="translate(${dx - 9} ${dy - 13})" d="M9 0C9 0 0 10.5 0 16a9 9 0 0 0 18 0C18 10.5 9 0 9 0z" fill="${COL.red}"/>`;
    const [ax, ay] = polar(cx, cy, R, a0 + span - per * 0.9);
    svg += `<path d="M${ax - 8} ${ay + 6} L${ax + 4} ${ay - 4} M${ax + 4} ${ay - 4} L${ax - 7} ${ay - 7} M${ax + 4} ${ay - 4} L${ax + 3} ${ay + 7}" stroke="#8E8A84" stroke-width="2.5" fill="none" stroke-linecap="round"/>`;
    // Today marker.
    const ti = ring.findIndex((d) => d.date === this._today);
    if (ti >= 0) {
      const [x, y] = polar(cx, cy, R, ang(ti) + per / 2);
      const kc = KIND_COL[ring[ti].kind === "period_predicted" ? "period" : ring[ti].kind] || COL.grey;
      svg += `<g class="today-mark" data-action="logday" data-date="${this._today}"><circle cx="${x}" cy="${y}" r="31" fill="${COL.bg}" stroke="${kc}" stroke-width="5"/>
        <text x="${x}" y="${y - 7}" text-anchor="middle" fill="${COL.text}" font-size="11" font-weight="600">Day</text>
        <text x="${x}" y="${y + 15}" text-anchor="middle" fill="${COL.text}" font-size="22" font-weight="700">${ring[ti].day}</text></g>`;
    }
    return `<svg viewBox="-16 -16 432 432" class="ring">${svg}</svg>`;
  }

  _today_() {
    const ov = this._ov, p = ov.prediction, st = ov.status;
    const d = parse(this._today);
    const tips = st.tips.length ? `
      <button class="tips-toggle" data-action="tips">Here's what you can do <ha-icon icon="mdi:chevron-${this._tipsOpen ? "up" : "down"}"></ha-icon></button>` : "";
    const facts = [];
    if (p.next_period) facts.push(p.late_days
      ? ["mdi:water", COL.red, "Period late", plural(p.late_days, "day")]
      : ["mdi:water", COL.red, "Next period", fmtDay(p.next_period), p.days_until_period ? `in ${plural(p.days_until_period, "day")}` : "today"]);
    if (p.fertile_start) facts.push(["mdi:egg-outline", COL.blue, "Fertile window", `${fmtDay(p.fertile_start)} – ${fmtDay(p.fertile_end)}`]);
    if (p.ovulation) facts.push(["mdi:circle-double", COL.blueLight, "Ovulation", fmtDay(p.ovulation)]);
    const t = ov.treatment;
    if (t) {
      facts.push(["mdi:needle", TX.collection, esc(t.type_label + (t.protocol_label ? ` · ${t.protocol_label}` : "")), `Day ${t.day}`]);
      const nd = ov.next_dose;
      if (nd) facts.push(["mdi:bell-ring-outline", TX.stim, "Next dose",
        esc(`${nd.name}${nd.dose != null ? ` ${fmtNum(nd.dose)} ${nd.unit || ""}` : ""}`), `${nd.date === this._today ? "today" : "tomorrow"} ${nd.time}`]);
      const ahead = (dd) => dd && dd >= this._today;
      const next = [["Egg collection", ahead(t.collection) ? t.collection : ahead(t.expected_collection) ? t.expected_collection : null],
        ["Transfer", ahead(t.transfer) ? t.transfer : null], ["Blood test", ahead(t.test_date) ? t.test_date : null]].find(([, dd]) => dd);
      if (next) facts.push(["mdi:calendar-star", TX.test, next[0], fmtDay(next[1])]);
    }
    return `
      <div class="today">
        <div class="ring-wrap">${this._ringSvg() || `<div class="ring-empty"></div>`}
          <div class="ring-center">
            <div class="date"><b>Today,</b> ${d.getDate()} ${MONTHS[d.getMonth()]}</div>
            <div class="headline">${esc(st.headline)}</div>
            <div class="sub">${esc(st.sub)}</div>
            ${tips}
          </div>
        </div>
        ${this._tipsOpen ? `<ul class="tips">${st.tips.map((t) => `<li>${esc(t)}</li>`).join("")}</ul>` : ""}
        ${this._canEdit ? `<button class="feel" data-action="logday" data-date="${this._today}"><span class="smile"><ha-icon icon="mdi:emoticon-happy-outline"></ha-icon></span>How do you feel today?<ha-icon class="chev" icon="mdi:chevron-right"></ha-icon></button>` : ""}
        <div class="facts">${facts.map(([icon, col, label, val, extra]) => `<div class="fact"><ha-icon icon="${icon}" style="color:${col}"></ha-icon><div><div class="muted">${label}</div><div class="val">${val}${extra ? ` <span class="muted small">${extra}</span>` : ""}</div></div></div>`).join("")}</div>
      </div>`;
  }

  _strip() {
    const sel = parse(this._selected);
    const cells = [];
    for (let i = -24; i <= 10; i++) {
      const day = iso(addDays(sel, i));
      const c = this._cal[day] || { kind: "normal", dots: [] };
      const isToday = day === this._today, isSel = day === this._selected, future = day > this._today;
      const bg = DAY_BG[c.kind] || COL.surface2;
      cells.push(`<button class="day ${isSel ? "sel" : ""} ${future ? "future" : ""}" data-action="select" data-date="${day}" style="background:${bg}">
        <span class="dots">${(c.dots || []).slice(0, 3).map((col) => `<i style="background:${col}"></i>`).join("")}</span>
        ${c.kind === "ovulation" ? `<span class="ovdot"></span>` : ""}
        <span class="num">${parse(day).getDate()}</span>${isToday ? `<span class="tlabel">Today</span>` : ""}</button>`);
    }
    return `<div class="strip">${cells.join("")}</div>`;
  }

  _chip(cat, opt, on) {
    const col = cat.id === "period" ? (FLOW_COL[opt.id] || cat.color) : cat.color;
    const style = on ? `background:${col};color:#fff;border-color:${col}` : `background:${tint(col, 0.22)};color:${COL.text};border-color:transparent`;
    return `<button class="chip ${on ? "on" : ""}" ${this._canEdit ? "" : "disabled"} data-action="toggle" data-cat="${cat.id}" data-opt="${opt.id}" style="${style}">
      <ha-icon icon="${opt.icon}" style="color:${on ? "#fff" : col}"></ha-icon>${esc(opt.label)}</button>`;
  }

  _log() {
    const log = this._days[this._selected] || {};
    const title = this._selected === this._today ? "Today" : fmtLong(this._selected);
    if (this._editCats) return `${this._strip()}<div class="log"><h2>${esc(title)}</h2>${this._editCategories()}</div>`;
    const { order, hidden } = this._layout();
    const section = (id) => (id === "treatment" ? this._treatmentLog(log) : this._catSection(this._catById[id], log));
    const shown = order.filter((id) => !hidden.has(id));
    const more = order.filter((id) => hidden.has(id));
    const tools = `<div class="track-tools"><button class="link" data-action="foldall" data-open="true">Expand all</button>
      <button class="link" data-action="foldall" data-open="false">Collapse all</button>
      ${this._canEdit ? `<button class="link" data-action="catedit"><ha-icon icon="mdi:pencil-outline"></ha-icon>Edit categories</button>` : ""}</div>`;
    const moreLogged = more.filter((id) => this._hasValue(id, log)).length;
    const moreBlock = more.length ? `<section class="cat more ${this._moreOpen ? "open" : ""}">
      <button class="cat-h" data-action="more"><span class="cat-l">More categories</span>
        <span class="cat-s">${moreLogged ? `${moreLogged} logged` : `${more.length} ${more.length === 1 ? "category" : "categories"}`}</span>
        <ha-icon icon="mdi:chevron-${this._moreOpen ? "up" : "down"}"></ha-icon></button>
      ${this._moreOpen ? more.map(section).join("") : ""}</section>` : "";
    const sections = tools + shown.map(section).join("") + moreBlock;
    const tagsOn = log.tags || [];
    const tags = `<section><div class="h3row"><h3>My tags</h3>${this._canEdit ? `<button class="link" data-action="newtag"><ha-icon icon="mdi:plus"></ha-icon>Create new tag</button>` : ""}</div>
      ${this._newTag ? `<div class="newtag"><input class="tag-input" placeholder="Tag name" maxlength="40"><button class="btn" data-action="savetag">Add</button><button class="btn ghost" data-action="canceltag">Cancel</button></div>` : ""}
      <div class="taglist">${(this._ov.tags || []).map((t) => `<div class="tag ${tagsOn.includes(t) ? "on" : ""}">
        <button class="tagname" ${this._canEdit ? "" : "disabled"} data-action="tagtoggle" data-tag="${esc(t)}">${tagsOn.includes(t) ? `<ha-icon icon="mdi:check"></ha-icon>` : ""}${esc(t)}</button>
        ${this._canEdit ? `<button class="x" data-action="tagdelete" data-tag="${esc(t)}" title="Delete this tag"><ha-icon icon="mdi:close"></ha-icon></button>` : ""}</div>`).join("") || `<p class="muted">No tags yet.</p>`}</div></section>`;
    const note = `<section><h3>Notes</h3><textarea class="note" ${this._canEdit ? "" : "disabled"} placeholder="Anything else about today?" maxlength="2000">${esc(log.note || "")}</textarea></section>`;
    const by = log.updated_by_name ? `<p class="muted small">Last updated by ${esc(log.updated_by_name)}${log.updated_at ? ` · ${new Date(log.updated_at).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })}` : ""}</p>` : "";
    return `${this._strip()}<div class="log"><h2>${esc(title)}</h2>${by}${sections}${tags}${note}</div>`;
  }

  _layout() {
    // Category order and hidden categories are saved on the tracker; new categories go at the end.
    const tracking = !!(this._ov.treatment_tracking && this._tx);
    const ids = this._cats.map((c) => c.id).filter((id) => id !== "treatment" || tracking);
    const def = ids.filter((id) => id !== "treatment");
    if (tracking) def.splice(def.indexOf("sex") + 1, 0, "treatment");
    const layout = this._ov.layout || {};
    const saved = (layout.order || []).filter((id) => ids.includes(id));
    return { order: [...saved, ...def.filter((id) => !saved.includes(id))], hidden: new Set(layout.hidden || []) };
  }

  _hasValue(id, log) {
    if (id === "treatment") return !!((log.treatment || []).length || (log.meds || []).length || Object.keys(log.results || {}).length);
    const v = log[id];
    return Array.isArray(v) ? v.length > 0 : !!v;
  }

  _isOpen(id, log) {
    // What you open or close sticks for this visit; otherwise Period and anything logged that day start open.
    if (this._fold && id in this._fold) return this._fold[id];
    return id === "period" || this._hasValue(id, log);
  }

  _catHeader(id, label, color, summary, open) {
    return `<button class="cat-h" data-action="fold" data-cat="${id}"><span class="cat-dot" style="background:${color}"></span>
      <span class="cat-l">${esc(label)}</span><span class="cat-s">${esc(summary)}</span>
      <ha-icon icon="mdi:chevron-${open ? "up" : "down"}"></ha-icon></button>`;
  }

  _catSection(cat, log) {
    const value = log[cat.id];
    const isOn = (opt) => (Array.isArray(value) ? value.includes(opt) : value === opt);
    const open = this._isOpen(cat.id, log);
    const chosen = cat.options.filter((o) => isOn(o.id)).map((o) => o.label).join(", ");
    return `<section class="cat ${open ? "open" : ""}">${this._catHeader(cat.id, cat.label, cat.color, chosen, open)}
      ${open ? `<div class="chips">${cat.options.map((o) => this._chip(cat, o, isOn(o.id))).join("")}</div>` : ""}</section>`;
  }

  _editCategories() {
    const d = this._editCats, tracking = !!(this._ov.treatment_tracking && this._tx);
    const shown = d.order.filter((id) => id !== "treatment" || tracking);
    const rows = shown.map((id, i) => {
      const cat = this._catById[id];
      return `<div class="edit-row"><label class="check grow"><input type="checkbox" data-change="catshow" data-cat="${id}"
          ${d.hidden.includes(id) ? "" : "checked"} ${id === "period" ? "disabled" : ""}>
          <span class="cat-dot" style="background:${cat.color}"></span>${esc(cat.label)}</label>
        <button class="x" data-action="catmove" data-cat="${id}" data-step="-1" ${i === 0 ? "disabled" : ""} title="Move up"><ha-icon icon="mdi:arrow-up"></ha-icon></button>
        <button class="x" data-action="catmove" data-cat="${id}" data-step="1" ${i === shown.length - 1 ? "disabled" : ""} title="Move down"><ha-icon icon="mdi:arrow-down"></ha-icon></button></div>`;
    }).join("");
    return `<section class="panel"><h3>Edit categories</h3>
      <p class="muted small">Untick categories you don't use and they move to "More categories" at the bottom of Track, so nothing is lost. Use the arrows to change the order. This is the same for everyone who logs for this tracker.</p>
      ${rows}
      <div class="track-tools"><button class="btn" data-action="catsave">Done</button><button class="btn ghost" data-action="catcancel">Cancel</button>
        <button class="link" data-action="catreset">Reset to the default order</button></div></section>`;
  }

  _medOptions(selected) {
    const groups = {};
    for (const m of this._tx.meds) (groups[m.kind] ||= []).push(m);
    return Object.entries(groups).map(([k, ms]) => `<optgroup label="${esc(this._tx.kinds[k] || k)}">${ms.map((m) =>
      `<option value="${esc(m.id)}" ${m.id === selected ? "selected" : ""}>${esc(m.name)}</option>`).join("")}</optgroup>`).join("");
  }

  _unitOptions(selected) {
    return ["", ...this._tx.units].map((u) => `<option value="${esc(u)}" ${u === (selected || "") ? "selected" : ""}>${esc(u || "unit")}</option>`).join("");
  }

  _lastMed() {
    // The medicine logged most recently on or before the selected day, so the form starts on it.
    const day = Object.keys(this._days || {}).filter((d) => d <= this._selected && (this._days[d].meds || []).length).sort().pop();
    const meds = day ? this._days[day].meds : [];
    const m = meds.length && this._txMeds[meds[meds.length - 1].med];
    return m || this._tx.meds[0];
  }

  _doseText(d) {
    const m = this._txMeds[d.med] || { name: d.med };
    return `${m.name}${d.dose != null ? ` ${fmtNum(d.dose)} ${d.unit || ""}` : ""}`.trim();
  }

  _treatmentLog(log) {
    const doses = (log.meds || []).map((d) => `<div class="dose"><ha-icon icon="mdi:needle" style="color:${TX.collection}"></ha-icon>
      <span class="grow"><b>${esc(this._doseText(d))}</b></span><span class="muted">${esc(d.time || "")}</span>
      ${this._canEdit ? `<button class="x" data-action="dosedel" data-dose="${esc(d.id)}" title="Remove this dose"><ha-icon icon="mdi:close"></ha-icon></button>` : ""}</div>`).join("");
    const first = this._lastMed();
    const form = this._canEdit ? `<div class="form-row">
      <select class="f-med" data-change="medpick">${this._medOptions(first && first.id)}</select>
      <input class="f-dose" type="number" min="0" step="any" placeholder="Dose" inputmode="decimal">
      <select class="f-unit">${this._unitOptions(first && first.unit)}</select>
      <input class="f-time" type="time" value="${this._selected === this._today ? hhmm(new Date()) : ""}">
      <button class="btn" data-action="doseadd">Add dose</button></div>` : "";
    const res = log.results || {};
    const results = `<div class="results">${this._tx.results.map((f) => `<label class="res"><span>${esc(f.label)}</span>
      <input type="number" min="0" step="${f.kind === "int" ? 1 : "any"}" inputmode="decimal" data-change="result" data-key="${f.id}" value="${fmtNum(res[f.id])}" ${this._canEdit ? "" : "disabled"}>
      <em>${esc(f.unit)}</em></label>`).join("")}</div>`;
    const cat = this._catById.treatment, open = this._isOpen("treatment", log);
    const summary = [(log.treatment || []).map((x) => (cat.options.find((o) => o.id === x) || { label: x }).label).join(", "),
      (log.meds || []).length ? plural(log.meds.length, "dose") : "", Object.keys(res).length ? "results" : ""].filter(Boolean).join(" · ");
    const value = log.treatment || [];
    return `<section class="cat ${open ? "open" : ""}">${this._catHeader("treatment", cat.label, cat.color, summary, open)}
      ${open ? `<div class="chips">${cat.options.map((o) => this._chip(cat, o, value.includes(o.id))).join("")}</div>
      <h4>Medicines</h4>${doses || `<p class="muted small">No doses logged on this day.</p>`}${form}
      <h4>Results</h4><p class="muted small">Scan, blood test and lab numbers. Leave anything you didn't get blank.</p>${results}` : ""}</section>`;
  }

  _calendarView() {
    const m = this._month, first = new Date(m), startPad = (first.getDay() + 6) % 7;
    const daysIn = new Date(m.getFullYear(), m.getMonth() + 1, 0).getDate();
    const cells = [];
    for (let i = 0; i < startPad; i++) cells.push(`<div class="cal-cell pad"></div>`);
    for (let d = 1; d <= daysIn; d++) {
      const day = iso(new Date(m.getFullYear(), m.getMonth(), d));
      const c = this._cal[day] || { kind: "normal", dots: [] };
      const cls = ["cal-cell", `k-${c.kind}`, day === this._today ? "is-today" : "", day === this._selected ? "is-sel" : ""].join(" ");
      cells.push(`<button class="${cls}" data-action="logday" data-date="${day}"><span class="n">${d}</span>
        <span class="dots">${(c.dots || []).slice(0, 4).map((col) => `<i style="background:${col}"></i>`).join("")}</span></button>`);
    }
    return `<div class="cal">
      <div class="cal-head"><button class="icon" data-action="month" data-step="-1"><ha-icon icon="mdi:chevron-left"></ha-icon></button>
        <h2>${MONTHS[m.getMonth()]} ${m.getFullYear()}</h2>
        <button class="icon" data-action="month" data-step="1"><ha-icon icon="mdi:chevron-right"></ha-icon></button></div>
      <div class="cal-grid">${["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((w) => `<div class="wd">${w}</div>`).join("")}${cells.join("")}</div>
      <div class="legend"><span><i style="background:${COL.red}"></i>Period</span><span><i class="pred"></i>Predicted period</span>
        <span><i style="background:${COL.blue}"></i>Fertile window</span><span><i style="background:${COL.blueDark}"></i>Peak / ovulation</span>
        ${this._ov.treatment_tracking ? `<span><i style="background:${TX.stim}"></i>Stimulation</span><span><i style="background:${TX.collection}"></i>Egg collection</span>
        <span><i style="background:${TX.transfer}"></i>Transfer</span><span><i style="background:${TX.tww}"></i>Waiting to test</span><span><i style="background:${TX.test}"></i>Test day</span>` : ""}</div></div>`;
  }

  _ringIcon(fraction, color, dots = 0) {
    const C = 2 * Math.PI * 22, f = Math.max(0.04, Math.min(1, fraction));
    return `<svg viewBox="0 0 60 60" class="mini"><circle cx="30" cy="30" r="22" stroke="${COL.grey}" stroke-width="9" fill="none"/>
      <circle cx="30" cy="30" r="22" stroke="${color}" stroke-width="9" fill="none" stroke-linecap="round" stroke-dasharray="${(C * f).toFixed(1)} ${C}" transform="rotate(-90 30 30)"/>
      ${dots ? `<circle cx="14" cy="12" r="4" fill="${COL.blueLight}"/><circle cx="21" cy="8" r="2.5" fill="${COL.blueLight}"/>` : ""}</svg>`;
  }

  _analysisView() {
    const a = this._analysis;
    if (!a) return `<p class="muted">Loading…</p>`;
    const s = a.stats, done = a.cycles.filter((c) => c.length);
    const typical = (ok) => ok == null ? `<span class="muted">Needs 2+ cycles</span>` : ok ? `<span class="ok"><ha-icon icon="mdi:check-circle"></ha-icon>Typical</span>` : `<span class="warn"><ha-icon icon="mdi:alert-circle"></ha-icon>Atypical</span>`;
    const recent = a.cycles.slice(-7);
    const maxDays = Math.max(6, ...recent.map((c) => c.period_length));
    const avgRow = [];
    for (let i = 0; i < s.period_length; i++) {
      const levels = recent.map((c) => FLOW_LEVEL[c.flows[i]]).filter(Boolean);
      const lvl = levels.length ? Math.round(levels.reduce((x, y) => x + y, 0) / levels.length) : 1;
      avgRow.push(Object.keys(FLOW_LEVEL).find((k) => FLOW_LEVEL[k] === lvl));
    }
    const bar = (flows) => `<div class="fbar" style="grid-template-columns:repeat(${maxDays},1fr)">${flows.map((f, i) => `<span style="background:${FLOW_COL[f] || COL.surface2};${i === 0 ? "border-radius:12px 0 0 12px;" : ""}${i === flows.length - 1 ? "border-radius:0 12px 12px 0;" : ""}"></span>`).join("")}</div>`;
    const rows = [`<div class="frow"><b>Average</b>${bar(avgRow)}</div>`]
      .concat(recent.slice().reverse().map((c) => `<div class="frow"><span>${fmtDay(c.start)}</span>${bar(c.flows)}</div>`));
    const maxLen = Math.max(35, ...done.filter((c) => !c.gap).map((c) => c.length));
    const history = done.slice(-12).reverse().map((c) => c.treatment && !c.gap
      ? `<div class="hrow"><span>${fmtDay(c.start)}</span>
      <div class="hbar"><span class="p" style="width:${(c.period_length / maxLen) * 100}%"></span><span class="r" style="background:${TX.collection};width:${(Math.max(0, Math.min(c.length, maxLen) - c.period_length) / maxLen) * 100}%"></span></div><b>${c.length}d</b></div>`
      : c.gap
      ? `<div class="hrow gap"><span>${fmtDay(c.start)} ${parse(c.start).getFullYear()}</span><div class="muted small">Nothing logged for ${c.length} days, so this isn't counted</div><b class="muted">gap</b></div>`
      : `<div class="hrow"><span>${fmtDay(c.start)}</span>
      <div class="hbar"><span class="p" style="width:${(c.period_length / maxLen) * 100}%"></span><span class="r" style="width:${((c.length - c.period_length) / maxLen) * 100}%"></span></div><b>${c.length}d</b></div>`).join("");
    return `<div class="analysis">
      <div class="stat"><div class="stat-l">${this._ringIcon(1, COL.blueLight)}<div><div class="muted">Cycle length</div><div class="big">${plural(s.cycle_length, "day")}</div></div></div>
        <div class="stat-r">${s.cycles_used ? `<div class="muted">${s.typical_cycles} of your last ${plural(s.cycles_used, "cycle")} were</div>${typical(s.typical_cycles === s.cycles_used)}` : `<span class="muted">Log or import a few cycles</span>`}</div></div>
      <div class="stat"><div class="stat-l">${this._ringIcon(0.03, COL.blueLight, 1)}<div><div class="muted">Cycle variation</div><div class="big">${s.variation == null ? "—" : plural(s.variation, "day")}</div></div></div>
        <div class="stat-r">${typical(s.variation_typical)}</div></div>
      <h2>Period flow</h2>
      <div class="stat"><div class="stat-l">${this._ringIcon(s.period_length / 28 * 1.5, COL.red)}<div><div class="muted">Average period length</div><div class="big">${plural(s.period_length, "day")}</div></div></div>
        <div class="stat-r">${typical(s.period_typical)}</div></div>
      <div class="panel legend-flow">${Object.entries(FLOW_LABEL).map(([k, l]) => `<span><i style="background:${FLOW_COL[k]}"></i>${l}</span>`).join("")}</div>
      <div class="panel flows">${rows.join("")}<div class="frow axis"><span></span><div class="fbar" style="grid-template-columns:repeat(${maxDays},1fr)">${Array.from({ length: maxDays }, (_, i) => `<em>${i === 0 ? "Day 1" : `D${i + 1}`}</em>`).join("")}</div></div></div>
      <h2>Cycle history</h2>
      <div class="panel history">${history || `<p class="muted">No complete cycles yet.</p>`}
        ${done.some((c) => c.treatment) ? `<p class="muted small"><i class="sw" style="background:${TX.collection}"></i>Treatment cycles aren't counted in your averages.</p>` : ""}</div>
    </div>`;
  }

  _settings() {
    const t = this._tracker, st = this._ov.settings, owner = t.role === "owner";
    const num = (key, label, min, max) => `<label class="field"><span>${label}</span><input type="number" min="${min}" max="${max}" value="${st[key]}" data-change="setting" data-key="${key}" ${owner ? "" : "disabled"}><em>days</em></label>`;
    let html = `<div class="settings">`;
    html += `<section class="panel"><h3>Cycle settings</h3>
      <label class="field"><span>Goal</span><select data-change="setting" data-key="goal" ${owner ? "" : "disabled"}>
        <option value="conceive" ${st.goal === "conceive" ? "selected" : ""}>Trying to conceive</option>
        <option value="track" ${st.goal === "track" ? "selected" : ""}>Track my cycle</option></select></label>
      ${num("cycle_length", "Usual cycle length", 15, 60)}${num("period_length", "Usual period length", 1, 15)}${num("luteal_length", "Luteal phase", 8, 20)}
      <p class="muted small">The usual lengths are only used until a few cycles are logged or imported.${owner ? "" : " Only the owner can change these."}</p></section>`;
    if (owner) {
      const sh = this._sharing;
      html += `<section class="panel"><h3>Who can see this</h3><p class="muted small">Private by default. Choose who else can see your cycle, and whether they can also log for you.</p>`;
      html += sh ? (sh.users.length ? sh.users.map((u) => {
        const lvl = sh.sharing[u.id] || "none";
        return `<div class="share"><span>${esc(u.name)}</span><div class="seg">${[["none", "Hidden"], ["view", "Can view"], ["edit", "Can edit"]].map(([v, l]) => `<button class="${lvl === v ? "on" : ""}" data-action="share" data-user="${u.id}" data-level="${v}">${l}</button>`).join("")}</div></div>`;
      }).join("") : `<p class="muted">No other users.</p>`) : `<p class="muted">Loading…</p>`;
      if (sh) {
        html += `<div class="share expose"><span>Home Assistant sensors<br><em class="muted small">Cycle day, next period and more for automations. Sensors are visible to every Home Assistant user and kept in history.</em></span>
          <div class="seg">${[[false, "Off"], [true, "On"]].map(([v, l]) => `<button class="${sh.expose_entities === v ? "on" : ""}" data-action="expose" data-on="${v}">${l}</button>`).join("")}</div></div>`;
      }
      html += `</section>`;
      html += this._notifySettings();
      const tracking = !!this._ov.treatment_tracking;
      html += `<section class="panel"><h3>Fertility treatment</h3>
        <div class="share"><span>Track IVF, FET, IUI or egg freezing<br><em class="muted small">Adds a Treatment tab with medicines, dose reminders, results and a summary for your clinic. Natural predictions pause while a treatment cycle runs.</em></span>
        <div class="seg">${[[false, "Off"], [true, "On"]].map(([v, l]) => `<button class="${tracking === v ? "on" : ""}" data-action="txtoggle" data-on="${v}">${l}</button>`).join("")}</div></div></section>`;
    } else {
      html += `<section class="panel"><h3>Sharing</h3><p class="muted small">${t.role === "edit" ? "You can view and log for this tracker." : "You can view this tracker."} Only its owner can change who has access.</p></section>`;
    }
    if (this._canEdit) {
      const imp = this._import;
      html += `<section class="panel"><h3>Import from Clue</h3>
        <p class="muted small">In the Clue app, use Download my data, then pick the zip Clue emails you. If it asks, enter the password from Clue's email. You'll see a preview before anything is saved.</p>
        <input type="file" class="file" data-change="importfile" accept=".json,.cluedata,.zip,application/json,application/zip">
        ${imp && imp.error ? `<p class="warn">${esc(imp.error)}</p>` : ""}
        ${imp && imp.needsPassword ? `<div class="newtag"><input class="zip-pw" type="password" autocomplete="off" placeholder="Password from Clue's email"><button class="btn" data-action="unlockzip">Unlock</button></div>` : ""}
        ${imp && imp.preview ? `<div class="preview"><p><b>${imp.preview.days}</b> days from <b>${fmtDay(imp.preview.range[0])} ${parse(imp.preview.range[0]).getFullYear()}</b> to <b>${fmtDay(imp.preview.range[1])} ${parse(imp.preview.range[1]).getFullYear()}</b>, ${plural(imp.preview.tags, "tag")}.</p>
          ${Object.keys(imp.preview.unknown || {}).length ? `<p class="muted small">Not recognised, so not imported: ${Object.entries(imp.preview.unknown).map(([k, v]) => `${esc(k)} ×${v}`).join(", ")}</p>` : ""}
          ${Object.keys(imp.preview.skipped || {}).length ? `<p class="muted small">Not tracked here (wearable or body data): ${Object.entries(imp.preview.skipped).map(([k, v]) => `${esc(k.replace(/_/g, " "))} ×${v}`).join(", ")}</p>` : ""}
          <button class="btn" data-action="import">Import ${imp.preview.days} days</button></div>` : ""}
        ${imp && imp.done ? `<p class="ok"><ha-icon icon="mdi:check-circle"></ha-icon>Imported ${imp.done.days} days (${imp.done.new_days} new).</p>` : ""}
      </section>`;
    }
    html += `<p class="muted small tc">Clue Cycle ${CC_VERSION} · unofficial, not affiliated with Clue. Not medical advice and not a method of contraception.</p></div>`;
    return html;
  }

  _targetChecks(cls, selected) {
    const targets = (this._sched && this._sched.targets) || [];
    if (!targets.length) return `<p class="muted small">No phones found. Install the Home Assistant app and sign in as someone who can see this tracker.</p>`;
    return `<div class="checks">${targets.map((t) => `<label class="check"><input type="checkbox" class="${cls}" value="${esc(t.service)}" ${selected.includes(t.service) ? "checked" : ""}
      ${cls === "pn-target" ? `data-change="pn"` : ""}>${esc(t.device)} <span class="muted small">${esc(t.user)}</span></label>`).join("")}</div>`;
  }

  _notifySettings() {
    const pn = this._ov.phase_notify || { enabled: false, time: "08:00", targets: [], discreet: false };
    return `<section class="panel"><h3>Cycle notifications</h3>
      <p class="muted small">A notification when your phase changes, like your fertile window starting or your period being due. It's checked once a day.</p>
      <div class="share"><span>Notify me</span><div class="seg">${[[false, "Off"], [true, "On"]].map(([v, l]) => `<button class="${pn.enabled === v ? "on" : ""}" data-action="pn" data-on="${v}">${l}</button>`).join("")}</div></div>
      <label class="field"><span>Time of day</span><input type="time" class="pn-time" value="${esc(pn.time)}" data-change="pn"><em></em></label>
      <p class="muted small">Send to</p>${this._targetChecks("pn-target", pn.targets)}
      <label class="check"><input type="checkbox" class="pn-discreet" data-change="pn" ${pn.discreet ? "checked" : ""}>Discreet: only "There's an update on your cycle" on the lock screen</label>
      ${pn.enabled ? `<button class="btn ghost" data-action="pntest">Send a test</button>` : ""}</section>`;
  }

  _treatmentView() {
    const info = this._tx, t = this._ov.treatment, edit = this._canEdit;
    if (!info) return `<p class="muted">Loading…</p>`;
    const sel = (cls, options, value, blank) => `<select class="${cls}">${blank ? `<option value="">${esc(blank)}</option>` : ""}${Object.entries(options).map(([k, l]) =>
      `<option value="${esc(k)}" ${String(k) === String(value ?? "") ? "selected" : ""}>${esc(l)}</option>`).join("")}</select>`;
    const embryo = { 3: "Day 3 embryo", 5: "Day 5 blastocyst", 6: "Day 6 blastocyst" };
    const kv = (label, value) => (value ? `<div class="kv"><span class="muted">${label}</span><b>${value}</b></div>` : "");
    let html = `<div class="settings">`;
    if (t) {
      html += `<section class="panel"><h3>${esc(t.type_label)}${t.protocol_label ? ` · ${esc(t.protocol_label)}` : ""}</h3>
        <p class="big2">${esc(t.headline)}</p><p class="muted">${esc(t.sub)}</p>
        <div class="kvs">${kv("Started", fmtDay(t.start))}${kv("Stimulation", t.stim_start ? `from ${fmtDay(t.stim_start)} · ${plural(t.stim_days, "day")}` : "")}
          ${kv("Trigger", t.trigger && fmtDay(t.trigger))}${kv("Egg collection", t.collection ? fmtDay(t.collection) : t.expected_collection ? `${fmtDay(t.expected_collection)} (expected)` : "")}
          ${kv("Transfer", t.transfer && fmtDay(t.transfer))}${kv("Blood test", t.test_date && fmtDay(t.test_date))}</div>
        <p class="muted small">Log doses, scans and procedures on the Track tab. The dates above fill in from what you log.</p>
        ${edit ? `<div class="form-grid">
          <label>Protocol ${sel("t-protocol", info.protocols, t.protocol, "Not set")}</label>
          <label>Embryo ${sel("t-embryo", embryo, t.embryo_day, "Not set")}</label>
          <label>Blood test date${t.test_date && !this._summaryTest(t) ? ` (worked out as ${fmtDay(t.test_date)})` : ""} <input type="date" class="t-test" value="${esc(this._summaryTest(t))}"></label>
          <label>Note <input class="t-note" maxlength="2000" value="${esc(t.note || "")}"></label></div>
          <button class="btn ghost" data-action="txsave" data-id="${esc(t.id)}">Save</button>
          <div class="form-grid end">
          <label>Outcome ${sel("t-outcome", info.outcomes, "", "Choose…")}</label>
          <label>Last day <input type="date" class="t-end" value="${this._today}"></label></div>
          <button class="btn" data-action="txend" data-id="${esc(t.id)}">End this cycle</button>` : ""}</section>`;
    } else if (edit) {
      html += `<section class="panel"><h3>Start a treatment cycle</h3>
        <p class="muted small">While it runs, the ring follows the treatment instead of natural predictions, and this cycle is left out of your averages.</p>
        <div class="form-grid">
          <label>Treatment ${sel("t-type", info.types, "ivf")}</label>
          <label>Protocol ${sel("t-protocol", info.protocols, "", "Not set")}</label>
          <label>First day <input type="date" class="t-start" value="${this._today}"></label>
          <label>Embryo ${sel("t-embryo", embryo, "", "Not set")}</label>
          <label>Blood test date <input type="date" class="t-test"></label></div>
        <button class="btn" data-action="txstart">Start</button></section>`;
    } else {
      html += `<section class="panel"><h3>No treatment cycle running</h3><p class="muted small">Only people who can edit this tracker can start one.</p></section>`;
    }
    if (edit) html += this._remindersPanel() + this._medsPanel();
    html += this._summaryPanel();
    html += `<p class="muted small tc">Always follow your clinic's instructions. Clue Cycle only keeps track and is not medical advice.</p></div>`;
    return html;
  }

  _summaryTest(t) {
    const rec = (this._tx.cycles || []).find((c) => c.id === t.id);
    return (rec && rec.test_date) || "";
  }

  _remindersPanel() {
    const sc = this._sched || { schedules: [], targets: [] };
    const tname = (svc) => (sc.targets.find((x) => x.service === svc) || { device: svc }).device;
    const rows = sc.schedules.map((r) => `<div class="sched"><div class="grow"><b>${esc(r.time)}</b> ${esc(this._doseText(r))}
        <div class="muted small">${fmtDay(r.start)}${r.end ? ` – ${fmtDay(r.end)}` : " onwards"} · ${esc(r.targets.map(tname).join(", "))}${r.discreet ? " · discreet" : ""}</div></div>
      <div class="seg">${[[false, "Off"], [true, "On"]].map(([v, l]) => `<button class="${r.enabled === v ? "on" : ""}" data-action="schedtoggle" data-id="${esc(r.id)}" data-on="${v}">${l}</button>`).join("")}</div>
      <button class="btn ghost" data-action="schedtest" data-id="${esc(r.id)}">Test</button>
      <button class="x" data-action="scheddel" data-id="${esc(r.id)}" title="Delete this reminder"><ha-icon icon="mdi:close"></ha-icon></button></div>`).join("");
    const first = this._lastMed();
    return `<section class="panel"><h3>Dose reminders</h3>
      <p class="muted small">A notification at dose time with Done and Snooze buttons. Done logs the dose for you. If it isn't logged within 30 minutes, it asks once more.</p>
      ${rows || `<p class="muted small">No reminders yet.</p>`}
      <h4>Add a reminder</h4>
      <div class="form-row"><select class="s-med" data-change="medpick">${this._medOptions(first && first.id)}</select>
        <input class="s-dose" type="number" min="0" step="any" placeholder="Dose" inputmode="decimal">
        <select class="s-unit">${this._unitOptions(first && first.unit)}</select>
        <input class="s-time" type="time" value="19:00"></div>
      <div class="form-grid"><label>First day <input type="date" class="s-start" value="${this._today}"></label>
        <label>Last day (optional) <input type="date" class="s-end"></label></div>
      <p class="muted small">Send to</p>${this._targetChecks("s-target", sc.targets.length === 1 ? [sc.targets[0].service] : [])}
      <label class="check"><input type="checkbox" class="s-discreet">Discreet: only "Time for your 19:00 dose" on the lock screen</label>
      <label class="check"><input type="checkbox" class="s-follow" checked>Ask again after 30 minutes if it isn't logged</label>
      <button class="btn" data-action="schedadd">Add reminder</button></section>`;
  }

  _medsPanel() {
    const custom = this._tx.meds.filter((m) => m.custom);
    const kinds = Object.entries(this._tx.kinds).map(([k, l]) => `<option value="${esc(k)}">${esc(l)}</option>`).join("");
    return `<section class="panel"><h3>Your medicines</h3>
      <p class="muted small">Common medicines are already in the list. Add anything else your clinic prescribes.</p>
      ${custom.map((m) => `<div class="dose"><span class="grow"><b>${esc(m.name)}</b> <span class="muted small">${esc(this._tx.kinds[m.kind] || m.kind)}${m.unit ? ` · ${esc(m.unit)}` : ""}</span></span>
        <button class="x" data-action="meddel" data-med="${esc(m.id)}" title="Remove"><ha-icon icon="mdi:close"></ha-icon></button></div>`).join("")}
      <div class="form-row"><input class="m-name" maxlength="40" placeholder="Name"><select class="m-kind">${kinds}</select>
        <select class="m-unit">${this._unitOptions("")}</select><button class="btn ghost" data-action="medadd">Add medicine</button></div></section>`;
  }

  _summaryPanel() {
    const list = this._summary || [];
    if (!list.length) return "";
    const fields = Object.fromEntries(this._tx.results.map((f) => [f.id, f]));
    const cards = list.map((c) => {
      const dates = [["Stimulation", c.stim_start && `${fmtDay(c.stim_start)}, ${plural(c.stim_days, "day")}`], ["Trigger", c.trigger && fmtDay(c.trigger)],
        ["Egg collection", c.collection && fmtDay(c.collection)], ["Transfer", c.transfer && fmtDay(c.transfer)], ["Blood test", c.test_date && fmtDay(c.test_date)]]
        .filter(([, v]) => v).map(([l, v]) => `<span><span class="muted">${l}</span> ${v}</span>`).join("");
      const meds = c.medicines.map((m) => `<tr><td>${esc(m.name)}</td><td>${plural(m.days, "day")}</td><td>${fmtDay(m.first)} – ${fmtDay(m.last)}</td>
        <td>${esc(Object.entries(m.totals).map(([u, v]) => `${fmtNum(v)} ${u}`).join(", "))}</td></tr>`).join("");
      const results = Object.entries(c.results).map(([k, vals]) => `<span><span class="muted">${esc((fields[k] || { label: k }).label)}</span>
        ${esc(vals.map((v) => `${fmtNum(v.value)}${fields[k] && fields[k].unit ? ` ${fields[k].unit}` : ""}${vals.length > 1 ? ` (${fmtDay(v.date)})` : ""}`).join(", "))}</span>`).join("");
      return `<div class="sum"><div class="sum-h"><b>${esc(c.type_label)}</b>${c.protocol_label ? ` · ${esc(c.protocol_label)}` : ""}
          <span class="muted">${fmtDay(c.start)} ${parse(c.start).getFullYear()}${c.end ? ` – ${fmtDay(c.end)}` : " – now"}</span>
          ${c.outcome ? `<span class="badge">${esc(this._tx.outcomes[c.outcome] || c.outcome)}</span>` : ""}
          ${this._canEdit && c.end ? `<button class="x" data-action="txdel" data-id="${esc(c.id)}" title="Delete this treatment cycle"><ha-icon icon="mdi:delete-outline"></ha-icon></button>` : ""}</div>
        ${dates ? `<div class="sum-line">${dates}</div>` : ""}
        ${meds ? `<table><thead><tr><th>Medicine</th><th>Days</th><th>Dates</th><th>Total</th></tr></thead><tbody>${meds}</tbody></table>` : ""}
        ${results ? `<div class="sum-line">${results}</div>` : ""}${c.note ? `<p class="muted small">${esc(c.note)}</p>` : ""}</div>`;
    }).join("");
    return `<section class="panel"><div class="h3row"><h3>Summary for your clinic</h3>
      <span><button class="btn ghost" data-action="txcopy">Copy</button> <button class="btn ghost" data-action="txprint">Print or PDF</button></span></div>${cards}</section>`;
  }

  _summaryText() {
    const fields = Object.fromEntries(this._tx.results.map((f) => [f.id, f]));
    return (this._summary || []).map((c) => [
      `${c.type_label}${c.protocol_label ? ` (${c.protocol_label})` : ""}: ${c.start} to ${c.end || "now"}${c.outcome ? `, ${this._tx.outcomes[c.outcome] || c.outcome}` : ""}`,
      c.stim_start ? `Stimulation from ${c.stim_start}, ${c.stim_days} days` : "", c.trigger ? `Trigger ${c.trigger}` : "",
      c.collection ? `Egg collection ${c.collection}` : "", c.transfer ? `Transfer ${c.transfer}` : "", c.test_date ? `Blood test ${c.test_date}` : "",
      ...c.medicines.map((m) => `${m.name}: ${m.days} days, ${m.first} to ${m.last}${Object.keys(m.totals).length ? `, total ${Object.entries(m.totals).map(([u, v]) => `${fmtNum(v)} ${u}`).join(", ")}` : ""}`),
      ...Object.entries(c.results).map(([k, vals]) => `${(fields[k] || { label: k }).label}: ${vals.map((v) => `${fmtNum(v.value)}${fields[k] && fields[k].unit ? ` ${fields[k].unit}` : ""} (${v.date})`).join(", ")}`),
      c.note ? `Note: ${c.note}` : "",
    ].filter(Boolean).join("\n")).join("\n\n");
  }

  _printSummary() {
    const body = esc(this._summaryText()).replace(/\n/g, "<br>");
    const frame = document.createElement("iframe");
    frame.style.cssText = "position:fixed;width:0;height:0;border:0;right:0;bottom:0";
    document.body.appendChild(frame);
    const doc = frame.contentWindow.document;
    doc.open();
    doc.write(`<!doctype html><title>Treatment summary</title><body style="font:14px/1.5 system-ui,sans-serif;color:#111;padding:24px">
      <h2>Treatment summary</h2><p style="color:#666">From Clue Cycle, ${new Date().toLocaleDateString()}</p><p>${body}</p></body>`);
    doc.close();
    setTimeout(() => { frame.contentWindow.focus(); frame.contentWindow.print(); setTimeout(() => frame.remove(), 1000); }, 200);
  }

  _val(cls) { const el = this._root.querySelector(`.${cls}`); return el ? el.value : ""; }

  async _try(fn) {
    try { return await fn(); } catch (err) { this._toast(err.message || String(err)); return null; }
  }

  async _savePhaseNotify(enabled) {
    const targets = [...this._root.querySelectorAll(".pn-target:checked")].map((x) => x.value);
    const pn = this._ov.phase_notify || {};
    if (enabled === undefined) enabled = !!pn.enabled;
    if (enabled && !targets.length) {
      // Turning it on with nothing ticked: default to the owner's own phones.
      const mine = ((this._sched && this._sched.targets) || []).filter((t) => t.user === (this._hass.user && this._hass.user.name));
      targets.push(...mine.map((t) => t.service));
    }
    const res = await this._try(() => this._ws({ type: "clue_cycle/settings_set", entry_id: this._entryId,
      phase_notify: { enabled, time: this._val("pn-time") || "08:00", targets, discreet: !!this._root.querySelector(".pn-discreet:checked") } }));
    if (res) await this._reload();
  }

  /* ---------- events ---------- */

  async _set(changes, date = this._selected) {
    if (!this._canEdit) return;
    try {
      const res = await this._ws({ type: "clue_cycle/set_day", entry_id: this._entryId, date, changes });
      this._days[date] = { ...res.log, updated_by_name: this._hass.user?.name };
      this._render();
      this._scheduleReload();
    } catch (err) { this._toast(err.message || String(err)); }
  }

  async _onClick(e) {
    const el = e.target.closest("[data-action]");
    if (!el || el.disabled) return;
    const a = el.dataset.action;
    if (a === "open") {
      const path = this._config.navigation_path;
      if (path) { history.pushState(null, "", path); window.dispatchEvent(new CustomEvent("location-changed", { detail: { replace: false } })); }
      return;
    }
    if (a === "view") {
      this._view = el.dataset.view;
      await this._reload();
    } else if (a === "tips") { this._tipsOpen = !this._tipsOpen; this._render(); }
    else if (a === "logday" || a === "select") {
      this._selected = el.dataset.date;
      this._month = parse(this._selected); this._month.setDate(1);
      this._view = "log"; await this._reload();
    }
    else if (a === "month") { this._month = new Date(this._month.getFullYear(), this._month.getMonth() + Number(el.dataset.step), 1); await this._reload(); }
    else if (a === "toggle") {
      const cat = this._catById[el.dataset.cat], opt = el.dataset.opt, log = this._days[this._selected] || {};
      if (cat.single) await this._set({ [cat.id]: log[cat.id] === opt ? null : opt });
      else {
        const cur = log[cat.id] || [];
        await this._set({ [cat.id]: cur.includes(opt) ? cur.filter((x) => x !== opt) : [...cur, opt] });
      }
    } else if (a === "tagtoggle") {
      const tag = el.dataset.tag, cur = (this._days[this._selected] || {}).tags || [];
      await this._set({ tags: cur.includes(tag) ? cur.filter((x) => x !== tag) : [...cur, tag] });
    } else if (a === "newtag") { this._newTag = true; this._render(); this._root.querySelector(".tag-input")?.focus(); }
    else if (a === "canceltag") { this._newTag = false; this._render(); }
    else if (a === "savetag") {
      const name = this._root.querySelector(".tag-input")?.value.trim();
      if (!name) return;
      try { await this._ws({ type: "clue_cycle/tag_add", entry_id: this._entryId, name }); this._newTag = false; await this._reload(); }
      catch (err) { this._toast(err.message); }
    } else if (a === "tagdelete") {
      if (!confirm(`Delete the tag "${el.dataset.tag}"? It will be removed from every day it's logged on.`)) return;
      await this._ws({ type: "clue_cycle/tag_remove", entry_id: this._entryId, name: el.dataset.tag });
      await this._reload();
    } else if (a === "share") {
      const sharing = { ...this._sharing.sharing };
      if (el.dataset.level === "none") delete sharing[el.dataset.user]; else sharing[el.dataset.user] = el.dataset.level;
      const res = await this._ws({ type: "clue_cycle/sharing_set", entry_id: this._entryId, sharing });
      this._sharing.sharing = res.sharing; this._render();
    } else if (a === "expose") {
      const on = el.dataset.on === "true";
      if (on && !confirm("Turn on Home Assistant sensors? They're visible to every Home Assistant user and kept in history.")) return;
      const res = await this._ws({ type: "clue_cycle/sharing_set", entry_id: this._entryId, expose_entities: on });
      this._sharing.expose_entities = res.expose_entities; this._render();
    } else if (a === "fold") {
      const log = this._days[this._selected] || {};
      this._fold = { ...(this._fold || {}), [el.dataset.cat]: !this._isOpen(el.dataset.cat, log) };
      this._render();
    } else if (a === "foldall") {
      const open = el.dataset.open === "true";
      this._fold = Object.fromEntries(this._layout().order.map((id) => [id, open]));
      this._moreOpen = open && this._moreOpen;
      this._render();
    } else if (a === "more") {
      this._moreOpen = !this._moreOpen; this._render();
    } else if (a === "catedit") {
      const { order, hidden } = this._layout();
      this._editCats = { order: [...order], hidden: [...hidden] }; this._render();
    } else if (a === "catmove") {
      const d = this._editCats, tracking = !!(this._ov.treatment_tracking && this._tx);
      const shown = d.order.filter((id) => id !== "treatment" || tracking);
      const i = shown.indexOf(el.dataset.cat), other = shown[i + Number(el.dataset.step)];
      if (other) {
        const a1 = d.order.indexOf(el.dataset.cat), a2 = d.order.indexOf(other);
        [d.order[a1], d.order[a2]] = [d.order[a2], d.order[a1]];
        this._render();
      }
    } else if (a === "catreset") {
      this._ov.layout = {}; const { order } = this._layout();
      this._editCats = { order, hidden: this._editCats.hidden }; this._render();
    } else if (a === "catcancel") {
      this._editCats = null; this._render();
    } else if (a === "catsave") {
      const r = await this._try(() => this._ws({ type: "clue_cycle/layout_set", entry_id: this._entryId,
        order: this._editCats.order, hidden: this._editCats.hidden }));
      if (r) { this._ov.layout = r; this._editCats = null; this._render(); this._scheduleReload(); }
    } else if (a === "doseadd") {
      const dose = this._val("f-dose"), time = this._val("f-time");
      const res = await this._try(() => this._ws({ type: "clue_cycle/dose_add", entry_id: this._entryId, date: this._selected,
        med: this._val("f-med"), dose: dose === "" ? null : Number(dose), unit: this._val("f-unit") || null, time: time || null }));
      if (res) { this._days[this._selected] = { ...res.log, updated_by_name: this._hass.user?.name }; this._render(); this._scheduleReload(); }
    } else if (a === "dosedel") {
      const res = await this._try(() => this._ws({ type: "clue_cycle/dose_remove", entry_id: this._entryId, date: this._selected, dose_id: el.dataset.dose }));
      if (res) { this._days[this._selected] = res.log; this._render(); this._scheduleReload(); }
    } else if (a === "txtoggle") {
      const on = el.dataset.on === "true";
      if (await this._try(() => this._ws({ type: "clue_cycle/settings_set", entry_id: this._entryId, treatment_tracking: on }))) await this._reload();
    } else if (a === "pn") {
      await this._savePhaseNotify(el.dataset.on === "true");
    } else if (a === "pntest") {
      const r = await this._try(() => this._ws({ type: "clue_cycle/notify_test", entry_id: this._entryId }));
      if (r) this._toast(r.sent ? `Test sent to ${plural(r.sent, "phone")}` : "Nothing was sent. Check the phones ticked above.");
    } else if (a === "txstart") {
      const embryo = this._val("t-embryo");
      const r = await this._try(() => this._ws({ type: "clue_cycle/treatment_start", entry_id: this._entryId, treatment_type: this._val("t-type"),
        protocol: this._val("t-protocol") || null, start: this._val("t-start"), embryo_day: embryo ? Number(embryo) : null, test_date: this._val("t-test") || null }));
      if (r) await this._reload();
    } else if (a === "txsave") {
      const embryo = this._val("t-embryo");
      const r = await this._try(() => this._ws({ type: "clue_cycle/treatment_update", entry_id: this._entryId, treatment_id: el.dataset.id,
        protocol: this._val("t-protocol") || null, embryo_day: embryo ? Number(embryo) : null, test_date: this._val("t-test") || null, note: this._val("t-note") }));
      if (r) { this._toast("Saved"); await this._reload(); }
    } else if (a === "txend") {
      const outcome = this._val("t-outcome");
      if (!outcome) { this._toast("Choose an outcome first"); return; }
      if (!confirm("End this treatment cycle? Natural predictions resume from the next period.")) return;
      const r = await this._try(() => this._ws({ type: "clue_cycle/treatment_update", entry_id: this._entryId, treatment_id: el.dataset.id,
        outcome, end: this._val("t-end") || this._today }));
      if (r) await this._reload();
    } else if (a === "txdel") {
      if (!confirm("Delete this treatment cycle from the summary? The doses and results logged on its days are kept.")) return;
      if (await this._try(() => this._ws({ type: "clue_cycle/treatment_delete", entry_id: this._entryId, treatment_id: el.dataset.id })) !== null) await this._reload();
    } else if (a === "txcopy") {
      await this._try(async () => { await navigator.clipboard.writeText(this._summaryText()); this._toast("Summary copied"); });
    } else if (a === "txprint") {
      this._printSummary();
    } else if (a === "schedadd") {
      const targets = [...this._root.querySelectorAll(".s-target:checked")].map((x) => x.value);
      const dose = this._val("s-dose");
      const r = await this._try(() => this._ws({ type: "clue_cycle/schedule_set", entry_id: this._entryId, med: this._val("s-med"),
        dose: dose === "" ? null : Number(dose), unit: this._val("s-unit") || null, time: this._val("s-time"), start: this._val("s-start") || null,
        end: this._val("s-end") || null, targets, discreet: !!this._root.querySelector(".s-discreet:checked"),
        follow_up: !!this._root.querySelector(".s-follow:checked") }));
      if (r) await this._reload();
    } else if (a === "schedtoggle") {
      const r0 = this._sched.schedules.find((x) => x.id === el.dataset.id);
      const r = r0 && await this._try(() => this._ws({ type: "clue_cycle/schedule_set", entry_id: this._entryId, schedule_id: r0.id, med: r0.med,
        dose: r0.dose, unit: r0.unit, time: r0.time, start: r0.start, end: r0.end, targets: r0.targets, discreet: r0.discreet,
        follow_up: r0.follow_up, enabled: el.dataset.on === "true" }));
      if (r) await this._reload();
    } else if (a === "schedtest") {
      const r = await this._try(() => this._ws({ type: "clue_cycle/notify_test", entry_id: this._entryId, schedule_id: el.dataset.id }));
      if (r) this._toast(r.sent ? `Test sent to ${plural(r.sent, "phone")}` : "Nothing was sent");
    } else if (a === "scheddel") {
      if (!confirm("Delete this reminder?")) return;
      if (await this._try(() => this._ws({ type: "clue_cycle/schedule_remove", entry_id: this._entryId, schedule_id: el.dataset.id })) !== null) await this._reload();
    } else if (a === "medadd") {
      const name = this._val("m-name").trim();
      if (!name) return;
      const r = await this._try(() => this._ws({ type: "clue_cycle/med_add", entry_id: this._entryId, name, kind: this._val("m-kind"), unit: this._val("m-unit") }));
      if (r) await this._reload();
    } else if (a === "meddel") {
      if (await this._try(() => this._ws({ type: "clue_cycle/med_remove", entry_id: this._entryId, med: el.dataset.med })) !== null) await this._reload();
    } else if (a === "unlockzip") {
      const pw = this._root.querySelector(".zip-pw")?.value;
      if (pw) await this._previewImport(pw);
    } else if (a === "import") {
      try {
        const msg = { type: "clue_cycle/import", entry_id: this._entryId, content: this._import.content, filename: this._import.name };
        if (this._import.password) msg.password = this._import.password;
        const done = await this._ws(msg);
        this._import = { done }; await this._reload();
      } catch (err) { this._import = { error: err.message }; this._render(); }
    }
  }

  async _onChange(e) {
    const el = e.target;
    if (el.classList.contains("note")) { await this._set({ note: el.value }); return; }
    const kind = el.dataset.change;
    if (kind === "tracker") {
      this.disconnectedCallback();
      this._tracker = this._trackers.find((t) => t.entry_id === el.value); this._entryId = el.value; this._sharing = null;
      this._subscribe(); await this._reload();
    } else if (kind === "setting") {
      const key = el.dataset.key, value = key === "goal" ? el.value : Number(el.value);
      try { await this._ws({ type: "clue_cycle/settings_set", entry_id: this._entryId, [key]: value }); await this._reload(); }
      catch (err) { this._toast(err.message); }
    } else if (kind === "catshow") {
      const d = this._editCats, id = el.dataset.cat;
      d.hidden = el.checked ? d.hidden.filter((x) => x !== id) : [...d.hidden, id];
    } else if (kind === "result") {
      const v = el.value.trim();
      await this._set({ results: { [el.dataset.key]: v === "" ? null : Number(v) } });
    } else if (kind === "medpick") {
      // Picking a medicine sets its usual unit; no re-render, so the rest of the form is kept.
      const med = this._txMeds[el.value], unit = el.parentElement.querySelector(".f-unit, .s-unit");
      if (med && unit) unit.value = med.unit || "";
    } else if (kind === "pn") {
      await this._savePhaseNotify();
    } else if (kind === "importfile" && el.files && el.files[0]) {
      const file = el.files[0];
      const content = await new Promise((res, rej) => {
        const r = new FileReader();
        r.onload = () => res(String(r.result).split(",")[1] || "");
        r.onerror = () => rej(r.error);
        r.readAsDataURL(file);
      });
      this._import = { content, name: file.name };
      await this._previewImport();
    }
  }

  async _previewImport(password) {
    const { content, name } = this._import;
    const msg = { type: "clue_cycle/import", entry_id: this._entryId, content, filename: name, dry_run: true };
    if (password) msg.password = password;
    try {
      const preview = await this._ws(msg);
      this._import = { content, name, password, preview };
    } catch (err) {
      // Clue's data download is a password-protected zip: ask for the password and try again.
      this._import = { content, name, error: err.message, needsPassword: err.code === "password_required" };
    }
    this._render();
  }

  _toast(message) {
    this.dispatchEvent(new CustomEvent("hass-notification", { detail: { message }, bubbles: true, composed: true }));
  }

  _css() {
    return `
    ha-card { background: ${COL.bg}; color: ${COL.text}; border-radius: 18px; overflow: hidden; }
    .cc { font-family: var(--paper-font-body1_-_font-family, Roboto, system-ui, sans-serif); }
    .cc-main { padding: 18px 18px 0; }
    .muted { color: ${COL.muted}; } .small { font-size: 12px; } .tc { text-align: center; }
    .top { display: flex; align-items: center; gap: 10px; margin-bottom: 6px; }
    .tracker-name, .tracker { font-size: 18px; font-weight: 600; color: ${COL.text}; background: transparent; border: 0; }
    .tracker option { background: ${COL.surface}; }
    .badge { font-size: 11px; padding: 3px 8px; border-radius: 99px; background: ${COL.surface2}; color: ${COL.muted}; }
    .body { min-height: 420px; padding-bottom: 12px; }
    .tabs { display: flex; border-top: 1px solid ${COL.line}; margin: 0 -18px; }
    .tab { flex: 1; background: none; border: 0; color: ${COL.muted}; padding: 10px 4px 12px; display: flex; flex-direction: column; align-items: center; gap: 3px; font-size: 12px; cursor: pointer; }
    .tab.on { color: ${COL.blueLight}; }
    button { font: inherit; cursor: pointer; }
    h2 { font-size: 22px; margin: 18px 0 10px; } h3 { font-size: 18px; margin: 18px 0 10px; }
    .empty { text-align: center; padding: 50px 10px; } .empty ha-icon { --mdc-icon-size: 40px; color: ${COL.muted}; }
    /* Today */
    .today { max-width: 520px; margin: 0 auto; }
    .ring-wrap { position: relative; width: 100%; max-width: 440px; margin: 0 auto; aspect-ratio: 1; }
    .ring { width: 100%; height: 100%; display: block; }
    .ring-empty { width: 100%; height: 100%; border-radius: 50%; border: 30px solid ${COL.grey}; box-sizing: border-box; }
    .today-mark { cursor: pointer; }
    .ring-center { position: absolute; inset: 22%; display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; }
    .ring-center .date { font-size: 16px; color: ${COL.text}; margin-bottom: 8px; }
    .ring-center .headline { font-size: clamp(20px, 4.4vw, 30px); font-weight: 700; line-height: 1.2; }
    .ring-center .sub { color: ${COL.muted}; margin-top: 6px; font-size: 14px; }
    .tips-toggle { background: none; border: 0; color: ${COL.blueLight}; margin-top: 10px; font-size: 15px; display: flex; align-items: center; gap: 2px; }
    .tips { background: ${COL.surface}; border-radius: 14px; padding: 12px 16px 12px 32px; margin: 4px 0 12px; line-height: 1.5; }
    .feel { width: 100%; display: flex; align-items: center; gap: 12px; background: ${COL.brownBtn}; color: #fff; border: 0; border-radius: 22px; padding: 14px 18px; font-size: 17px; font-weight: 600; margin: 8px 0 14px; }
    .feel .smile { background: ${COL.orange}; border-radius: 50%; width: 34px; height: 34px; display: grid; place-items: center; }
    .feel .chev { margin-left: auto; color: ${COL.orange}; }
    .facts { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; }
    .fact { display: flex; gap: 10px; align-items: center; background: ${COL.surface}; border-radius: 14px; padding: 10px 12px; }
    .fact .val { font-weight: 600; }
    /* Log */
    .strip { display: flex; gap: 6px; overflow-x: auto; padding: 4px 2px 10px; scrollbar-width: thin; }
    .strip .day { position: relative; flex: 0 0 58px; height: 64px; border: 3px solid transparent; border-radius: 10px; color: #fff; }
    .strip .day.sel { border-color: ${COL.blueLight}; }
    .strip .day.future { opacity: 0.75; }
    .strip .num { position: absolute; right: 7px; bottom: 5px; font-size: 18px; font-weight: 600; }
    .strip .tlabel { position: absolute; left: 6px; bottom: 6px; font-size: 9px; text-transform: uppercase; opacity: 0.85; }
    .strip .dots { position: absolute; left: 5px; top: 5px; display: flex; gap: 3px; }
    .strip .dots i, .cal-cell .dots i, .legend i, .legend-flow i { display: inline-block; width: 8px; height: 8px; border-radius: 50%; }
    .strip .ovdot { position: absolute; right: 6px; top: 6px; width: 10px; height: 10px; border-radius: 50%; background: ${COL.blueLight}; }
    .log h2 { margin-top: 8px; }
    .chips { display: flex; flex-wrap: wrap; gap: 10px; }
    .chip { display: inline-flex; align-items: center; gap: 8px; border: 2px solid transparent; border-radius: 22px; padding: 9px 16px 9px 12px; font-size: 16px; font-weight: 500; }
    .chip ha-icon { --mdc-icon-size: 22px; }
    .chip:disabled { cursor: default; opacity: 0.9; }
    .h3row { display: flex; align-items: center; justify-content: space-between; }
    .link { background: none; border: 0; color: ${COL.blueLight}; font-size: 16px; display: flex; align-items: center; gap: 4px; }
    .taglist { display: grid; gap: 8px; }
    .tag { display: flex; align-items: center; background: ${COL.surface}; border-radius: 10px; }
    .tag.on { background: ${tint(COL.blue, 0.35)}; }
    .tagname { flex: 1; text-align: left; background: none; border: 0; color: ${COL.text}; font-size: 16px; font-weight: 600; padding: 14px 16px; display: flex; gap: 8px; align-items: center; }
    .tag .x { background: none; border: 0; color: ${COL.text}; padding: 10px 14px; }
    .newtag { display: flex; gap: 8px; margin-bottom: 10px; }
    .newtag input, .note, .field input, .field select { background: ${COL.surface2}; color: ${COL.text}; border: 1px solid ${COL.line}; border-radius: 10px; padding: 10px 12px; font-size: 15px; }
    .newtag input { flex: 1; }
    .note { width: 100%; min-height: 90px; box-sizing: border-box; resize: vertical; }
    .btn { background: ${COL.blueLight}; color: #13233F; border: 0; border-radius: 12px; padding: 10px 16px; font-weight: 600; }
    .btn.ghost { background: ${COL.surface2}; color: ${COL.text}; }
    /* Calendar */
    .cal-head { display: flex; align-items: center; justify-content: space-between; }
    .icon { background: ${COL.surface}; border: 0; border-radius: 50%; width: 40px; height: 40px; color: ${COL.text}; }
    .cal-grid { display: grid; grid-template-columns: repeat(7, 1fr); gap: 6px; }
    .wd { text-align: center; color: ${COL.muted}; font-size: 12px; padding-bottom: 4px; }
    .cal-cell { position: relative; aspect-ratio: 1; border: 2px solid transparent; border-radius: 12px; background: ${COL.surface}; color: ${COL.text}; }
    .cal-cell.pad { background: none; }
    .cal-cell .n { position: absolute; right: 8px; bottom: 6px; font-weight: 600; }
    .cal-cell .dots { position: absolute; left: 6px; top: 6px; display: flex; gap: 3px; flex-wrap: wrap; }
    .k-period { background: ${COL.red}; color: #fff; } .k-period_predicted { background: rgba(232,71,63,0.18); border-color: rgba(232,71,63,0.6); }
    .k-fertile { background: ${COL.blue}; color: #fff; } .k-fertile_peak, .k-ovulation { background: ${COL.blueDark}; color: #fff; }
    .k-ovulation::after { content: ""; position: absolute; right: 8px; top: 8px; width: 10px; height: 10px; border-radius: 50%; background: ${COL.blueLight}; }
    .cal-cell.is-today { box-shadow: 0 0 0 2px ${COL.text} inset; } .cal-cell.is-sel { border-color: ${COL.blueLight}; }
    .legend, .legend-flow { display: flex; flex-wrap: wrap; gap: 14px; margin: 14px 0; color: ${COL.muted}; font-size: 13px; }
    .legend span, .legend-flow span { display: flex; align-items: center; gap: 6px; }
    .legend i.pred { background: rgba(232,71,63,0.3); border: 1px solid ${COL.red}; }
    /* Analysis */
    .analysis { display: grid; gap: 12px; max-width: 760px; margin: 0 auto; }
    .analysis h2 { margin: 14px 0 0; }
    .stat, .panel { background: transparent; border: 1px solid ${COL.line}; border-radius: 18px; padding: 14px 16px; }
    .stat { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
    .stat-l { display: flex; align-items: center; gap: 14px; } .stat-r { text-align: right; }
    .mini { width: 64px; height: 64px; } .big { font-size: 26px; font-weight: 700; }
    .ok, .warn { display: inline-flex; align-items: center; gap: 6px; font-weight: 500; }
    .ok ha-icon { color: ${COL.green}; } .warn ha-icon, .warn { color: #E8A33D; }
    .legend-flow { margin: 0; justify-content: space-around; }
    .frow { display: grid; grid-template-columns: 70px 1fr; align-items: center; gap: 10px; margin: 8px 0; font-size: 14px; }
    .fbar { display: grid; gap: 2px; } .fbar span { height: 22px; } .fbar em { font-style: normal; color: ${COL.muted}; font-size: 12px; text-align: center; }
    .hrow { display: grid; grid-template-columns: 70px 1fr 44px; align-items: center; gap: 10px; margin: 8px 0; font-size: 14px; }
    .hbar { display: flex; height: 14px; border-radius: 8px; overflow: hidden; background: ${COL.surface}; }
    .hbar .p { background: ${COL.red}; } .hbar .r { background: ${COL.grey}; }
    /* Settings */
    .settings { display: grid; gap: 12px; max-width: 640px; margin: 0 auto; }
    .settings h3 { margin-top: 0; }
    .field { display: grid; grid-template-columns: 1fr 150px 40px; align-items: center; gap: 10px; margin: 8px 0; }
    .field select { grid-column: span 2; }
    .field em { color: ${COL.muted}; font-style: normal; }
    .share { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 8px 0; border-top: 1px solid ${COL.line}; }
    .seg { display: flex; background: ${COL.surface2}; border-radius: 12px; padding: 3px; }
    .seg button { background: none; border: 0; color: ${COL.muted}; padding: 7px 12px; border-radius: 9px; font-size: 14px; }
    .seg button.on { background: ${COL.blueLight}; color: #13233F; font-weight: 600; }
    .preview { background: ${COL.surface}; border-radius: 12px; padding: 10px 14px; margin-top: 10px; }
    .file { color: ${COL.muted}; display: block; margin-top: 8px; }
    /* Track: collapsible categories */
    .track-tools { display: flex; flex-wrap: wrap; gap: 4px 18px; align-items: center; margin: 4px 0 6px; }
    .track-tools .link { font-size: 14px; }
    .cat { border-top: 1px solid ${COL.line}; padding: 2px 0; }
    .cat.open { padding-bottom: 12px; }
    .cat-h { width: 100%; display: flex; align-items: center; gap: 10px; background: none; border: 0; color: ${COL.text}; padding: 12px 0; text-align: left; }
    .cat-dot { width: 10px; height: 10px; border-radius: 50%; flex: 0 0 auto; display: inline-block; }
    .cat-l { font-size: 18px; font-weight: 700; flex: 0 0 auto; }
    .cat-s { flex: 1; min-width: 0; color: ${COL.muted}; font-size: 14px; text-align: right; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .cat-h ha-icon { color: ${COL.muted}; flex: 0 0 auto; }
    .cat.more > .cat-h .cat-l { color: ${COL.muted}; }
    .cat.more .cat { margin-left: 8px; }
    .edit-row { display: flex; align-items: center; gap: 6px; border-top: 1px solid ${COL.line}; padding: 4px 0; }
    .edit-row .check { margin: 4px 0; font-size: 16px; }
    .edit-row .x:disabled { opacity: 0.25; }
    /* Treatment */
    .k-stim { background: rgba(232,163,61,0.75); color: #fff; } .k-tww { background: rgba(126,98,201,0.6); color: #fff; }
    .k-trigger { background: ${TX.trigger}; color: #fff; } .k-collection { background: ${TX.collection}; color: #fff; }
    .k-collection_expected { background: rgba(43,166,160,0.3); border-color: ${TX.collection}; border-style: dashed; }
    .k-transfer { background: ${TX.transfer}; color: #fff; } .k-test { background: ${TX.test}; color: #fff; }
    .dose, .sched { display: flex; align-items: center; gap: 10px; padding: 8px 0; border-top: 1px solid ${COL.line}; }
    .grow { flex: 1; min-width: 0; }
    .form-row { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
    .form-row > * { flex: 1 1 110px; }
    .form-row .btn { flex: 0 0 auto; }
    .form-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; margin: 10px 0; }
    .form-grid label { display: grid; gap: 4px; color: ${COL.muted}; font-size: 13px; }
    .form-grid.end { margin-top: 18px; padding-top: 14px; border-top: 1px solid ${COL.line}; }
    .form-row input, .form-row select, .form-grid input, .form-grid select, .res input {
      background: ${COL.surface2}; color: ${COL.text}; border: 1px solid ${COL.line}; border-radius: 10px; padding: 9px 10px; font-size: 15px; min-width: 0; color-scheme: dark; }
    .results { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 8px 14px; }
    .res { display: grid; grid-template-columns: 1fr 90px 52px; align-items: center; gap: 8px; font-size: 14px; }
    .res em { color: ${COL.muted}; font-style: normal; font-size: 12px; }
    .checks { display: grid; gap: 6px; margin: 4px 0 10px; }
    .check { display: flex; align-items: center; gap: 8px; font-size: 14px; margin: 6px 0; }
    .check input { width: 18px; height: 18px; accent-color: ${COL.blueLight}; }
    h4 { margin: 16px 0 4px; font-size: 15px; }
    .big2 { font-size: 22px; font-weight: 700; margin: 4px 0 2px; }
    .kvs { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 8px; margin: 12px 0; }
    .kv { background: ${COL.surface}; border-radius: 12px; padding: 8px 12px; display: grid; gap: 2px; font-size: 14px; }
    .sum { border-top: 1px solid ${COL.line}; padding: 12px 0; }
    .sum-h { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
    .sum-h .x { margin-left: auto; }
    .sum-line { display: flex; flex-wrap: wrap; gap: 6px 16px; margin: 8px 0; font-size: 14px; }
    .sum table { width: 100%; border-collapse: collapse; font-size: 13px; margin: 6px 0; }
    .sum th { text-align: left; color: ${COL.muted}; font-weight: 500; padding: 4px 6px; }
    .sum td { padding: 5px 6px; border-top: 1px solid ${COL.line}; }
    .sched .seg button { padding: 5px 9px; }
    .x { background: none; border: 0; color: ${COL.text}; padding: 6px; }
    i.sw { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 6px; vertical-align: middle; }
    @media (min-width: 900px) { .cc-main { padding: 22px 28px 0; } .tabs { margin: 0 -28px; } }
    `;
  }
}

if (!customElements.get("clue-cycle-card")) customElements.define("clue-cycle-card", ClueCycleCard);
window.customCards = window.customCards || [];
if (!window.customCards.find((c) => c.type === "clue-cycle-card")) {
  window.customCards.push({ type: "clue-cycle-card", name: "Clue Cycle", description: "Clue-style cycle tracker: ring, daily log, calendar and analysis.", preview: false });
}
console.info(`%c CLUE-CYCLE-CARD %c ${CC_VERSION} `, "background:#E8473F;color:#fff;border-radius:3px 0 0 3px", "background:#2E5089;color:#fff;border-radius:0 3px 3px 0");
