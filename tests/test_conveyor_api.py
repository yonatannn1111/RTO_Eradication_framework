"""Conveyor API tests — no PLC needed (reader is mocked)."""
import json
from unittest.mock import patch

import pytest


@pytest.fixture
def app():
    from modules.conveyor_api import create_app
    return create_app("127.0.0.1", 502, {"belt_a": "127.0.0.1"})


@pytest.fixture
def client(app):
    return app.test_client()


class _FakeStatus:
    def __init__(self, **kw):
        self.belt_id = kw.get("belt_id", "belt_a")
        self.queue = kw.get("queue", 0)
        self.speed = kw.get("speed", 0.0)
        self.status = kw.get("status", "stopped")
        self.motor = kw.get("motor", 0)
        self.timer_ms = kw.get("timer_ms", 0)
        self.bags_processed = kw.get("bags_processed", 0)
        self.updated_at = "2026-10-12 10:00:00"
        self.error = kw.get("error", "")


def test_index(client):
    r = client.get("/")
    assert r.status_code == 200
    body = r.get_json()
    assert body["service"] == "conveyor-load-api"
    assert "belt_a" in body["belts"]


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.get_json()["ok"] is True


def test_status_returns_json(client):
    fake = _FakeStatus(queue=5, speed=1.0, status="running", motor=1)
    with patch("modules.conveyor_api.app.get_reader") as gr:
        gr.return_value.get_status.return_value = fake
        r = client.get("/conveyor/status")
    assert r.status_code == 200
    body = r.get_json()
    assert "belt_a" in body["belts"]
    assert body["belts"]["belt_a"]["queue"] == 5
    assert body["belts"]["belt_a"]["status"] == "running"


def test_unknown_belt_returns_404(client):
    r = client.get("/conveyor/status/nope")
    assert r.status_code == 404
    assert "unknown belt" in r.get_json()["error"]


def test_unavailable_plc_returns_error_status(client):
    """Reader returns status='error' — API should surface it, not crash."""
    fake = _FakeStatus(status="error", error="Connection refused")
    with patch("modules.conveyor_api.app.get_reader") as gr:
        gr.return_value.get_status.return_value = fake
        r = client.get("/conveyor/status")
    assert r.status_code == 200
    body = r.get_json()
    assert body["belts"]["belt_a"]["status"] == "error"
    assert "Connection refused" in body["belts"]["belt_a"]["error"]


def test_force_query_param(client):
    fake = _FakeStatus(queue=0, status="stopped")
    with patch("modules.conveyor_api.app.get_reader") as gr:
        gr.return_value.get_status.return_value = fake
        client.get("/conveyor/status?force=1")
        # confirm the reader was asked for a forced read
        gr.return_value.get_status.assert_called_with(force=True)