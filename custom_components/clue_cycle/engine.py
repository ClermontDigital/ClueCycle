"""Cycle maths: periods, cycles, statistics, predictions and the daily status.

Pure Python with no Home Assistant imports, so it can be tested on its own.

Day logs are ``{"YYYY-MM-DD": {"period": "medium", "mind": ["calm"], ...}}``. Periods are
derived from the logged flow, the way Clue does it: a period is a run of flow days (light or
heavier; spotting does not count) that may skip a day or two, and a new cycle starts on the
first flow day after a gap.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from statistics import mean
from typing import Any

from .categories import CATEGORY_BY_ID, FLOW_LEVELS, TAG_COLOR

PERIOD_GAP_DAYS = 2        # flow days this close together belong to the same period
MIN_CYCLE_DAYS = 10        # a "new" period sooner than this is treated as part of the last one
MAX_TRACKED_CYCLE = 90     # longer "cycles" are almost always months where nothing was logged
STATS_CYCLES = 6           # cycles used for averages and variation, like Clue
TYPICAL_CYCLE = (21, 35)
TYPICAL_PERIOD = (2, 7)
TYPICAL_VARIATION_MAX = 7  # days between the shortest and longest recent cycle
FERTILE_BEFORE = 5         # sperm survive up to ~5 days, so the window opens 5 days early
FERTILE_AFTER = 1
PEAK_BEFORE = 2            # highest chance: the 2 days before ovulation and the day itself
PMS_DAYS = 5


@dataclass
class Settings:
    """Per-tracker settings, used until there are enough logged cycles."""

    cycle_length: int = 28
    period_length: int = 5
    luteal_length: int = 14
    goal: str = "conceive"  # conceive | track

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "Settings":
        data = data or {}
        return cls(
            cycle_length=int(data.get("cycle_length", 28)),
            period_length=int(data.get("period_length", 5)),
            luteal_length=int(data.get("luteal_length", 14)),
            goal=str(data.get("goal", "conceive")),
        )


@dataclass
class Period:
    start: date
    end: date
    flows: dict[date, str] = field(default_factory=dict)

    @property
    def length(self) -> int:
        return (self.end - self.start).days + 1


@dataclass
class Cycle:
    start: date
    period: Period
    length: int | None = None  # None for the current, unfinished cycle

    @property
    def gap(self) -> bool:
        """True when the cycle is really a stretch of untracked months, not a cycle."""
        return bool(self.length and self.length > MAX_TRACKED_CYCLE)

    def as_dict(self) -> dict[str, Any]:
        return {
            "start": self.start.isoformat(),
            "length": self.length,
            "gap": self.gap,
            "period_length": self.period.length,
            "flows": [self.period.flows.get(self.start + timedelta(days=i)) for i in range(self.period.length)],
        }


def _parse(d: str) -> date | None:
    try:
        return date.fromisoformat(d)
    except (TypeError, ValueError):
        return None


def flow_days(days: dict[str, dict[str, Any]]) -> dict[date, str]:
    """Days with real period flow (spotting excluded)."""
    out: dict[date, str] = {}
    for key, log in days.items():
        flow = (log or {}).get("period")
        if flow in FLOW_LEVELS:
            day = _parse(key)
            if day:
                out[day] = flow
    return out


def periods(days: dict[str, dict[str, Any]]) -> list[Period]:
    """Group flow days into periods, oldest first."""
    flows = flow_days(days)
    result: list[Period] = []
    for day in sorted(flows):
        if result:
            last = result[-1]
            gap = (day - last.end).days
            if gap <= PERIOD_GAP_DAYS + 1 or (day - last.start).days < MIN_CYCLE_DAYS:
                last.end = day
                last.flows[day] = flows[day]
                continue
        result.append(Period(start=day, end=day, flows={day: flows[day]}))
    return result


def cycles(days: dict[str, dict[str, Any]]) -> list[Cycle]:
    """Cycles, oldest first. The last one is the current cycle (length None)."""
    ps = periods(days)
    out: list[Cycle] = []
    for i, p in enumerate(ps):
        length = (ps[i + 1].start - p.start).days if i + 1 < len(ps) else None
        out.append(Cycle(start=p.start, period=p, length=length))
    return out


@dataclass
class Stats:
    cycle_length: int
    period_length: int
    variation: int | None
    shortest: int
    longest: int
    cycles_used: int
    typical_cycles: int
    cycle_typical: bool
    period_typical: bool
    variation_typical: bool | None

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def stats(cyc: list[Cycle], settings: Settings) -> Stats:
    """Averages over the last few complete cycles, falling back to the settings."""
    # Tracking gaps would wreck the averages, so they're left out like Clue's excluded cycles.
    complete = [c for c in cyc if c.length and not c.gap][-STATS_CYCLES:]
    lengths = [c.length for c in complete if c.length]
    recent_periods = [c.period.length for c in cyc[-STATS_CYCLES:]]
    cycle_len = round(mean(lengths)) if lengths else settings.cycle_length
    period_len = round(mean(recent_periods)) if recent_periods else settings.period_length
    shortest = min(lengths) if lengths else cycle_len
    longest = max(lengths) if lengths else cycle_len
    variation = (longest - shortest) if len(lengths) >= 2 else None
    typical = sum(1 for n in lengths if TYPICAL_CYCLE[0] <= n <= TYPICAL_CYCLE[1])
    return Stats(
        cycle_length=cycle_len,
        period_length=period_len,
        variation=variation,
        shortest=shortest,
        longest=longest,
        cycles_used=len(lengths),
        typical_cycles=typical,
        cycle_typical=TYPICAL_CYCLE[0] <= cycle_len <= TYPICAL_CYCLE[1],
        period_typical=TYPICAL_PERIOD[0] <= period_len <= TYPICAL_PERIOD[1],
        variation_typical=None if variation is None else variation <= TYPICAL_VARIATION_MAX,
    )


@dataclass
class Prediction:
    cycle_start: date | None
    cycle_day: int | None
    next_period: date | None
    next_period_end: date | None
    days_until_period: int | None
    late_days: int
    ovulation: date | None
    fertile_start: date | None
    fertile_end: date | None
    peak_start: date | None
    phase: str
    ring_length: int

    def as_dict(self) -> dict[str, Any]:
        out = {}
        for key, value in self.__dict__.items():
            out[key] = value.isoformat() if isinstance(value, date) else value
        return out


def predict(days: dict[str, dict[str, Any]], settings: Settings, today: date) -> tuple[Prediction, Stats, list[Cycle]]:
    """Predict the current cycle from the logged history."""
    cyc = cycles(days)
    st = stats(cyc, settings)
    current = [c for c in cyc if c.start <= today]
    if not current:
        empty = Prediction(None, None, None, None, None, 0, None, None, None, None, "unknown", st.cycle_length)
        return empty, st, cyc
    cur = current[-1]
    cycle_day = (today - cur.start).days + 1
    next_period = cur.start + timedelta(days=st.cycle_length)
    late = max(0, (today - next_period).days)  # due today is not late yet
    if late:
        # Clue keeps counting the cycle and says it's late rather than jumping ahead.
        next_period = today + timedelta(days=1)
    next_end = next_period + timedelta(days=st.period_length - 1)
    luteal = settings.luteal_length
    # Ovulation is about one luteal phase before the next period.
    ovulation = cur.start + timedelta(days=st.cycle_length - luteal)
    # Widen the window by how much recent cycles vary: earliest likely ovulation to latest.
    earliest = cur.start + timedelta(days=st.shortest - luteal)
    latest = cur.start + timedelta(days=st.longest - luteal)
    fertile_start = earliest - timedelta(days=FERTILE_BEFORE)
    fertile_end = latest + timedelta(days=FERTILE_AFTER)
    peak_start = ovulation - timedelta(days=PEAK_BEFORE)
    in_period = cur.period.start <= today <= cur.period.end
    if in_period or (cycle_day <= st.period_length and today <= cur.period.end + timedelta(days=1)):
        phase = "period"
    elif late:
        phase = "late"
    elif today == next_period:
        phase = "due"
    elif fertile_start <= today <= fertile_end:
        phase = "ovulation" if today == ovulation else ("fertile_peak" if peak_start <= today <= ovulation else "fertile")
    elif today < fertile_start:
        phase = "follicular"
    elif (next_period - today).days <= PMS_DAYS:
        phase = "pms"
    else:
        phase = "luteal"
    ring_length = max(st.cycle_length, cycle_day)
    pred = Prediction(
        cycle_start=cur.start,
        cycle_day=cycle_day,
        next_period=next_period,
        next_period_end=next_end,
        days_until_period=(next_period - today).days,
        late_days=late,
        ovulation=ovulation,
        fertile_start=fertile_start,
        fertile_end=fertile_end,
        peak_start=peak_start,
        phase=phase,
        ring_length=ring_length,
    )
    return pred, st, cyc


def _days(n: int) -> str:
    return f"{n} day" if n == 1 else f"{n} days"


TIPS = {
    "period": [
        "Log your flow each day. The more you track, the better the predictions get.",
        "Heat, gentle movement and staying hydrated can ease cramps.",
    ],
    "follicular": [
        "Energy often rises after your period as oestrogen climbs.",
        "Your fertile window is coming up. Keep tracking discharge to spot the change.",
    ],
    "fertile": [
        "Having sex every one to two days in the fertile window gives the best chance.",
        "Egg-white discharge often means you're at your most fertile.",
        "An ovulation test can confirm when you ovulate.",
    ],
    "fertile_peak": [
        "These are the days with the highest chance of conceiving.",
        "A positive ovulation test means ovulation is likely in the next 24-36 hours.",
    ],
    "ovulation": [
        "Ovulation is predicted for today. Sex today or tomorrow still counts.",
        "Some people feel a twinge on one side when they ovulate. Log it as ovulation pain.",
    ],
    "luteal": [
        "Progesterone is high in this phase, so you may feel calmer or more tired.",
        "If you're trying to conceive, a pregnancy test is most accurate from the day your period is due.",
    ],
    "pms": [
        "PMS symptoms like bloating, cravings or mood changes are common now.",
        "Logging how you feel shows which symptoms repeat each cycle.",
    ],
    "due": [
        "Your period is predicted to start today.",
        "Log the first day as soon as it starts so the next prediction is accurate.",
    ],
    "late": [
        "Stress, illness, travel or changes in sleep can delay a period.",
        "If there's a chance you could be pregnant, a pregnancy test is accurate now.",
    ],
    "unknown": [
        "Log the first day of your period to start predictions.",
        "Or import your history from Clue to get predictions straight away.",
    ],
}


def status(pred: Prediction, settings: Settings, today: date, days: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """The headline and tips shown in the middle of the ring."""
    ttc = settings.goal == "conceive"
    logged_today = (days.get(today.isoformat()) or {}).get("period") in FLOW_LEVELS
    if pred.phase == "unknown":
        headline, sub = "Track your period", "Log the first day of your period to see predictions"
    elif pred.phase == "period":
        headline = f"Period day {pred.cycle_day}" if logged_today else "Period may still be going"
        sub = f"Next period in {_days(pred.days_until_period or 0)}" if not logged_today else "Log your flow today"
    elif pred.phase == "due":
        headline, sub = "Period expected today", "Log it when it starts"
    elif pred.phase == "late":
        headline = f"Period is {_days(pred.late_days)} late"
        sub = "Log it when it starts"
    elif pred.phase in ("fertile", "fertile_peak", "ovulation"):
        after_ovulation = pred.ovulation and today > pred.ovulation
        if ttc:
            if pred.phase in ("fertile_peak", "ovulation"):
                headline = "Best timing to try to conceive"
            elif after_ovulation:
                headline = "Still good timing to try to conceive"
            else:
                headline = "Good timing to try to conceive"
        else:
            headline = "Fertile window"
        sub = "Ovulation predicted today" if pred.phase == "ovulation" else (
            f"Ovulation predicted in {_days((pred.ovulation - today).days)}"
            if pred.ovulation and pred.ovulation > today else f"Next period in {_days(pred.days_until_period or 0)}"
        )
    elif pred.phase == "follicular":
        n = (pred.fertile_start - today).days if pred.fertile_start else 0
        headline = f"Fertile window starts in {_days(n)}"
        sub = f"Next period in {_days(pred.days_until_period or 0)}"
    elif pred.phase == "pms":
        headline = f"Period in {_days(pred.days_until_period or 0)}"
        sub = "PMS may be on its way"
    else:
        headline = f"Next period in {_days(pred.days_until_period or 0)}"
        sub = "Luteal phase"
    return {"headline": headline, "sub": sub, "tips": TIPS.get(pred.phase, [])}


def day_dots(log: dict[str, Any] | None, tags: list[str]) -> list[str]:
    """Colours of the categories logged on a day, for the dots on the ring."""
    if not log:
        return []
    colors: list[str] = []
    for key, value in log.items():
        # Period days are already coloured red, so they don't get a dot too.
        if key in ("period", "note", "updated_by", "updated_at") or not value:
            continue
        if key == "tags":
            colors.append(TAG_COLOR)
            continue
        cat = CATEGORY_BY_ID.get(key)
        if cat:
            colors.append(cat["color"])
    return colors[:6]


def ring(pred: Prediction, days: dict[str, dict[str, Any]], st: Stats) -> list[dict[str, Any]]:
    """One entry per day of the current cycle for the ring."""
    if not pred.cycle_start:
        return []
    out = []
    for i in range(pred.ring_length):
        day = pred.cycle_start + timedelta(days=i)
        log = days.get(day.isoformat()) or {}
        flow = log.get("period")
        if flow in FLOW_LEVELS:
            kind = "period"
        elif i < st.period_length and flow is None and pred.cycle_day and i >= pred.cycle_day:
            kind = "period_predicted"
        elif pred.ovulation and day == pred.ovulation:
            kind = "ovulation"
        elif pred.peak_start and pred.peak_start <= day <= (pred.ovulation or day):
            kind = "fertile_peak"
        elif pred.fertile_start and pred.fertile_start <= day <= (pred.fertile_end or day):
            kind = "fertile"
        else:
            kind = "normal"
        out.append({
            "day": i + 1,
            "date": day.isoformat(),
            "kind": kind,
            "flow": flow if flow in FLOW_LEVELS or flow == "spotting" else None,
            "dots": day_dots(log, log.get("tags") or []),
        })
    return out


def overview(days: dict[str, dict[str, Any]], settings: Settings, today: date) -> dict[str, Any]:
    """Everything the Today view needs in one payload."""
    pred, st, cyc = predict(days, settings, today)
    return {
        "today": today.isoformat(),
        "prediction": pred.as_dict(),
        "stats": st.as_dict(),
        "status": status(pred, settings, today, days),
        "ring": ring(pred, days, st),
        "cycles": [c.as_dict() for c in cyc[-12:]],
    }


def upcoming(days: dict[str, dict[str, Any]], settings: Settings, today: date, count: int = 3) -> list[dict[str, Any]]:
    """Predicted periods, fertile windows and ovulation days for the next few cycles."""
    pred, st, _ = predict(days, settings, today)
    if not pred.next_period:
        return []
    events = []
    start = pred.next_period
    for i in range(count):
        cycle_start = start + timedelta(days=st.cycle_length * i)
        ov = cycle_start + timedelta(days=st.cycle_length - settings.luteal_length)
        events.append({"kind": "period", "start": cycle_start.isoformat(),
                       "end": (cycle_start + timedelta(days=st.period_length - 1)).isoformat()})
        events.append({"kind": "fertile",
                       "start": (cycle_start + timedelta(days=st.shortest - settings.luteal_length - FERTILE_BEFORE)).isoformat(),
                       "end": (cycle_start + timedelta(days=st.longest - settings.luteal_length + FERTILE_AFTER)).isoformat()})
        events.append({"kind": "ovulation", "start": ov.isoformat(), "end": ov.isoformat()})
    # The current cycle's own fertile window and ovulation, if they're still ahead.
    if pred.fertile_end and pred.fertile_end >= today:
        events.insert(0, {"kind": "fertile", "start": pred.fertile_start.isoformat(), "end": pred.fertile_end.isoformat()})
    if pred.ovulation and pred.ovulation >= today:
        events.insert(0, {"kind": "ovulation", "start": pred.ovulation.isoformat(), "end": pred.ovulation.isoformat()})
    return events


def calendar(days: dict[str, dict[str, Any]], settings: Settings, today: date,
             start: date, end: date) -> dict[str, dict[str, Any]]:
    """Kind and dots for every day in a range, for the day strip and the month view.

    Past cycles get an estimated fertile window (ovulation one luteal phase before the next
    period); the current and future cycles use the predictions.
    """
    pred, st, cyc = predict(days, settings, today)
    luteal = settings.luteal_length
    kinds: dict[date, str] = {}

    def mark(first: date, last: date, kind: str, overwrite: bool = False) -> None:
        d = first
        while d <= last:
            if overwrite or d not in kinds:
                kinds[d] = kind
            d += timedelta(days=1)

    # Logged periods always win.
    for day, _flow in flow_days(days).items():
        kinds[day] = "period"
    # Past cycles: estimated ovulation and fertile window from the next cycle's start.
    for c in cyc:
        if c.length:
            nxt = c.start + timedelta(days=c.length)
            ov = nxt - timedelta(days=luteal)
            mark(ov - timedelta(days=FERTILE_BEFORE), ov + timedelta(days=FERTILE_AFTER), "fertile")
            mark(ov - timedelta(days=PEAK_BEFORE), ov - timedelta(days=1), "fertile_peak", overwrite=True)
            if ov not in kinds or kinds[ov] != "period":
                kinds[ov] = "ovulation"
    # Current cycle and the next few: predictions.
    if pred.cycle_start:
        if pred.fertile_start and pred.fertile_end:
            mark(pred.fertile_start, pred.fertile_end, "fertile")
        if pred.peak_start and pred.ovulation:
            mark(pred.peak_start, pred.ovulation - timedelta(days=1), "fertile_peak", overwrite=True)
            kinds[pred.ovulation] = "ovulation"
        for ev in upcoming(days, settings, today, count=6):
            first, last = date.fromisoformat(ev["start"]), date.fromisoformat(ev["end"])
            if ev["kind"] == "period":
                mark(first, last, "period_predicted")
            elif ev["kind"] == "fertile":
                mark(first, last, "fertile")
            else:
                kinds[first] = "ovulation"
    for day, flow in flow_days(days).items():
        kinds[day] = "period"

    out: dict[str, dict[str, Any]] = {}
    d = start
    while d <= end:
        log = days.get(d.isoformat()) or {}
        kind = kinds.get(d, "normal")
        if kind in ("period_predicted",) and d <= today:
            kind = "normal"  # a prediction that didn't come true isn't shown in the past
        out[d.isoformat()] = {
            "kind": kind,
            "flow": log.get("period"),
            "dots": day_dots(log, log.get("tags") or []),
            "logged": bool({k for k in log if k not in ("updated_by", "updated_at")}),
        }
        d += timedelta(days=1)
    return out
