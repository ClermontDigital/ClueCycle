"""Setup, the WebSocket API, and who can see and change what."""
from datetime import date, timedelta

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.clue_cycle.access import CONF_EXPOSE, CONF_OWNER, CONF_SHARING
from custom_components.clue_cycle.const import DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component


async def _setup(hass: HomeAssistant, owner: str, sharing=None, expose=False) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, title="Alex", unique_id=owner,
        data={"name": "Alex", CONF_OWNER: owner},
        options={"goal": "conceive", "cycle_length": 28, "period_length": 5, "luteal_length": 14,
                 CONF_SHARING: sharing or {}, CONF_EXPOSE: expose},
    )
    entry.add_to_hass(hass)
    assert await async_setup_component(hass, "http", {})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _ws(client, **msg):
    await client.send_json_auto_id(msg)
    return await client.receive_json()


async def test_owner_logs_and_reads(hass, hass_ws_client, hass_admin_user):
    entry = await _setup(hass, hass_admin_user.id)
    client = await hass_ws_client(hass)
    trackers = await _ws(client, type=f"{DOMAIN}/trackers")
    assert trackers["result"] == [{"entry_id": entry.entry_id, "name": "Alex", "role": "owner", "owner": hass_admin_user.id}]

    today = date.today()
    start = today - timedelta(days=3)
    for i in range(3):
        r = await _ws(client, type=f"{DOMAIN}/set_day", entry_id=entry.entry_id,
                      date=(start + timedelta(days=i)).isoformat(), changes={"period": "medium", "mind": ["calm"]})
        assert r["success"], r
    ov = await _ws(client, type=f"{DOMAIN}/overview", entry_id=entry.entry_id, date=today.isoformat())
    assert ov["result"]["prediction"]["cycle_day"] == 4
    assert ov["result"]["tracker"]["role"] == "owner"

    days = await _ws(client, type=f"{DOMAIN}/days", entry_id=entry.entry_id, start=start.isoformat(), end=today.isoformat())
    log = days["result"][start.isoformat()]
    assert log["period"] == "medium" and log["updated_by"] == hass_admin_user.id

    # Clearing a value removes it; an empty day disappears.
    await _ws(client, type=f"{DOMAIN}/set_day", entry_id=entry.entry_id, date=start.isoformat(),
              changes={"period": None, "mind": []})
    days = await _ws(client, type=f"{DOMAIN}/days", entry_id=entry.entry_id, start=start.isoformat(), end=start.isoformat())
    assert days["result"] == {}


async def test_rejects_bad_values(hass, hass_ws_client, hass_admin_user):
    entry = await _setup(hass, hass_admin_user.id)
    client = await hass_ws_client(hass)
    r = await _ws(client, type=f"{DOMAIN}/set_day", entry_id=entry.entry_id, date="2026-10-07", changes={"period": "gushing"})
    assert not r["success"] and r["error"]["code"] == "invalid"
    r = await _ws(client, type=f"{DOMAIN}/set_day", entry_id=entry.entry_id, date="2026-10-07", changes={"tags": ["nope"]})
    assert not r["success"]
    r = await _ws(client, type=f"{DOMAIN}/tag_add", entry_id=entry.entry_id, name="Back pain")
    assert r["result"] == ["Back pain"]
    r = await _ws(client, type=f"{DOMAIN}/set_day", entry_id=entry.entry_id, date="2026-10-07", changes={"tags": ["back pain"]})
    assert r["result"]["log"]["tags"] == ["Back pain"]


async def test_private_by_default(hass, hass_ws_client, hass_admin_user, hass_read_only_user, hass_read_only_access_token):
    entry = await _setup(hass, hass_admin_user.id)
    other = await hass_ws_client(hass, hass_read_only_access_token)
    assert (await _ws(other, type=f"{DOMAIN}/trackers"))["result"] == []
    r = await _ws(other, type=f"{DOMAIN}/overview", entry_id=entry.entry_id)
    assert not r["success"] and r["error"]["code"] == "not_found"


async def test_shared_view_cannot_edit_or_reshare(hass, hass_ws_client, hass_admin_user, hass_read_only_user,
                                                  hass_read_only_access_token):
    entry = await _setup(hass, hass_admin_user.id, sharing={hass_read_only_user.id: "view"})
    other = await hass_ws_client(hass, hass_read_only_access_token)
    assert (await _ws(other, type=f"{DOMAIN}/trackers"))["result"][0]["role"] == "view"
    assert (await _ws(other, type=f"{DOMAIN}/overview", entry_id=entry.entry_id))["success"]
    r = await _ws(other, type=f"{DOMAIN}/set_day", entry_id=entry.entry_id, date="2026-10-07", changes={"period": "light"})
    assert r["error"]["code"] == "unauthorized"
    r = await _ws(other, type=f"{DOMAIN}/sharing_set", entry_id=entry.entry_id, sharing={})
    assert r["error"]["code"] == "unauthorized"


async def test_owner_shares_for_editing_then_revokes(hass, hass_ws_client, hass_admin_user, hass_read_only_user,
                                                     hass_read_only_access_token):
    entry = await _setup(hass, hass_admin_user.id)
    owner = await hass_ws_client(hass)
    other = await hass_ws_client(hass, hass_read_only_access_token)
    r = await _ws(owner, type=f"{DOMAIN}/sharing", entry_id=entry.entry_id)
    assert hass_read_only_user.id in [u["id"] for u in r["result"]["users"]]
    await _ws(owner, type=f"{DOMAIN}/sharing_set", entry_id=entry.entry_id, sharing={hass_read_only_user.id: "edit"})
    r = await _ws(other, type=f"{DOMAIN}/set_day", entry_id=entry.entry_id, date="2026-10-07", changes={"period": "light"})
    assert r["success"] and r["result"]["log"]["updated_by"] == hass_read_only_user.id
    await _ws(owner, type=f"{DOMAIN}/sharing_set", entry_id=entry.entry_id, sharing={})
    assert (await _ws(other, type=f"{DOMAIN}/trackers"))["result"] == []


async def test_live_updates_reach_other_viewers(hass, hass_ws_client, hass_admin_user, hass_read_only_user,
                                                hass_read_only_access_token):
    entry = await _setup(hass, hass_admin_user.id, sharing={hass_read_only_user.id: "view"})
    owner = await hass_ws_client(hass)
    other = await hass_ws_client(hass, hass_read_only_access_token)
    sub = await _ws(other, type=f"{DOMAIN}/subscribe", entry_id=entry.entry_id)
    assert sub["success"]
    await _ws(owner, type=f"{DOMAIN}/set_day", entry_id=entry.entry_id, date="2026-10-07", changes={"period": "light"})
    event = await other.receive_json()
    assert event["type"] == "event" and event["event"] == {"changed": True}


async def test_import_dry_run_then_real(hass, hass_ws_client, hass_admin_user):
    import base64, json
    entry = await _setup(hass, hass_admin_user.id)
    client = await hass_ws_client(hass)
    raw = json.dumps({"data": [{"day": "2026-09-13", "period": "heavy", "tags": ["TIRED"]},
                               {"day": "2026-09-14", "period": "medium"}]})
    content = base64.b64encode(raw.encode()).decode()
    r = await _ws(client, type=f"{DOMAIN}/import", entry_id=entry.entry_id, content=content, dry_run=True)
    assert r["result"]["days"] == 2 and r["result"]["dry_run"]
    days = await _ws(client, type=f"{DOMAIN}/days", entry_id=entry.entry_id, start="2026-09-01", end="2026-09-30")
    assert days["result"] == {}
    r = await _ws(client, type=f"{DOMAIN}/import", entry_id=entry.entry_id, content=content)
    assert r["result"]["new_days"] == 2
    ov = await _ws(client, type=f"{DOMAIN}/overview", entry_id=entry.entry_id, date="2026-09-20")
    assert ov["result"]["tags"] == ["TIRED"] and ov["result"]["prediction"]["cycle_day"] == 8


async def test_sensors_only_when_owner_turns_them_on(hass, hass_admin_user):
    await _setup(hass, hass_admin_user.id)
    assert not [s for s in hass.states.async_entity_ids() if "alex" in s]


async def test_sensors_when_exposed(hass, hass_admin_user):
    await _setup(hass, hass_admin_user.id, expose=True)
    ids = hass.states.async_entity_ids()
    assert "sensor.alex_cycle_cycle_day" in ids
    assert "binary_sensor.alex_cycle_on_period" in ids
    assert "calendar.alex_cycle_cycle" in ids


async def test_config_flow_creates_private_tracker(hass, hass_admin_user):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {
        "name": "Alex", "owner": hass_admin_user.id, "goal": "conceive", "cycle_length": 32, "period_length": 6})
    assert result["type"] == "create_entry"
    assert result["data"][CONF_OWNER] == hass_admin_user.id
    assert result["options"][CONF_SHARING] == {}
