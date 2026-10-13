"""
Cost function — quantifies urgency of eradicating a compromised belt now
vs. waiting.

    cost = queue_length       × W_queue
         + flights_affected   × W_flights
         + criticality_score  × W_crit
         + time_of_day_factor × W_tod
         + wait_minutes       × W_wait      (W_wait is negative)

Higher score = more urgent.

Decision thresholds (configurable):
    score >= immediate        →  "IMMEDIATE"
    wait <= score < immediate →  "WAIT"
    score < wait              →  "DELAY"
"""
from dataclasses import dataclass, field
from datetime import datetime

from .config import CostConfig


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

@dataclass
class CostInputs:
    queue_length: int
    flights_affected: int
    belt_criticality: str           # "low" | "medium" | "high" | "critical"
    wait_minutes: float = 0.0
    when: datetime | None = None    # defaults to now


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

@dataclass
class CostResult:
    score: float
    decision: str                    # IMMEDIATE | WAIT | DELAY
    breakdown: dict = field(default_factory=dict)
    inputs: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

def _time_factor(when: datetime, tod_cfg: dict) -> float:
    """
    Returns a multiplier in [off_peak, peak] based on hour of day.
    """
    hour = when.hour
    peak_hours = set(tod_cfg.get("peak_hours", []))
    if hour in peak_hours:
        return float(tod_cfg.get("peak_multiplier", 1.0))
    return float(tod_cfg.get("off_peak_multiplier", 0.3))


def _decide(score: float, thresholds: dict) -> str:
    if score >= thresholds.get("immediate", 50):
        return "IMMEDIATE"
    if score >= thresholds.get("wait", 20):
        return "WAIT"
    return "DELAY"


def compute_cost(
    inputs: CostInputs,
    config: CostConfig | None = None,
) -> CostResult:
    """Compute the urgency score and decision."""
    cfg = config or CostConfig.load()

    when = inputs.when or datetime.now()
    crit_score = cfg.criticality_levels.get(inputs.belt_criticality.lower(), 1)
    tod_factor = _time_factor(when, cfg.time_of_day)

    w = cfg.weights
    q_term  = inputs.queue_length      * w.get("queue_length", 2.0)
    f_term  = inputs.flights_affected  * w.get("flights_affected", 10.0)
    c_term  = crit_score               * w.get("belt_criticality", 5.0)
    w_term  = inputs.wait_minutes      * w.get("wait_minutes", -3.0)
    t_term  = tod_factor               * w.get("time_of_day", 8.0)

    score = q_term + f_term + c_term + w_term + t_term
    decision = _decide(score, cfg.thresholds)

    return CostResult(
        score=round(score, 2),
        decision=decision,
        breakdown={
            "queue_term":     round(q_term, 2),
            "flights_term":   round(f_term, 2),
            "crit_term":      round(c_term, 2),
            "wait_term":      round(w_term, 2),
            "tod_term":       round(t_term, 2),
        },
        inputs={
            "queue_length":     inputs.queue_length,
            "flights_affected": inputs.flights_affected,
            "belt_criticality": inputs.belt_criticality,
            "wait_minutes":     inputs.wait_minutes,
            "when":             when.strftime("%Y-%m-%d %H:%M:%S"),
            "criticality_score": crit_score,
            "time_of_day_factor": tod_factor,
        },
    )


# ---------------------------------------------------------------------------
# Convenience — is it urgent enough to act now?
# ---------------------------------------------------------------------------

def is_immediate(result: CostResult) -> bool:
    return result.decision == "IMMEDIATE"