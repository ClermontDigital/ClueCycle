"""Optional calendar: logged periods plus predicted periods, fertile windows and ovulation."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import engine
from .api import settings_for
from .entity import CycleEntity

TITLES = {"period": "Period", "fertile": "Fertile window", "ovulation": "Ovulation (predicted)"}


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([CycleCalendar(hass, entry, "calendar")])


class CycleCalendar(CycleEntity, CalendarEntity):
    def _events(self) -> list[CalendarEvent]:
        today = dt_util.now().date()
        settings = settings_for(self._entry)
        events = [
            CalendarEvent(start=p.start, end=p.end + timedelta(days=1), summary="Period")
            for p in engine.periods(self.store.days)
        ]
        for item in engine.upcoming(self.store.days, settings, today, count=6):
            start = date.fromisoformat(item["start"])
            end = date.fromisoformat(item["end"])
            title = TITLES[item["kind"]]
            if item["kind"] == "period":
                title = "Period (predicted)"
            events.append(CalendarEvent(start=start, end=end + timedelta(days=1), summary=title))
        return sorted(events, key=lambda e: e.start)

    @property
    def event(self) -> CalendarEvent | None:
        today = dt_util.now().date()
        for ev in self._events():
            if ev.end > today:
                return ev
        return None

    async def async_get_events(self, hass: HomeAssistant, start_date: datetime, end_date: datetime) -> list[CalendarEvent]:
        lo, hi = start_date.date(), end_date.date()
        return [ev for ev in self._events() if ev.start <= hi and ev.end > lo]
