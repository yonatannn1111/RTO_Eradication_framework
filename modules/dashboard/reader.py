"""
HTTP client for the dashboard. Every call returns a dict with either
the payload or an "error" key — the UI never crashes on a missing service.
"""
import logging
from datetime import datetime

import requests

from modules.dashboard.config import DashboardConfig


log = logging.getLogger("dashboard.reader")


def _get(url: str, timeout: float) -> dict:
    try:
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.Timeout:
        return {"error": f"timeout after {timeout}s", "url": url}
    except requests.exceptions.ConnectionError:
        return {"error": "service unreachable", "url": url}
    except requests.exceptions.HTTPError as e:
        return {"error": f"HTTP {e.response.status_code}", "url": url}
    except Exception as e:
        return {"error": str(e), "url": url}


def fetch_conveyor(cfg: DashboardConfig) -> dict:
    """Task 17 — /conveyor/status"""
    return _get(f"{cfg.conveyor_url}/conveyor/status", cfg.http_timeout_s)


def fetch_scheduler(cfg: DashboardConfig) -> dict:
    """Task 18 — /tasks/status"""
    return _get(f"{cfg.scheduler_url}/tasks/status", cfg.http_timeout_s)


def fetch_safety(cfg: DashboardConfig) -> dict:
    """Task 20 — /safety/status"""
    return _get(f"{cfg.safety_url}/safety/status", cfg.http_timeout_s)


def fetch_alerts_from_run_dir(run_dir: str = "output") -> list[dict]:
    """
    Read forensic alerts from the latest orchestrator run directory
    (Task 16). Each run has detection.json + comparison.json.
    """
    import json
    from pathlib import Path

    base = Path(run_dir)
    if not base.exists():
        return []

    runs = sorted(base.glob("run_*"), key=lambda p: p.name, reverse=True)
    if not runs:
        return []

    latest = runs[0]
    alerts = []

    det = latest / "detection.json"
    if det.exists():
        try:
            d = json.load(det.open())
            if d.get("status") == "detected":
                for ch in d.get("changes", []):
                    alerts.append({
                        "timestamp": d.get("detected_at", "?"),
                        "register": f"MW{ch.get('register', '?')}",
                        "baseline": ch.get("baseline", "?"),
                        "observed": ch.get("observed", "?"),
                        "run_dir": latest.name,
                        "severity": "unknown",
                    })
        except Exception as e:
            log.warning(f"could not parse {det}: {e}")

    comp = latest / "comparison.json"
    if comp.exists() and alerts:
        try:
            c = json.load(comp.open())
            # attach severity from the comparison report to each alert
            severities = {}
            for ch in c.get("changes", []):
                offset = ch.get("offset", -1)
                register = offset // 2 if offset >= 0 else -1
                severities[register] = ch.get("severity", "unknown")
            for a in alerts:
                reg_num = int(a["register"].replace("MW", ""))
                a["severity"] = severities.get(reg_num, "unknown")
        except Exception as e:
            log.warning(f"could not parse {comp}: {e}")

    return alerts


def gather_all(cfg: DashboardConfig) -> dict:
    """One-shot fetch of every service. Used by the Streamlit app."""
    return {
        "conveyor":  fetch_conveyor(cfg),
        "scheduler": fetch_scheduler(cfg),
        "safety":    fetch_safety(cfg),
        "alerts":    fetch_alerts_from_run_dir(),
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }