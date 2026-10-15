"""
Test 4 — Scheduler waits for safe window.

Verifies that when the scheduler says WAIT N, the orchestrator
sleeps before re-checking, rather than restoring immediately.
"""
import asyncio
from unittest.mock import patch, MagicMock

import pytest

from modules.orchestrator.events_db import EventsDB
from modules.orchestrator.full_orchestrator import (
    OrchestratorConfig, PLCConfig, incident_response_cycle,
)


@pytest.mark.asyncio
async def test_wait_verdict_sleeps_before_restoring(tmp_path, tmp_snapshot):
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

    # WAIT once, then NOW
    calls = {"n": 0}
    def fake_fetch(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"ok": True, "belts": {
                "plc_a": {"action": "WAIT", "minutes": 0,
                          "reason": "not yet"},
            }}
        return {"ok": True, "belts": {
            "plc_a": {"action": "NOW", "reason": "critical"},
        }}

    # capture the sleeps
    sleep_times = []
    real_sleep = asyncio.sleep

    async def fake_sleep(t):
        sleep_times.append(t)
        return await real_sleep(0.01)   # don't actually sleep long

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
               side_effect=fake_fetch), \
         patch("modules.orchestrator.full_orchestrator.asyncio.sleep",
               side_effect=fake_sleep):

        alert = {"plc_id": "plc_a", "detected_at": "x",
                 "changes": [{"register": 1, "baseline": 500, "observed": 12000}]}
        result = await incident_response_cycle(cfg.plcs[0], alert, cfg, db)

    assert result["outcome"] == "restored"

    # A sleep should have occurred (from the WAIT path)
    assert any(t > 0 for t in sleep_times), \
        f"expected a sleep, got {sleep_times}"

    # Both decisions should be in the DB
    rows = db.query(plc_id="plc_a")
    db.close()
    decisions = [r for r in rows if r["event_type"] == "safe_window_decision"]
    assert len(decisions) >= 2
    actions = [r["details"]["action"] for r in decisions]
    assert "WAIT" in actions
    assert "NOW" in actions