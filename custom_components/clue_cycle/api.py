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
from .access import (
    CONF_EXPOSE, CONF_SHARING, ROLE_OWNER, SHARE_LEVELS, can_edit, describe, owner_of, role_for, sharing_of,
)
from .categories import CATEGORIES, TAG_COLOR
from .const import (
    CONF_CYCLE_LENGTH, CONF_GOAL, CONF_LUTEAL_LENGTH, CONF_PERIOD_LENGTH, DOMAIN, GOALS, SIGNAL_UPDATED,
)
from .importer import ImportError_, parse_clue_export
from .storage import CycleStore, InvalidLog

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
    payload = engine.overview(store.days, settings, _today(msg))
    payload.update({
        "tracker": describe(entry, role),
        "settings": settings.__dict__,
        "tags": store.tags,
        "upcoming": engine.upcoming(store.days, settings, _today(msg)),
    })
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
    connection.send_result(msg["id"], engine.calendar(store.days, settings_for(entry), _today(msg), start, end))


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
    pred, st, cyc = engine.predict(store.days, settings, _today(msg))
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
        parsed = await hass.async_add_executor_job(parse_clue_export, raw)
    except ImportError_ as err:
        connection.send_error(msg["id"], "invalid", f"Not a Clue export this can read: {err}")
        return
    summary = {"range": parsed["range"], "days": len(parsed["days"]), "tags": len(parsed["tags"]),
               "unknown": parsed["unknown"], "dry_run": msg["dry_run"]}
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
})
@websocket_api.async_response
async def ws_settings_set(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    if not (res := _resolve(hass, connection, msg, "owner")):
        return
    entry, _, _ = res
    options = dict(entry.options)
    for key in (CONF_GOAL, CONF_CYCLE_LENGTH, CONF_PERIOD_LENGTH, CONF_LUTEAL_LENGTH):
        if key in msg:
            options[key] = msg[key]
    hass.config_entries.async_update_entry(entry, options=options)
    _changed(hass, entry.entry_id)
    connection.send_result(msg["id"], settings_for(entry).__dict__)


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


COMMANDS = (
    ws_trackers, ws_categories, ws_overview, ws_days, ws_calendar, ws_set_day, ws_tag_add, ws_tag_remove,
    ws_analysis, ws_import, ws_settings_set, ws_sharing, ws_sharing_set, ws_subscribe,
)


@callback
def async_register_api(hass: HomeAssistant) -> None:
    for command in COMMANDS:
        websocket_api.async_register_command(hass, command)
