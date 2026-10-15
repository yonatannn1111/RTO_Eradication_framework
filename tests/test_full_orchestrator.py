"""Full orchestrator tests — mocked, no PLC."""
import asyncio
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from modules.orchestrator.events_db import EventsDB
from modules.orchestrator.full_orchestrator import (
    OrchestratorConfig, PLCConfig, incident_response_cycle,
)


# ---------------------------------------------------------------------------
# DB tests
# ---------------------------------------------------------------------------

def test_db_writes_and_reads(tmp_path):
    db = EventsDB(tmp_path / "ev.db")
    db.log("plc_a", "alert_received", {"changes": [{"register": 1}]})
    db.log("plc_a", "restore_end", {"ok": True, "attempts": 1}, ok=True)
    rows = db.query(plc_id="plc_a")
    db.close()

    assert len(rows) == 2
    assert rows[0]["event_type"] == "restore_end"
    assert rows[0]["ok"] is True
    assert rows[1]["event_type"] == "alert_received"


def test_db_indexes_by_plc(tmp_path):
    db = EventsDB(tmp_path / "ev.db")
    for i in range(5):
        db.log("plc_a", "e", {"i": i})
    for i in range(3):
        db.log("plc_b", "e", {"i": i})
    a = db.query(plc_id="plc_a", limit=100)
    b = db.query(plc_id="plc_b", limit=100)
    db.close()
    assert len(a) == 5
    assert len(b) == 3


def test_db_filters_by_event_type(tmp_path):
    db = EventsDB(tmp_path / "ev.db")
    db.log("plc_a", "alert_received")
    db.log("plc_a", "restore_end", ok=True)
    db.log("plc_a", "validate_result", ok=True)
    rows = db.query(event_type="restore_end")
    db.close()
    assert len(rows) == 1
    assert rows[0]["event_type"] == "restore_end"


# ---------------------------------------------------------------------------
# Cycle tests
# ---------------------------------------------------------------------------

@pytest.fixture
def cfg(tmp_path):
    return OrchestratorConfig(
        plc_ip="127.0.0.1",
        safety_url="http://x:5003",
        output_dir=str(tmp_path),
        db_path=str(tmp_path / "ev.db"),
        plcs=[PLCConfig(
            plc_id="plc_a",
            trusted_snapshot="/tmp/trusted.json",
            watch_registers={1: 500},
        )],
    )


def _alert():
    return {
        "plc_id": "plc_a",
        "detected_at": "2026-10-15 10:00:00",
        "changes": [{"register": 1, "baseline": 500, "observed": 12000}],
    }


def test_cycle_executes_full_flow_on_now(cfg, tmp_path):
    db = EventsDB(cfg.db_path)

    with patch("modules.forensics.capture_pre_eradication",
               return_value={"path": "pre.json", "sha256_hash": "aaa"}), \
         patch("modules.forensics.capture_post_eradication",
               return_value={"path": "post.json", "sha256_hash": "bbb"}), \
         patch("modules.forensics.restore_with_retry",
               return_value=(True, [MagicMock(ok=True)], {"overall": "PASS"})), \
         patch("modules.forensics.validate",
               return_value=(True, {"overall": "PASS"})), \
         patch("modules.orchestrator.scheduler_connector.fetch_decisions",
               return_value={
                   "ok": True,
                   "belts": {"plc_a": {
                       "action": "NOW", "reason": "critical",
                       "minutes": None,
                   }},
               }):
        result = asyncio.run(incident_response_cycle(
            cfg.plcs[0], _alert(), cfg, db,
        ))

    db.close()
    assert result["outcome"] == "restored"


def test_cycle_handles_wait_verdict(cfg):
    db = EventsDB(cfg.db_path)
    calls = {"n": 0}

    def fake_decisions(*args, **kwargs):
        calls["n"] += 1
        action = "WAIT" if calls["n"] == 1 else "NOW"
        return {
            "ok": True,
            "belts": {"plc_a": {
                "action": action, "minutes": 0, "reason": "test",
            }},
        }

    with patch("modules.forensics.capture_pre_eradication",
               return_value={"path": "pre.json", "sha256_hash": "aaa"}), \
         patch("modules.forensics.capture_post_eradication",
               return_value={"path": "post.json", "sha256_hash": "bbb"}), \
         patch("modules.forensics.restore_with_retry",
               return_value=(True, [MagicMock(ok=True)], {"overall": "PASS"})), \
         patch("modules.forensics.validate",
               return_value=(True, {"overall": "PASS"})), \
         patch("modules.orchestrator.scheduler_connector.fetch_decisions",
               side_effect=fake_decisions):
        result = asyncio.run(incident_response_cycle(
            cfg.plcs[0], _alert(), cfg, db,
        ))

    db.close()
    assert result["outcome"] == "restored"
    # The WAIT path should have gone through the retry, so more than one
    # pre-snapshot should have been logged.
    rows = EventsDB(cfg.db_path).query(plc_id="plc_a")
    assert any(r["event_type"] == "safe_window_decision" for r in rows)


def test_cycle_handles_scheduler_failure(cfg):
    db = EventsDB(cfg.db_path)

    with patch("modules.forensics.capture_pre_eradication",
               return_value={"path": "pre.json", "sha256_hash": "aaa"}), \
         patch("modules.orchestrator.scheduler_connector.fetch_decisions",
               return_value={"ok": False, "error": "unreachable", "belts": {}}):
        result = asyncio.run(incident_response_cycle(
            cfg.plcs[0], _alert(), cfg, db,
        ))

    db.close()
    assert result["outcome"] == "scheduler_query_failed"


def test_cycle_logs_to_db(cfg):
    db = EventsDB(cfg.db_path)

    with patch("modules.forensics.capture_pre_eradication",
               return_value={"path": "pre.json", "sha256_hash": "aaa"}), \
         patch("modules.forensics.capture_post_eradication",
               return_value={"path": "post.json", "sha256_hash": "bbb"}), \
         patch("modules.forensics.restore_with_retry",
               return_value=(True, [MagicMock(ok=True)], {"overall": "PASS"})), \
         patch("modules.forensics.validate",
               return_value=(True, {"overall": "PASS"})), \
         patch("modules.orchestrator.scheduler_connector.fetch_decisions",
               return_value={
                   "ok": True,
                   "belts": {"plc_a": {"action": "NOW", "reason": "x"}},
               }):
        asyncio.run(incident_response_cycle(
            cfg.plcs[0], _alert(), cfg, db,
        ))

    types = {r["event_type"] for r in db.query(plc_id="plc_a")}
    db.close()

    expected = {
        "alert_received", "snapshot_before", "safe_window_decision",
        "snapshot_final", "restore_start", "restore_end",
        "validate_result", "cycle_complete",
    }
    assert expected.issubset(types)