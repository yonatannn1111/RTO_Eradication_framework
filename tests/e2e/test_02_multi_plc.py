"""
Test 2 — Multiple PLCs handled in parallel.

Verifies that two PLC workers proceed concurrently, not sequentially.
"""
import asyncio
import time
from unittest.mock import patch, MagicMock

import pytest

from modules.orchestrator.events_db import EventsDB
from modules.orchestrator.full_orchestrator import (
    OrchestratorConfig, PLCConfig, incident_response_cycle,
)


@pytest.mark.asyncio
async def test_multiple_plcs_run_in_parallel(tmp_path, tmp_snapshot):
    """
    Run two cycles concurrently and verify total time is closer to
    the per-cycle time than twice that amount.
    """
    cfg = OrchestratorConfig(
        plc_ip="127.0.0.1",
        safety_url="http://test:5003",
        output_dir=str(tmp_path),
        db_path=str(tmp_path / "events.db"),
        plcs=[
            PLCConfig(plc_id="plc_a", trusted_snapshot=tmp_snapshot,
                      watch_registers={1: 500}),
            PLCConfig(plc_id="plc_b", trusted_snapshot=tmp_snapshot,
                      watch_registers={1: 500}),
        ],
    )
    db = EventsDB(cfg.db_path)

    def fake_fetch(*args, **kwargs):
        return {"ok": True, "belts": {
            "plc_a": {"action": "NOW", "reason": "test"},
            "plc_b": {"action": "NOW", "reason": "test"},
        }}

    # Slow down the restore slightly to simulate real work
    def slow_restore(*args, **kwargs):
        time.sleep(0.3)
        return True, [MagicMock(ok=True)], {"overall": "PASS"}

    with patch("modules.forensics.capture_pre_eradication",
               return_value={"path": "pre.json", "sha256_hash": "a"}), \
         patch("modules.forensics.capture_post_eradication",
               return_value={"path": "post.json", "sha256_hash": "b"}), \
         patch("modules.forensics.restore_with_retry",
               side_effect=slow_restore), \
         patch("modules.forensics.validate",
               return_value=(True, {"overall": "PASS"})), \
         patch("modules.orchestrator.scheduler_connector.fetch_decisions",
               side_effect=fake_fetch):

        alerts = [
            {"plc_id": "plc_a", "detected_at": "x",
             "changes": [{"register": 1, "baseline": 0, "observed": 1}]},
            {"plc_id": "plc_b", "detected_at": "x",
             "changes": [{"register": 1, "baseline": 0, "observed": 1}]},
        ]
        t0 = time.time()
        results = await asyncio.gather(*(
            incident_response_cycle(cfg.plcs[i], alerts[i], cfg, db)
            for i in range(2)
        ))
        elapsed = time.time() - t0

    # both should complete
    assert len(results) == 2
    assert all(r["outcome"] == "restored" for r in results)

    # Parallelism check: elapsed should be closer to 0.3s than 0.6s.
    assert elapsed < 0.55, f"cycles did not run in parallel (took {elapsed:.3f}s)"

    # Both PLCs should be in the DB
    a_rows = db.query(plc_id="plc_a")
    b_rows = db.query(plc_id="plc_b")
    db.close()
    assert len(a_rows) >= 3
    assert len(b_rows) >= 3