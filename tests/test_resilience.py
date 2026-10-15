"""Resilience tests — simulate PLC outages without a real PLC."""
from pathlib import Path
from unittest.mock import patch

import pytest

from modules.scheduler.twin import ConveyorTwin, TwinConfig
from modules.scheduler.plc_source import PLCReading


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_reading(time_s: float = 0.0, queue: int = 0) -> PLCReading:
    return PLCReading(
        timestamp="2026-10-13 10:00:00.000",
        time_s=time_s,
        motor=1,
        speed_ms=500,
        timer_ms=0,
        bag_count=10,
        status=1,
        sensor=queue,
        queue_length=queue,
    )


@pytest.fixture
def cfg(tmp_path):
    """Small retry budget so outage → gap cycles finish within a short test."""
    return TwinConfig(
        sample_interval=0.05,
        mode="realtime",
        output_dir=str(tmp_path),
        max_attempts=3,          # smaller retry budget for fast tests
        max_backoff_s=0.1,       # very short backoff
    )


# ---------------------------------------------------------------------------
# Outage + recovery
# ---------------------------------------------------------------------------

def test_twin_survives_single_outage(cfg, tmp_path):
    """
    Mid-run outage long enough to exhaust the retry budget →
    gap markers written to the sample CSV, and a plc_restored event
    logged when the PLC comes back.
    """
    twin = ConveyorTwin(cfg)

    call_count = {"n": 0}

    def flaky_read():
        call_count["n"] += 1
        # Fail for 12 consecutive reads. With max_attempts=3,
        # that's 4 outer ticks that exhaust retries → gap markers.
        if 3 <= call_count["n"] <= 14:
            raise ConnectionError("simulated PLC reboot")
        return _fake_reading(time_s=call_count["n"] * 0.05, queue=0)

    with patch.object(twin._reader, "connect"), \
         patch.object(twin._reader, "read", side_effect=flaky_read), \
         patch.object(twin._reader, "close"):
        twin.run(duration_s=3.0)

    # --- event log assertions ---------------------------------------------
    events = [e["event"] for e in twin.events]
    assert "twin_started" in events
    assert "plc_restored" in events
    assert "twin_stopped" in events

    # --- summary reflects the outage --------------------------------------
    summary = twin.resilience_summary()
    assert summary["gap_samples"] >= 1, \
        f"expected gap samples, got {summary['gap_samples']}"
    assert summary["restoration_events"] >= 1, \
        f"expected restoration events, got {summary['restoration_events']}"

    # --- gap markers live in the sample CSV, not state.samples ------------
    sample_csvs = [p for p in Path(tmp_path).glob("twin_*.csv")
                   if "events" not in p.name]
    assert len(sample_csvs) == 1, "expected exactly one sample CSV"

    rows = sample_csvs[0].read_text().splitlines()[1:]      # skip header
    gap_rows = [r for r in rows if r.split(",")[2] == "-1"]
    assert len(gap_rows) >= 1, \
        f"expected gap rows in {sample_csvs[0]}, got {len(gap_rows)}"


def test_twin_recovers_without_gaps_from_short_blip(cfg):
    """
    A short failure (fewer than max_attempts consecutive failures) is
    absorbed inside _read_resilient — no gap rows are written to the
    sample CSV. The twin still notices the brief outage, so one
    plc_restored event is logged, but no data was lost.
    """
    twin = ConveyorTwin(cfg)

    call_count = {"n": 0}

    def flaky_read():
        call_count["n"] += 1
        # fail exactly twice → within a single outer tick's retry budget
        if 3 <= call_count["n"] <= 4:
            raise ConnectionError("brief blip")
        return _fake_reading(time_s=call_count["n"] * 0.05, queue=0)

    with patch.object(twin._reader, "connect"), \
         patch.object(twin._reader, "read", side_effect=flaky_read), \
         patch.object(twin._reader, "close"):
        twin.run(duration_s=0.5)

    summary = twin.resilience_summary()

    # No gap rows were needed — the retry loop recovered the same tick
    assert summary["gap_samples"] == 0, \
        f"expected no gap samples, got {summary['gap_samples']}"

    # The twin did notice the outage → one restoration event
    assert summary["restoration_events"] == 1, \
        f"expected 1 restoration event, got {summary['restoration_events']}"

    # And it stopped cleanly
    assert "twin_stopped" in [e["event"] for e in twin.events]

# ---------------------------------------------------------------------------
# Summaries
# ---------------------------------------------------------------------------

def test_resilience_summary_shape(cfg):
    twin = ConveyorTwin(cfg)
    s = twin.resilience_summary()
    for k in ("total_samples", "gap_samples",
              "outage_ticks", "restoration_events", "restorations"):
        assert k in s


def test_resilience_summary_after_run(cfg):
    """Run the twin with a healthy PLC and verify the summary is sane."""
    twin = ConveyorTwin(cfg)
    with patch.object(twin._reader, "connect"), \
         patch.object(twin._reader, "read",
                       return_value=_fake_reading(queue=2)), \
         patch.object(twin._reader, "close"):
        twin.run(duration_s=0.3)

    s = twin.resilience_summary()
    assert s["total_samples"] >= 1
    assert s["gap_samples"] == 0
    assert s["restoration_events"] == 0


# ---------------------------------------------------------------------------
# CSV output
# ---------------------------------------------------------------------------

def test_event_csv_written(cfg, tmp_path):
    twin = ConveyorTwin(cfg)
    with patch.object(twin._reader, "connect"), \
         patch.object(twin._reader, "read",
                       return_value=_fake_reading()), \
         patch.object(twin._reader, "close"):
        twin.run(duration_s=0.2)

    events_csvs = list(Path(tmp_path).glob("twin_events_*.csv"))
    assert len(events_csvs) == 1

    content = events_csvs[0].read_text().splitlines()
    assert content[0] == "timestamp,time_s,event,detail"
    assert any("twin_started" in line for line in content)
    assert any("twin_stopped" in line for line in content)


def test_sample_csv_written(cfg, tmp_path):
    twin = ConveyorTwin(cfg)
    with patch.object(twin._reader, "connect"), \
         patch.object(twin._reader, "read",
                       return_value=_fake_reading(queue=5)), \
         patch.object(twin._reader, "close"):
        twin.run(duration_s=0.2)

    sample_csvs = list(Path(tmp_path).glob("twin_*.csv"))
    # one twin_*.csv, excluding twin_events_*.csv
    sample_csvs = [p for p in sample_csvs if "events" not in p.name]
    assert len(sample_csvs) == 1

    content = sample_csvs[0].read_text().splitlines()
    assert content[0] == "timestamp,time_s,queue_length,motor,bag_count,speed_ms"
    assert len(content) >= 2   # header + at least one sample