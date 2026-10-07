"""Per-tracker storage: the day logs and custom tags, kept in HA's .storage."""
from __future__ import annotations

import asyncio
import re
import secrets
from datetime import date, datetime, timezone
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from . import treatment as tx
from .categories import CATEGORY_BY_ID, FLOW_LEVELS, SPOTTING, is_single, option_ids

STORAGE_VERSION = 1
META_KEYS = ("updated_by", "updated_at")
MAX_TAGS = 100
MAX_NOTE = 2000
MAX_DOSES_PER_DAY = 30
MAX_CUSTOM_MEDS = 60
MAX_SCHEDULES = 30
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class InvalidLog(ValueError):
    """Raised when a day update contains something the tracker can't store."""


class CycleStore:
    """Read-change-write is serialised so two people logging at once can't drop an edit."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store = Store(hass, STORAGE_VERSION, f"clue_cycle.{entry_id}", private=True)
        self._lock = asyncio.Lock()
        self.days: dict[str, dict[str, Any]] = {}
        self.tags: list[str] = []
        self.treatments: list[dict[str, Any]] = []   # fertility treatment cycles, oldest first
        self.meds: list[dict[str, Any]] = []         # the tracker's own medicines, on top of the built-in ones
        self.schedules: list[dict[str, Any]] = []    # dose reminders
        self.notified: dict[str, Any] = {}           # the last phase a notification went out for

    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        self.days = data.get("days") or {}
        self.tags = data.get("tags") or []
        self.treatments = data.get("treatments") or []
        self.meds = data.get("meds") or []
        self.schedules = data.get("schedules") or []
        self.notified = data.get("notified") or {}

    async def _save(self) -> None:
        await self._store.async_save({"days": self.days, "tags": self.tags, "treatments": self.treatments,
                                      "meds": self.meds, "schedules": self.schedules, "notified": self.notified})

    async def async_set_notified(self, phase: str | None, day: str) -> None:
        async with self._lock:
            self.notified = {"phase": phase, "date": day}
            await self._save()

    def catalogue(self) -> dict[str, dict[str, Any]]:
        return tx.catalogue(self.meds)

    def tx(self) -> dict[str, Any]:
        """What the engine needs to know about treatment."""
        return {"cycles": self.treatments, "meds": self.catalogue()}

    def _clean_dose(self, dose: Any) -> dict[str, Any]:
        if not isinstance(dose, dict):
            raise InvalidLog("a dose must be an object")
        med = dose.get("med")
        cat = self.catalogue()
        if med not in cat:
            raise InvalidLog(f"unknown medicine: {med}")
        amount = dose.get("dose")
        if amount in ("", None):
            amount = None
        elif not isinstance(amount, (int, float)) or isinstance(amount, bool) or not 0 <= amount <= 100000:
            raise InvalidLog("dose must be a number")
        unit = str(dose.get("unit") or cat[med].get("unit") or "")[:12]
        time = dose.get("time") or None
        if time is not None and not TIME_RE.match(str(time)):
            raise InvalidLog("time must be HH:MM")
        return {"id": str(dose.get("id") or secrets.token_hex(4))[:16], "med": med, "dose": amount,
                "unit": unit, "time": time}

    @staticmethod
    def _clean_results(value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise InvalidLog("results must be an object")
        out = {}
        for key, raw in value.items():
            field = tx.RESULT_BY_ID.get(key)
            if not field:
                raise InvalidLog(f"unknown result: {key}")
            if raw in (None, ""):
                continue
            if not isinstance(raw, (int, float)) or isinstance(raw, bool) or not 0 <= raw <= 1_000_000:
                raise InvalidLog(f"{field['label']} must be a number")
            out[key] = int(raw) if field["kind"] == "int" else round(float(raw), 2)
        return out

    def _clean(self, key: str, value: Any) -> Any:
        """Validate one category value, returning what gets stored (None clears it)."""
        if value in (None, "", []):
            return None
        if key == "note":
            if not isinstance(value, str):
                raise InvalidLog("note must be text")
            return value.strip()[:MAX_NOTE] or None
        if key == "tags":
            if not isinstance(value, list) or not all(isinstance(t, str) for t in value):
                raise InvalidLog("tags must be a list of names")
            known = {t.lower(): t for t in self.tags}
            cleaned = []
            for tag in value:
                name = known.get(tag.strip().lower())
                if not name:
                    raise InvalidLog(f"unknown tag: {tag}")
                if name not in cleaned:
                    cleaned.append(name)
            return cleaned
        if key == "meds":
            if not isinstance(value, list) or len(value) > MAX_DOSES_PER_DAY:
                raise InvalidLog("meds must be a list of doses")
            return [self._clean_dose(d) for d in value] or None
        if key == "results":
            return self._clean_results(value) or None
        if key not in CATEGORY_BY_ID:
            raise InvalidLog(f"unknown category: {key}")
        allowed = option_ids(key)
        if key == "period":
            allowed = set(FLOW_LEVELS) | {SPOTTING}
        if is_single(key):
            if isinstance(value, list):
                value = value[0] if value else None
            if value is None:
                return None
            if value not in allowed:
                raise InvalidLog(f"{key}: unknown option {value}")
            return value
        if not isinstance(value, list):
            value = [value]
        bad = [v for v in value if v not in allowed]
        if bad:
            raise InvalidLog(f"{key}: unknown option {bad[0]}")
        return list(dict.fromkeys(value))

    async def async_set_day(self, day: str, changes: dict[str, Any], user_id: str | None,
                            replace: bool = False) -> dict[str, Any]:
        """Merge (or replace) one day's log. Keys set to None/empty are removed."""
        async with self._lock:
            current = {} if replace else dict(self.days.get(day) or {})
            for key, value in changes.items():
                if key in META_KEYS:
                    continue
                if key == "results" and isinstance(value, dict) and not replace:
                    # Results merge field by field; a field set to null is removed.
                    merged = {**(current.get("results") or {}), **value}
                    value = {k: v for k, v in merged.items() if v not in (None, "")}
                cleaned = self._clean(key, value)
                if cleaned is None:
                    current.pop(key, None)
                else:
                    current[key] = cleaned
            content = {k: v for k, v in current.items() if k not in META_KEYS}
            if content:
                current["updated_by"] = user_id
                current["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                self.days[day] = current
            else:
                self.days.pop(day, None)
            await self._save()
            return self.days.get(day, {})

    async def async_add_tag(self, name: str) -> list[str]:
        name = name.strip()[:40]
        if not name:
            raise InvalidLog("tag name is empty")
        async with self._lock:
            if name.lower() not in {t.lower() for t in self.tags}:
                if len(self.tags) >= MAX_TAGS:
                    raise InvalidLog("too many tags")
                self.tags.append(name)
                await self._save()
            return list(self.tags)

    async def async_remove_tag(self, name: str) -> list[str]:
        """Remove a tag and take it off every day it was logged on."""
        async with self._lock:
            target = name.strip().lower()
            self.tags = [t for t in self.tags if t.lower() != target]
            for key, log in list(self.days.items()):
                tags = [t for t in (log.get("tags") or []) if t.lower() != target]
                if tags:
                    log["tags"] = tags
                elif "tags" in log:
                    log.pop("tags")
                    if not {k for k in log if k not in META_KEYS}:
                        self.days.pop(key)
            await self._save()
            return list(self.tags)

    async def async_import(self, days: dict[str, dict[str, Any]], tags: list[str], user_id: str | None) -> dict[str, int]:
        """Merge imported days in. Imported values win over existing ones for the same category."""
        async with self._lock:
            known = {t.lower() for t in self.tags}
            for tag in tags:
                if tag.lower() not in known:
                    self.tags.append(tag)
                    known.add(tag.lower())
            stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
            added = 0
            for day, log in days.items():
                current = dict(self.days.get(day) or {})
                if not current:
                    added += 1
                for key, value in log.items():
                    if key == "tags":
                        merged = list(dict.fromkeys((current.get("tags") or []) + value))
                        current["tags"] = merged
                    else:
                        current[key] = value
                current["updated_by"] = user_id
                current["updated_at"] = stamp
                self.days[day] = current
            await self._save()
            return {"days": len(days), "new_days": added, "tags": len(tags)}

    def _stamp(self, day: str, user_id: str | None) -> None:
        log = self.days[day]
        log["updated_by"] = user_id
        log["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # Doses -------------------------------------------------------------------------------------

    async def async_add_dose(self, day: str, dose: dict[str, Any], user_id: str | None) -> dict[str, Any]:
        cleaned = self._clean_dose({k: v for k, v in dose.items() if k != "id"})
        async with self._lock:
            log = self.days.setdefault(day, {})
            doses = log.setdefault("meds", [])
            if len(doses) >= MAX_DOSES_PER_DAY:
                raise InvalidLog("too many doses on one day")
            doses.append(cleaned)
            self._stamp(day, user_id)
            await self._save()
            return self.days[day]

    async def async_remove_dose(self, day: str, dose_id: str, user_id: str | None) -> dict[str, Any]:
        async with self._lock:
            log = self.days.get(day) or {}
            doses = [d for d in log.get("meds") or [] if d.get("id") != dose_id]
            if doses:
                log["meds"] = doses
            else:
                log.pop("meds", None)
            if {k for k in log if k not in META_KEYS}:
                self.days[day] = log
                self._stamp(day, user_id)
            else:
                self.days.pop(day, None)
            await self._save()
            return self.days.get(day, {})

    def dose_logged(self, day: str, med: str) -> bool:
        return any(d.get("med") == med for d in (self.days.get(day) or {}).get("meds") or [])

    # Custom medicines -------------------------------------------------------------------------

    async def async_add_med(self, name: str, kind: str, unit: str) -> dict[str, Any]:
        name = name.strip()[:40]
        if not name:
            raise InvalidLog("medicine name is empty")
        if kind not in tx.MED_KINDS:
            raise InvalidLog(f"unknown kind: {kind}")
        unit = (unit or "").strip()[:12]
        async with self._lock:
            if any(m["name"].lower() == name.lower() for m in self.catalogue().values()):
                raise InvalidLog(f"{name} is already in the list")
            if len(self.meds) >= MAX_CUSTOM_MEDS:
                raise InvalidLog("too many medicines")
            med = {"id": "custom_" + secrets.token_hex(4), "name": name, "kind": kind, "unit": unit}
            self.meds.append(med)
            await self._save()
            return med

    async def async_remove_med(self, med_id: str) -> None:
        async with self._lock:
            if not any(m["id"] == med_id for m in self.meds):
                raise InvalidLog("only medicines you added can be removed")
            used = sum(1 for log in self.days.values() if any(d.get("med") == med_id for d in log.get("meds") or []))
            if used or any(s.get("med") == med_id for s in self.schedules):
                raise InvalidLog("it's logged or has a reminder, so it can't be removed")
            self.meds = [m for m in self.meds if m["id"] != med_id]
            await self._save()

    # Treatment cycles -------------------------------------------------------------------------

    @staticmethod
    def _date(value: Any, what: str) -> str | None:
        if value in (None, ""):
            return None
        try:
            return date.fromisoformat(str(value)).isoformat()
        except ValueError as err:
            raise InvalidLog(f"{what} must be a date") from err

    def _clean_treatment(self, current: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any]:
        t = dict(current)
        for key, value in changes.items():
            if key == "type":
                if value not in tx.TREATMENT_TYPES:
                    raise InvalidLog(f"unknown treatment type: {value}")
                t[key] = value
            elif key == "protocol":
                if value not in (None, "") and value not in tx.PROTOCOLS:
                    raise InvalidLog(f"unknown protocol: {value}")
                t[key] = value or None
            elif key == "outcome":
                if value not in (None, "") and value not in tx.OUTCOMES:
                    raise InvalidLog(f"unknown outcome: {value}")
                t[key] = value or None
            elif key in ("start", "end", "test_date"):
                t[key] = self._date(value, key.replace("_", " "))
            elif key == "embryo_day":
                if value not in (None, "") and value not in (3, 5, 6):
                    raise InvalidLog("embryo day must be 3, 5 or 6")
                t[key] = value or None
            elif key == "note":
                t[key] = str(value or "").strip()[:MAX_NOTE] or None
            else:
                raise InvalidLog(f"unknown field: {key}")
        if not t.get("start"):
            raise InvalidLog("a treatment cycle needs a start date")
        if t.get("end") and t["end"] < t["start"]:
            raise InvalidLog("the end can't be before the start")
        return t

    def _check_overlap(self, t: dict[str, Any]) -> None:
        """Treatment cycles can't overlap; one without an end runs until it's ended."""
        forever = "9999-12-31"
        for other in self.treatments:
            if other.get("id") == t.get("id"):
                continue
            if t["start"] <= (other.get("end") or forever) and other["start"] <= (t.get("end") or forever):
                raise InvalidLog("that overlaps another treatment cycle; end that one first")

    async def async_start_treatment(self, changes: dict[str, Any]) -> dict[str, Any]:
        async with self._lock:
            t = self._clean_treatment({"type": "ivf"}, changes)
            self._check_overlap(t)
            t["id"] = secrets.token_hex(4)
            self.treatments.append(t)
            self.treatments.sort(key=lambda x: x["start"])
            await self._save()
            return t

    async def async_update_treatment(self, treatment_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        async with self._lock:
            for i, current in enumerate(self.treatments):
                if current["id"] == treatment_id:
                    t = self._clean_treatment(current, changes)
                    self._check_overlap(t)
                    self.treatments[i] = t
                    self.treatments.sort(key=lambda x: x["start"])
                    await self._save()
                    return t
            raise InvalidLog("no such treatment cycle")

    async def async_delete_treatment(self, treatment_id: str) -> None:
        """Forget the treatment cycle record. The doses and results logged on its days stay."""
        async with self._lock:
            self.treatments = [t for t in self.treatments if t["id"] != treatment_id]
            await self._save()

    # Reminders ----------------------------------------------------------------------------------

    async def async_set_schedule(self, data: dict[str, Any], allowed_targets: set[str],
                                 user_id: str | None) -> dict[str, Any]:
        if data.get("med") not in self.catalogue():
            raise InvalidLog(f"unknown medicine: {data.get('med')}")
        if not TIME_RE.match(str(data.get("time") or "")):
            raise InvalidLog("time must be HH:MM")
        targets = list(dict.fromkeys(data.get("targets") or []))
        if not targets:
            raise InvalidLog("pick at least one phone to remind")
        if set(targets) - allowed_targets:
            raise InvalidLog("you can only remind the phones of people who can see this tracker")
        dose = self._clean_dose({"med": data["med"], "dose": data.get("dose"), "unit": data.get("unit")})
        start = self._date(data.get("start"), "start") or date.today().isoformat()
        end = self._date(data.get("end"), "end")
        if end and end < start:
            raise InvalidLog("the last day can't be before the first")
        async with self._lock:
            current = next((s for s in self.schedules if s["id"] == data.get("id")), None) if data.get("id") else None
            if data.get("id") and not current:
                raise InvalidLog("no such reminder")
            if not current and len(self.schedules) >= MAX_SCHEDULES:
                raise InvalidLog("too many reminders")
            sched = {
                "id": current["id"] if current else secrets.token_hex(4),
                # Goes in the notification's action ids, so a stray action can't log a dose.
                "token": current["token"] if current else secrets.token_hex(8),
                "med": dose["med"], "dose": dose["dose"], "unit": dose["unit"], "time": data["time"],
                "start": start, "end": end, "targets": targets,
                "discreet": bool(data.get("discreet", False)),
                "follow_up": bool(data.get("follow_up", True)),
                "enabled": bool(data.get("enabled", True)),
                "created_by": current["created_by"] if current else user_id,
            }
            if current:
                self.schedules[self.schedules.index(current)] = sched
            else:
                self.schedules.append(sched)
            self.schedules.sort(key=lambda s: s["time"])
            await self._save()
            return sched

    async def async_remove_schedule(self, schedule_id: str) -> None:
        async with self._lock:
            self.schedules = [s for s in self.schedules if s["id"] != schedule_id]
            await self._save()

    async def async_clear(self) -> None:
        async with self._lock:
            self.days = {}
            self.tags = []
            self.treatments = []
            self.meds = []
            self.schedules = []
            await self._save()
