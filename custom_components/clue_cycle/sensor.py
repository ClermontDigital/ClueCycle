"""Optional sensors, for automations such as "period expected tomorrow" reminders."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import engine
from .entity import CycleEntity

PHASES = ["period", "follicular", "fertile", "fertile_peak", "ovulation", "luteal", "pms", "due", "late", "unknown", "treatment"]


@dataclass(frozen=True)
class SensorSpec:
    key: str
    value: Callable[[engine.Prediction, engine.Stats], Any]
    device_class: SensorDeviceClass | None = None
    unit: str | None = None
    icon: str | None = None
    options: list[str] | None = None


SPECS = [
    SensorSpec("cycle_day", lambda p, s: p.cycle_day, icon="mdi:calendar-today"),
    SensorSpec("phase", lambda p, s: p.phase, SensorDeviceClass.ENUM, options=PHASES, icon="mdi:circle-slice-5"),
    SensorSpec("next_period", lambda p, s: p.next_period, SensorDeviceClass.DATE, icon="mdi:water"),
    SensorSpec("days_until_period", lambda p, s: p.days_until_period, unit=UnitOfTime.DAYS, icon="mdi:calendar-clock"),
    SensorSpec("ovulation", lambda p, s: p.ovulation, SensorDeviceClass.DATE, icon="mdi:egg-outline"),
    SensorSpec("fertile_window_start", lambda p, s: p.fertile_start, SensorDeviceClass.DATE, icon="mdi:calendar-start"),
    SensorSpec("fertile_window_end", lambda p, s: p.fertile_end, SensorDeviceClass.DATE, icon="mdi:calendar-end"),
    SensorSpec("cycle_length", lambda p, s: s.cycle_length, unit=UnitOfTime.DAYS, icon="mdi:sync"),
    SensorSpec("period_length", lambda p, s: s.period_length, unit=UnitOfTime.DAYS, icon="mdi:water-outline"),
    SensorSpec("cycle_variation", lambda p, s: s.variation, unit=UnitOfTime.DAYS, icon="mdi:chart-bell-curve"),
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities(CycleSensor(hass, entry, spec) for spec in SPECS)


class CycleSensor(CycleEntity, SensorEntity):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, spec: SensorSpec) -> None:
        super().__init__(hass, entry, spec.key)
        self._spec = spec
        self._attr_device_class = spec.device_class
        self._attr_native_unit_of_measurement = spec.unit
        self._attr_icon = spec.icon
        if spec.options:
            self._attr_options = spec.options

    @property
    def native_value(self) -> Any:
        pred, st, _ = self.snapshot()
        return self._spec.value(pred, st)
