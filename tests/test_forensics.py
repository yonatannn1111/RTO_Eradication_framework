"""Snapshot format and hash validation (no PLC needed)."""
import hashlib
import json


def test_hash_is_deterministic():
    payload = {
        "timestamp": "2026-09-28 10:00:00",
        "plc_ip": "127.0.0.1",
        "areas": {"DB1": [0, 1, 2], "DB2": [3, 4, 5], "Merker": [0]},
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    h1 = hashlib.sha256(canonical.encode()).hexdigest()
    h2 = hashlib.sha256(canonical.encode()).hexdigest()
    assert h1 == h2


def test_diff_detects_change():
    from modules.forensics import diff
    a = {"areas": {"DB1": [0, 0, 0], "DB2": [0, 0, 0], "Merker": [0]}}
    b = {"areas": {"DB1": [0, 9, 0], "DB2": [0, 0, 0], "Merker": [0]}}
    result = diff(a, b)
    assert result["areas"]["DB1"]["count"] == 1
    assert result["areas"]["DB1"]["changes"][0]["offset"] == 1
