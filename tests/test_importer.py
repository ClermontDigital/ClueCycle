"""Clue export parsing."""
import base64
import io
import json
import zipfile

import pytest

from custom_components.clue_cycle.importer import ImportError_, PasswordRequired, parse_clue_export


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
    assert d["2026-08-15"]["pain"] == ["period_cramps", "headache"]
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


def test_current_clue_download_shapes():
    """The option names and shapes Clue's "Download my data" measurements.json uses (2026)."""
    records = [
        {"id": "a", "date": "2026-05-01", "type": "period", "value": {"option": "heavy"}},
        {"id": "b", "date": "2026-05-01", "type": "pain", "value": [{"option": "period_cramps"}, {"option": "breast_tenderness"}]},
        {"id": "c", "date": "2026-05-01", "type": "birth_control_pill", "value": {"option": "double_dose"}},
        {"id": "d", "date": "2026-05-01", "type": "pms", "value": {"option": "yes"}},
        {"id": "e", "date": "2026-05-01", "type": "sleep_duration", "value": {"minutes": 430}},
        {"id": "f", "date": "2026-05-01", "type": "energy", "value": [{"option": "tired"}]},
        {"id": "g", "date": "2026-05-02", "type": "partying", "value": [{"option": "big_night"}]},
        {"id": "h", "date": "2026-05-02", "type": "sleep_quality", "value": [{"option": "night_sweats"}]},
        {"id": "i", "date": "2026-05-02", "type": "stool", "value": [{"option": "constipation"}]},
        {"id": "j", "date": "2026-05-02", "type": "spotting", "value": [{"option": "brown"}]},
        {"id": "k", "date": "2026-05-02", "type": "appointments", "value": [{"option": "ob_gyn"}]},
        {"id": "l", "date": "2026-05-02", "type": "resting_heart_rate", "value": {"bpm": 60}, "source": "wearable_apple"},
        {"id": "m", "date": "2026-05-02", "type": "weight", "value": {"kilograms": 60.0}},
    ]
    out = parse_clue_export(json.dumps(records))
    d = out["days"]
    assert d["2026-05-01"] == {"period": "heavy", "pain": ["period_cramps", "breast_tenderness"],
                               "birth_control": ["pill_double"], "feelings": ["pms"], "sleep": "6_9",
                               "energy": ["tired"]}
    assert d["2026-05-02"] == {"party": ["big_night"], "sleep_quality": ["night_sweats"], "poop": ["constipation"],
                               "period": "spotting", "appointments": ["ob_gyn"]}
    assert out["unknown"] == {}
    assert out["skipped"] == {"resting_heart_rate": 1, "weight": 1}


# A tiny synthetic export zipped with `zip -P testpass`, the way Clue protects its download.
PROTECTED_ZIP = base64.b64decode("UEsDBBQACQAIAM+mR12UQFh+ZgAAAIsAAAARABwAbWVhc3VyZW1lbnRzLmpzb25VVAkAA+YkxmrmJMZqdXgLAAEE9QEAAAQAAAAALZO3etAd3+0PRM19gnrghqmWNIxSGJARviopK3A9Oz1pfTSRczsH0x4EgpLOuopmvOOjBiggLFEt8fTqPfRY3RQguc9ei0aE2A53u0oIcYFZU1rnmS5LxY3XNLRXjSwAwBbcSIrqUEsHCJRAWH5mAAAAiwAAAFBLAwQKAAkAAADPpkddQ7+mow4AAAACAAAAEwAcAGN5Y2xlX3NldHRpbmdzLmpzb25VVAkAA+YkxmrmJMZqdXgLAAEE9QEAAAQAAAAAiVxBb5zYI3SOcdgkaIhQSwcIQ7+mow4AAAACAAAAUEsBAh4DFAAJAAgAz6ZHXZRAWH5mAAAAiwAAABEAGAAAAAAAAQAAAKSBAAAAAG1lYXN1cmVtZW50cy5qc29uVVQFAAPmJMZqdXgLAAEE9QEAAAQAAAAAUEsBAh4DCgAJAAAAz6ZHXUO/pqMOAAAAAgAAABMAGAAAAAAAAQAAAKSBwQAAAGN5Y2xlX3NldHRpbmdzLmpzb25VVAUAA+Ykxmp1eAsAAQT1AQAABAAAAABQSwUGAAAAAAIAAgCwAAAALAEAAAAA")


def test_password_protected_zip():
    with pytest.raises(PasswordRequired):
        parse_clue_export(PROTECTED_ZIP)
    with pytest.raises(PasswordRequired):
        parse_clue_export(PROTECTED_ZIP, "wrong")
    out = parse_clue_export(PROTECTED_ZIP, "testpass")
    assert out["days"] == {"2026-09-13": {"period": "heavy"}, "2026-09-14": {"pain": ["period_cramps"]}}
