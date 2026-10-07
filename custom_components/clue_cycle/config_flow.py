"""Config flow: one tracker per person, owned by that person's Home Assistant user."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector

from .access import CONF_OWNER, CONF_SHARING
from .reminders import OWNER_PHONES
from .storage import InvalidLog
from .const import (
    CONF_CYCLE_LENGTH, CONF_GOAL, CONF_LUTEAL_LENGTH, CONF_NAME, CONF_PERIOD_LENGTH, DEFAULT_CYCLE_LENGTH,
    CONF_PHASE_NOTIFY, DEFAULT_LUTEAL_LENGTH, DEFAULT_PERIOD_LENGTH, DOMAIN, GOALS,
)


async def _user_options(hass) -> list[selector.SelectOptionDict]:
    users = [u for u in await hass.auth.async_get_users() if u.is_active and not u.system_generated]
    return [selector.SelectOptionDict(value=u.id, label=u.name or "Unnamed")
            for u in sorted(users, key=lambda u: (u.name or "").lower())]


def _number(minimum: int, maximum: int) -> selector.NumberSelector:
    return selector.NumberSelector(selector.NumberSelectorConfig(
        min=minimum, max=maximum, step=1, mode=selector.NumberSelectorMode.BOX, unit_of_measurement="days"))


def _goal() -> selector.SelectSelector:
    return selector.SelectSelector(selector.SelectSelectorConfig(options=GOALS, translation_key="goal"))


class ClueCycleConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        users = await _user_options(self.hass)
        if user_input is not None:
            owner = user_input[CONF_OWNER]
            await self.async_set_unique_id(owner)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=user_input[CONF_NAME].strip() or "Cycle",
                data={CONF_NAME: user_input[CONF_NAME].strip(), CONF_OWNER: owner},
                options={
                    CONF_GOAL: user_input[CONF_GOAL],
                    CONF_CYCLE_LENGTH: int(user_input[CONF_CYCLE_LENGTH]),
                    CONF_PERIOD_LENGTH: int(user_input[CONF_PERIOD_LENGTH]),
                    CONF_LUTEAL_LENGTH: DEFAULT_LUTEAL_LENGTH,
                    CONF_SHARING: {},  # private until the owner shares it
                },
            )
        schema = vol.Schema({
            vol.Required(CONF_NAME): str,
            vol.Required(CONF_OWNER): selector.SelectSelector(selector.SelectSelectorConfig(options=users)),
            vol.Required(CONF_GOAL, default="conceive"): _goal(),
            vol.Required(CONF_CYCLE_LENGTH, default=DEFAULT_CYCLE_LENGTH): _number(15, 60),
            vol.Required(CONF_PERIOD_LENGTH, default=DEFAULT_PERIOD_LENGTH): _number(1, 15),
        })
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return ClueCycleOptionsFlow()


# Admin options form fields (only the phase notification ends up in the entry's options).
CONF_NOTIFY_PHASE = "notify_phase"
CONF_NOTIFY_PHASE_TIME = "notify_phase_time"
CONF_NOTIFY_CHECKIN = "notify_checkin"
CONF_NOTIFY_CHECKIN_TIME = "notify_checkin_time"
CONF_OPEN_PATH = "open_path"


class ClueCycleOptionsFlow(OptionsFlow):
    """Admin settings. Sharing is deliberately not here: only the owner decides that, in the card.

    An admin can also switch on the owner's own notifications (cycle phase changes and the daily
    check-in). They only ever go to the owner's phones, so this doesn't show the admin any data.
    """

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        opts = self.config_entry.options
        data = self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id) or {}
        store = data.get("store")
        phase = dict(opts.get(CONF_PHASE_NOTIFY) or {})
        checkin = dict(store.checkin if store else {})
        if user_input is not None:
            hhmm = lambda v, d: (str(v or d))[:5]  # noqa: E731 - the time selector gives HH:MM:SS
            phase.update({"enabled": bool(user_input[CONF_NOTIFY_PHASE]), "time": hhmm(user_input.get(CONF_NOTIFY_PHASE_TIME), "08:00"),
                          "targets": phase.get("targets") or [OWNER_PHONES], "discreet": bool(phase.get("discreet", False))})
            if store:
                checkin.update({"enabled": bool(user_input[CONF_NOTIFY_CHECKIN]),
                                "time": hhmm(user_input.get(CONF_NOTIFY_CHECKIN_TIME), "12:00"),
                                "targets": checkin.get("targets") or [OWNER_PHONES],
                                "open_path": (user_input.get(CONF_OPEN_PATH) or "").strip()})
                try:
                    # Recipients already set were checked when they were chosen.
                    await store.async_set_checkin(checkin, set(checkin["targets"]))
                except InvalidLog as err:
                    return self.async_show_form(step_id="init", data_schema=self._schema(opts, phase, checkin),
                                                errors={"base": "invalid_path"}, description_placeholders={"error": str(err)})
            return self.async_create_entry(data={
                **opts,
                CONF_GOAL: user_input[CONF_GOAL],
                CONF_CYCLE_LENGTH: int(user_input[CONF_CYCLE_LENGTH]),
                CONF_PERIOD_LENGTH: int(user_input[CONF_PERIOD_LENGTH]),
                CONF_LUTEAL_LENGTH: int(user_input[CONF_LUTEAL_LENGTH]),
                CONF_PHASE_NOTIFY: phase,
            })
        return self.async_show_form(step_id="init", data_schema=self._schema(opts, phase, checkin))

    @staticmethod
    def _schema(opts: dict[str, Any], phase: dict[str, Any], checkin: dict[str, Any]) -> vol.Schema:
        return vol.Schema({
            vol.Required(CONF_GOAL, default=opts.get(CONF_GOAL, "conceive")): _goal(),
            vol.Required(CONF_CYCLE_LENGTH, default=opts.get(CONF_CYCLE_LENGTH, DEFAULT_CYCLE_LENGTH)): _number(15, 60),
            vol.Required(CONF_PERIOD_LENGTH, default=opts.get(CONF_PERIOD_LENGTH, DEFAULT_PERIOD_LENGTH)): _number(1, 15),
            vol.Required(CONF_LUTEAL_LENGTH, default=opts.get(CONF_LUTEAL_LENGTH, DEFAULT_LUTEAL_LENGTH)): _number(8, 20),
            vol.Required(CONF_NOTIFY_PHASE, default=bool(phase.get("enabled"))): bool,
            vol.Required(CONF_NOTIFY_PHASE_TIME, default=f"{phase.get('time', '08:00')}:00"): selector.TimeSelector(),
            vol.Required(CONF_NOTIFY_CHECKIN, default=bool(checkin.get("enabled"))): bool,
            vol.Required(CONF_NOTIFY_CHECKIN_TIME, default=f"{checkin.get('time', '12:00')}:00"): selector.TimeSelector(),
            vol.Optional(CONF_OPEN_PATH, description={"suggested_value": checkin.get("open_path", "")}): str,
        })
