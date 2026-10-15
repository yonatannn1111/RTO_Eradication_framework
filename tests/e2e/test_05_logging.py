"""
Test 5 — Every component logs properly.

Runs a single complete cycle and asserts the SQLite event log
contains the expected shape, ordering, and ok flags.
"""
import asyncio
import sqlite3
from unittest.mock import patch, MagicMock

import pytest

from modules.orchestrator.events_db import EventsDB
from modules.orchestrator.full_orchestrator import (
    OrchestratorConfig, PLCConfig, incident_response_cycle,
)


@pytest.mark.asyncio
async def test_all_events_logged_with_ok_flags(tmp_path, tmp_snapshot):
    cfg = OrchestratorConfig(
        plc_ip="127.0.0.1",
        safety_url="http://test:5003",
        output_dir=str(tmp_path),
        db_path=str(tmp_path / "events.db"),
        plcs=[PLCConfig(plc_id="plc_a",
                        trusted_snapshot=tmp_snapshot,
                        watch_registers={1: 500})],
    )
    db = EventsDB(cfg.db_path)

    def fake_fetch(*args, **kwargs):
        return {"ok": True, "belts": {
            "plc_a": {"action": "NOW", "reason": "test"},
        }}

    with patch("modules.forensics.capture_pre_eradication",
               return_value={"path": "pre.json", "sha256_hash": "a"}), \
         patch("modules.forensics.capture_post_eradication",
               return_value={"path": "post.json", "sha256_hash": "b"}), \
         patch("modules.forensics.restore_with_retry",
               return_value=(True, [MagicMock(ok=True)],
                             {"overall": "PASS"})), \
         patch("modules.forensics.validate",
               return_value=(True, {"overall": "PASS"})), \
         patch("modules.orchestrator.scheduler_connector.fetch_decisions",
               side_effect=fake_fetch):
        alert = {"plc_id": "plc_a", "detected_at": "x",
                 "changes": [{"register": 1, "baseline": 500, "observed": 12000}]}
        await incident_response_cycle(cfg.plcs[0], alert, cfg, db)

    db.close()

    # Direct SQLite inspection — bypass the wrapper
    conn = sqlite3.connect(cfg.db_path)
    rows = conn.execute(
        "SELECT event_type, ok FROM events WHERE plc_id='plc_a' ORDER BY id"
    ).fetchall()
    conn.close()

    types_in_order = [r[0] for r in rows]

    expected_order = [
        "alert_received",
        "snapshot_before",
        "safe_window_decision",
        "snapshot_final",
        "restore_start",
        "restore_end",
        "validate_result",
        "cycle_complete",
    ]
    assert types_in_order == expected_order, \
        f"unexpected order: {types_in_order}"

    # ok flag semantics
    ok_map = dict(rows)
    assert ok_map["snapshot_before"] == 1
    assert ok_map["snapshot_final"] == 1
    assert ok_map["restore_end"] == 1
    assert ok_map["validate_result"] == 1
    assert ok_map["alert_received"] is None
    assert ok_map["safe_window_decision"] is None
    assert ok_map["cycle_complete"] is None