"""Clue export parsing."""
import io
import json
import zipfile

import pytest

from custom_components.clue_cycle.importer import ImportError_, parse_clue_export


def test_daily_records_format():
    raw = json.dumps({"data": [
        {"day": "2026-08-15T00:00:00Z", "period": "heavy", "pain": ["cramps", "headache"],
         "tags": ["BACK PAIN"], "mind": ["brain fog", "calm"]},
        {"day": "2026-08-16T00:00:00Z", "period": "very_heavy", "collection_method": ["menstrual cup"],
         "notes": "rough day", "unicorns": ["yes"]},
        {"day": "2026-08-20T00:00:00Z", "spotting": "light", "sleep": "6-9"},
    ]})
    out = parse_clue_export(raw)
    d = out["days"]
    assert d["2026-08-15"]["period"] == "heavy"
    assert d["2026-08-15"]["pain"] == ["cramps", "headache"]
    assert d["2026-08-15"]["mind"] == ["brain_fog", "calm"]
    assert d["2026-08-15"]["tags"] == ["BACK PAIN"]
    assert d["2026-08-16"]["period"] == "super_heavy"
    assert d["2026-08-16"]["collection"] == ["cup"]
    assert d["2026-08-16"]["note"] == "rough day"
    assert d["2026-08-20"]["period"] == "spotting" and d["2026-08-20"]["sleep"] == "6_9"
    assert out["tags"] == ["BACK PAIN"]
    assert out["unknown"] == {"unicorns": 1}
    assert out["range"] == ["2026-08-15", "2026-08-20"]


def test_measurements_format_in_a_zip():
    records = [
        {"date": "2026-09-13", "type": "period", "value": {"option": "medium"}},
        {"date": "2026-09-13", "type": "social life", "value": [{"option": "sociable"}]},
        {"date": "2026-09-14", "type": "sex", "value": {"option": "unprotected_sex"}},
        {"date": "2026-09-14", "type": "tags", "value": ["Seizure", "seizure"]},
    ]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("ClueExport/measurements.json", json.dumps(records))
    out = parse_clue_export(buf.getvalue())
    d = out["days"]
    assert d["2026-09-13"] == {"period": "medium", "social": ["sociable"]}
    assert d["2026-09-14"]["sex"] == ["unprotected"]
    assert d["2026-09-14"]["tags"] == ["Seizure"]


def test_rejects_non_clue_files():
    with pytest.raises(ImportError_):
        parse_clue_export(b"not json")
    with pytest.raises(ImportError_):
        parse_clue_export(json.dumps({"hello": 1}))
