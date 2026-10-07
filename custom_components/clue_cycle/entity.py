"""Shared base for the optional sensors (only created when the owner turns them on)."""
from __future__ import annotations

from datetime import date
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity
from homeassistant.util import dt as dt_util

from . import engine
from .api import settings_for
from .const import DOMAIN, SIGNAL_UPDATED


class CycleEntity(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, key: str) -> None:
        self.hass = hass
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"{entry.title} cycle",
            manufacturer="Clue Cycle (unofficial)",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def store(self):
        return self.hass.data[DOMAIN][self._entry.entry_id]["store"]

    def snapshot(self) -> tuple[engine.Prediction, engine.Stats, date]:
        today = dt_util.now().date()
        pred, st, _ = engine.predict(self.store.days, settings_for(self._entry), today)
        return pred, st, today

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(
            self.hass, SIGNAL_UPDATED.format(self._entry.entry_id), self._refresh))

    @callback
    def _refresh(self) -> None:
        self.async_write_ha_state()


def iso(value: Any) -> Any:
    return value.isoformat() if isinstance(value, date) else value
