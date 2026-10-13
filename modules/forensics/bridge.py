"""
Forensic-to-Scheduler bridge — client side.

Called by the detection pipeline when a register change is confirmed to
be an infection. Submits a task to the scheduler and returns the ACK.
"""
import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime


log = logging.getLogger("forensics.bridge")


DEFAULT_SCHEDULER_URL = "http://127.0.0.1:5002"


# ---------------------------------------------------------------------------
# Infection classification
# ---------------------------------------------------------------------------

# Map from changed register -> infection type
INFECTION_MAP = {
    0: "motor-flag-manipulation",
    1: "timer-manipulation",
    2: "timer-value-corruption",
    3: "counter-overflow",
    4: "status-flag-manipulation",
    5: "sensor-manipulation",
}


def classify_infection(change: dict) -> str:
    """Determine the infection type from a change record."""
    reg = change.get("register")
    if reg in INFECTION_MAP:
        return INFECTION_MAP[reg]
    return f"unknown-register-{reg}"


# ---------------------------------------------------------------------------
# Submission result
# ---------------------------------------------------------------------------

@dataclass
class SubmitResult:
    ok: bool
    task_id: str = ""
    queue_size: int = 0
    error: str = ""


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

def submit_to_scheduler(
    plc_id: str,
    infection_type: str,
    scheduler_url: str = DEFAULT_SCHEDULER_URL,
    detected_at: str | None = None,
    timeout_s: float = 5.0,
) -> SubmitResult:
    """
    POST an infection event to the scheduler. Returns a SubmitResult.

    The scheduler acknowledges with 202 Accepted and a task_id; the actual
    processing happens asynchronously on the scheduler's worker thread.
    """
    url = f"{scheduler_url.rstrip('/')}/tasks/submit"
    payload = {
        "plc_id": plc_id,
        "infection_type": infection_type,
        "detected_at": detected_at or
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            data = json.loads(resp.read().decode())
            log.info(f"submitted infection: task_id={data.get('task_id')} "
                     f"queue_size={data.get('queue_size')}")
            return SubmitResult(
                ok=True,
                task_id=data.get("task_id", ""),
                queue_size=data.get("queue_size", 0),
            )
    except urllib.error.HTTPError as e:
        msg = f"HTTP {e.code}: {e.read().decode()[:200]}"
        log.error(f"scheduler rejected: {msg}")
        return SubmitResult(ok=False, error=msg)
    except urllib.error.URLError as e:
        msg = f"cannot reach scheduler at {scheduler_url}: {e.reason}"
        log.error(msg)
        return SubmitResult(ok=False, error=msg)
    except Exception as e:
        log.error(f"submission failed: {e}")
        return SubmitResult(ok=False, error=str(e))


# ---------------------------------------------------------------------------
# High-level helper — submit every change from a diff report
# ---------------------------------------------------------------------------

def report_infection(
    plc_id: str,
    changes: list[dict],
    scheduler_url: str = DEFAULT_SCHEDULER_URL,
) -> list[SubmitResult]:
    """
    Called by the detection pipeline after a diff. Submits one task per
    changed register (or a single task if you prefer — see below).

    Returns a list of SubmitResults, one per change.
    """
    results = []
    for ch in changes:
        itype = classify_infection(ch)
        r = submit_to_scheduler(plc_id, itype, scheduler_url)
        results.append(r)
    return results


# ---------------------------------------------------------------------------
# Alternative — single task covering all changes
# ---------------------------------------------------------------------------

def report_infection_aggregated(
    plc_id: str,
    changes: list[dict],
    scheduler_url: str = DEFAULT_SCHEDULER_URL,
) -> SubmitResult:
    """
    Submit one task with the dominant infection type when there are
    multiple changes. Use this when you don't want one task per register.
    """
    if not changes:
        return SubmitResult(ok=False, error="no changes to report")

    # pick the "first" register as representative
    itype = classify_infection(changes[0])
    if len(changes) > 1:
        itype += f" (+{len(changes) - 1} more)"
    return submit_to_scheduler(plc_id, itype, scheduler_url)