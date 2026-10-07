"""Optional on/off sensors: on a period today, in the fertile window today."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import CycleEntity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([PeriodSensor(hass, entry, "on_period"), FertileSensor(hass, entry, "fertile_window")])


class PeriodSensor(CycleEntity, BinarySensorEntity):
    _attr_icon = "mdi:water"

    @property
    def is_on(self) -> bool:
        pred, _, _ = self.snapshot()
        return pred.phase == "period"


class FertileSensor(CycleEntity, BinarySensorEntity):
    _attr_icon = "mdi:egg-outline"

    @property
    def is_on(self) -> bool:
        pred, _, _ = self.snapshot()
        return pred.phase in ("fertile", "fertile_peak", "ovulation")
