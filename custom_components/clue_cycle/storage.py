"""Per-tracker storage: the day logs and custom tags, kept in HA's .storage."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .categories import CATEGORY_BY_ID, FLOW_LEVELS, SPOTTING, is_single, option_ids

STORAGE_VERSION = 1
META_KEYS = ("updated_by", "updated_at")
MAX_TAGS = 100
MAX_NOTE = 2000


class InvalidLog(ValueError):
    """Raised when a day update contains something the tracker can't store."""


class CycleStore:
    """Read-change-write is serialised so two people logging at once can't drop an edit."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store = Store(hass, STORAGE_VERSION, f"clue_cycle.{entry_id}", private=True)
        self._lock = asyncio.Lock()
        self.days: dict[str, dict[str, Any]] = {}
        self.tags: list[str] = []

    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        self.days = data.get("days") or {}
        self.tags = data.get("tags") or []

    async def _save(self) -> None:
        await self._store.async_save({"days": self.days, "tags": self.tags})

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

    async def async_clear(self) -> None:
        async with self._lock:
            self.days = {}
            self.tags = []
            await self._save()
