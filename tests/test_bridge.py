"""Forensic-to-scheduler bridge tests — mocked HTTP and queue."""
import json
from unittest.mock import patch, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Client-side tests
# ---------------------------------------------------------------------------

def test_classify_infection_known_register():
    from modules.forensics.bridge import classify_infection
    assert classify_infection({"register": 0}) == "motor-flag-manipulation"
    assert classify_infection({"register": 1}) == "timer-manipulation"
    assert classify_infection({"register": 3}) == "counter-overflow"


def test_classify_infection_unknown_register():
    from modules.forensics.bridge import classify_infection
    assert classify_infection({"register": 99}) == "unknown-register-99"


def test_submit_success(monkeypatch):
    from modules.forensics import bridge

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({
        "ack": True, "task_id": "abc123", "queue_size": 0,
    }).encode()
    mock_resp.__enter__ = lambda s: mock_resp
    mock_resp.__exit__ = lambda *a: None

    with patch("modules.forensics.bridge.urllib.request.urlopen",
               return_value=mock_resp):
        r = bridge.submit_to_scheduler("127.0.0.1", "timer-manipulation")

    assert r.ok is True
    assert r.task_id == "abc123"


def test_submit_scheduler_unreachable():
    from modules.forensics import bridge
    from urllib.error import URLError

    with patch("modules.forensics.bridge.urllib.request.urlopen",
               side_effect=URLError("connection refused")):
        r = bridge.submit_to_scheduler("127.0.0.1", "timer-manipulation")

    assert r.ok is False
    assert "cannot reach scheduler" in r.error


# ---------------------------------------------------------------------------
# Server-side tests — task worker
# ---------------------------------------------------------------------------

def test_worker_enqueues_and_processes():
    from modules.scheduler.bridge import TaskWorker

    processed = []

    def handler(task):
        processed.append(task.task_id)
        return "ok"

    w = TaskWorker(handler=handler)
    w.start()
    try:
        t = w.submit("127.0.0.1", "timer-manipulation", "2026-10-13 10:00:00")
        assert t.status == "queued"
        # wait for processing
        import time
        for _ in range(50):
            if w.get(t.task_id).status == "done":
                break
            time.sleep(0.05)
        assert w.get(t.task_id).status == "done"
        assert t.task_id in processed
    finally:
        w.stop()


def test_worker_queue_accumulates_when_busy():
    from modules.scheduler.bridge import TaskWorker
    import time

    def slow_handler(task):
        time.sleep(0.5)
        return "slow"

    w = TaskWorker(handler=slow_handler, poll_interval=0.05)
    w.start()
    try:
        ids = [
            w.submit(f"plc{i}", "timer-manipulation", "2026-10-13 10:00:00").task_id
            for i in range(3)
        ]
        # Immediately after submitting, 2 should still be queued
        snap = w.snapshot()
        assert snap["queue_size"] >= 1
        assert snap["worker_alive"] is True
    finally:
        w.stop()


# ---------------------------------------------------------------------------
# Flask endpoint tests
# ---------------------------------------------------------------------------

@pytest.fixture
def bridge_client():
    from modules.scheduler.bridge import TaskWorker, create_app
    w = TaskWorker()
    w.start()
    app = create_app(w)
    client = app.test_client()
    yield client, w
    w.stop()


def test_endpoint_submit_valid(bridge_client):
    client, _ = bridge_client
    r = client.post("/tasks/submit", json={
        "plc_id": "127.0.0.1",
        "infection_type": "timer-manipulation",
        "detected_at": "2026-10-13 10:00:00",
    })
    assert r.status_code == 202
    body = r.get_json()
    assert body["ack"] is True
    assert "task_id" in body


def test_endpoint_submit_missing_fields(bridge_client):
    client, _ = bridge_client
    r = client.post("/tasks/submit", json={"plc_id": "x"})
    assert r.status_code == 400
    assert "missing fields" in r.get_json()["error"]


def test_endpoint_status(bridge_client):
    client, _ = bridge_client
    r = client.get("/tasks/status")
    assert r.status_code == 200
    body = r.get_json()
    assert "queue_size" in body
    assert "worker_alive" in body


def test_endpoint_task_detail(bridge_client):
    client, w = bridge_client
    r = client.post("/tasks/submit", json={
        "plc_id": "127.0.0.1",
        "infection_type": "counter-overflow",
        "detected_at": "2026-10-13 10:00:00",
    })
    tid = r.get_json()["task_id"]

    r = client.get(f"/tasks/{tid}")
    assert r.status_code == 200
    body = r.get_json()
    assert body["plc_id"] == "127.0.0.1"
    assert body["infection_type"] == "counter-overflow"


def test_endpoint_unknown_task(bridge_client):
    client, _ = bridge_client
    r = client.get("/tasks/nope")
    assert r.status_code == 404