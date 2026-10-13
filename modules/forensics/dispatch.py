"""
Forensic → Scheduler dispatch (Task 22).

Synchronous bridge: sends a forensic alert to the scheduler's /dispatch
endpoint and returns the safe window. Every interaction is logged with
timing so the <2s SLA can be verified.
"""
import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_DIR = Path("logs")
LOG_FILE = LOG_DIR / "bridge.log"
_configured = False


def _get_logger():
    global _configured
    logger = logging.getLogger("forensics.dispatch")
    if not _configured:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        fmt = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        fh = logging.FileHandler(LOG_FILE)
        fh.setFormatter(fmt)
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        logger.setLevel(logging.INFO)
        logger.addHandler(fh)
        logger.addHandler(sh)
        logger.propagate = False
        _configured = True
    return logger


log = _get_logger()


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------

@dataclass
class DispatchResult:
    ok: bool
    belt_id: str = ""
    action: str = ""
    minutes: int | None = None
    reason: str = ""
    elapsed_s: float = 0.0
    error: str = ""
    raw: dict = field(default_factory=dict)

    def as_dict(self):
        return {
            "ok": self.ok,
            "belt_id": self.belt_id,
            "action": self.action,
            "minutes": self.minutes,
            "reason": self.reason,
            "elapsed_s": round(self.elapsed_s, 3),
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# Core dispatch
# ---------------------------------------------------------------------------

DEFAULT_SCHEDULER_URL = "http://127.0.0.1:5003"
SLA_S = 2.0


def dispatch_to_scheduler(
    belt_id: str,
    infection_type: str,
    detected_at: str | None = None,
    scheduler_url: str = DEFAULT_SCHEDULER_URL,
    timeout_s: float = SLA_S,
    live_inputs: dict | None = None,
    criticality: str = "medium",
) -> DispatchResult:
    """
    Send a forensic alert to the scheduler and return the safe window.

    Parameters
    ----------
    belt_id         : identifier of the affected belt
    infection_type  : human-readable infection category
    detected_at     : ISO-ish timestamp of the alert (defaults to now)
    scheduler_url   : base URL of the scheduler API
    timeout_s       : hard timeout (default 2.0s — enforces the SLA)
    live_inputs     : optional dict {queue_now, arrival_rate, service_rate}
                      to skip the scheduler's own PLC read
    criticality     : belt criticality level
    """
    started = time.time()
    ts = detected_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    payload = {
        "belt_id": belt_id,
        "infection_type": infection_type,
        "detected_at": ts,
        "criticality": criticality,
    }
    if live_inputs:
        payload.update(live_inputs)

    body = json.dumps(payload).encode()
    url = f"{scheduler_url.rstrip('/')}/dispatch"
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )

    log.info(f"dispatch request → {url} "
             f"belt={belt_id} type={infection_type} at={ts}")

    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            data = json.loads(resp.read().decode())
            elapsed = time.time() - started

            window = data.get("window", {})
            result = DispatchResult(
                ok=True,
                belt_id=data.get("belt_id", belt_id),
                action=window.get("action", ""),
                minutes=window.get("minutes"),
                reason=window.get("reason", ""),
                elapsed_s=elapsed,
                raw=data,
            )

            log.info(
                f"dispatch response ← belt={belt_id} "
                f"action={result.action} minutes={result.minutes} "
                f"elapsed={elapsed:.3f}s"
            )

            if elapsed > SLA_S:
                log.warning(
                    f"SLA breach: {elapsed:.3f}s > {SLA_S}s for belt={belt_id}"
                )

            return result

    except urllib.error.HTTPError as e:
        elapsed = time.time() - started
        msg = f"HTTP {e.code}: {e.read().decode()[:200]}"
        log.error(f"dispatch failed (HTTP): {msg} elapsed={elapsed:.3f}s")
        return DispatchResult(
            ok=False, belt_id=belt_id, elapsed_s=elapsed, error=msg,
        )

    except urllib.error.URLError as e:
        elapsed = time.time() - started
        msg = f"scheduler unreachable at {scheduler_url}: {e.reason}"
        log.error(f"dispatch failed (URLError): {msg} elapsed={elapsed:.3f}s")
        return DispatchResult(
            ok=False, belt_id=belt_id, elapsed_s=elapsed, error=msg,
        )

    except Exception as e:
        elapsed = time.time() - started
        msg = f"{type(e).__name__}: {e}"
        log.error(f"dispatch failed (unexpected): {msg} elapsed={elapsed:.3f}s")
        return DispatchResult(
            ok=False, belt_id=belt_id, elapsed_s=elapsed, error=msg,
        )


# ---------------------------------------------------------------------------
# Convenience wrapper for a diff/alert object
# ---------------------------------------------------------------------------

def dispatch_from_alert(
    alert: dict,
    belt_id: str,
    scheduler_url: str = DEFAULT_SCHEDULER_URL,
    **kwargs,
) -> DispatchResult:
    """
    Wrapper that takes an alert dict (from a diff report) and dispatches.

    Expected alert keys: register, severity, old_value, new_value.
    Falls back to a generic infection_type if not derivable.
    """
    reg = alert.get("register") or alert.get("offset", 0) // 2
    infection_type = alert.get("severity")
    if not infection_type:
        infection_type = f"register-{reg}-change"

    return dispatch_to_scheduler(
        belt_id=belt_id,
        infection_type=infection_type,
        detected_at=alert.get("timestamp"),
        scheduler_url=scheduler_url,
        **kwargs,
    )