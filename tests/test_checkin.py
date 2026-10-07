"""The daily check-in, "the owner's phones" as a recipient, and the admin notification switches."""
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.clue_cycle.const import DOMAIN
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.util import dt as dt_util

from .test_api import _setup, _ws


def _phone(hass: HomeAssistant, user_id: str, name: str, os_name: str = "iOS") -> list[ServiceCall]:
    MockConfigEntry(domain="mobile_app", title=name,
                    data={"user_id": user_id, "device_name": name, "os_name": os_name}).add_to_hass(hass)
    calls: list[ServiceCall] = []

    async def _record(call: ServiceCall) -> None:
        calls.append(call)

    hass.services.async_register("notify", f"mobile_app_{name.lower().replace(' ', '_')}", _record)
    return calls


async def test_checkin_goes_to_the_owners_phones_and_opens_track(hass, hass_ws_client, hass_admin_user):
    entry = await _setup(hass, hass_admin_user.id)
    phone = _phone(hass, hass_admin_user.id, "Owner phone")
    mac = _phone(hass, hass_admin_user.id, "Owner mac", os_name="macOS")
    client = await hass_ws_client(hass)
    r = await _ws(client, type=f"{DOMAIN}/checkin_set", entry_id=entry.entry_id, enabled=True, time="12:00",
                  targets=["owner"], open_path="/dashboard-cycle/cycle")
    assert r["success"] and r["result"]["targets"] == ["owner"]
    reminders = hass.data[DOMAIN][entry.entry_id]["reminders"]
    await reminders._checkin_due(dt_util.now().replace(hour=12, minute=0))
    assert len(phone) == 1 and not mac                       # phones, not Macs
    sent = phone[0].data
    assert sent["message"] == "How do you feel today?"
    assert sent["data"]["url"] == "/dashboard-cycle/cycle?cc_view=track" == sent["data"]["clickAction"]
    # A phone signed in after the reminder was set up is included too.
    later = _phone(hass, hass_admin_user.id, "New phone")
    await reminders._checkin_due(dt_util.now().replace(hour=12, minute=0))
    assert len(later) == 1


async def test_checkin_is_skipped_once_something_is_logged(hass, hass_ws_client, hass_admin_user):
    entry = await _setup(hass, hass_admin_user.id)
    phone = _phone(hass, hass_admin_user.id, "Owner phone")
    client = await hass_ws_client(hass)
    await _ws(client, type=f"{DOMAIN}/checkin_set", entry_id=entry.entry_id, enabled=True, targets=["owner"])
    await _ws(client, type=f"{DOMAIN}/set_day", entry_id=entry.entry_id, date=dt_util.now().date().isoformat(),
              changes={"feelings": ["happy"]})
    await hass.data[DOMAIN][entry.entry_id]["reminders"]._checkin_due(dt_util.now())
    assert phone == []


async def test_editors_can_set_it_viewers_cannot(hass, hass_ws_client, hass_admin_user, hass_read_only_user,
                                                 hass_read_only_access_token):
    entry = await _setup(hass, hass_admin_user.id, sharing={hass_read_only_user.id: "view"})
    viewer = await hass_ws_client(hass, hass_read_only_access_token)
    r = await _ws(viewer, type=f"{DOMAIN}/checkin_set", entry_id=entry.entry_id, enabled=True, targets=["owner"])
    assert r["error"]["code"] == "unauthorized"
    owner = await hass_ws_client(hass)
    r = await _ws(owner, type=f"{DOMAIN}/checkin_set", entry_id=entry.entry_id, enabled=True, targets=["mobile_app_strangers_phone"])
    assert not r["success"]


async def test_admin_can_switch_on_the_owners_notifications(hass, hass_admin_user):
    """For a tracker the admin can't see: notifications only ever go to the owner's own phones."""
    entry = await _setup(hass, "someone-else")
    r = await hass.config_entries.options.async_init(entry.entry_id)
    r = await hass.config_entries.options.async_configure(r["flow_id"], {
        "goal": "track", "cycle_length": 28, "period_length": 5, "luteal_length": 14,
        "notify_phase": True, "notify_phase_time": "08:00:00", "notify_checkin": True, "notify_checkin_time": "12:00:00",
        "open_path": "/lovelace/cycle"})
    assert r["type"] == "create_entry"
    await hass.async_block_till_done()
    assert entry.options["phase_notify"]["enabled"] and entry.options["phase_notify"]["targets"] == ["owner"]
    store = hass.data[DOMAIN][entry.entry_id]["store"]
    assert store.checkin["enabled"] and store.checkin["targets"] == ["owner"] and store.checkin["open_path"] == "/lovelace/cycle"
    assert store.notified.get("phase")   # seeded, so switching on doesn't announce the current phase
