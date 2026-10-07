"""WebSocket API for the Clue Cycle card.

Every command resolves the tracker and the caller's role first (see access.py): viewers can read,
editors can also log, import and manage tags, and only the owner can change settings and sharing.
"""
from __future__ import annotations

import base64
import binascii
from datetime import date
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect, async_dispatcher_send
from homeassistant.util import dt as dt_util

from . import engine
from . import treatment as tx
from .access import (
    CONF_EXPOSE, CONF_SHARING, ROLE_OWNER, SHARE_LEVELS, can_edit, describe, owner_of, role_for, sharing_of,
)
from .categories import CATEGORIES, TAG_COLOR
from .const import (
    CONF_CYCLE_LENGTH, CONF_GOAL, CONF_LUTEAL_LENGTH, CONF_PERIOD_LENGTH, CONF_PHASE_NOTIFY, CONF_TREATMENT, DOMAIN,
    GOALS, SIGNAL_UPDATED,
)
from .importer import ImportError_, PasswordRequired, parse_clue_export
from .reminders import OWNER_PHONES, Reminders, async_targets, next_dose
from .storage import TIME_RE, CycleStore, InvalidLog

MAX_IMPORT_BYTES = 25 * 1024 * 1024


def settings_for(entry: ConfigEntry) -> engine.Settings:
    return engine.Settings.from_dict({**entry.data, **entry.options})


def _entries(hass: HomeAssistant) -> list[ConfigEntry]:
    return [e for e in hass.config_entries.async_entries(DOMAIN) if e.entry_id in hass.data.get(DOMAIN, {})]


def _resolve(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any],
             need: str = "view") -> tuple[ConfigEntry, CycleStore, str] | None:
    """Find the tracker and check the caller may use it. Sends the error itself on failure."""
    entry = hass.config_entries.async_get_entry(msg["entry_id"])
    data = hass.data.get(DOMAIN, {}).get(msg["entry_id"])
    role = role_for(entry, connection.user.id) if entry else None
    # Not-found and not-allowed look the same, so the API doesn't reveal which trackers exist.
    if not entry or not data or not role:
        connection.send_error(msg["id"], "not_found", "No such tracker")
        return None
    if need == "edit" and not can_edit(role):
        connection.send_error(msg["id"], "unauthorized", "You can view this tracker but not change it")
        return None
    if need == "owner" and role != ROLE_OWNER:
        connection.send_error(msg["id"], "unauthorized", "Only the tracker's owner can change this")
        return None
    return entry, data["store"], role


def _reminders(hass: HomeAssistant, entry: ConfigEntry) -> Reminders:
    return hass.data[DOMAIN][entry.entry_id]["reminders"]


def _tracking(entry: ConfigEntry) -> bool:
    return bool(entry.options.get(CONF_TREATMENT, False))


def _today(msg: dict[str, Any]) -> date:
    if msg.get("date"):
        try:
            return date.fromisoformat(msg["date"])
        except ValueError:
            pass
    return dt_util.now().date()


async def _user_names(hass: HomeAssistant) -> dict[str, str]:
    return {u.id: u.name or "Someone" for u in await hass.auth.async_get_users()}


@callback
def _changed(hass: HomeAssistant, entry_id: str) -> None:
    async_dispatcher_send(hass, SIGNAL_UPDATED.format(entry_id))


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/trackers"})
@callback
def ws_trackers(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Trackers the caller can see."""
    out = []
    for entry in _entries(hass):
        role = role_for(entry, connection.user.id)
        if role:
            out.append(describe(entry, role))
    connection.send_result(msg["id"], out)


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/categories"})
@callback
def ws_categories(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    connection.send_result(msg["id"], {"categories": CATEGORIES, "tag_color": TAG_COLOR})


@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/overview",
    vol.Required("entry_id"): str,
    vol.Optional("date"): str,
})
@websocket_api.async_response
async def ws_overview(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    if not (res := _resolve(hass, connection, msg)):
        return
    entry, store, role = res
    settings = settings_for(entry)
    payload = engine.overview(store.days, settings, _today(msg), store.tx())
    payload.update({
        "tracker": describe(entry, role),
        "settings": settings.__dict__,
        "treatment_tracking": _tracking(entry),
        "next_dose": next_dose(store, dt_util.now()) if _tracking(entry) else None,
        "tags": store.tags,
        "layout": store.layout,
        "upcoming": engine.upcoming(store.days, settings, _today(msg), tx=store.tx()),
    })
    if role == ROLE_OWNER:
        payload["phase_notify"] = _reminders(hass, entry).phase_settings()
    connection.send_result(msg["id"], payload)


@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/days",
    vol.Required("entry_id"): str,
    vol.Required("start"): str,
    vol.Required("end"): str,
})
@websocket_api.async_response
async def ws_days(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    if not (res := _resolve(hass, connection, msg)):
        return
    _, store, _ = res
    names = await _user_names(hass)
    out = {}
    for day, log in store.days.items():
        if msg["start"] <= day <= msg["end"]:
            item = dict(log)
            if item.get("updated_by"):
                item["updated_by_name"] = names.get(item["updated_by"], "Someone")
            out[day] = item
    connection.send_result(msg["id"], out)


@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/calendar",
    vol.Required("entry_id"): str,
    vol.Required("start"): str,
    vol.Required("end"): str,
    vol.Optional("date"): str,
})
@websocket_api.async_response
async def ws_calendar(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Kind (period, predicted, fertile, peak, ovulation) and dots for each day in a range."""
    if not (res := _resolve(hass, connection, msg)):
        return
    entry, store, _ = res
    try:
        start, end = date.fromisoformat(msg["start"]), date.fromisoformat(msg["end"])
    except ValueError:
        connection.send_error(msg["id"], "invalid", "Bad date")
        return
    if (end - start).days > 400:
        connection.send_error(msg["id"], "invalid", "Range too long")
        return
    connection.send_result(msg["id"], engine.calendar(store.days, settings_for(entry), _today(msg), start, end, store.tx()))


@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/set_day",
    vol.Required("entry_id"): str,
    vol.Required("date"): str,
    vol.Required("changes"): dict,
    vol.Optional("replace", default=False): bool,
})
@websocket_api.async_response
async def ws_set_day(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    if not (res := _resolve(hass, connection, msg, "edit")):
        return
    entry, store, _ = res
    try:
        day = date.fromisoformat(msg["date"]).isoformat()
        log = await store.async_set_day(day, msg["changes"], connection.user.id, msg["replace"])
    except (ValueError, InvalidLog) as err:
        connection.send_error(msg["id"], "invalid", str(err))
        return
    _changed(hass, entry.entry_id)
    connection.send_result(msg["id"], {"date": day, "log": log})


@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/tag_add",
    vol.Required("entry_id"): str,
    vol.Required("name"): str,
})
@websocket_api.async_response
async def ws_tag_add(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    if not (res := _resolve(hass, connection, msg, "edit")):
        return
    entry, store, _ = res
    try:
        tags = await store.async_add_tag(msg["name"])
    except InvalidLog as err:
        connection.send_error(msg["id"], "invalid", str(err))
        return
    _changed(hass, entry.entry_id)
    connection.send_result(msg["id"], tags)


@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/tag_remove",
    vol.Required("entry_id"): str,
    vol.Required("name"): str,
})
@websocket_api.async_response
async def ws_tag_remove(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    if not (res := _resolve(hass, connection, msg, "edit")):
        return
    entry, store, _ = res
    tags = await store.async_remove_tag(msg["name"])
    _changed(hass, entry.entry_id)
    connection.send_result(msg["id"], tags)


@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/analysis",
    vol.Required("entry_id"): str,
    vol.Optional("date"): str,
})
@websocket_api.async_response
async def ws_analysis(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    if not (res := _resolve(hass, connection, msg)):
        return
    entry, store, _ = res
    settings = settings_for(entry)
    pred, st, cyc = engine.predict(store.days, settings, _today(msg), store.tx())
    connection.send_result(msg["id"], {
        "stats": st.as_dict(),
        "prediction": pred.as_dict(),
        "cycles": [c.as_dict() for c in cyc],
    })


@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/import",
    vol.Required("entry_id"): str,
    vol.Required("content"): str,           # base64 of the file the user picked
    vol.Optional("filename", default=""): str,
    vol.Optional("dry_run", default=False): bool,
    vol.Optional("password"): vol.All(str, vol.Length(max=200)),  # Clue's zips are password protected
})
@websocket_api.async_response
async def ws_import(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    if not (res := _resolve(hass, connection, msg, "edit")):
        return
    entry, store, _ = res
    try:
        raw = base64.b64decode(msg["content"], validate=False)
    except (binascii.Error, ValueError):
        connection.send_error(msg["id"], "invalid", "Couldn't read the file")
        return
    if len(raw) > MAX_IMPORT_BYTES:
        connection.send_error(msg["id"], "invalid", "That file is too big for a Clue export")
        return
    try:
        parsed = await hass.async_add_executor_job(parse_clue_export, raw, msg.get("password") or None)
    except PasswordRequired as err:
        connection.send_error(msg["id"], "password_required", str(err).capitalize())
        return
    except ImportError_ as err:
        connection.send_error(msg["id"], "invalid", f"Not a Clue export this can read: {err}")
        return
    summary = {"range": parsed["range"], "days": len(parsed["days"]), "tags": len(parsed["tags"]),
               "unknown": parsed["unknown"], "skipped": parsed.get("skipped", {}), "dry_run": msg["dry_run"]}
    if not msg["dry_run"]:
        summary.update(await store.async_import(parsed["days"], parsed["tags"], connection.user.id))
        _changed(hass, entry.entry_id)
    connection.send_result(msg["id"], summary)


@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/settings_set",
    vol.Required("entry_id"): str,
    vol.Optional(CONF_GOAL): vol.In(GOALS),
    vol.Optional(CONF_CYCLE_LENGTH): vol.All(int, vol.Range(min=15, max=60)),
    vol.Optional(CONF_PERIOD_LENGTH): vol.All(int, vol.Range(min=1, max=15)),
    vol.Optional(CONF_LUTEAL_LENGTH): vol.All(int, vol.Range(min=8, max=20)),
    vol.Optional(CONF_TREATMENT): bool,
    vol.Optional(CONF_PHASE_NOTIFY): {
        vol.Required("enabled"): bool,
        vol.Optional("time", default="08:00"): vol.All(str, vol.Match(TIME_RE)),
        vol.Optional("targets", default=[]): [str],
        vol.Optional("discreet", default=False): bool,
    },
})
@websocket_api.async_response
async def ws_settings_set(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    if not (res := _resolve(hass, connection, msg, "owner")):
        return
    entry, _, _ = res
    options = dict(entry.options)
    for key in (CONF_GOAL, CONF_CYCLE_LENGTH, CONF_PERIOD_LENGTH, CONF_LUTEAL_LENGTH, CONF_TREATMENT):
        if key in msg:
            options[key] = msg[key]
    reminders = _reminders(hass, entry)
    turned_on = False
    if CONF_PHASE_NOTIFY in msg:
        cfg = dict(msg[CONF_PHASE_NOTIFY])
        allowed = {t["service"] for t in await async_targets(hass, entry)} | {OWNER_PHONES}
        if set(cfg["targets"]) - allowed:
            connection.send_error(msg["id"], "invalid", "Pick phones belonging to people who can see this tracker")
            return
        if cfg["enabled"] and not cfg["targets"]:
            connection.send_error(msg["id"], "invalid", "Pick at least one phone to notify")
            return
        turned_on = cfg["enabled"] and not reminders.phase_settings()["enabled"]
        options[CONF_PHASE_NOTIFY] = cfg
    hass.config_entries.async_update_entry(entry, options=options)
    if turned_on:
        await reminders.async_seed_phase()
    reminders.async_reschedule()
    _changed(hass, entry.entry_id)
    connection.send_result(msg["id"], {**settings_for(entry).__dict__, CONF_TREATMENT: _tracking(entry),
                                       CONF_PHASE_NOTIFY: reminders.phase_settings()})


@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/sharing",
    vol.Required("entry_id"): str,
})
@websocket_api.async_response
async def ws_sharing(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    if not (res := _resolve(hass, connection, msg, "owner")):
        return
    entry, _, _ = res
    users = [
        {"id": u.id, "name": u.name or "Unnamed"}
        for u in await hass.auth.async_get_users()
        if u.is_active and not u.system_generated and u.id != owner_of(entry)
    ]
    connection.send_result(msg["id"], {
        "users": sorted(users, key=lambda u: u["name"].lower()),
        "sharing": sharing_of(entry),
        "expose_entities": bool(entry.options.get(CONF_EXPOSE, False)),
    })


@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/sharing_set",
    vol.Required("entry_id"): str,
    vol.Optional("sharing"): {str: vol.In(SHARE_LEVELS)},
    vol.Optional("expose_entities"): bool,
})
@websocket_api.async_response
async def ws_sharing_set(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    if not (res := _resolve(hass, connection, msg, "owner")):
        return
    entry, _, _ = res
    options = dict(entry.options)
    if "sharing" in msg:
        valid = {u.id for u in await hass.auth.async_get_users() if not u.system_generated}
        options[CONF_SHARING] = {uid: lvl for uid, lvl in msg["sharing"].items()
                                 if uid in valid and uid != owner_of(entry)}
    reload = False
    if "expose_entities" in msg and bool(msg["expose_entities"]) != bool(options.get(CONF_EXPOSE, False)):
        options[CONF_EXPOSE] = bool(msg["expose_entities"])
        reload = True
    hass.config_entries.async_update_entry(entry, options=options)
    if reload:
        hass.config_entries.async_schedule_reload(entry.entry_id)
    connection.send_result(msg["id"], {"sharing": sharing_of(entry), "expose_entities": options.get(CONF_EXPOSE, False)})


@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/subscribe",
    vol.Required("entry_id"): str,
})
@callback
def ws_subscribe(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Tell the card when anyone changes this tracker, so open dashboards refresh."""
    if not _resolve(hass, connection, msg):
        return
    entry_id = msg["entry_id"]

    @callback
    def _forward() -> None:
        # Re-check on every event: the owner may have stopped sharing since the card subscribed.
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry and role_for(entry, connection.user.id):
            connection.send_message(websocket_api.event_message(msg["id"], {"changed": True}))

    connection.subscriptions[msg["id"]] = async_dispatcher_connect(hass, SIGNAL_UPDATED.format(entry_id), _forward)
    connection.send_result(msg["id"])


@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/layout_set",
    vol.Required("entry_id"): str,
    vol.Required("order"): [str],
    vol.Optional("hidden", default=[]): [str],
})
@websocket_api.async_response
async def ws_layout_set(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """The Track tab's category order and which categories sit under "More categories"."""
    if not (res := _resolve(hass, connection, msg, "edit")):
        return
    entry, store, _ = res
    layout = await store.async_set_layout(msg["order"], msg["hidden"])
    _changed(hass, entry.entry_id)
    connection.send_result(msg["id"], layout)


# Fertility treatment ---------------------------------------------------------------------------

@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/treatment_info", vol.Required("entry_id"): str})
@websocket_api.async_response
async def ws_treatment_info(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Medicines, the choices for the forms, and the tracker's treatment cycles."""
    if not (res := _resolve(hass, connection, msg)):
        return
    _, store, _ = res
    connection.send_result(msg["id"], {
        # Grouped by kind, built-in medicines in the usual clinic order, then the tracker's own.
        "meds": sorted(store.catalogue().values(), key=lambda m: (list(tx.MED_KINDS).index(m["kind"]), m.get("custom", False))),
        "kinds": tx.MED_KINDS, "units": tx.UNITS, "types": tx.TREATMENT_TYPES, "protocols": tx.PROTOCOLS,
        "outcomes": tx.OUTCOMES, "results": tx.RESULT_FIELDS, "cycles": store.treatments,
    })


@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/dose_add",
    vol.Required("entry_id"): str,
    vol.Required("date"): str,
    vol.Required("med"): str,
    vol.Optional("dose"): vol.Any(None, vol.Coerce(float)),
    vol.Optional("unit"): vol.Any(None, str),
    vol.Optional("time"): vol.Any(None, str),
})
@websocket_api.async_response
async def ws_dose_add(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    if not (res := _resolve(hass, connection, msg, "edit")):
        return
    entry, store, _ = res
    try:
        day = date.fromisoformat(msg["date"]).isoformat()
        log = await store.async_add_dose(day, {k: msg.get(k) for k in ("med", "dose", "unit", "time")}, connection.user.id)
    except (ValueError, InvalidLog) as err:
        connection.send_error(msg["id"], "invalid", str(err))
        return
    _changed(hass, entry.entry_id)
    connection.send_result(msg["id"], {"date": day, "log": log})


@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/dose_remove",
    vol.Required("entry_id"): str,
    vol.Required("date"): str,
    vol.Required("dose_id"): str,
})
@websocket_api.async_response
async def ws_dose_remove(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    if not (res := _resolve(hass, connection, msg, "edit")):
        return
    entry, store, _ = res
    log = await store.async_remove_dose(msg["date"], msg["dose_id"], connection.user.id)
    _changed(hass, entry.entry_id)
    connection.send_result(msg["id"], {"date": msg["date"], "log": log})


@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/med_add",
    vol.Required("entry_id"): str,
    vol.Required("name"): str,
    vol.Required("kind"): str,
    vol.Optional("unit", default=""): str,
})
@websocket_api.async_response
async def ws_med_add(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    if not (res := _resolve(hass, connection, msg, "edit")):
        return
    entry, store, _ = res
    try:
        med = await store.async_add_med(msg["name"], msg["kind"], msg["unit"])
    except InvalidLog as err:
        connection.send_error(msg["id"], "invalid", str(err))
        return
    _changed(hass, entry.entry_id)
    connection.send_result(msg["id"], med)


@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/med_remove",
    vol.Required("entry_id"): str,
    vol.Required("med"): str,
})
@websocket_api.async_response
async def ws_med_remove(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    if not (res := _resolve(hass, connection, msg, "edit")):
        return
    entry, store, _ = res
    try:
        await store.async_remove_med(msg["med"])
    except InvalidLog as err:
        connection.send_error(msg["id"], "invalid", str(err))
        return
    _changed(hass, entry.entry_id)
    connection.send_result(msg["id"])


TREATMENT_FIELDS = {
    vol.Optional("treatment_type"): str,   # stored as "type"; "type" is the WebSocket message type
    vol.Optional("protocol"): vol.Any(None, str),
    vol.Optional("start"): str,
    vol.Optional("end"): vol.Any(None, str),
    vol.Optional("test_date"): vol.Any(None, str),
    vol.Optional("embryo_day"): vol.Any(None, int),
    vol.Optional("outcome"): vol.Any(None, str),
    vol.Optional("note"): vol.Any(None, str),
}


@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/treatment_start", vol.Required("entry_id"): str, **TREATMENT_FIELDS,
})
@websocket_api.async_response
async def ws_treatment_start(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    if not (res := _resolve(hass, connection, msg, "edit")):
        return
    entry, store, _ = res
    fields = _treatment_fields(msg)
    try:
        t = await store.async_start_treatment(fields)
    except InvalidLog as err:
        connection.send_error(msg["id"], "invalid", str(err))
        return
    _changed(hass, entry.entry_id)
    connection.send_result(msg["id"], t)


@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/treatment_update", vol.Required("entry_id"): str, vol.Required("treatment_id"): str,
    **TREATMENT_FIELDS,
})
@websocket_api.async_response
async def ws_treatment_update(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    if not (res := _resolve(hass, connection, msg, "edit")):
        return
    entry, store, _ = res
    fields = _treatment_fields(msg)
    try:
        t = await store.async_update_treatment(msg["treatment_id"], fields)
    except InvalidLog as err:
        connection.send_error(msg["id"], "invalid", str(err))
        return
    _changed(hass, entry.entry_id)
    connection.send_result(msg["id"], t)


def _treatment_fields(msg: dict[str, Any]) -> dict[str, Any]:
    fields = {k: msg[k] for k in ("protocol", "start", "end", "test_date", "embryo_day", "outcome", "note") if k in msg}
    if "treatment_type" in msg:
        fields["type"] = msg["treatment_type"]
    return fields


@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/treatment_delete", vol.Required("entry_id"): str, vol.Required("treatment_id"): str,
})
@websocket_api.async_response
async def ws_treatment_delete(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    if not (res := _resolve(hass, connection, msg, "edit")):
        return
    entry, store, _ = res
    await store.async_delete_treatment(msg["treatment_id"])
    _changed(hass, entry.entry_id)
    connection.send_result(msg["id"])


@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/treatment_summary", vol.Required("entry_id"): str, vol.Optional("date"): str,
})
@websocket_api.async_response
async def ws_treatment_summary(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    if not (res := _resolve(hass, connection, msg)):
        return
    _, store, _ = res
    connection.send_result(msg["id"], tx.summary(store.treatments, store.days, store.catalogue(), _today(msg)))


# Notifications ----------------------------------------------------------------------------------

@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/schedules", vol.Required("entry_id"): str})
@websocket_api.async_response
async def ws_schedules(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Dose reminders, and the phones that can be notified (people who can see the tracker)."""
    if not (res := _resolve(hass, connection, msg, "edit")):
        return
    entry, store, _ = res
    schedules = [{k: v for k, v in s.items() if k != "token"} for s in store.schedules]
    connection.send_result(msg["id"], {"schedules": schedules, "targets": await async_targets(hass, entry),
                                       "owner_name": await _owner_name(hass, entry), "checkin": store.checkin})


async def _owner_name(hass: HomeAssistant, entry: ConfigEntry) -> str:
    user = await hass.auth.async_get_user(owner_of(entry))
    return (user.name if user else None) or "The owner"


@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/checkin_set",
    vol.Required("entry_id"): str,
    vol.Required("enabled"): bool,
    vol.Optional("time", default="12:00"): str,
    vol.Optional("targets", default=[]): [str],
    vol.Optional("skip_if_logged", default=True): bool,
    vol.Optional("message"): str,
    vol.Optional("open_path"): str,
})
@websocket_api.async_response
async def ws_checkin_set(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """The daily "How do you feel today?" reminder. Anyone who can log for the tracker can set it."""
    if not (res := _resolve(hass, connection, msg, "edit")):
        return
    entry, store, _ = res
    allowed = {t["service"] for t in await async_targets(hass, entry)}
    data = {k: msg[k] for k in ("enabled", "time", "targets", "skip_if_logged", "message", "open_path") if k in msg}
    try:
        cfg = await store.async_set_checkin({**store.checkin, **data}, allowed)
    except InvalidLog as err:
        connection.send_error(msg["id"], "invalid", str(err))
        return
    _reminders(hass, entry).async_reschedule()
    connection.send_result(msg["id"], cfg)


@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/schedule_set",
    vol.Required("entry_id"): str,
    vol.Optional("schedule_id"): vol.Any(None, str),
    vol.Required("med"): str,
    vol.Optional("dose"): vol.Any(None, vol.Coerce(float)),
    vol.Optional("unit"): vol.Any(None, str),
    vol.Required("time"): str,
    vol.Optional("start"): vol.Any(None, str),
    vol.Optional("end"): vol.Any(None, str),
    vol.Required("targets"): [str],
    vol.Optional("discreet", default=False): bool,
    vol.Optional("follow_up", default=True): bool,
    vol.Optional("enabled", default=True): bool,
})
@websocket_api.async_response
async def ws_schedule_set(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    if not (res := _resolve(hass, connection, msg, "edit")):
        return
    entry, store, _ = res
    allowed = {t["service"] for t in await async_targets(hass, entry)}
    data = {k: v for k, v in msg.items() if k not in ("type", "entry_id", "id", "schedule_id")}
    data["id"] = msg.get("schedule_id")
    try:
        sched = await store.async_set_schedule(data, allowed, connection.user.id)
    except InvalidLog as err:
        connection.send_error(msg["id"], "invalid", str(err))
        return
    _reminders(hass, entry).async_reschedule()
    _changed(hass, entry.entry_id)
    connection.send_result(msg["id"], {k: v for k, v in sched.items() if k != "token"})


@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/schedule_remove", vol.Required("entry_id"): str, vol.Required("schedule_id"): str,
})
@websocket_api.async_response
async def ws_schedule_remove(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    if not (res := _resolve(hass, connection, msg, "edit")):
        return
    entry, store, _ = res
    await store.async_remove_schedule(msg["schedule_id"])
    _reminders(hass, entry).async_reschedule()
    _changed(hass, entry.entry_id)
    connection.send_result(msg["id"])


@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/notify_test",
    vol.Required("entry_id"): str,
    vol.Optional("schedule_id"): str,   # a dose reminder
    vol.Optional("checkin"): bool,      # the daily check-in; with neither, the phase notification (owner only)
})
@websocket_api.async_response
async def ws_notify_test(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    need = "edit" if msg.get("schedule_id") or msg.get("checkin") else "owner"
    if not (res := _resolve(hass, connection, msg, need)):
        return
    entry, store, _ = res
    reminders = _reminders(hass, entry)
    if msg.get("schedule_id"):
        sched = next((s for s in store.schedules if s["id"] == msg["schedule_id"]), None)
        if not sched:
            connection.send_error(msg["id"], "not_found", "No such reminder")
            return
        sent = await reminders.async_send(sched, dt_util.now().date(), test=True)
    elif msg.get("checkin"):
        sent = await reminders.async_send_checkin(store.checkin, test=True)
    else:
        _, status = reminders.current_phase(dt_util.now().date())
        sent = await reminders.async_send_phase(status, reminders.phase_settings(), test=True)
    connection.send_result(msg["id"], {"sent": sent})


COMMANDS = (
    ws_trackers, ws_categories, ws_overview, ws_days, ws_calendar, ws_set_day, ws_tag_add, ws_tag_remove,
    ws_analysis, ws_import, ws_settings_set, ws_sharing, ws_sharing_set, ws_subscribe, ws_layout_set,
    ws_treatment_info, ws_dose_add, ws_dose_remove, ws_med_add, ws_med_remove, ws_treatment_start,
    ws_treatment_update, ws_treatment_delete, ws_treatment_summary, ws_schedules, ws_schedule_set,
    ws_schedule_remove, ws_notify_test, ws_checkin_set,
)


@callback
def async_register_api(hass: HomeAssistant) -> None:
    for command in COMMANDS:
        websocket_api.async_register_command(hass, command)
