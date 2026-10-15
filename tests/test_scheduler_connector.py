"""Scheduler-orchestrator connector tests — mocked HTTP + restore."""
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from modules.orchestrator.scheduler_connector import (
    ConnectorConfig, ConnectorAction, ActionLogger,
    fetch_decisions, run_connector, _do_restore,
)


# ---------------------------------------------------------------------------
# fetch_decisions
# ---------------------------------------------------------------------------

def _mock_response(payload):
    m = MagicMock()
    m.read.return_value = json.dumps(payload).encode()
    m.__enter__ = lambda s: m
    m.__exit__ = lambda *a: None
    return m


def test_fetch_decisions_ok():
    cfg = ConnectorConfig(safety_url="http://x:5003")
    payload = {
        "belts": {
            "plc_a": {"action": "NOW", "reason": "queue critical"},
            "plc_b": {"action": "WAIT", "minutes": 8,
                      "reason": "queue growing"},
        },
    }
    with patch("modules.orchestrator.scheduler_connector.urllib.request.urlopen",
               return_value=_mock_response(payload)):
        result = fetch_decisions(cfg)
    assert result["ok"] is True
    assert "plc_a" in result["belts"]
    assert "plc_b" in result["belts"]


def test_fetch_decisions_scheduler_down():
    from urllib.error import URLError
    cfg = ConnectorConfig(safety_url="http://x:5003")
    with patch("modules.orchestrator.scheduler_connector.urllib.request.urlopen",
               side_effect=URLError("connection refused")):
        result = fetch_decisions(cfg)
    assert result["ok"] is False
    assert "unreachable" in result["error"]


# ---------------------------------------------------------------------------
# ActionLogger
# ---------------------------------------------------------------------------

def test_action_logger_writes_jsonl(tmp_path):
    log = ActionLogger(tmp_path / "actions.jsonl")
    rec = ConnectorAction(
        timestamp="2026-10-15 10:00:00",
        belt_id="plc_a",
        verdict="NOW",
        action_taken="restored",
        restore_ok=True,
        restore_attempts=1,
    )
    log.write(rec)
    log.write(rec)
    lines = (tmp_path / "actions.jsonl").read_text().strip().split("\n")
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["verdict"] == "NOW"
    assert first["restore_ok"] is True


# ---------------------------------------------------------------------------
# _do_restore
# ---------------------------------------------------------------------------

def test_do_restore_missing_snapshot():
    cfg = ConnectorConfig(trusted_snapshot="/no/such/file.json")
    ok, attempts, err = _do_restore(cfg)
    assert ok is False
    assert attempts == 0
    assert "missing" in err


def test_do_restore_success(tmp_path):
    snap = tmp_path / "trusted.json"
    snap.write_text("{}")
    cfg = ConnectorConfig(trusted_snapshot=str(snap))

    with patch("modules.forensics.restore_with_retry",
               return_value=(True, [MagicMock(ok=True)], {"overall": "PASS"})):
        ok, attempts, err = _do_restore(cfg)
    assert ok is True
    assert attempts == 1
    assert err == ""


# ---------------------------------------------------------------------------
# run_connector — end-to-end with mocks
# ---------------------------------------------------------------------------

def _decisions_now():
    return {"ok": True, "belts": {
        "plc_a": {"action": "NOW", "reason": "critical"},
    }}


def test_connector_executes_restore_on_now(tmp_path):
    cfg = ConnectorConfig(
        trusted_snapshot=str(tmp_path / "trusted.json"),
        action_log_path=str(tmp_path / "actions.jsonl"),
        poll_interval_s=0.01,
        max_actions=1,
    )
    Path(cfg.trusted_snapshot).write_text("{}")

    log = ActionLogger(cfg.action_log_path)
    with patch("modules.orchestrator.scheduler_connector.fetch_decisions",
               return_value=_decisions_now()), \
         patch("modules.orchestrator.scheduler_connector._do_restore",
               return_value=(True, 1, "")):
        actions = run_connector(cfg, logger=log)

    assert len(actions) >= 1
    assert actions[0].verdict == "NOW"
    assert actions[0].restore_ok is True
    assert actions[0].action_taken == "restored"


def test_connector_waits_on_wait_verdict(tmp_path):
    cfg = ConnectorConfig(
        trusted_snapshot=str(tmp_path / "trusted.json"),
        action_log_path=str(tmp_path / "actions.jsonl"),
        poll_interval_s=0.01,
        max_actions=1,
    )
    Path(cfg.trusted_snapshot).write_text("{}")

    decisions = {"ok": True, "belts": {
        "plc_a": {"action": "WAIT", "minutes": 1, "reason": "growing"},
    }}

    sleep_calls = []
    with patch("modules.orchestrator.scheduler_connector.fetch_decisions",
               side_effect=[decisions, _decisions_now()]), \
         patch("modules.orchestrator.scheduler_connector._do_restore",
               return_value=(True, 1, "")), \
         patch("modules.orchestrator.scheduler_connector.time.sleep",
               side_effect=lambda s: sleep_calls.append(s)):
        log = ActionLogger(cfg.action_log_path)
        actions = run_connector(cfg, logger=log)

    verdicts = [a.verdict for a in actions]
    assert "WAIT" in verdicts
    assert "NOW" in verdicts
    # a wait sleep of 60 s (capped) should have been requested
    assert any(s == 60.0 for s in sleep_calls)


def test_connector_logs_error_when_scheduler_down(tmp_path):
    cfg = ConnectorConfig(
        trusted_snapshot=str(tmp_path / "trusted.json"),
        action_log_path=str(tmp_path / "actions.jsonl"),
        poll_interval_s=0.01,
        max_actions=1,
    )
    Path(cfg.trusted_snapshot).write_text("{}")

    with patch("modules.orchestrator.scheduler_connector.fetch_decisions",
               return_value={"ok": False, "error": "scheduler unreachable",
                             "belts": {}}), \
         patch("modules.orchestrator.scheduler_connector.time.sleep"):
        # avoid infinite loop: interrupt on second call
        call_count = {"n": 0}
        def fake_sleep(_):
            call_count["n"] += 1
            if call_count["n"] > 2:
                raise KeyboardInterrupt
        with patch("modules.orchestrator.scheduler_connector.time.sleep",
                   side_effect=fake_sleep):
            log = ActionLogger(cfg.action_log_path)
            actions = run_connector(cfg, logger=log)

    assert any(a.verdict == "ERROR" for a in actions)
    assert any("unreachable" in a.reason for a in actions)