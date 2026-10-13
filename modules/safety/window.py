"""
Compute the safe window for a single PLC.

A "safe window" answers: given the current queue length and the belt's
arrival/service rates, how urgently must we eradicate?

    NOW          → eradicate immediately, queue is at/above threshold
    WAIT X min   → queue is growing, eradicate within X minutes
    DELAY        → queue is stable or draining, no rush

The window is derived from a short SimPy forecast: simulate the belt
forward in time and find the earliest moment the queue crosses the
critical threshold. That gives X minutes directly.
"""
from dataclasses import dataclass, field
from typing import Optional

import simpy


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

@dataclass
class WindowThresholds:
    critical_queue: int = 40       # when queue reaches this, action is NOW
    warning_queue: int = 10        # mild pressure
    max_delay_min: float = 30.0    # cap on WAIT X minutes
    simulate_horizon_min: float = 60.0


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

@dataclass
class SafeWindow:
    action: str                     # "NOW" | "WAIT" | "DELAY"
    minutes: Optional[int] = None   # populated for WAIT
    reason: str = ""
    inputs: dict = field(default_factory=dict)
    forecast: list = field(default_factory=list)   # (minute, queue) samples

    def as_dict(self):
        out = {"action": self.action, "reason": self.reason}
        if self.minutes is not None:
            out["minutes"] = self.minutes
        return out


# ---------------------------------------------------------------------------
# SimPy forecast
# ---------------------------------------------------------------------------

def _forecast(queue_now: int,
              arrival_rate: float,      # bags / second
              service_rate: float,      # bags / second
              horizon_min: float,
              sample_s: float = 5.0):
    """
    Fluid-model forecast: Q(t) = max(0, Q0 + (λ - μ) * t).
    Returns list of (minute, queue) at sample points.
    """
    samples = []
    env = simpy.Environment()

    def model():
        q = float(queue_now)
        for _ in range(int(horizon_min * 60 / sample_s)):
            yield env.timeout(sample_s)
            q = max(0.0, q + (arrival_rate - service_rate) * sample_s)
            samples.append((env.now / 60.0, q))

    env.process(model())
    env.run(until=horizon_min * 60)
    return samples


def compute_safe_window(
    queue_now: int,
    arrival_rate: float,
    service_rate: float,
    belt_criticality: str = "medium",
    thresholds: WindowThresholds | None = None,
) -> SafeWindow:
    """Return the safe-window recommendation for one belt."""
    th = thresholds or WindowThresholds()

    # --- trivial cases -----------------------------------------------------
    if queue_now >= th.critical_queue:
        return SafeWindow(
            action="NOW",
            reason=f"Queue at {queue_now} bags (≥ critical {th.critical_queue})",
            inputs={
                "queue_now": queue_now,
                "arrival_rate": arrival_rate,
                "service_rate": service_rate,
                "belt_criticality": belt_criticality,
            },
        )

    if service_rate <= 0:
        return SafeWindow(
            action="NOW",
            reason="Belt not running — queue cannot drain",
            inputs={
                "queue_now": queue_now,
                "arrival_rate": arrival_rate,
                "service_rate": service_rate,
            },
        )

    # --- simulate forward --------------------------------------------------
    samples = _forecast(queue_now, arrival_rate, service_rate,
                        th.simulate_horizon_min)

    # Find earliest minute at which queue crosses critical_queue
    for minute, q in samples:
        if q >= th.critical_queue:
            wait_min = max(0.0, minute)
            # action priority — critical belt doubles urgency
            if belt_criticality == "critical":
                wait_min = wait_min / 2.0
            if wait_min < 1.0:
                return SafeWindow(
                    action="NOW",
                    reason=f"Queue will reach {th.critical_queue} within 1 min",
                    inputs={"queue_now": queue_now,
                            "arrival_rate": arrival_rate,
                            "service_rate": service_rate},
                    forecast=samples,
                )
            if wait_min > th.max_delay_min:
                return SafeWindow(
                    action="DELAY",
                    reason=f"Queue stable below {th.critical_queue} for "
                           f">{th.max_delay_min} min",
                    inputs={"queue_now": queue_now,
                            "arrival_rate": arrival_rate,
                            "service_rate": service_rate},
                    forecast=samples,
                )
            return SafeWindow(
                action="WAIT",
                minutes=int(round(wait_min)),
                reason=f"{queue_now} bags in queue; "
                       f"critical in ~{int(round(wait_min))} min",
                inputs={"queue_now": queue_now,
                        "arrival_rate": arrival_rate,
                        "service_rate": service_rate},
                forecast=samples,
            )

    # --- never crosses threshold in the horizon ---------------------------
    return SafeWindow(
        action="DELAY",
        reason=f"Queue stable below {th.critical_queue} for "
               f"{int(th.simulate_horizon_min)} min",
        inputs={"queue_now": queue_now,
                "arrival_rate": arrival_rate,
                "service_rate": service_rate},
        forecast=samples,
    )