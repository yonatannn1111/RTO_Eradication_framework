"""Dashboard reader tests — mocked HTTP, no services needed."""
from unittest.mock import patch, MagicMock

import pytest

from modules.dashboard.config import DashboardConfig
from modules.dashboard import reader


@pytest.fixture
def cfg():
    return DashboardConfig(
        conveyor_url="http://test:5001",
        scheduler_url="http://test:5002",
        safety_url="http://test:5003",
        http_timeout_s=1.0,
    )


def _resp(payload):
    m = MagicMock()
    m.json.return_value = payload
    m.raise_for_status.return_value = None
    return m


def test_fetch_conveyor_ok(cfg):
    payload = {"belts": {"plc_a": {"queue": 3, "status": "running"}}}
    with patch("modules.dashboard.reader.requests.get",
               return_value=_resp(payload)):
        out = reader.fetch_conveyor(cfg)
    assert out["belts"]["plc_a"]["queue"] == 3


def test_fetch_handles_connection_error(cfg):
    import requests
    with patch("modules.dashboard.reader.requests.get",
               side_effect=requests.exceptions.ConnectionError()):
        out = reader.fetch_conveyor(cfg)
    assert "error" in out
    assert "unreachable" in out["error"]


def test_fetch_handles_timeout(cfg):
    import requests
    with patch("modules.dashboard.reader.requests.get",
               side_effect=requests.exceptions.Timeout()):
        out = reader.fetch_safety(cfg)
    assert "error" in out
    assert "timeout" in out["error"]


def test_fetch_handles_http_error(cfg):
    import requests
    m = MagicMock()
    m.raise_for_status.side_effect = requests.exceptions.HTTPError(
        response=MagicMock(status_code=500)
    )
    with patch("modules.dashboard.reader.requests.get", return_value=m):
        out = reader.fetch_scheduler(cfg)
    assert "error" in out
    assert "500" in out["error"]


def test_gather_all_structure(cfg):
    good = _resp({"belts": {}})
    with patch("modules.dashboard.reader.requests.get", return_value=good):
        out = reader.gather_all(cfg)
    assert set(out.keys()) == {
        "conveyor", "scheduler", "safety", "alerts", "fetched_at",
    }


def test_alerts_from_missing_dir(tmp_path):
    out = reader.fetch_alerts_from_run_dir(str(tmp_path / "nonexistent"))
    assert out == []