"""Clue Cycle: a private, multi-user period and cycle tracker for Home Assistant.

Unofficial and not affiliated with Clue or BioWink GmbH.
"""
from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components import frontend
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from .access import CONF_EXPOSE
from .api import async_register_api
from .const import CARD_FILENAME, CARD_URL, DOMAIN, SIGNAL_UPDATED
from .reminders import Reminders
from .storage import CycleStore

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.CALENDAR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    hass.data.setdefault(DOMAIN, {})
    async_register_api(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    store = CycleStore(hass, entry.entry_id)
    await store.async_load()
    expose = bool(entry.options.get(CONF_EXPOSE, False))
    reminders = Reminders(hass, entry, store)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {"store": store, "expose": expose, "reminders": reminders}
    reminders.async_start()
    entry.async_on_unload(reminders.async_stop)

    @callback
    def _midnight(_now) -> None:
        # Cycle day, phase and countdowns change at midnight even when nothing is logged.
        async_dispatcher_send(hass, SIGNAL_UPDATED.format(entry.entry_id))

    entry.async_on_unload(async_track_time_change(hass, _midnight, hour=0, minute=0, second=5))
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    if expose:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    try:
        await _async_setup_frontend(hass)
    except Exception:  # noqa: BLE001 - the tracker works without the card being auto-registered
        _LOGGER.warning("Clue Cycle: card setup failed", exc_info=True)
    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Settings changes just refresh; turning sensors on or off needs a reload (api.py schedules it)."""
    async_dispatcher_send(hass, SIGNAL_UPDATED.format(entry.entry_id))


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    ok = True
    if data.get("expose"):
        ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Deleting the tracker deletes its data too."""
    store = CycleStore(hass, entry.entry_id)
    await store._store.async_remove()  # noqa: SLF001 - our own store


async def _async_setup_frontend(hass: HomeAssistant) -> None:
    """Serve the bundled card and make sure dashboards load it (once per HA run)."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get("_frontend"):
        return
    domain_data["_frontend"] = True

    card_path = Path(__file__).parent / "www" / CARD_FILENAME
    try:
        version = (await async_get_integration(hass, DOMAIN)).version
    except Exception:  # noqa: BLE001
        version = None
    url = f"{CARD_URL}?v={version}" if version else CARD_URL
    try:
        await hass.http.async_register_static_paths([StaticPathConfig(CARD_URL, str(card_path), False)])
    except Exception:  # noqa: BLE001 - already registered after a reload
        _LOGGER.debug("Clue Cycle: card path already registered")
    if not await _async_register_resource(hass, url):
        try:
            frontend.add_extra_js_url(hass, url)
        except Exception:  # noqa: BLE001 - frontend not loaded (tests, minimal installs)
            _LOGGER.warning("Clue Cycle: couldn't auto-load the card; add %s as a dashboard resource", CARD_URL)


async def _async_register_resource(hass: HomeAssistant, url: str) -> bool:
    """Add or refresh the Lovelace resource so storage-mode dashboards load the card."""
    try:
        from homeassistant.components.lovelace import LOVELACE_DATA

        lovelace = hass.data.get(LOVELACE_DATA)
        resources = getattr(lovelace, "resources", None)
        if resources is None or not hasattr(resources, "async_create_item"):
            return False
        if hasattr(resources, "loaded") and not resources.loaded:
            await resources.async_load()
        base = url.split("?")[0]
        for item in resources.async_items():
            existing = item.get("url", "")
            if existing.split("?")[0] == base:
                if existing != url:
                    await resources.async_update_item(item["id"], {"url": url})
                return True
        await resources.async_create_item({"res_type": "module", "url": url})
        return True
    except Exception:  # noqa: BLE001 - the card can still be added by hand
        _LOGGER.warning("Clue Cycle: couldn't register the card resource", exc_info=True)
        return False
