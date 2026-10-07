/* Clue Cycle card - a Clue-style cycle tracker for Home Assistant.
 * Unofficial; not affiliated with Clue or BioWink GmbH.
 * Buildless: plain JS custom element, served by the clue_cycle integration.
 */
const CC_VERSION = "0.1.1";

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
    this._view = this._config.view || "today";
  }

  static getStubConfig() { return {}; }
  getCardSize() { return 14; }
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
    this._root.innerHTML = `<style>${this._css()}</style><div class="cc"><div class="cc-main">Loading…</div></div>`;
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
    this._render();
  }

  get _canEdit() { return this._tracker && (this._tracker.role === "owner" || this._tracker.role === "edit"); }

  /* ---------- rendering ---------- */

  _render() {
    const views = [["today", "Today", "mdi:circle-double"], ["log", "Log", "mdi:plus-circle-outline"],
      ["calendar", "Calendar", "mdi:calendar-month-outline"], ["analysis", "Analysis", "mdi:chart-box-outline"],
      ["settings", "Settings", "mdi:cog-outline"]];
    const picker = this._trackers.length > 1
      ? `<select class="tracker" data-change="tracker">${this._trackers.map((t) => `<option value="${t.entry_id}" ${t.entry_id === this._entryId ? "selected" : ""}>${esc(t.name)}</option>`).join("")}</select>`
      : `<div class="tracker-name">${esc(this._tracker.name)}</div>`;
    const role = this._tracker.role === "view" ? `<span class="badge">View only</span>` : this._tracker.role === "edit" ? `<span class="badge">Shared with you</span>` : "";
    const body = { today: () => this._today_(), log: () => this._log(), calendar: () => this._calendarView(),
      analysis: () => this._analysisView(), settings: () => this._settings() }[this._view]();
    this._main.innerHTML = `
      <div class="top">${picker}${role}</div>
      <div class="body">${body}</div>
      <nav class="tabs">${views.map(([id, label, icon]) => `<button class="tab ${this._view === id ? "on" : ""}" data-action="view" data-view="${id}"><ha-icon icon="${icon}"></ha-icon><span>${label}</span></button>`).join("")}</nav>`;
    if (this._view === "log") {
      const sel = this._main.querySelector(".strip .day.sel");
      if (sel) sel.scrollIntoView({ block: "nearest", inline: "center" });
    }
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
      const k = d.kind === "ovulation" ? "fertile_peak" : d.kind;
      if (runs.length && runs[runs.length - 1].k === k) runs[runs.length - 1].end = i;
      else runs.push({ k, start: i, end: i });
    });
    const order = ["fertile", "fertile_peak", "period_predicted", "period"];
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
    // Ovulation marker.
    const ovi = ring.findIndex((d) => d.kind === "ovulation");
    if (ovi >= 0) {
      const [x, y] = polar(cx, cy, R, ang(ovi) + per / 2);
      svg += `<circle cx="${x}" cy="${y}" r="11" fill="${COL.blueLight}"/><circle cx="${x}" cy="${y}" r="3.6" fill="${COL.blueDark}"/>`;
    }
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
      const bg = c.kind === "period" ? COL.red : c.kind === "period_predicted" ? "rgba(232,71,63,0.22)"
        : c.kind === "fertile" ? COL.blue : (c.kind === "fertile_peak" || c.kind === "ovulation") ? COL.blueDark : COL.surface2;
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
    const sections = this._cats.map((cat) => {
      const value = log[cat.id];
      const isOn = (opt) => (Array.isArray(value) ? value.includes(opt) : value === opt);
      return `<section><h3>${esc(cat.label)}</h3><div class="chips">${cat.options.map((o) => this._chip(cat, o, isOn(o.id))).join("")}</div></section>`;
    }).join("");
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
        <span><i style="background:${COL.blue}"></i>Fertile window</span><span><i style="background:${COL.blueDark}"></i>Peak / ovulation</span></div></div>`;
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
    const maxLen = Math.max(35, ...done.map((c) => c.length));
    const history = done.slice(-12).reverse().map((c) => `<div class="hrow"><span>${fmtDay(c.start)}</span>
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
      <div class="panel history">${history || `<p class="muted">No complete cycles yet.</p>`}</div>
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
    } else {
      html += `<section class="panel"><h3>Sharing</h3><p class="muted small">${t.role === "edit" ? "You can view and log for this tracker." : "You can view this tracker."} Only its owner can change who has access.</p></section>`;
    }
    if (this._canEdit) {
      const imp = this._import;
      html += `<section class="panel"><h3>Import from Clue</h3>
        <p class="muted small">In the Clue app, export your data (Settings → Data export), then pick the file here. You'll see a preview before anything is saved.</p>
        <input type="file" class="file" data-change="importfile" accept=".json,.cluedata,.zip,application/json,application/zip">
        ${imp && imp.error ? `<p class="warn">${esc(imp.error)}</p>` : ""}
        ${imp && imp.preview ? `<div class="preview"><p><b>${imp.preview.days}</b> days from <b>${fmtDay(imp.preview.range[0])} ${parse(imp.preview.range[0]).getFullYear()}</b> to <b>${fmtDay(imp.preview.range[1])} ${parse(imp.preview.range[1]).getFullYear()}</b>, ${plural(imp.preview.tags, "tag")}.</p>
          ${Object.keys(imp.preview.unknown || {}).length ? `<p class="muted small">Not recognised (skipped): ${Object.entries(imp.preview.unknown).map(([k, v]) => `${esc(k)} ×${v}`).join(", ")}</p>` : ""}
          <button class="btn" data-action="import">Import ${imp.preview.days} days</button></div>` : ""}
        ${imp && imp.done ? `<p class="ok"><ha-icon icon="mdi:check-circle"></ha-icon>Imported ${imp.done.days} days (${imp.done.new_days} new).</p>` : ""}
      </section>`;
    }
    html += `<p class="muted small tc">Clue Cycle ${CC_VERSION} · unofficial, not affiliated with Clue. Not medical advice and not a method of contraception.</p></div>`;
    return html;
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
    } else if (a === "import") {
      try {
        const done = await this._ws({ type: "clue_cycle/import", entry_id: this._entryId, content: this._import.content, filename: this._import.name });
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
    } else if (kind === "importfile" && el.files && el.files[0]) {
      const file = el.files[0];
      const content = await new Promise((res, rej) => {
        const r = new FileReader();
        r.onload = () => res(String(r.result).split(",")[1] || "");
        r.onerror = () => rej(r.error);
        r.readAsDataURL(file);
      });
      try {
        const preview = await this._ws({ type: "clue_cycle/import", entry_id: this._entryId, content, filename: file.name, dry_run: true });
        this._import = { preview, content, name: file.name };
      } catch (err) { this._import = { error: err.message }; }
      this._render();
    }
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
    .field { display: grid; grid-template-columns: 1fr 120px 40px; align-items: center; gap: 10px; margin: 8px 0; }
    .field select { grid-column: span 2; }
    .field em { color: ${COL.muted}; font-style: normal; }
    .share { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 8px 0; border-top: 1px solid ${COL.line}; }
    .seg { display: flex; background: ${COL.surface2}; border-radius: 12px; padding: 3px; }
    .seg button { background: none; border: 0; color: ${COL.muted}; padding: 7px 12px; border-radius: 9px; font-size: 14px; }
    .seg button.on { background: ${COL.blueLight}; color: #13233F; font-weight: 600; }
    .preview { background: ${COL.surface}; border-radius: 12px; padding: 10px 14px; margin-top: 10px; }
    .file { color: ${COL.muted}; display: block; margin-top: 8px; }
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
