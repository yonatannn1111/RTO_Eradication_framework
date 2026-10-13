"""Forensic → scheduler dispatch tests — mocked HTTP."""
import json
from unittest.mock import patch, MagicMock
from urllib.error import URLError

import pytest

from modules.forensics.dispatch import (
    dispatch_to_scheduler, DispatchResult, SLA_S,
)


def _resp(payload, status=200):
    m = MagicMock()
    m.read.return_value = json.dumps(payload).encode()
    m.status = status
    m.__enter__ = lambda s: m
    m.__exit__ = lambda *a: None
    return m


def test_dispatch_success():
    payload = {
        "belt_id": "plc_a",
        "window": {
            "action": "WAIT",
            "minutes": 8,
            "reason": "45 bags in queue",
        },
    }
    with patch("modules.forensics.dispatch.urllib.request.urlopen",
               return_value=_resp(payload)):
        r = dispatch_to_scheduler("plc_a", "timer-manipulation")
    assert r.ok is True
    assert r.action == "WAIT"
    assert r.minutes == 8
    assert r.elapsed_s < SLA_S


def test_dispatch_now_action():
    payload = {"belt_id": "plc_a", "window": {"action": "NOW",
                                              "reason": "critical"}}
    with patch("modules.forensics.dispatch.urllib.request.urlopen",
               return_value=_resp(payload)):
        r = dispatch_to_scheduler("plc_a", "counter-overflow")
    assert r.ok is True
    assert r.action == "NOW"
    assert r.minutes is None


def test_dispatch_scheduler_unreachable():
    with patch("modules.forensics.dispatch.urllib.request.urlopen",
               side_effect=URLError("connection refused")):
        r = dispatch_to_scheduler("plc_a", "timer-manipulation")
    assert r.ok is False
    assert "unreachable" in r.error


def test_dispatch_http_error():
    from urllib.error import HTTPError
    err = HTTPError("http://x", 503, "Service Unavailable", {}, None)
    err.read = lambda: b'{"error": "plc offline"}'
    with patch("modules.forensics.dispatch.urllib.request.urlopen",
               side_effect=err):
        r = dispatch_to_scheduler("plc_a", "timer-manipulation")
    assert r.ok is False
    assert "503" in r.error


def test_dispatch_live_inputs_passed_through():
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["body"] = json.loads(req.data.decode())
        return _resp({"belt_id": "plc_a", "window": {"action": "DELAY"}})

    with patch("modules.forensics.dispatch.urllib.request.urlopen",
               side_effect=fake_urlopen):
        dispatch_to_scheduler(
            "plc_a", "timer-manipulation",
            live_inputs={"queue_now": 5, "arrival_rate": 1.0,
                         "service_rate": 0.5},
        )
    assert captured["body"]["queue_now"] == 5
    assert captured["body"]["arrival_rate"] == 1.0
    assert captured["body"]["service_rate"] == 0.5


def test_dispatch_from_alert_helper():
    from modules.forensics.dispatch import dispatch_from_alert
    payload = {"belt_id": "plc_a",
               "window": {"action": "NOW", "reason": "critical"}}
    with patch("modules.forensics.dispatch.urllib.request.urlopen",
               return_value=_resp(payload)):
        r = dispatch_from_alert(
            {"register": 3, "severity": "medium"},
            belt_id="plc_a",
        )
    assert r.ok is True
    assert r.action == "NOW"