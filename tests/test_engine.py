"""The cycle maths."""
from datetime import date, timedelta

from custom_components.clue_cycle import engine
from tests.history import build

S = engine.Settings()


def test_periods_and_cycles():
    days, current = build()
    cyc = engine.cycles(days)
    assert len(cyc) == 7
    assert [c.length for c in cyc[:-1]] == [30, 32, 33, 29, 34, 32]
    assert cyc[-1].length is None and cyc[-1].start == current
    assert all(c.period.length == 6 for c in cyc)


def test_spotting_and_short_gaps():
    days = {
        "2026-01-01": {"period": "medium"},
        "2026-01-02": {"period": "heavy"},
        "2026-01-04": {"period": "light"},     # one skipped day: same period
        "2026-01-12": {"period": "spotting"},  # spotting never starts a cycle
        "2026-01-30": {"period": "medium"},
    }
    ps = engine.periods(days)
    assert [(p.start.isoformat(), p.length) for p in ps] == [("2026-01-01", 4), ("2026-01-30", 1)]


def test_stats_match_clue_style_numbers():
    days, _ = build()
    st = engine.stats(engine.cycles(days), S)
    assert st.cycle_length == 32
    assert st.variation == 5 and st.variation_typical
    assert st.period_length == 6 and st.period_typical
    assert st.typical_cycles == 6 and st.cycle_typical


def test_day_22_is_still_good_timing():
    days, current = build()
    today = current + timedelta(days=21)  # cycle day 22
    pred, st, _ = engine.predict(days, S, today)
    assert pred.cycle_day == 22
    assert pred.ovulation == current + timedelta(days=18)        # day 19
    assert pred.fertile_start == current + timedelta(days=10)    # day 11 (shortest 29 - 14 - 5)
    assert pred.fertile_end == current + timedelta(days=21)      # day 22 (longest 34 - 14 + 1)
    assert pred.phase == "fertile"
    msg = engine.status(pred, S, today, days)
    assert msg["headline"] == "Still good timing to try to conceive"
    assert pred.next_period == current + timedelta(days=32)


def test_phases_through_a_cycle():
    days, current = build()
    def phase(n):
        return engine.predict(days, S, current + timedelta(days=n - 1))[0].phase
    assert phase(1) == "period"
    assert phase(8) == "follicular"
    assert phase(18) == "fertile_peak"
    assert phase(19) == "ovulation"
    assert phase(25) == "luteal"
    assert phase(30) == "pms"
    assert phase(33) == "due"
    assert phase(35) == "late"


def test_late_status():
    days, current = build()
    today = current + timedelta(days=34)  # due on day 33, so 2 days late
    pred, _, _ = engine.predict(days, S, today)
    assert pred.late_days == 2
    assert engine.status(pred, S, today, days)["headline"] == "Period is 2 days late"


def test_track_goal_wording():
    days, current = build()
    today = current + timedelta(days=17)
    pred, _, _ = engine.predict(days, S, today)
    st = engine.status(pred, engine.Settings(goal="track"), today, days)
    assert st["headline"] == "Fertile window"


def test_no_history_falls_back_to_settings():
    pred, st, cyc = engine.predict({}, S, date(2026, 10, 7))
    assert pred.phase == "unknown" and cyc == [] and st.cycle_length == 28
    assert engine.status(pred, S, date(2026, 10, 7), {})["headline"] == "Track your period"


def test_ring_marks_period_fertile_ovulation_and_dots():
    days, current = build()
    days[(current + timedelta(days=3)).isoformat()]["mind"] = ["calm"]
    ov = engine.overview(days, S, current + timedelta(days=21))
    kinds = [d["kind"] for d in ov["ring"]]
    assert len(kinds) == 32
    assert kinds[:6] == ["period"] * 6
    assert kinds[18] == "ovulation" and kinds[17] == "fertile_peak" and kinds[10] == "fertile"
    assert "#F07B3F" in ov["ring"][3]["dots"]


def test_upcoming_predictions():
    days, current = build()
    ev = engine.upcoming(days, S, current + timedelta(days=5))
    periods = [e for e in ev if e["kind"] == "period"]
    assert periods[0]["start"] == (current + timedelta(days=32)).isoformat()
    assert len(periods) == 3


def test_calendar_marks_past_and_future():
    days, current = build()
    today = current + timedelta(days=21)
    cal = engine.calendar(days, S, today, current - timedelta(days=40), current + timedelta(days=70))
    assert cal[current.isoformat()]["kind"] == "period"
    assert cal[(current + timedelta(days=18)).isoformat()]["kind"] == "ovulation"
    assert cal[(current + timedelta(days=32)).isoformat()]["kind"] == "period_predicted"
    # last complete cycle (32 days) got an estimated ovulation 14 days before this cycle started
    assert cal[(current - timedelta(days=14)).isoformat()]["kind"] == "ovulation"
    assert cal[current.isoformat()]["logged"] is True


def test_tracking_gaps_are_left_out_of_the_stats():
    days, current = build()
    # Push the whole history back so there's a 300-day hole before the latest period.
    shifted = {}
    for key, log in days.items():
        d = date.fromisoformat(key)
        shifted[(d - timedelta(days=300) if d < current else d).isoformat()] = log
    cyc = engine.cycles(shifted)
    assert any(c.gap for c in cyc)
    st = engine.stats(cyc, S)
    assert st.cycle_length == 32 and st.cycles_used == 5
