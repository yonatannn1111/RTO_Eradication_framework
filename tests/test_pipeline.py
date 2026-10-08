"""End-to-end pipeline tests — mocked, no PLC needed."""
import json
from pathlib import Path
from unittest.mock import patch

import pytest


# --- fixtures --------------------------------------------------------------

@pytest.fixture
def cfg():
    return {
        "plc": {"ip": "127.0.0.1", "modbus_port": 502, "s7_port": 1102,
                "https_port": 8443},
        "snapshot": {"db1_size": 4, "db2_size": 4, "merker_size": 4},
        "output_dir": "output_test",
    }


@pytest.fixture
def mock_capture(tmp_path):
    """Fake snapshot file so we don't need a real PLC."""
    def _fake_capture(ip, tcp_port=1102, output_dir=".", **kwargs):
        out = Path(output_dir); out.mkdir(parents=True, exist_ok=True)
        fname = out / f"snap_{len(list(out.glob('snap_*.json')))}.json"
        payload = {
            "timestamp": "2026-10-08 17:00:00",
            "plc_ip": ip,
            "areas": {"DB1": [0, 0, 0, 0], "DB2": [0, 0, 0, 0], "Merker": [0, 0, 0, 0]},
        }
        fname.write_text(json.dumps(payload))
        return {"path": str(fname), **payload}
    return _fake_capture


# --- tests -----------------------------------------------------------------

def test_run_dir_created(tmp_path):
    from modules.orchestrator.main import make_run_dir
    d = make_run_dir(str(tmp_path / "output"))
    assert (d / "snapshots").exists()
    assert (d / "reports").exists()


def test_dashboard_writes_files(tmp_path):
    from modules.orchestrator.dashboard import build_dashboard
    (tmp_path / "clean_snapshot.json").write_text(json.dumps({
        "timestamp": "x", "plc_ip": "127.0.0.1",
        "areas": {"DB1": [0, 1]},
    }))
    (tmp_path / "comparison.json").write_text(json.dumps({
        "total_changes": 2,
        "changes_by_severity": {"critical": 1, "high": 1},
        "changes_by_area": {"DB1": 2},
    }))
    payload = build_dashboard(tmp_path)
    assert (tmp_path / "dashboard.json").exists()
    assert (tmp_path / "dashboard.html").exists()
    assert payload["summary"]["total_changes"] == 2


def test_pipeline_skips_when_no_change(cfg, mock_capture):
    from modules.orchestrator import main as orch

    with patch("modules.forensics.capture", side_effect=mock_capture), \
         patch("modules.ot_infrastructure.verify_plc") as mock_v, \
         patch("modules.forensics.watcher.RegisterWatcher.wait", return_value=None):

        mock_v.return_value.modbus_open = True
        mock_v.return_value.s7_open = True
        mock_v.return_value.https_open = True
        mock_v.return_value.errors = []

        results = orch.run_pipeline(cfg, detect_timeout=0.1)

    assert results["dirty"] is None
    assert results["diff"] is None