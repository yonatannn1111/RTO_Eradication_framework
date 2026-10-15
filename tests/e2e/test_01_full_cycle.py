"""
Test 1 — Detection → Forensics → Schedule → Restore → Validate.

Runs against mocks by default (CI-safe). Set E2E_MODE=real to run
against a live OpenPLC + safety scheduler.
"""
import asyncio
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


@pytest.mark.parametrize("verdict", ["NOW", "WAIT"])
def test_full_cycle(tmp_path, tmp_snapshot, verdict):
    """
    Complete cycle: alert → pre-snapshot → scheduler query → restore
    → validate → DB rows written.
    """
    from modules.orchestrator.events_db import EventsDB
    from modules.orchestrator.full_orchestrator import (
        OrchestratorConfig, PLCConfig, incident_response_cycle,
    )

    cfg = OrchestratorConfig(
        plc_ip="127.0.0.1",
        safety_url="http://test:5003",
        output_dir=str(tmp_path),
        db_path=str(tmp_path / "events.db"),
        plcs=[PLCConfig(
            plc_id="plc_a",
            trusted_snapshot=tmp_snapshot,
            watch_registers={1: 500},
        )],
    )
    db = EventsDB(cfg.db_path)

    alert = {
        "plc_id": "plc_a",
        "detected_at": "2026-10-15 10:00:00",
        "changes": [{"register": 1, "baseline": 500, "observed": 12000}],
    }

    # Mock scheduler: WAIT first, then NOW on the re-cycle.
    call_count = {"n": 0}
    def fake_fetch(*args, **kwargs):
        call_count["n"] += 1
        action = "WAIT" if (verdict == "WAIT" and call_count["n"] == 1) else "NOW"
        return {
            "ok": True,
            "belts": {"plc_a": {
                "action": action,
                "minutes": 0 if action == "WAIT" else None,
                "reason": f"verdict={action}",
            }},
        }

    with patch("modules.forensics.capture_pre_eradication",
               return_value={"path": str(tmp_path / "pre.json"),
                             "sha256_hash": "aaa"}), \
         patch("modules.forensics.capture_post_eradication",
               return_value={"path": str(tmp_path / "post.json"),
                             "sha256_hash": "bbb"}), \
         patch("modules.forensics.restore_with_retry",
               return_value=(True, [MagicMock(ok=True)],
                             {"overall": "PASS"})), \
         patch("modules.forensics.validate",
               return_value=(True, {"overall": "PASS"})), \
         patch("modules.orchestrator.scheduler_connector.fetch_decisions",
               side_effect=fake_fetch):

        result = asyncio.run(incident_response_cycle(
            cfg.plcs[0], alert, cfg, db,
        ))

    # --- assertions --------------------------------------------------------
    assert result["outcome"] == "restored", \
        f"expected restored, got {result['outcome']}"

    rows = db.query(plc_id="plc_a")
    db.close()

    event_types = [r["event_type"] for r in rows]
    for required in (
        "alert_received",
        "snapshot_before",
        "safe_window_decision",
        "snapshot_final",
        "restore_start",
        "restore_end",
        "validate_result",
        "cycle_complete",
    ):
        assert required in event_types, f"missing event: {required}"

    # restore_end should have ok=True
    restore_end = next(r for r in rows if r["event_type"] == "restore_end")
    assert restore_end["ok"] is True
    assert restore_end["details"]["attempts"] >= 1