"""Import a data export from the Clue app.

Clue has shipped two export shapes over the years, both JSON:

* the older ``.cluedata`` backup, one record per day::

    {"data": [{"day": "2024-03-06T00:00:00Z", "period": "heavy", "pain": ["cramps"],
               "tags": ["back pain"], "notes": "..."}]}

* the newer list of measurements, one record per value::

    [{"date": "2024-03-06", "type": "period", "value": {"option": "heavy"}}, ...]

Both are mapped onto this integration's categories. Anything unrecognised is counted and
reported back, not silently dropped, so the mapping can be extended from real exports.
"""
from __future__ import annotations

import io
import json
import re
import zipfile
from collections import Counter
from datetime import date
from typing import Any

from .categories import FLOW_LEVELS, SPOTTING, option_ids

# Clue category names (normalised) -> our category id
CATEGORY_ALIASES = {
    "period": "period", "bleeding": "period", "menstruation": "period",
    "spotting": "period",
    "collection_method": "collection", "collection": "collection", "period_products": "collection",
    "feelings": "feelings", "emotions": "feelings", "mood": "feelings", "emotion": "feelings",
    "pain": "pain",
    "energy": "energy",
    "sleep": "sleep",
    "mind": "mind", "mental": "mind",
    "social": "social", "social_life": "social",
    "cravings": "cravings", "craving": "cravings",
    "digestion": "digestion",
    "poop": "poop", "stool": "poop",
    "discharge": "discharge", "fluid": "discharge", "cervical_fluid": "discharge", "cervical_mucus": "discharge",
    "sex": "sex", "sex_life": "sex", "sex_drive": "sex", "sexual_activity": "sex",
    "tests": "tests", "test": "tests", "ovulation_test": "tests", "pregnancy_test": "tests",
    "skin": "skin",
    "hair": "hair",
    "exercise": "exercise", "activity": "exercise",
    "ailment": "ailments", "ailments": "ailments",
    "medication": "medication", "meds": "medication", "pills": "medication",
}

# Clue option names (normalised) -> our option id, per category, where they differ
OPTION_ALIASES = {
    "period": {"very_heavy": "super_heavy", "superheavy": "super_heavy", "extra_heavy": "super_heavy"},
    "collection": {"menstrual_cup": "cup", "pantyliner": "panty_liner", "liner": "panty_liner",
                   "period_pants": "period_underwear", "underwear": "period_underwear"},
    "feelings": {"premenstrual_syndrome": "pms"},
    "pain": {"ovulation": "ovulation_pain", "tender_breast": "tender_breasts", "breasts": "tender_breasts"},
    "energy": {"energised": "energized"},
    "sleep": {"0_3_hrs": "0_3", "3_6_hrs": "3_6", "6_9_hrs": "6_9", "9_hrs": "9_plus", "more_than_9": "9_plus",
              "9": "9_plus", ">9": "9_plus"},
    "mind": {"brainfog": "brain_fog"},
    "poop": {"diarrhoea": "diarrhea"},
    "discharge": {"eggwhite": "egg_white", "egg_white_like": "egg_white"},
    "sex": {"protected_sex": "protected", "unprotected_sex": "unprotected", "withdrawal_sex": "withdrawal",
            "high_sex_drive": "high_drive", "low_sex_drive": "low_drive"},
    "tests": {"ovulation_test_pos": "ovulation_positive", "ovulation_test_neg": "ovulation_negative",
              "pregnancy_test_pos": "pregnancy_positive", "pregnancy_test_neg": "pregnancy_negative",
              "positive": "ovulation_positive", "negative": "ovulation_negative"},
}


class ImportError_(ValueError):
    """The file isn't a Clue export this importer understands."""


def _norm(value: Any) -> str:
    text = str(value).strip().lower()
    text = re.sub(r"[\s\-/]+", "_", text)
    return re.sub(r"[^a-z0-9_>]", "", text)


def _day(value: Any) -> str | None:
    if not value:
        return None
    text = str(value)[:10]
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return None


def _options(value: Any) -> list[str]:
    """Flatten whatever Clue stored for a category into a list of option names."""
    if value is None or value is False:
        return []
    if value is True:
        return ["yes"]
    if isinstance(value, (str, int, float)):
        return [str(value)]
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            out.extend(_options(item))
        return out
    if isinstance(value, dict):
        for key in ("option", "value", "options", "selected", "name"):
            if key in value:
                return _options(value[key])
        return [k for k, v in value.items() if v is True]
    return []


def _decode(raw: bytes | str) -> Any:
    """Accept raw JSON, or a zip containing the JSON (Clue's newer exports are zipped)."""
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    if raw[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            names = [n for n in zf.namelist() if n.lower().endswith((".json", ".cluedata"))]
            if not names:
                raise ImportError_("the zip has no JSON file in it")
            # Prefer the measurements file when there are several.
            names.sort(key=lambda n: ("measure" not in n.lower(), n))
            raw = zf.read(names[0])
    try:
        return json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as err:
        raise ImportError_(f"not valid JSON: {err}") from err


class _Collector:
    def __init__(self) -> None:
        self.days: dict[str, dict[str, Any]] = {}
        self.tags: list[str] = []
        self.unknown: Counter[str] = Counter()

    def tag(self, day: str, name: str) -> None:
        name = str(name).strip()[:40]
        if not name:
            return
        if name.lower() not in {t.lower() for t in self.tags}:
            self.tags.append(name)
        canonical = next(t for t in self.tags if t.lower() == name.lower())
        log = self.days.setdefault(day, {})
        log.setdefault("tags", [])
        if canonical not in log["tags"]:
            log["tags"].append(canonical)

    def add(self, day: str, clue_category: str, value: Any) -> None:
        cat_key = _norm(clue_category)
        if cat_key in ("tags", "tag", "custom_tags"):
            for name in _options(value):
                self.tag(day, name)
            return
        if cat_key in ("notes", "note"):
            text = " ".join(str(v) for v in _options(value)).strip()
            if text:
                log = self.days.setdefault(day, {})
                log["note"] = (log.get("note", "") + "\n" + text).strip()[:2000]
            return
        cat = CATEGORY_ALIASES.get(cat_key)
        if not cat:
            self.unknown[cat_key] += 1
            return
        aliases = OPTION_ALIASES.get(cat, {})
        for raw in _options(value):
            opt = aliases.get(_norm(raw), _norm(raw))
            if cat == "period":
                if cat_key == "spotting" or opt in ("spotting", "light_spotting", "heavy_spotting"):
                    opt = SPOTTING
                if opt not in FLOW_LEVELS and opt != SPOTTING:
                    self.unknown[f"period:{opt}"] += 1
                    continue
                log = self.days.setdefault(day, {})
                # Real flow beats spotting on the same day.
                if log.get("period") in FLOW_LEVELS and opt == SPOTTING:
                    continue
                log["period"] = opt
                continue
            if opt not in option_ids(cat):
                self.unknown[f"{cat}:{opt}"] += 1
                continue
            if cat == "sleep":
                self.days.setdefault(day, {})["sleep"] = opt
                continue
            log = self.days.setdefault(day, {})
            values = log.setdefault(cat, [])
            if opt not in values:
                values.append(opt)


def parse_clue_export(raw: bytes | str) -> dict[str, Any]:
    """Return {"days", "tags", "unknown", "range"} from a Clue export file."""
    data = _decode(raw)
    col = _Collector()
    records: list[Any]
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        records = data["data"]
    elif isinstance(data, dict) and isinstance(data.get("measurements"), list):
        records = data["measurements"]
    elif isinstance(data, list):
        records = data
    else:
        raise ImportError_("unrecognised Clue export layout")

    for rec in records:
        if not isinstance(rec, dict):
            continue
        day = _day(rec.get("date") or rec.get("day") or rec.get("timestamp"))
        if not day:
            continue
        if "type" in rec:  # measurement shape
            col.add(day, rec["type"], rec.get("value"))
            continue
        for key, value in rec.items():  # one-record-per-day shape
            if key in ("day", "date", "timestamp", "id"):
                continue
            col.add(day, key, value)

    if not col.days:
        raise ImportError_("no days found in the file")
    days_sorted = sorted(col.days)
    return {
        "days": col.days,
        "tags": col.tags,
        "unknown": dict(col.unknown.most_common(40)),
        "range": [days_sorted[0], days_sorted[-1]],
    }
