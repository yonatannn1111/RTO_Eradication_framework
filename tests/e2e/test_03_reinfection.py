"""
Test 3 — Reinfection after restoration.

Simulates an attacker that re-corrupts the PLC after every restore,
and verifies the orchestrator handles multiple cycles.
"""
import asyncio
from unittest.mock import patch, MagicMock

import pytest

from modules.orchestrator.events_db import EventsDB
from modules.orchestrator.full_orchestrator import (
    OrchestratorConfig, PLCConfig, incident_response_cycle,
)


@pytest.mark.asyncio
async def test_reinfection_triggers_second_cycle(tmp_path, tmp_snapshot):
    """
    Cycle 1 restores the PLC. Then a second alert (reinfection) triggers
    cycle 2, which also restores. Both cycles log cleanly.
    """
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

        # first infection
        alert1 = {"plc_id": "plc_a", "detected_at": "x",
                  "changes": [{"register": 1, "baseline": 500, "observed": 12000}]}
        r1 = await incident_response_cycle(cfg.plcs[0], alert1, cfg, db)

        # attacker reinfects
        alert2 = {"plc_id": "plc_a", "detected_at": "x+5s",
                  "changes": [{"register": 1, "baseline": 500, "observed": 12000}]}
        r2 = await incident_response_cycle(cfg.plcs[0], alert2, cfg, db)

    assert r1["outcome"] == "restored"
    assert r2["outcome"] == "restored"

    # DB should contain 2 complete cycles
    rows = db.query(plc_id="plc_a")
    db.close()

    completes = [r for r in rows if r["event_type"] == "cycle_complete"]
    assert len(completes) == 2
    alerts = [r for r in rows if r["event_type"] == "alert_received"]
    assert len(alerts) == 2
    restores = [r for r in rows if r["event_type"] == "restore_end"]
    assert len(restores) == 2
    assert all(r["ok"] is True for r in restores)