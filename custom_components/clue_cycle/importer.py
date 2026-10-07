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
    "pms": "feelings",
    "pain": "pain",
    "energy": "energy",
    "sleep": "sleep", "sleep_duration": "sleep",
    "sleep_quality": "sleep_quality",
    "mind": "mind", "mental": "mind",
    "social": "social", "social_life": "social",
    "cravings": "cravings", "craving": "cravings",
    "digestion": "digestion",
    "poop": "poop", "stool": "poop",
    "discharge": "discharge", "fluid": "discharge", "cervical_fluid": "discharge", "cervical_mucus": "discharge",
    "sex": "sex", "sex_life": "sex", "sex_drive": "sex", "sexual_activity": "sex",
    "tests": "tests", "test": "tests", "ovulation_test": "tests", "pregnancy_test": "tests",
    "birth_control": "birth_control", "birth_control_pill": "birth_control", "pill": "birth_control",
    "birth_control_shot": "birth_control",
    "skin": "skin",
    "hair": "hair",
    "exercise": "exercise", "activity": "exercise",
    "party": "party", "partying": "party",
    "leisure": "leisure",
    "ailment": "ailments", "ailments": "ailments",
    "medication": "medication", "meds": "medication",
    "appointments": "appointments", "appointment": "appointments",
}

# Synced from a wearable or not tracked here; reported as skipped rather than unrecognised.
NOT_TRACKED = {"resting_heart_rate", "heart_rate_variability", "weight", "temperature", "bbt", "steps"}

# Other spellings (older Clue exports, the old .cluedata format, earlier versions of this
# integration) -> our option id, per category
OPTION_ALIASES = {
    "period": {"very_heavy": "super_heavy", "superheavy": "super_heavy", "extra_heavy": "super_heavy"},
    "collection": {"menstrual_cup": "cup", "pantyliner": "panty_liner", "liner": "panty_liner",
                   "period_pants": "period_underwear", "underwear": "period_underwear"},
    "feelings": {"premenstrual_syndrome": "pms", "yes": "pms", "mood_swing": "mood_swings"},
    "pain": {"cramps": "period_cramps", "ovulation_pain": "ovulation", "tender_breasts": "breast_tenderness",
             "tender_breast": "breast_tenderness", "breasts": "breast_tenderness", "back_pain": "lower_back",
             "back": "lower_back", "joint_pain": "joint"},
    "energy": {"energised": "fully_energized", "energized": "fully_energized", "high": "energetic",
               "high_energy": "energetic", "low": "tired", "low_energy": "tired"},
    "sleep": {"0_3_hrs": "0_3", "3_6_hrs": "3_6", "6_9_hrs": "6_9", "9_hrs": "9_plus", "more_than_9": "9_plus",
              "9": "9_plus", ">9": "9_plus"},
    "mind": {"brainfog": "brain_fog"},
    "digestion": {"great": "ok", "great_digestion": "ok", "nauseated": "nauseous"},
    "poop": {"great": "ok", "normal": "ok", "constipated": "constipation", "diarrhoea": "diarrhea"},
    "discharge": {"eggwhite": "egg_white", "egg_white_like": "egg_white"},
    "sex": {"protected_sex": "protected", "unprotected_sex": "unprotected", "withdrawal_sex": "withdrawal",
            "high_drive": "high_sex_drive", "low_drive": "low_sex_drive", "toys": "sex_toys"},
    "tests": {"ovulation_test_pos": "ovulation_positive", "ovulation_test_neg": "ovulation_negative",
              "pregnancy_test_pos": "pregnancy_positive", "pregnancy_test_neg": "pregnancy_negative",
              "positive": "ovulation_positive", "negative": "ovulation_negative"},
    "birth_control": {"taken": "pill_taken", "late": "pill_late", "missed": "pill_missed",
                      "double_dose": "pill_double", "double": "pill_double", "administered": "shot",
                      "injected": "shot"},
    "hair": {"good": "good_hair", "bad": "bad_hair", "oily": "oily_scalp"},
    "party": {"drinks": "alcohol", "drinking": "alcohol", "big_night_out": "big_night", "smoking": "cigarettes"},
    "leisure": {"holiday": "vacation"},
    "medication": {"painkiller": "painkillers", "antibiotic": "antibiotics", "cold_flu_meds": "cold_or_flu_meds",
                   "cold_flu": "cold_or_flu_meds"},
}


def _sleep_bin(value: Any) -> str | None:
    """Clue now logs sleep as a duration; bucket it into Clue's 0-3 / 3-6 / 6-9 / 9+ hours."""
    if not isinstance(value, dict):
        return None
    if isinstance(value.get("minutes"), (int, float)):
        hours = value["minutes"] / 60
    elif isinstance(value.get("hours"), (int, float)):
        hours = value["hours"]
    else:
        return None
    return "0_3" if hours < 3 else "3_6" if hours < 6 else "6_9" if hours < 9 else "9_plus"


class ImportError_(ValueError):
    """The file isn't a Clue export this importer understands."""


class PasswordRequired(ImportError_):
    """The zip is encrypted (Clue's data download is) and needs the password from Clue's email."""


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


def _decode(raw: bytes | str, password: str | None = None) -> Any:
    """Accept raw JSON, or a zip containing the JSON (Clue's data download is a zip, password protected)."""
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    if raw[:2] == b"PK":
        try:
            zf = zipfile.ZipFile(io.BytesIO(raw))
        except zipfile.BadZipFile as err:
            raise ImportError_("the zip file is damaged") from err
        with zf:
            names = [n for n in zf.namelist() if n.lower().endswith((".json", ".cluedata"))]
            if not names:
                raise ImportError_("the zip has no JSON file in it")
            # Prefer the measurements file when there are several.
            names.sort(key=lambda n: ("measure" not in n.lower(), n))
            info = zf.getinfo(names[0])
            if info.flag_bits & 0x1 and not password:
                raise PasswordRequired("this zip is password protected; enter the password from Clue's email")
            try:
                raw = zf.read(info, pwd=password.encode("utf-8") if password else None)
            except RuntimeError as err:  # zipfile's "Bad password for file"
                raise PasswordRequired("that password didn't open the zip") from err
            except NotImplementedError as err:  # AES-encrypted zips
                raise ImportError_("this zip's encryption can't be opened here; unzip it and pick measurements.json") from err
    try:
        return json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as err:
        raise ImportError_(f"not valid JSON: {err}") from err


class _Collector:
    def __init__(self) -> None:
        self.days: dict[str, dict[str, Any]] = {}
        self.tags: list[str] = []
        self.unknown: Counter[str] = Counter()
        self.skipped: Counter[str] = Counter()

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
        if cat_key in NOT_TRACKED:
            self.skipped[cat_key] += 1
            return
        cat = CATEGORY_ALIASES.get(cat_key)
        if not cat:
            self.unknown[cat_key] += 1
            return
        if cat == "sleep" and (bucket := _sleep_bin(value)):
            self.days.setdefault(day, {})["sleep"] = bucket
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


def parse_clue_export(raw: bytes | str, password: str | None = None) -> dict[str, Any]:
    """Return {"days", "tags", "unknown", "skipped", "range"} from a Clue export file."""
    data = _decode(raw, password)
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
        "skipped": dict(col.skipped),
        "range": [days_sorted[0], days_sorted[-1]],
    }
