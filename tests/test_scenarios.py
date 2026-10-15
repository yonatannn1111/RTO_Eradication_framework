"""Attack scenario tests — mocked, no PLC."""
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from scenarios.metrics import (
    ScenarioResult, Stopwatch, MetricsCollector, estimate_mis_sorted_bags,
)


# ---------------------------------------------------------------------------
# Metrics primitives
# ---------------------------------------------------------------------------

def test_stopwatch_measures_time():
    import time
    sw = Stopwatch().start()
    time.sleep(0.05)
    elapsed = sw.stop()
    assert 0.04 <= elapsed <= 0.15


def test_estimate_mis_sorted_default_zero():
    # reject rate 0 → no mis-sorted bags regardless of downtime
    assert estimate_mis_sorted_bags(30.0, bags_per_second=2.0) == 0


def test_estimate_mis_sorted_with_rate():
    # 10 s downtime, 2 bags/s, 10% reject rate → 2
    assert estimate_mis_sorted_bags(10.0, 2.0, reject_rate=0.1) == 2


def test_collector_writes_individual_json(tmp_path):
    c = MetricsCollector(tmp_path)
    r = ScenarioResult(
        scenario="1 - Timer Attack",
        started_at="2026-10-15 10:00:00",
        forensic_recovery_pct=100.0,
        downtime_s=3.4,
        mis_sorted_bags=0,
        validation_pass=True,
    )
    c.add(r)
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    data = json.loads(files[0].read_text())
    assert data["scenario"] == "1 - Timer Attack"
    assert data["forensic_recovery_pct"] == 100.0


def test_collector_csv_and_markdown(tmp_path):
    c = MetricsCollector(tmp_path)
    c.add(ScenarioResult(
        scenario="1 - Timer Attack",
        started_at="x", forensic_recovery_pct=95.0,
        downtime_s=8.0, mis_sorted_bags=0, validation_pass=True,
    ))
    c.add(ScenarioResult(
        scenario="2 - Counter Attack",
        started_at="x", forensic_recovery_pct=100.0,
        downtime_s=3.0, mis_sorted_bags=0, validation_pass=True,
    ))
    csv_path = c.to_csv()
    md_path = c.to_markdown()

    assert Path(csv_path).exists()
    assert Path(md_path).exists()
    csv_text = Path(csv_path).read_text()
    assert "1 - Timer Attack" in csv_text
    assert "95.0" in csv_text


def test_collector_summary(tmp_path):
    c = MetricsCollector(tmp_path)
    c.add(ScenarioResult(scenario="A", started_at="x",
                         forensic_recovery_pct=90.0, downtime_s=10.0,
                         validation_pass=True))
    c.add(ScenarioResult(scenario="B", started_at="x",
                         forensic_recovery_pct=100.0, downtime_s=4.0,
                         validation_pass=True))
    s = c.summary()
    assert s["scenarios_run"] == 2
    assert s["avg_recovery_pct"] == 95.0
    assert s["avg_downtime_s"] == 7.0
    assert s["all_validation_passed"] is True


# ---------------------------------------------------------------------------
# Runner integration
# ---------------------------------------------------------------------------

def test_run_scenario_completes_full_cycle(tmp_path):
    from scenarios.runner import run_scenario, ScenarioConfig

    cfg = ScenarioConfig(
        plc_ip="127.0.0.1",
        trusted_snapshot=str(tmp_path / "trusted.json"),
        detection_timeout_s=1.0,
    )
    (tmp_path / "trusted.json").write_text("{}")

    fake_alert = MagicMock()
    fake_alert.detected_at = "2026-10-15 10:00:00"
    fake_alert.all_changes = [{"register": 1, "baseline": 500, "observed": 12000}]

    with patch("scenarios.runner._wait_for_detection", return_value=fake_alert), \
         patch("scenarios.runner._run_restore", return_value=(True, 1, "")), \
         patch("scenarios.runner._validate", return_value=True):
        result = run_scenario(
            name="test",
            trigger_fn=lambda: None,
            baseline={1: 500},
            cfg=cfg,
        )

    assert result.forensic_recovery_pct == 100.0
    assert result.validation_pass is True
    assert result.restore_attempts == 1
    assert result.downtime_s >= 0


def test_run_scenario_handles_detection_timeout(tmp_path):
    from scenarios.runner import run_scenario, ScenarioConfig

    cfg = ScenarioConfig(
        trusted_snapshot=str(tmp_path / "t.json"),
        detection_timeout_s=0.1,
    )
    (tmp_path / "t.json").write_text("{}")

    with patch("scenarios.runner._wait_for_detection", return_value=None):
        result = run_scenario("timeout-test", lambda: None, {1: 0}, cfg)

    assert result.forensic_recovery_pct == 0.0
    assert "timeout" in result.notes


def test_run_scenario_reports_partial_recovery(tmp_path):
    from scenarios.runner import run_scenario, ScenarioConfig

    cfg = ScenarioConfig(trusted_snapshot=str(tmp_path / "t.json"))
    (tmp_path / "t.json").write_text("{}")

    fake_alert = MagicMock()
    fake_alert.detected_at = "x"
    fake_alert.all_changes = [{"register": 1, "baseline": 500, "observed": 12000}]

    with patch("scenarios.runner._wait_for_detection", return_value=fake_alert), \
         patch("scenarios.runner._run_restore", return_value=(True, 1, "")), \
         patch("scenarios.runner._validate", return_value=False):
        result = run_scenario("partial", lambda: None, {1: 500}, cfg)

    # restore ok but validation failed → 75%
    assert result.forensic_recovery_pct == 75.0
    assert result.validation_pass is False