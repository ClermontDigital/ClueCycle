"""Fertility treatment: IVF, frozen embryo transfer, IUI, egg freezing and ovulation induction.

Pure Python like engine.py. A treatment cycle is an explicit record (type, protocol, start date and,
once it's over, an end date and outcome). What happened during it comes from the ordinary day logs:
doses under ``meds``, procedures under the ``treatment`` category, and numbers under ``results``.

While a treatment cycle is running, natural predictions (fertile window, ovulation, next period)
are switched off and the ring follows the treatment instead. Treatment cycles are also left out of
the natural averages, so the predictions afterwards aren't skewed by a medicated cycle.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from .categories import FLOW_LEVELS

MED_KINDS: dict[str, str] = {
    "stim": "Stimulation",
    "antagonist": "Antagonist",
    "agonist": "Down-regulation",
    "trigger": "Trigger",
    "progesterone": "Progesterone",
    "estrogen": "Oestrogen",
    "other": "Other",
}
UNITS = ["IU", "mcg", "mg", "ml", "tablet", "pessary", "applicator", "patch", "pump", "spray"]
MED_COLOR = "#2BA6A0"

# Medicines commonly used in Australian clinics. Anything else can be added as a custom medicine.
DEFAULT_MEDS: list[dict[str, str]] = [
    {"id": "gonal_f", "name": "Gonal-f", "kind": "stim", "unit": "IU"},
    {"id": "puregon", "name": "Puregon", "kind": "stim", "unit": "IU"},
    {"id": "rekovelle", "name": "Rekovelle", "kind": "stim", "unit": "mcg"},
    {"id": "elonva", "name": "Elonva", "kind": "stim", "unit": "mcg"},
    {"id": "menopur", "name": "Menopur", "kind": "stim", "unit": "IU"},
    {"id": "pergoveris", "name": "Pergoveris", "kind": "stim", "unit": "IU"},
    {"id": "clomiphene", "name": "Clomiphene (Clomid)", "kind": "stim", "unit": "mg"},
    {"id": "letrozole", "name": "Letrozole", "kind": "stim", "unit": "mg"},
    {"id": "orgalutran", "name": "Orgalutran", "kind": "antagonist", "unit": "mcg"},
    {"id": "cetrotide", "name": "Cetrotide", "kind": "antagonist", "unit": "mg"},
    {"id": "lucrin", "name": "Lucrin", "kind": "agonist", "unit": "ml"},
    {"id": "synarel", "name": "Synarel", "kind": "agonist", "unit": "spray"},
    {"id": "ovidrel", "name": "Ovidrel", "kind": "trigger", "unit": "mcg"},
    {"id": "pregnyl", "name": "Pregnyl", "kind": "trigger", "unit": "IU"},
    {"id": "decapeptyl", "name": "Decapeptyl", "kind": "trigger", "unit": "mg"},
    {"id": "crinone", "name": "Crinone", "kind": "progesterone", "unit": "applicator"},
    {"id": "utrogestan", "name": "Utrogestan", "kind": "progesterone", "unit": "mg"},
    {"id": "prolutex", "name": "Prolutex", "kind": "progesterone", "unit": "mg"},
    {"id": "progesterone_oil", "name": "Progesterone in oil", "kind": "progesterone", "unit": "ml"},
    {"id": "progynova", "name": "Progynova", "kind": "estrogen", "unit": "mg"},
    {"id": "estradot", "name": "Estradot patch", "kind": "estrogen", "unit": "patch"},
    {"id": "estrogel", "name": "Estrogel", "kind": "estrogen", "unit": "pump"},
    {"id": "aspirin", "name": "Aspirin", "kind": "other", "unit": "mg"},
    {"id": "clexane", "name": "Clexane", "kind": "other", "unit": "mg"},
    {"id": "prednisolone", "name": "Prednisolone", "kind": "other", "unit": "mg"},
    {"id": "doxycycline", "name": "Doxycycline", "kind": "other", "unit": "mg"},
    {"id": "metformin", "name": "Metformin", "kind": "other", "unit": "mg"},
    {"id": "prenatal", "name": "Prenatal vitamin", "kind": "other", "unit": "tablet"},
]

TREATMENT_TYPES: dict[str, str] = {
    "ivf": "IVF / ICSI",
    "fet": "Frozen embryo transfer",
    "iui": "IUI",
    "egg_freezing": "Egg freezing",
    "oi": "Ovulation induction",
}
PROTOCOLS: dict[str, str] = {
    "antagonist": "Antagonist",
    "long_agonist": "Long down-regulation",
    "flare": "Short (flare)",
    "mild": "Mild or natural",
    "medicated_fet": "Medicated FET",
    "natural_fet": "Natural FET",
    "other": "Other",
}
OUTCOMES: dict[str, str] = {
    "positive": "Positive pregnancy test",
    "negative": "Negative test",
    "chemical": "Chemical pregnancy",
    "freeze_all": "Freeze-all, no transfer yet",
    "eggs_frozen": "Eggs frozen",
    "cancelled": "Cycle cancelled",
    "other": "Other",
}
RESULT_FIELDS: list[dict[str, str]] = [
    {"id": "follicles", "label": "Follicles", "unit": "", "kind": "int"},
    {"id": "lining_mm", "label": "Lining", "unit": "mm", "kind": "float"},
    {"id": "estradiol", "label": "Oestradiol (E2)", "unit": "pmol/L", "kind": "float"},
    {"id": "progesterone", "label": "Progesterone", "unit": "nmol/L", "kind": "float"},
    {"id": "lh", "label": "LH", "unit": "IU/L", "kind": "float"},
    {"id": "eggs_collected", "label": "Eggs collected", "unit": "", "kind": "int"},
    {"id": "mature_eggs", "label": "Mature eggs", "unit": "", "kind": "int"},
    {"id": "fertilised", "label": "Fertilised", "unit": "", "kind": "int"},
    {"id": "blastocysts", "label": "Blastocysts", "unit": "", "kind": "int"},
    {"id": "embryos_transferred", "label": "Embryos transferred", "unit": "", "kind": "int"},
    {"id": "embryos_frozen", "label": "Embryos frozen", "unit": "", "kind": "int"},
    {"id": "hcg", "label": "hCG (beta)", "unit": "IU/L", "kind": "float"},
]
RESULT_BY_ID = {f["id"]: f for f in RESULT_FIELDS}

EGG_COLLECTION_AFTER_TRIGGER = 2   # trigger at night, collection about 36 hours later
TEST_AFTER_BLASTOCYST = 9          # blood test days after a day 5/6 transfer; clinics vary, so it's editable
TEST_AFTER_DAY3 = 11
TEST_AFTER_IUI = 14
WINDOW_BEFORE = 7                  # a cycle that starts this close before treatment belongs to it
MAX_RING = 70

TIPS = {
    "preparation": [
        "Log each dose as you take it, or tap Done on the reminder.",
        "Your clinic's instructions always come first. This only keeps track.",
    ],
    "stimulation": [
        "Inject at about the same time each day.",
        "Log your scan and blood test results to see how the follicles are tracking.",
    ],
    "triggered": [
        "Egg collection is usually about 36 hours after the trigger.",
        "Follow your clinic's fasting instructions for the collection.",
    ],
    "awaiting_transfer": [
        "Log the embryo updates from the lab under Results as they come in.",
    ],
    "transfer": [
        "Keep taking your progesterone exactly as prescribed.",
    ],
    "two_week_wait": [
        "Home tests this early can be misleading. The blood test is the one to trust.",
        "Keep taking your support medicines until the clinic says to stop.",
    ],
    "test_day": [
        "Log the hCG result under Results, then end this cycle with its outcome.",
    ],
    "after_test": [
        "End this cycle with its outcome when you're ready. Natural predictions resume after that.",
    ],
}


def catalogue(custom: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    """Built-in medicines plus the tracker's own, by id."""
    meds = {m["id"]: dict(m, custom=False) for m in DEFAULT_MEDS}
    for m in custom or []:
        meds[m["id"]] = dict(m, custom=True)
    return meds


def _d(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def _days(n: int) -> str:
    return f"{n} day" if n == 1 else f"{n} days"


def window(t: dict[str, Any], today: date) -> tuple[date, date]:
    """The dates a treatment cycle covers, for leaving its cycles out of the natural stats."""
    start = _d(t.get("start")) or today
    end = _d(t.get("end")) or max(today, start)
    return start - timedelta(days=WINDOW_BEFORE), end


def active(cycles: list[dict[str, Any]] | None, today: date) -> dict[str, Any] | None:
    """The treatment cycle running today, if any."""
    for t in reversed(cycles or []):
        start, end = _d(t.get("start")), _d(t.get("end"))
        if start and start <= today and (end is None or end >= today):
            return t
    return None


def _scan(t: dict[str, Any], days: dict[str, dict[str, Any]], meds: dict[str, dict[str, Any]],
          today: date) -> dict[str, Any]:
    """Pick out the stimulation days, trigger, collection and transfer from the day logs."""
    start = _d(t.get("start")) or today
    last = _d(t.get("end")) or (start + timedelta(days=MAX_RING))
    stim: list[date] = []
    trigger = collection = transfer = None
    d = start
    while d <= last:
        log = days.get(d.isoformat()) or {}
        chips = log.get("treatment") or []
        kinds = {meds.get(dose.get("med"), {}).get("kind") for dose in log.get("meds") or []}
        if "stim" in kinds:
            stim.append(d)
        if trigger is None and ("trigger" in chips or "trigger" in kinds):
            trigger = d
        if collection is None and "egg_collection" in chips:
            collection = d
        if transfer is None and ({"fresh_transfer", "frozen_transfer", "iui"} & set(chips)):
            transfer = d
        d += timedelta(days=1)
    return {"stim": stim, "trigger": trigger, "collection": collection, "transfer": transfer}


def timeline(t: dict[str, Any], days: dict[str, dict[str, Any]], meds: dict[str, dict[str, Any]],
             today: date) -> dict[str, Any]:
    """Where a treatment cycle is up to, and what the middle of the ring should say."""
    kind = t.get("type", "ivf")
    start = _d(t.get("start")) or today
    end = _d(t.get("end"))
    s = _scan(t, days, meds, today)
    stim, trigger, collection, transfer = s["stim"], s["trigger"], s["collection"], s["transfer"]
    expected_collection = None
    if trigger and not collection and kind in ("ivf", "egg_freezing"):
        expected_collection = trigger + timedelta(days=EGG_COLLECTION_AFTER_TRIGGER)
    test_date = _d(t.get("test_date"))
    if not test_date and transfer:
        if kind == "iui":
            wait = TEST_AFTER_IUI
        else:
            wait = TEST_AFTER_DAY3 if int(t.get("embryo_day") or 5) <= 3 else TEST_AFTER_BLASTOCYST
        test_date = transfer + timedelta(days=wait)
    if not test_date and kind == "oi" and trigger:
        test_date = trigger + timedelta(days=TEST_AFTER_IUI + 2)

    after = "IUI" if kind == "iui" else "transfer"
    day = (today - start).days + 1
    if transfer and today > transfer:
        dpt = (today - transfer).days
        if test_date and today == test_date:
            phase, headline, sub = "test_day", "Test day", "Pregnancy blood test today"
        elif test_date and today > test_date:
            phase, headline, sub = "after_test", f"Tested on {test_date.day} {test_date:%b}", "Log the result and end this cycle"
        else:
            phase = "two_week_wait"
            headline = f"{_days(dpt)} past {after}"
            sub = f"Blood test in {_days((test_date - today).days)}" if test_date else "Waiting for the test date"
    elif transfer and today == transfer:
        phase, headline = "transfer", ("IUI day" if kind == "iui" else "Transfer day")
        sub = f"Blood test {test_date.day} {test_date:%b}" if test_date else "Good luck"
    elif collection and today >= collection:
        n = (today - collection).days
        phase = "awaiting_transfer"
        headline = "Egg collection day" if n == 0 else f"Day {n} after egg collection"
        sub = "Freeze-all or transfer, as your clinic plans" if kind == "ivf" else "Log the lab's updates under Results"
    elif trigger and today >= trigger:
        phase = "triggered"
        nxt = collection or expected_collection
        if nxt and today < nxt:
            word = "booked" if collection else "expected"
            headline, sub = "Trigger done", f"Egg collection {word} {nxt.day} {nxt:%b}"
        elif nxt and today == nxt:
            headline, sub = "Egg collection today", "About 36 hours after the trigger"
        else:
            headline, sub = "Trigger done", "Log the next step when it happens"
    elif stim and today >= stim[0]:
        n = (today - stim[0]).days + 1
        phase, headline = "stimulation", f"Stim day {n}"
        sub = f"{_days(len(stim))} of stimulation logged"
    else:
        phase, headline = "preparation", f"Treatment day {day}"
        sub = TREATMENT_TYPES.get(kind, "Treatment")
    if end and end < today:
        phase, headline, sub = "ended", "Treatment cycle ended", OUTCOMES.get(t.get("outcome") or "", "")

    return {
        "id": t.get("id"),
        "type": kind,
        "type_label": TREATMENT_TYPES.get(kind, kind),
        "protocol": t.get("protocol"),
        "protocol_label": PROTOCOLS.get(t.get("protocol") or "", ""),
        "start": start.isoformat(),
        "end": end.isoformat() if end else None,
        "outcome": t.get("outcome"),
        "note": t.get("note") or "",
        "embryo_day": t.get("embryo_day"),
        "day": day,
        "phase": phase,
        "headline": headline,
        "sub": sub,
        "tips": TIPS.get(phase, []),
        "stim_start": stim[0].isoformat() if stim else None,
        "stim_days": len(stim),
        "trigger": trigger.isoformat() if trigger else None,
        "collection": collection.isoformat() if collection else None,
        "expected_collection": expected_collection.isoformat() if expected_collection else None,
        "transfer": transfer.isoformat() if transfer else None,
        "test_date": test_date.isoformat() if test_date else None,
    }


def day_kinds(tl: dict[str, Any], days: dict[str, dict[str, Any]], meds: dict[str, dict[str, Any]],
              last: date) -> dict[date, str]:
    """The treatment colouring for each day of a treatment cycle (period days are left to the caller)."""
    out: dict[date, str] = {}
    start = date.fromisoformat(tl["start"])
    d = start
    while d <= last:
        log = days.get(d.isoformat()) or {}
        if any(meds.get(x.get("med"), {}).get("kind") == "stim" for x in log.get("meds") or []):
            out[d] = "stim"
        d += timedelta(days=1)
    transfer, test = _d(tl["transfer"]), _d(tl["test_date"])
    if transfer and test:
        d = transfer + timedelta(days=1)
        while d < test:
            out[d] = "tww"
            d += timedelta(days=1)
    for key, kind in (("trigger", "trigger"), ("expected_collection", "collection_expected"),
                      ("collection", "collection"), ("transfer", "transfer"), ("test_date", "test")):
        if tl.get(key):
            out[date.fromisoformat(tl[key])] = kind
    return out


def ring(tl: dict[str, Any], days: dict[str, dict[str, Any]], meds: dict[str, dict[str, Any]],
         today: date, dots) -> list[dict[str, Any]]:
    """One entry per day of the treatment cycle, from its start to a little past the test date."""
    start = date.fromisoformat(tl["start"])
    ends = [start + timedelta(days=27), today + timedelta(days=3)]
    for key in ("test_date", "expected_collection", "transfer"):
        if tl.get(key):
            ends.append(date.fromisoformat(tl[key]) + timedelta(days=2))
    last = min(max(ends), start + timedelta(days=MAX_RING - 1))
    kinds = day_kinds(tl, days, meds, last)
    out = []
    d, i = start, 0
    while d <= last:
        log = days.get(d.isoformat()) or {}
        flow = log.get("period")
        kind = "period" if flow in FLOW_LEVELS else kinds.get(d, "normal")
        out.append({"day": i + 1, "date": d.isoformat(), "kind": kind,
                    "flow": flow if flow in FLOW_LEVELS or flow == "spotting" else None,
                    "dots": dots(log, log.get("tags") or [])})
        d += timedelta(days=1)
        i += 1
    return out


def summary(cycles: list[dict[str, Any]] | None, days: dict[str, dict[str, Any]],
            meds: dict[str, dict[str, Any]], today: date) -> list[dict[str, Any]]:
    """Per treatment cycle: dates, protocol, medicine totals and results, newest first. For the clinic."""
    out = []
    for t in reversed(cycles or []):
        tl = timeline(t, days, meds, today)
        start = date.fromisoformat(tl["start"])
        last = _d(t.get("end")) or today
        totals: dict[tuple[str, str], float] = defaultdict(float)
        dose_days: dict[str, set[str]] = defaultdict(set)
        results: dict[str, Any] = {}
        procedures: list[dict[str, str]] = []
        d = start
        while d <= last:
            log = days.get(d.isoformat()) or {}
            for dose in log.get("meds") or []:
                med = meds.get(dose.get("med"), {"name": dose.get("med", "?")})
                unit = dose.get("unit") or med.get("unit") or ""
                if isinstance(dose.get("dose"), (int, float)):
                    totals[(med["name"], unit)] += dose["dose"]
                dose_days[med["name"]].add(d.isoformat())
            for chip in log.get("treatment") or []:
                procedures.append({"date": d.isoformat(), "id": chip})
            for key, value in (log.get("results") or {}).items():
                results.setdefault(key, []).append({"date": d.isoformat(), "value": value})
            d += timedelta(days=1)
        med_rows = []
        for name in sorted(dose_days):
            units = {u: round(v, 2) for (n, u), v in totals.items() if n == name}
            med_rows.append({"name": name, "days": len(dose_days[name]),
                             "first": min(dose_days[name]), "last": max(dose_days[name]), "totals": units})
        tl.update({"medicines": med_rows, "procedures": procedures, "results": results})
        out.append(tl)
    return out
