"""A synthetic history shaped like a real one: ~32-day cycles, 6-day periods."""
from datetime import date, timedelta

FLOWS = ["heavy", "heavy", "medium", "medium", "light", "light"]
LENGTHS = [30, 32, 33, 29, 34, 32]  # average 31.7 -> 32, variation 5


def build(first=date(2026, 3, 6), lengths=LENGTHS, current_period=True):
    days, start = {}, first
    for length in lengths:
        for i, flow in enumerate(FLOWS):
            days[(start + timedelta(days=i)).isoformat()] = {"period": flow}
        start += timedelta(days=length)
    if current_period:
        for i, flow in enumerate(FLOWS):
            days[(start + timedelta(days=i)).isoformat()] = {"period": flow}
    return days, start  # start = first day of the current cycle
