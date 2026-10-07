"""Phone notifications: dose reminders and cycle phase changes.

Dose reminders arrive at the dose time with Done and Snooze buttons.

Done logs the dose on that day, Snooze asks again in 15 minutes, and if nothing has been logged
30 minutes after the reminder it asks once more. Notifications only go to the Home Assistant
companion apps of people who can see the tracker.

The daily check-in ("How do you feel today?", like Clue's own reminder) goes out at a set time, and by
default only if nothing has been logged that day yet. Tapping it opens the tracker on the Track tab.

Phase notifications are checked once a day at the owner's chosen time: when today's phase differs
from the last one notified (fertile window starting, period due, test day and so on), the ring's
headline goes out as the notification.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from functools import partial
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later, async_track_time_change
from homeassistant.util import dt as dt_util
from homeassistant.util import slugify

from . import engine
from .access import owner_of, sharing_of
from .const import CONF_PHASE_NOTIFY, SIGNAL_UPDATED
from .storage import CycleStore

_LOGGER = logging.getLogger(__name__)

ACTION_PREFIX = "CLUECYCLE"
ACTION_EVENT = "mobile_app_notification_action"
SNOOZE = timedelta(minutes=15)
FOLLOW_UP = timedelta(minutes=30)
DEFAULT_PHASE_TIME = "08:00"
# Phases that don't get a notification: a logged period is something she already knows about.
QUIET_PHASES = {"unknown", "period", "ended"}


async def async_targets(hass: HomeAssistant, entry: ConfigEntry) -> list[dict[str, str]]:
    """Companion-app notify services belonging to the owner or anyone the tracker is shared with."""
    allowed = {owner_of(entry), *sharing_of(entry)}
    names = {u.id: u.name or "Someone" for u in await hass.auth.async_get_users()}
    out = []
    for app in hass.config_entries.async_entries("mobile_app"):
        user_id = app.data.get("user_id")
        device = app.data.get("device_name") or app.title
        service = f"mobile_app_{slugify(device)}"
        if user_id in allowed and hass.services.has_service("notify", service):
            out.append({"service": service, "device": device, "user": names.get(user_id, "Someone")})
    return sorted(out, key=lambda t: (t["user"].lower(), t["device"].lower()))


OWNER_PHONES = "owner"   # stands for the tracker owner's phones, worked out when each notification is sent


def owner_services(hass: HomeAssistant, entry: ConfigEntry) -> list[str]:
    """The owner's companion apps on phones and tablets (not Macs), including ones added since setup."""
    out = []
    for app in hass.config_entries.async_entries("mobile_app"):
        if app.data.get("user_id") != owner_of(entry) or app.data.get("os_name") == "macOS":
            continue
        service = f"mobile_app_{slugify(app.data.get('device_name') or app.title)}"
        if hass.services.has_service("notify", service):
            out.append(service)
    return out


async def resolve_targets(hass: HomeAssistant, entry: ConfigEntry, targets: list[str]) -> list[str]:
    """Expand "owner", and drop any phone whose person no longer has access to the tracker."""
    allowed = {t["service"] for t in await async_targets(hass, entry)}
    out: list[str] = []
    for target in targets or []:
        for service in (owner_services(hass, entry) if target == OWNER_PHONES else [target]):
            if service in allowed and service not in out:
                out.append(service)
    return out


def next_dose(store: CycleStore, now: datetime) -> dict[str, Any] | None:
    """The next reminder that hasn't been logged yet, for the Today view."""
    cat = store.catalogue()
    best = None
    for offset in (0, 1):
        day = now.date() + timedelta(days=offset)
        for s in store.schedules:
            if not s.get("enabled") or not _runs_on(s, day):
                continue
            hour, minute = map(int, s["time"].split(":"))
            when = datetime.combine(day, datetime.min.time()).replace(hour=hour, minute=minute, tzinfo=now.tzinfo)
            if offset == 0 and (store.dose_logged(day.isoformat(), s["med"]) or when < now - FOLLOW_UP):
                continue
            if best is None or when < best[0]:
                best = (when, s, day)
        if best:
            break
    if not best:
        return None
    when, s, day = best
    med = cat.get(s["med"], {"name": s["med"]})
    return {"date": day.isoformat(), "time": s["time"], "med": s["med"], "name": med["name"],
            "dose": s.get("dose"), "unit": s.get("unit")}


def _runs_on(s: dict[str, Any], day: date) -> bool:
    iso = day.isoformat()
    return s.get("start", iso) <= iso and (not s.get("end") or iso <= s["end"])


class Reminders:
    """Schedules one time listener per enabled reminder and handles the notification buttons."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, store: CycleStore) -> None:
        self.hass = hass
        self.entry = entry
        self.store = store
        self._timers: list[CALLBACK_TYPE] = []
        self._pending: dict[tuple[str, str], CALLBACK_TYPE] = {}
        self._unsub_event: CALLBACK_TYPE | None = None

    @callback
    def async_start(self) -> None:
        self._unsub_event = self.hass.bus.async_listen(ACTION_EVENT, self._on_action)
        self.async_reschedule()

    # Phase notifications -------------------------------------------------------------------------

    def phase_settings(self) -> dict[str, Any]:
        cfg = dict(self.entry.options.get(CONF_PHASE_NOTIFY) or {})
        cfg.setdefault("enabled", False)
        cfg.setdefault("time", DEFAULT_PHASE_TIME)
        cfg.setdefault("targets", [])
        cfg.setdefault("discreet", False)
        return cfg

    def current_phase(self, today: date) -> tuple[str, dict[str, Any]]:
        """Today's phase (the treatment step while a treatment cycle runs) and the ring's wording."""
        settings = engine.Settings.from_dict({**self.entry.data, **self.entry.options})
        ov = engine.overview(self.store.days, settings, today, self.store.tx())
        phase = ov["treatment"]["phase"] if ov.get("treatment") else ov["prediction"]["phase"]
        return phase, ov["status"]

    async def async_seed_phase(self) -> None:
        """Remember today's phase without notifying, so turning this on doesn't send a stale one."""
        today = dt_util.now().date()
        phase, _ = self.current_phase(today)
        await self.store.async_set_notified(phase, today.isoformat())

    async def _phase_check(self, now: datetime) -> None:
        cfg = self.phase_settings()
        if not cfg["enabled"]:
            return
        today = dt_util.as_local(now).date()
        phase, status = self.current_phase(today)
        if phase == self.store.notified.get("phase"):
            return
        await self.store.async_set_notified(phase, today.isoformat())
        if phase in QUIET_PHASES:
            return
        await self.async_send_phase(status, cfg)

    async def async_send_phase(self, status: dict[str, Any], cfg: dict[str, Any], test: bool = False) -> int:
        if cfg.get("discreet"):
            title, message = "Clue Cycle", "There's an update on your cycle"
        else:
            title, message = status["headline"], status["sub"]
        sent = 0
        for target in await resolve_targets(self.hass, self.entry, cfg.get("targets") or []):
            try:
                await self.hass.services.async_call("notify", target, {
                    "title": f"Test: {title}" if test else title, "message": message,
                    "data": {"tag": f"cluecycle_phase_{self.entry.entry_id}", "group": "cluecycle"}}, blocking=True)
                sent += 1
            except Exception:  # noqa: BLE001
                _LOGGER.warning("Clue Cycle: couldn't send a phase notification to %s", target, exc_info=True)
        return sent

    # Daily check-in -------------------------------------------------------------------------------

    async def _checkin_due(self, now: datetime) -> None:
        cfg = self.store.checkin
        if not cfg.get("enabled"):
            return
        if cfg.get("skip_if_logged", True) and self.store.logged(dt_util.as_local(now).date().isoformat()):
            return   # already logged today, no need to ask
        await self.async_send_checkin(cfg)

    async def async_send_checkin(self, cfg: dict[str, Any], test: bool = False) -> int:
        data: dict[str, Any] = {"tag": f"cluecycle_checkin_{self.entry.entry_id}", "group": "cluecycle"}
        if cfg.get("open_path"):
            # Opens the tracker on the Track tab: `url` for iOS, `clickAction` for Android.
            path = f"{cfg['open_path']}?cc_view=track"
            data.update({"url": path, "clickAction": path})
        title = "Clue Cycle"
        sent = 0
        for target in await resolve_targets(self.hass, self.entry, cfg.get("targets") or []):
            try:
                await self.hass.services.async_call("notify", target, {
                    "title": f"Test: {title}" if test else title, "message": cfg.get("message") or "How do you feel today?",
                    "data": data}, blocking=True)
                sent += 1
            except Exception:  # noqa: BLE001
                _LOGGER.warning("Clue Cycle: couldn't send the daily check-in to %s", target, exc_info=True)
        return sent

    @callback
    def async_stop(self) -> None:
        for unsub in self._timers:
            unsub()
        self._timers.clear()
        for unsub in self._pending.values():
            unsub()
        self._pending.clear()
        if self._unsub_event:
            self._unsub_event()
            self._unsub_event = None

    @callback
    def async_reschedule(self) -> None:
        for unsub in self._timers:
            unsub()
        self._timers.clear()
        cfg = self.phase_settings()
        if cfg["enabled"]:
            hour, minute = map(int, cfg["time"].split(":"))
            self._timers.append(async_track_time_change(self.hass, self._phase_check, hour=hour, minute=minute, second=0))
        checkin = self.store.checkin
        if checkin.get("enabled"):
            hour, minute = map(int, checkin["time"].split(":"))
            self._timers.append(async_track_time_change(self.hass, self._checkin_due, hour=hour, minute=minute, second=0))
        for s in self.store.schedules:
            if s.get("enabled"):
                hour, minute = map(int, s["time"].split(":"))
                self._timers.append(async_track_time_change(
                    self.hass, partial(self._due, s["id"]), hour=hour, minute=minute, second=0))

    def _schedule(self, schedule_id: str) -> dict[str, Any] | None:
        return next((s for s in self.store.schedules if s["id"] == schedule_id), None)

    async def _due(self, schedule_id: str, now: datetime) -> None:
        s = self._schedule(schedule_id)
        day = dt_util.as_local(now).date()
        if not s or not s.get("enabled") or not _runs_on(s, day):
            return
        if self.store.dose_logged(day.isoformat(), s["med"]):
            return  # already taken early and logged
        await self.async_send(s, day)
        if s.get("follow_up"):
            self._later(s, day, FOLLOW_UP, only_if_not_logged=True)

    def _later(self, s: dict[str, Any], day: date, delay: timedelta, only_if_not_logged: bool = False) -> None:
        key = (s["id"], day.isoformat())
        if old := self._pending.pop(key, None):
            old()

        async def _again(_now: datetime) -> None:
            self._pending.pop(key, None)
            current = self._schedule(s["id"])
            if not current or (only_if_not_logged and self.store.dose_logged(day.isoformat(), current["med"])):
                return
            await self.async_send(current, day, again=True)

        self._pending[key] = async_call_later(self.hass, delay, _again)

    def _message(self, s: dict[str, Any], again: bool) -> tuple[str, str]:
        med = self.store.catalogue().get(s["med"], {"name": "your medicine"})
        if s.get("discreet"):
            return "Reminder", f"Time for your {s['time']} dose" + (" (still to do)" if again else "")
        amount = f"{s['dose']:g} {s.get('unit') or ''}".strip() if isinstance(s.get("dose"), (int, float)) else ""
        title = med["name"] + (f" {amount}" if amount else "")
        return title, f"{'Still to do: ' if again else ''}dose due at {s['time']}"

    async def async_send(self, s: dict[str, Any], day: date, again: bool = False, test: bool = False) -> int:
        """Notify every target phone. Returns how many were sent."""
        title, message = self._message(s, again)
        stamp = day.strftime("%Y%m%d")
        data = {
            "tag": f"cluecycle_{s['token']}",
            "group": "cluecycle",
            "push": {"interruption-level": "time-sensitive"},
            "actions": [] if test else [
                {"action": f"{ACTION_PREFIX}_DONE_{s['token']}_{stamp}", "title": "Done"},
                {"action": f"{ACTION_PREFIX}_SNOOZE_{s['token']}_{stamp}", "title": "Snooze 15 min"},
            ],
        }
        sent = 0
        for target in await resolve_targets(self.hass, self.entry, s.get("targets") or []):
            try:
                await self.hass.services.async_call(
                    "notify", target, {"title": f"Test: {title}" if test else title, "message": message, "data": data},
                    blocking=True)
                sent += 1
            except Exception:  # noqa: BLE001 - one phone failing shouldn't stop the others
                _LOGGER.warning("Clue Cycle: couldn't send a dose reminder to %s", target, exc_info=True)
        return sent

    async def _clear(self, s: dict[str, Any]) -> None:
        for target in await resolve_targets(self.hass, self.entry, s.get("targets") or []):
            if self.hass.services.has_service("notify", target):
                await self.hass.services.async_call(
                    "notify", target, {"message": "clear_notification", "data": {"tag": f"cluecycle_{s['token']}"}},
                    blocking=False)

    @callback
    def _on_action(self, event: Event) -> None:
        action = str(event.data.get("action") or "")
        parts = action.split("_")
        if len(parts) != 4 or parts[0] != ACTION_PREFIX or parts[1] not in ("DONE", "SNOOZE"):
            return
        s = next((x for x in self.store.schedules if x.get("token") == parts[2]), None)
        if not s:
            return
        try:
            day = datetime.strptime(parts[3], "%Y%m%d").date()
        except ValueError:
            return
        if parts[1] == "SNOOZE":
            self._later(s, day, SNOOZE)
            return
        self.hass.async_create_task(self._done(s, day, event.context.user_id))

    async def _done(self, s: dict[str, Any], day: date, user_id: str | None) -> None:
        if old := self._pending.pop((s["id"], day.isoformat()), None):
            old()
        if not self.store.dose_logged(day.isoformat(), s["med"]):
            now = dt_util.now()
            await self.store.async_add_dose(day.isoformat(), {
                "med": s["med"], "dose": s.get("dose"), "unit": s.get("unit"),
                "time": now.strftime("%H:%M") if now.date() == day else s["time"],
            }, user_id or s.get("created_by"))
            async_dispatcher_send(self.hass, SIGNAL_UPDATED.format(self.entry.entry_id))
        await self._clear(s)
