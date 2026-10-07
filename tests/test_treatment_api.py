"""Treatment logging, dose reminders and phase notifications over the API."""
from datetime import timedelta

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.clue_cycle.const import DOMAIN
from homeassistant.core import Context, HomeAssistant, ServiceCall
from homeassistant.util import dt as dt_util

from .test_api import _setup, _ws


def _fake_phone(hass: HomeAssistant, user_id: str, name: str = "Test phone") -> list[ServiceCall]:
    """A companion-app registration plus a notify service that records what it was sent."""
    MockConfigEntry(domain="mobile_app", title=name, data={"user_id": user_id, "device_name": name}).add_to_hass(hass)
    calls: list[ServiceCall] = []

    async def _record(call: ServiceCall) -> None:
        calls.append(call)

    hass.services.async_register("notify", "mobile_app_test_phone", _record)
    return calls


async def test_doses_results_and_a_treatment_cycle(hass, hass_ws_client, hass_admin_user):
    entry = await _setup(hass, hass_admin_user.id)
    client = await hass_ws_client(hass)
    eid = entry.entry_id
    info = await _ws(client, type=f"{DOMAIN}/treatment_info", entry_id=eid)
    assert any(m["id"] == "gonal_f" for m in info["result"]["meds"])
    r = await _ws(client, type=f"{DOMAIN}/med_add", entry_id=eid, name="Study drug", kind="stim", unit="IU")
    custom = r["result"]["id"]
    r = await _ws(client, type=f"{DOMAIN}/treatment_start", entry_id=eid, treatment_type="ivf", start="2026-03-01",
                  protocol="antagonist")
    assert r["success"], r
    tid = r["result"]["id"]
    clash = await _ws(client, type=f"{DOMAIN}/treatment_start", entry_id=eid, start="2026-03-10")
    assert not clash["success"] and "overlaps" in clash["error"]["message"]
    for day in ("2026-03-03", "2026-03-04"):
        r = await _ws(client, type=f"{DOMAIN}/dose_add", entry_id=eid, date=day, med="gonal_f", dose=150, time="19:00")
        assert r["success"] and r["result"]["log"]["meds"][0]["dose"] == 150
    r = await _ws(client, type=f"{DOMAIN}/dose_add", entry_id=eid, date="2026-03-04", med=custom, dose=75)
    dose_id = r["result"]["log"]["meds"][1]["id"]
    bad = await _ws(client, type=f"{DOMAIN}/dose_add", entry_id=eid, date="2026-03-04", med="nope")
    assert not bad["success"]
    r = await _ws(client, type=f"{DOMAIN}/set_day", entry_id=eid, date="2026-03-04", changes={"results": {"follicles": 8}})
    r = await _ws(client, type=f"{DOMAIN}/set_day", entry_id=eid, date="2026-03-04", changes={"results": {"lining_mm": 7.5}})
    assert r["result"]["log"]["results"] == {"follicles": 8, "lining_mm": 7.5}
    r = await _ws(client, type=f"{DOMAIN}/dose_remove", entry_id=eid, date="2026-03-04", dose_id=dose_id)
    assert len(r["result"]["log"]["meds"]) == 1
    ov = await _ws(client, type=f"{DOMAIN}/overview", entry_id=eid, date="2026-03-05")
    assert ov["result"]["treatment"]["headline"] == "Stim day 3"
    r = await _ws(client, type=f"{DOMAIN}/treatment_update", entry_id=eid, treatment_id=tid, end="2026-03-20", outcome="cancelled")
    assert r["result"]["outcome"] == "cancelled"
    s = await _ws(client, type=f"{DOMAIN}/treatment_summary", entry_id=eid, date="2026-03-25")
    assert s["result"][0]["medicines"][0]["totals"] == {"IU": 300}
    ov = await _ws(client, type=f"{DOMAIN}/overview", entry_id=eid, date="2026-03-25")
    assert ov["result"]["treatment"] is None


async def test_viewers_cannot_log_treatment(hass, hass_ws_client, hass_admin_user, hass_read_only_user,
                                            hass_read_only_access_token):
    entry = await _setup(hass, hass_admin_user.id, sharing={hass_read_only_user.id: "view"})
    other = await hass_ws_client(hass, hass_read_only_access_token)
    r = await _ws(other, type=f"{DOMAIN}/dose_add", entry_id=entry.entry_id, date="2026-03-03", med="gonal_f")
    assert r["error"]["code"] == "unauthorized"
    r = await _ws(other, type=f"{DOMAIN}/schedules", entry_id=entry.entry_id)
    assert r["error"]["code"] == "unauthorized"


async def test_dose_reminder_done_button_logs_the_dose(hass, hass_ws_client, hass_admin_user):
    entry = await _setup(hass, hass_admin_user.id)
    calls = _fake_phone(hass, hass_admin_user.id)
    client = await hass_ws_client(hass)
    eid = entry.entry_id
    r = await _ws(client, type=f"{DOMAIN}/schedules", entry_id=eid)
    assert r["result"]["targets"][0]["service"] == "mobile_app_test_phone"
    none = await _ws(client, type=f"{DOMAIN}/schedule_set", entry_id=eid, med="gonal_f", time="19:00", targets=[])
    assert not none["success"]
    stranger = await _ws(client, type=f"{DOMAIN}/schedule_set", entry_id=eid, med="gonal_f", time="19:00",
                         targets=["mobile_app_someone_else"])
    assert not stranger["success"]
    r = await _ws(client, type=f"{DOMAIN}/schedule_set", entry_id=eid, med="gonal_f", dose=150, unit="IU",
                  time="19:00", start="2026-01-01", targets=["mobile_app_test_phone"])
    assert r["success"] and "token" not in r["result"]
    sid = r["result"]["id"]
    reminders = hass.data[DOMAIN][eid]["reminders"]
    store = hass.data[DOMAIN][eid]["store"]
    now = dt_util.now().replace(hour=19, minute=0, second=0, microsecond=0)
    await reminders._due(sid, now)
    await hass.async_block_till_done()
    assert len(calls) == 1
    sent = calls[0].data
    assert sent["title"] == "Gonal-f 150 IU"
    done = sent["data"]["actions"][0]["action"]
    assert done.startswith("CLUECYCLE_DONE_")
    hass.bus.async_fire("mobile_app_notification_action", {"action": done}, context=Context(user_id=hass_admin_user.id))
    await hass.async_block_till_done()
    day = now.date().isoformat()
    assert store.dose_logged(day, "gonal_f")
    assert calls[-1].data["message"] == "clear_notification"
    # Already logged, so the next firing that day stays quiet.
    before = len(calls)
    await reminders._due(sid, now)
    assert len(calls) == before
    # A forged action with the wrong token does nothing.
    hass.bus.async_fire("mobile_app_notification_action", {"action": "CLUECYCLE_DONE_deadbeef_20260101"})
    await hass.async_block_till_done()
    assert not store.dose_logged("2026-01-01", "gonal_f")


async def test_phase_notification_only_when_the_phase_changes(hass, hass_ws_client, hass_admin_user):
    entry = await _setup(hass, hass_admin_user.id)
    calls = _fake_phone(hass, hass_admin_user.id)
    client = await hass_ws_client(hass)
    eid = entry.entry_id
    first = dt_util.now().date() - timedelta(days=20)
    for i in range(4):
        await _ws(client, type=f"{DOMAIN}/set_day", entry_id=eid, date=(first + timedelta(days=i)).isoformat(),
                  changes={"period": "medium"})
    r = await _ws(client, type=f"{DOMAIN}/settings_set", entry_id=eid,
                  phase_notify={"enabled": True, "time": "08:00", "targets": ["mobile_app_test_phone"]})
    assert r["success"] and r["result"]["phase_notify"]["enabled"]
    reminders = hass.data[DOMAIN][eid]["reminders"]
    store = hass.data[DOMAIN][eid]["store"]
    now = dt_util.now().replace(hour=8, minute=0)
    await reminders._phase_check(now)
    assert calls == []  # seeded on enabling, so nothing stale goes out
    # Pretend yesterday was a different phase: today's change is announced once.
    await store.async_set_notified("follicular", "2000-01-01")
    await reminders._phase_check(now)
    await reminders._phase_check(now)
    ov = await _ws(client, type=f"{DOMAIN}/overview", entry_id=eid)
    assert len(calls) == 1 and calls[0].data["title"] == ov["result"]["status"]["headline"]
    assert calls[0].data["message"] == ov["result"]["status"]["sub"]
    r = await _ws(client, type=f"{DOMAIN}/notify_test", entry_id=eid)
    assert r["result"]["sent"] == 1 and calls[-1].data["title"].startswith("Test: ")
