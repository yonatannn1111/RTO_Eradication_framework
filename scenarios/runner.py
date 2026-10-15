"""
Scenario runner — drives each attack, waits for the pipeline to respond,
and measures recovery.

Because the incident-response pipeline is event-driven, we simulate
what a real deployment would do:

    1. Trigger the attack (via the attack_simulation module)
    2. Wait until RegisterWatcher detects the change
    3. Start the stopwatch
    4. Run restore_with_retry() against the trusted snapshot
    5. Validate the restore
    6. Stop the stopwatch, record metrics

The runner is deterministic when the attacker is local — you can run
it against OpenPLC + S7 simulator or against a pure-Python mock.
"""
import logging
import time
from dataclasses import dataclass
from datetime import datetime

LOG = logging.getLogger("scenarios.runner")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class ScenarioConfig:
    plc_ip: str = "127.0.0.1"
    modbus_port: int = 502
    s7_port: int = 1102
    trusted_snapshot: str = ""
    detection_timeout_s: float = 30.0
    bags_per_second: float = 2.0          # for mis-sorted-bag estimate
    reject_rate_during_outage: float = 0.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_register(register: int, value: int, cfg: ScenarioConfig):
    """Convenience: write a holding register on the target PLC."""
    from pymodbus.client import ModbusTcpClient
    c = ModbusTcpClient(cfg.plc_ip, port=cfg.modbus_port)
    c.connect()
    try:
        c.write_register(address=register, value=value)
    finally:
        c.close()


def _wait_for_detection(baseline: dict, cfg: ScenarioConfig):
    """Block until RegisterWatcher sees a change in any watched register."""
    from modules.forensics.watcher import RegisterWatcher

    w = RegisterWatcher(
        cfg.plc_ip,
        port=cfg.modbus_port,
        baseline=baseline,
        poll_interval=0.2,
        timeout_s=cfg.detection_timeout_s,
    )
    w.start()
    return w.wait()


def _run_restore(cfg: ScenarioConfig):
    """Run the restore pipeline and return (ok, attempts, error)."""
    if not cfg.trusted_snapshot:
        return False, 0, "no trusted_snapshot configured"
    try:
        from modules.forensics import restore_with_retry
        ok, history, _ = restore_with_retry(
            cfg.trusted_snapshot, cfg.plc_ip,
            tcp_port=cfg.s7_port,
            max_attempts=3,
            retry_delay_s=2.0,
            raise_on_failure=False,
        )
        return ok, len(history), ""
    except Exception as e:
        return False, 0, f"{type(e).__name__}: {e}"


def _validate(cfg: ScenarioConfig) -> bool:
    """Confirm the PLC matches the trusted snapshot."""
    try:
        from modules.forensics import validate
        ok, _ = validate(
            cfg.trusted_snapshot, cfg.plc_ip,
            tcp_port=cfg.s7_port,
        )
        return ok
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Single-scenario driver
# ---------------------------------------------------------------------------

def run_scenario(
    name: str,
    trigger_fn,
    baseline: dict,
    cfg: ScenarioConfig,
) -> "ScenarioResult":
    """
    Run one scenario end-to-end and return its metrics.

    Parameters
    ----------
    name       : human-readable scenario name
    trigger_fn : callable that performs the attack
    baseline   : expected register values before the attack
    cfg        : shared configuration
    """
    from scenarios.metrics import (
        ScenarioResult, Stopwatch, estimate_mis_sorted_bags,
    )

    LOG.info(f"=== scenario '{name}' starting ===")
    result = ScenarioResult(
        scenario=name,
        started_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
    sw = Stopwatch()

    try:
        # 1. attack
        trigger_fn()
        LOG.info(f"[{name}] attack fired")

        # 2. wait for detection
        alert = _wait_for_detection(baseline, cfg)
        if alert is None:
            result.notes = "detection timeout — no change observed"
            LOG.warning(f"[{name}] detection timeout")
            result.ended_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            return result

        # 3. start stopwatch (downtime begins here)
        sw.start()
        LOG.info(f"[{name}] detected at {alert.detected_at}")

        # 4. restore
        ok, attempts, error = _run_restore(cfg)
        result.restore_attempts = attempts
        LOG.info(f"[{name}] restore ok={ok} attempts={attempts}")

        # 5. validate
        validated = _validate(cfg)
        result.validation_pass = validated
        LOG.info(f"[{name}] validation {'PASS' if validated else 'FAIL'}")

        # 6. stop stopwatch
        downtime = sw.stop()
        result.downtime_s = downtime

        # 7. forensic recovery %
        if validated:
            result.forensic_recovery_pct = 100.0
        elif ok:
            result.forensic_recovery_pct = 75.0
        else:
            result.forensic_recovery_pct = 0.0

        # 8. mis-sorted bags
        result.mis_sorted_bags = estimate_mis_sorted_bags(
            downtime_s=downtime,
            bags_per_second=cfg.bags_per_second,
            reject_rate=cfg.reject_rate_during_outage,
        )

        result.notes = error or "ok"
        result.details = {
            "detected_at": alert.detected_at,
            "changes": alert.all_changes,
            "downtime_s": downtime,
        }

    except Exception as e:
        result.notes = f"exception: {type(e).__name__}: {e}"
        LOG.exception(f"[{name}] scenario failed")

    result.ended_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    LOG.info(f"=== scenario '{name}' done: "
             f"recovery={result.forensic_recovery_pct:.0f}% "
             f"downtime={result.downtime_s:.2f}s "
             f"mis-sorted={result.mis_sorted_bags} ===")
    return result