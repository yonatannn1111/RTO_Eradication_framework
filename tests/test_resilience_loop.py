"""Reinfection resistance loop tests — mocked, no PLC."""
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from modules.orchestrator.resilience_loop import (
    ResilienceConfig, run_resilience_loop, CycleResult,
)


def _fake_change_event():
    from modules.forensics.watcher import ChangeEvent
    return ChangeEvent(
        detected_at="2026-10-15 10:00:00",
        elapsed_s=1.2,
        register=1,
        baseline=500,
        observed=12000,
        all_changes=[{"register": 1, "baseline": 500, "observed": 12000}],
    )


def _fake_pre(path: str):
    return {"path": path, "tag": "pre_eradication",
            "sha256_hash": "aaa", "areas": {}}


def _fake_post(path: str, linked_to: str):
    return {"path": path, "tag": "post_eradication",
            "sha256_hash": "bbb", "linked_to": {"file": linked_to}}


def test_loop_runs_max_cycles(tmp_path):
    cfg = ResilienceConfig(
        plc_ip="127.0.0.1",
        trusted_snapshot="/tmp/trusted.json",
        output_dir=str(tmp_path),
        max_cycles=2,
        detect_timeout_s=0.1,
    )

    # trusted snapshot must exist for the loop to attempt a restore
    Path(cfg.trusted_snapshot).write_text(json.dumps({
        "timestamp": "x", "plc_ip": "127.0.0.1",
        "areas": {"DB1": [0], "DB2": [0], "Merker": [0]},
    }))

    counter = {"n": 0}
    def fake_wait(cfg):
        counter["n"] += 1
        return _fake_change_event()

    pre_counter = {"n": 0}
    def fake_pre(*args, **kwargs):
        pre_counter["n"] += 1
        return _fake_pre(str(tmp_path / f"pre_{pre_counter['n']}.json"))

    post_counter = {"n": 0}
    def fake_post(*args, **kwargs):
        post_counter["n"] += 1
        return _fake_post(str(tmp_path / f"post_{post_counter['n']}.json"),
                          linked_to=f"pre_{post_counter['n']}.json")

    def fake_restore(*args, **kwargs):
        return True, [MagicMock(ok=True)], {"overall": "PASS"}

    with patch("modules.orchestrator.resilience_loop._wait_for_infection",
               side_effect=fake_wait), \
         patch("modules.orchestrator.resilience_loop.capture_pre_eradication",
               side_effect=fake_pre), \
         patch("modules.orchestrator.resilience_loop.capture_post_eradication",
               side_effect=fake_post), \
         patch("modules.orchestrator.resilience_loop.restore_with_retry",
               side_effect=fake_restore):
        results = run_resilience_loop(cfg)

    assert len(results) == 2
    for i, r in enumerate(results, start=1):
        assert r.cycle == i
        assert r.restore_ok is True
        assert r.detected_change == "MW1: 500 -> 12000"
        assert r.pre_snapshot
        assert r.post_snapshot


def test_loop_stops_on_timeout(tmp_path):
    cfg = ResilienceConfig(
        plc_ip="127.0.0.1",
        trusted_snapshot="/tmp/trusted.json",
        output_dir=str(tmp_path),
        max_cycles=5,
        detect_timeout_s=0.1,
    )

    with patch("modules.orchestrator.resilience_loop._wait_for_infection",
               return_value=None):
        results = run_resilience_loop(cfg)

    # only one cycle result (with the timeout error), then break
    assert len(results) == 1
    assert "no infection" in results[0].error


def test_loop_handles_restore_failure(tmp_path):
    cfg = ResilienceConfig(
        plc_ip="127.0.0.1",
        trusted_snapshot="/tmp/trusted.json",
        output_dir=str(tmp_path),
        max_cycles=1,
        detect_timeout_s=0.1,
    )
    Path(cfg.trusted_snapshot).write_text(json.dumps({
        "timestamp": "x", "plc_ip": "127.0.0.1",
        "areas": {"DB1": [0]},
    }))

    with patch("modules.orchestrator.resilience_loop._wait_for_infection",
               return_value=_fake_change_event()), \
         patch("modules.orchestrator.resilience_loop.capture_pre_eradication",
               return_value=_fake_pre(str(tmp_path / "pre.json"))), \
         patch("modules.orchestrator.resilience_loop.capture_post_eradication",
               return_value=_fake_post(str(tmp_path / "post.json"), "pre.json")), \
         patch("modules.orchestrator.resilience_loop.restore_with_retry",
               return_value=(False, [MagicMock(ok=False)], {"overall": "FAIL"})):
        results = run_resilience_loop(cfg)

    assert len(results) == 1
    assert results[0].restore_ok is False