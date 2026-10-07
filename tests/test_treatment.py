"""Fertility treatment: timeline, ring, stats exclusion and the clinic summary."""
from datetime import date, timedelta

from custom_components.clue_cycle import engine
from custom_components.clue_cycle import treatment as tx
from tests.history import build

S = engine.Settings()
MEDS = tx.catalogue(None)
START = date(2026, 3, 1)


def ivf_days() -> dict:
    """A synthetic antagonist IVF cycle: stims days 3-12, trigger day 13, collection 15, day-5 transfer 20."""
    days = {}
    for i in range(2, 12):
        days[(START + timedelta(days=i)).isoformat()] = {"meds": [{"id": f"g{i}", "med": "gonal_f", "dose": 150, "unit": "IU", "time": "19:00"}]}
    days[(START + timedelta(days=12)).isoformat()] = {"meds": [{"id": "t", "med": "ovidrel", "dose": 250, "unit": "mcg", "time": "21:00"}]}
    days[(START + timedelta(days=14)).isoformat()] = {"treatment": ["egg_collection"], "results": {"eggs_collected": 11, "mature_eggs": 9}}
    days[(START + timedelta(days=19)).isoformat()] = {"treatment": ["fresh_transfer"], "results": {"embryos_transferred": 1}}
    return days


T = {"id": "x", "type": "ivf", "protocol": "antagonist", "start": START.isoformat(), "embryo_day": 5}


def at(n: int) -> dict:
    return tx.timeline(T, ivf_days(), MEDS, START + timedelta(days=n))


def test_timeline_follows_the_cycle():
    assert at(0)["phase"] == "preparation"
    assert at(7)["phase"] == "stimulation" and at(7)["headline"] == "Stim day 6"
    tl = at(13)
    assert tl["phase"] == "triggered" and tl["sub"] == "Egg collection booked 15 Mar"
    assert at(14)["phase"] == "awaiting_transfer" and at(14)["headline"] == "Egg collection day"
    assert at(19)["phase"] == "transfer"
    tl = at(24)
    assert tl["phase"] == "two_week_wait" and tl["headline"] == "5 days past transfer"
    assert tl["test_date"] == "2026-03-29" and tl["sub"] == "Blood test in 4 days"
    assert at(28)["phase"] == "test_day"
    assert at(30)["phase"] == "after_test"


def test_expected_collection_from_the_trigger():
    days = ivf_days()
    del days[(START + timedelta(days=14)).isoformat()]
    tl = tx.timeline(T, days, MEDS, START + timedelta(days=13))
    assert tl["expected_collection"] == "2026-03-15" and tl["sub"] == "Egg collection expected 15 Mar"


def test_running_treatment_replaces_natural_predictions():
    days = ivf_days()
    today = START + timedelta(days=24)
    ov = engine.overview(days, S, today, {"cycles": [T], "meds": MEDS})
    assert ov["prediction"]["phase"] == "treatment" and ov["prediction"]["next_period"] is None
    assert ov["status"]["headline"] == "5 days past transfer"
    kinds = {d["date"]: d["kind"] for d in ov["ring"]}
    assert kinds["2026-03-05"] == "stim" and kinds["2026-03-13"] == "trigger"
    assert kinds["2026-03-15"] == "collection" and kinds["2026-03-20"] == "transfer"
    assert kinds["2026-03-25"] == "tww" and kinds["2026-03-29"] == "test"
    assert engine.upcoming(days, S, today, tx={"cycles": [T], "meds": MEDS}) == []
    cal = engine.calendar(days, S, today, START, START + timedelta(days=40), {"cycles": [T], "meds": MEDS})
    assert cal["2026-03-06"]["kind"] == "stim" and cal["2026-03-29"]["kind"] == "test"


def test_treatment_cycles_are_left_out_of_the_averages():
    days, current = build()
    plain = engine.stats(engine.cycles(days), S)
    cyc = engine.cycles(days)
    # Treat the third cycle as an IVF cycle that ended when the next period came.
    t = {"id": "y", "type": "ivf", "start": (cyc[2].start + timedelta(days=1)).isoformat(),
         "end": (cyc[3].start - timedelta(days=1)).isoformat()}
    pred, st, marked = engine.predict(days, S, current + timedelta(days=3), {"cycles": [t], "meds": MEDS})
    assert [c.treatment for c in marked].count(True) == 1 and marked[2].treatment
    assert st.cycles_used == plain.cycles_used - 1
    assert pred.phase != "treatment"


def test_summary_totals_for_the_clinic():
    out = tx.summary([dict(T, end="2026-03-29", outcome="positive")], ivf_days(), MEDS, date(2026, 4, 2))
    s = out[0]
    gonal = next(m for m in s["medicines"] if m["name"] == "Gonal-f")
    assert gonal["days"] == 10 and gonal["totals"] == {"IU": 1500}
    assert s["stim_days"] == 10 and s["trigger"] == "2026-03-13" and s["phase"] == "ended"
    assert s["results"]["eggs_collected"] == [{"date": "2026-03-15", "value": 11}]
    assert {"date": "2026-03-20", "id": "fresh_transfer"} in s["procedures"]
