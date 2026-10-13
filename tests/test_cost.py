"""Cost function tests."""
from datetime import datetime

import pytest

from modules.cost import CostConfig, CostInputs, compute_cost, is_immediate


@pytest.fixture
def cfg(tmp_path):
    p = tmp_path / "cost.yaml"
    p.write_text("""
weights:
  queue_length: 2.0
  flights_affected: 10.0
  belt_criticality: 5.0
  wait_minutes: -3.0
  time_of_day: 8.0
thresholds:
  immediate: 50
  wait: 20
criticality_levels:
  low: 1
  medium: 3
  high: 5
  critical: 10
time_of_day:
  peak_hours: [7, 8, 9, 16, 17, 18, 19]
  peak_multiplier: 1.0
  off_peak_multiplier: 0.3
""")
    return CostConfig.load(p)


def test_basic_calculation(cfg):
    # queue=8, flights=2, crit=high(5), wait=0, peak=1.0
    # = 8*2 + 2*10 + 5*5 + 0*-3 + 1.0*8 = 16 + 20 + 25 + 0 + 8 = 69
    r = compute_cost(
        CostInputs(queue_length=8, flights_affected=2,
                   belt_criticality="high", wait_minutes=0,
                   when=datetime(2026, 10, 13, 8, 0)),
        cfg,
    )
    assert r.score == 69.0
    assert r.decision == "IMMEDIATE"


def test_off_peak_reduces_score(cfg):
    peak = compute_cost(
        CostInputs(8, 2, "high", 0, when=datetime(2026, 10, 13, 8, 0)), cfg,
    )
    off = compute_cost(
        CostInputs(8, 2, "high", 0, when=datetime(2026, 10, 13, 2, 0)), cfg,
    )
    assert off.score < peak.score


def test_waiting_reduces_score(cfg):
    now = compute_cost(
        CostInputs(8, 2, "high", 0, when=datetime(2026, 10, 13, 8, 0)), cfg,
    )
    waited = compute_cost(
        CostInputs(8, 2, "high", 5, when=datetime(2026, 10, 13, 8, 0)), cfg,
    )
    assert waited.score == now.score - 15   # -3 * 5 minutes


def test_decision_delay_when_low(cfg):
    r = compute_cost(
        CostInputs(0, 0, "low", 0, when=datetime(2026, 10, 13, 2, 0)),
        cfg,
    )
    # 0 + 0 + 1*5 + 0 + 0.3*8 = 5 + 2.4 = 7.4 → DELAY
    assert r.decision == "DELAY"
    assert is_immediate(r) is False


def test_decision_wait_middle_band(cfg):
    r = compute_cost(
        CostInputs(2, 0, "low", 0, when=datetime(2026, 10, 13, 2, 0)),
        cfg,
    )
    # 2*2 + 0 + 5 + 0 + 2.4 = 4 + 5 + 2.4 = 11.4 → DELAY
    # push it up: wait value not used here
    r2 = compute_cost(
        CostInputs(4, 0, "low", 0, when=datetime(2026, 10, 13, 2, 0)),
        cfg,
    )
    # 4*2 + 0 + 5 + 0 + 2.4 = 8 + 5 + 2.4 = 15.4 → DELAY
    r3 = compute_cost(
        CostInputs(6, 0, "low", 0, when=datetime(2026, 10, 13, 2, 0)),
        cfg,
    )
    # 6*2 + 0 + 5 + 0 + 2.4 = 12 + 5 + 2.4 = 19.4 → DELAY
    r4 = compute_cost(
        CostInputs(7, 0, "low", 0, when=datetime(2026, 10, 13, 2, 0)),
        cfg,
    )
    # 7*2 + 0 + 5 + 0 + 2.4 = 14 + 5 + 2.4 = 21.4 → WAIT
    assert r4.decision == "WAIT"


def test_breakdown_keys(cfg):
    r = compute_cost(CostInputs(5, 1, "medium"), cfg)
    for k in ("queue_term", "flights_term", "crit_term",
              "wait_term", "tod_term"):
        assert k in r.breakdown