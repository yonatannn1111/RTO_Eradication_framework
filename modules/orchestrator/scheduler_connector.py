"""
Scheduler-Orchestrator connector (Task 26).

Polls the safety scheduler's /safety/status endpoint and reacts to the
verdict for each belt:

    NOW    -> execute restore immediately
    WAIT N -> sleep N minutes, then re-poll
    DELAY  -> log and re-poll after a fixed cooldown

Every action is written to a JSONL log so the entire decision chain
is auditable.
"""
import argparse
import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path

LOG = logging.getLogger("orchestrator.connector")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class ConnectorConfig:
    plc_ip: str = "127.0.0.1"
    plc_modbus_port: int = 502
    plc_s7_port: int = 1102
    safety_url: str = "http://127.0.0.1:5003"
    trusted_snapshot: str = ""              # clean baseline to restore from
    poll_interval_s: float = 10.0            # how often to ask the scheduler
    delay_cooldown_s: float = 60.0           # how long to wait when verdict is DELAY
    max_actions: int = 10                    # cap on restores in one run
    action_log_path: str = "logs/connector_actions.jsonl"
    belt_filter: str | None = None           # optional: only act on one belt


# ---------------------------------------------------------------------------
# Decision record
# ---------------------------------------------------------------------------

@dataclass
class ConnectorAction:
    timestamp: str
    belt_id: str
    verdict: str                            # NOW / WAIT / DELAY / ERROR
    minutes: int | None = None
    reason: str = ""
    action_taken: str = ""                  # restored / waited / skipped / failed
    restore_ok: bool | None = None
    restore_attempts: int = 0
    error: str = ""

    def as_dict(self):
        return asdict(self)


# ---------------------------------------------------------------------------
# HTTP poll
# ---------------------------------------------------------------------------

def fetch_decisions(cfg: ConnectorConfig, timeout_s: float = 2.0) -> dict:
    """
    Return the scheduler's per-belt decision dict, or an error-wrapped
    payload if the scheduler is unreachable.
    """
    url = f"{cfg.safety_url.rstrip('/')}/safety/status"
    try:
        with urllib.request.urlopen(url, timeout=timeout_s) as resp:
            data = json.loads(resp.read().decode())
            return {"ok": True, "belts": data.get("belts", {}),
                    "raw": data}
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"HTTP {e.code}",
                "belts": {}}
    except urllib.error.URLError as e:
        return {"ok": False,
                "error": f"scheduler unreachable: {e.reason}",
                "belts": {}}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}",
                "belts": {}}


# ---------------------------------------------------------------------------
# Action log
# ---------------------------------------------------------------------------

class ActionLogger:
    """Append-only JSONL log of every action the connector takes."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, action: ConnectorAction):
        with self.path.open("a") as f:
            f.write(json.dumps(action.as_dict(), default=str) + "\n")

    def read_all(self) -> list[dict]:
        if not self.path.exists():
            return []
        with self.path.open() as f:
            return [json.loads(line) for line in f if line.strip()]


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

def _do_restore(cfg: ConnectorConfig) -> tuple[bool, int, str]:
    """
    Attempt the restore and return (ok, attempts, error).
    """
    if not cfg.trusted_snapshot or not Path(cfg.trusted_snapshot).exists():
        return False, 0, f"trusted_snapshot missing: {cfg.trusted_snapshot}"

    try:
        from modules.forensics import restore_with_retry
        ok, history, last = restore_with_retry(
            cfg.trusted_snapshot, cfg.plc_ip,
            tcp_port=cfg.plc_s7_port,
            max_attempts=3,
            retry_delay_s=2.0,
            raise_on_failure=False,
        )
        return ok, len(history), ""
    except Exception as e:
        return False, 0, f"{type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run_connector(cfg: ConnectorConfig,
                  logger: ActionLogger | None = None) -> list[ConnectorAction]:
    """
    Poll the scheduler. React to each belt's verdict. Log every action.
    Runs until `max_actions` restores have been executed, or interrupted.
    """
    log = logger or ActionLogger(cfg.action_log_path)
    actions: list[ConnectorAction] = []
    restores_done = 0

    LOG.info(f"=== connector start — polling {cfg.safety_url} "
             f"every {cfg.poll_interval_s}s ===")
    LOG.info(f"    trusted snapshot: {cfg.trusted_snapshot or '(none)'}")
    LOG.info(f"    action log      : {cfg.action_log_path}")

    try:
        while restores_done < cfg.max_actions:
            polled_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            payload = fetch_decisions(cfg)

            if not payload["ok"]:
                rec = ConnectorAction(
                    timestamp=polled_at,
                    belt_id="*",
                    verdict="ERROR",
                    reason=payload["error"],
                    action_taken="none",
                )
                log.write(rec)
                actions.append(rec)
                LOG.error(f"poll failed: {payload['error']}")
                time.sleep(cfg.poll_interval_s)
                continue

            belts = payload["belts"]
            if not belts:
                LOG.info("no belts in scheduler response — waiting")
                time.sleep(cfg.poll_interval_s)
                continue

            # Optionally filter to one belt
            if cfg.belt_filter:
                belts = {cfg.belt_filter: belts.get(cfg.belt_filter)} \
                    if cfg.belt_filter in belts else {}

            for belt_id, decision in belts.items():
                if decision is None:
                    continue

                verdict = decision.get("action", "UNKNOWN")
                minutes = decision.get("minutes")
                reason = decision.get("reason", "")

                LOG.info(f"[{belt_id}] verdict={verdict} "
                         f"minutes={minutes} reason={reason!r}")

                action_taken = "none"
                restore_ok = None
                restore_attempts = 0
                error = ""

                if verdict == "NOW":
                    LOG.info(f"[{belt_id}] NOW → executing restore")
                    restore_ok, restore_attempts, error = _do_restore(cfg)
                    action_taken = "restored" if restore_ok else "restore_failed"
                    if restore_ok:
                        restores_done += 1
                        LOG.info(f"[{belt_id}] restore OK "
                                 f"({restore_attempts} attempt(s))")
                    else:
                        LOG.error(f"[{belt_id}] restore FAILED: {error}")

                elif verdict == "WAIT":
                    wait_min = minutes if minutes is not None else 1
                    wait_s = wait_min * 60
                    LOG.info(f"[{belt_id}] WAIT {wait_min} min "
                             f"→ sleeping {wait_s}s")
                    action_taken = f"waited {wait_min} min"
                    # For testing/demo purposes, we cap the wait at a reasonable value
                    capped = min(wait_s, 60.0)
                    if capped < wait_s:
                        LOG.info(f"[{belt_id}] wait capped at {capped}s for demo")
                    time.sleep(capped)

                elif verdict == "DELAY":
                    LOG.info(f"[{belt_id}] DELAY → cooling down "
                             f"{cfg.delay_cooldown_s}s")
                    action_taken = "delayed"
                    time.sleep(min(cfg.delay_cooldown_s, 30.0))

                else:
                    LOG.warning(f"[{belt_id}] unknown verdict {verdict!r}")
                    action_taken = "skipped"

                rec = ConnectorAction(
                    timestamp=polled_at,
                    belt_id=belt_id,
                    verdict=verdict,
                    minutes=minutes,
                    reason=reason,
                    action_taken=action_taken,
                    restore_ok=restore_ok,
                    restore_attempts=restore_attempts,
                    error=error,
                )
                log.write(rec)
                actions.append(rec)

                if restores_done >= cfg.max_actions:
                    break

            if restores_done >= cfg.max_actions:
                break

            time.sleep(cfg.poll_interval_s)

    except KeyboardInterrupt:
        LOG.info("connector interrupted by operator")

    LOG.info(f"=== connector done — {len(actions)} actions logged, "
             f"{restores_done} restores executed ===")
    return actions


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(
        description="Scheduler-Orchestrator connector (Task 26)"
    )
    p.add_argument("--plc", default="127.0.0.1")
    p.add_argument("--modbus-port", type=int, default=502)
    p.add_argument("--s7-port", type=int, default=1102)
    p.add_argument("--safety-url", default="http://127.0.0.1:5003")
    p.add_argument("--trusted-snapshot", required=True)
    p.add_argument("--poll-interval", type=float, default=10.0)
    p.add_argument("--delay-cooldown", type=float, default=60.0)
    p.add_argument("--max-actions", type=int, default=10)
    p.add_argument("--action-log", default="logs/connector_actions.jsonl")
    p.add_argument("--belt", default=None,
                   help="Only act on this belt (default: all)")
    p.add_argument("--verbose", "-v", action="store_true")
    return p.parse_args()


def main():
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    cfg = ConnectorConfig(
        plc_ip=args.plc,
        plc_modbus_port=args.modbus_port,
        plc_s7_port=args.s7_port,
        safety_url=args.safety_url,
        trusted_snapshot=args.trusted_snapshot,
        poll_interval_s=args.poll_interval,
        delay_cooldown_s=args.delay_cooldown,
        max_actions=args.max_actions,
        action_log_path=args.action_log,
        belt_filter=args.belt,
    )
    run_connector(cfg)


if __name__ == "__main__":
    main()