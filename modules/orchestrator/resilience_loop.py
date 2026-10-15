"""
Reinfection resistance loop (Task 25).

Repeatedly:
    1. wait for an infection (register change),
    2. pre-eradication snapshot,
    3. restore + validate,
    4. post-eradication snapshot,
    5. log cycle result, sleep, repeat.

Stops when `max_cycles` is reached or when the operator interrupts.
"""
import logging
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ..forensics import (
    capture_pre_eradication,
    capture_post_eradication,
    restore_with_retry,
    RestoreFailedError,
)
from ..forensics.watcher import RegisterWatcher, DEFAULT_WATCH


log = logging.getLogger("orchestrator.resilience")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class ResilienceConfig:
    plc_ip: str = "127.0.0.1"
    modbus_port: int = 502
    s7_port: int = 1102
    trusted_snapshot: str = ""            # clean baseline to restore from
    output_dir: str = "output"
    max_cycles: int = 5
    detect_timeout_s: float = 30.0
    inter_cycle_delay_s: float = 0.0
    watch_registers: dict = field(default_factory=lambda: dict(DEFAULT_WATCH))


# ---------------------------------------------------------------------------
# Result records
# ---------------------------------------------------------------------------

@dataclass
class CycleResult:
    cycle: int
    started_at: str
    ended_at: str = ""
    detected_change: str = ""
    pre_snapshot: str = ""
    restore_ok: bool = False
    restore_attempts: int = 0
    post_snapshot: str = ""
    error: str = ""


# ---------------------------------------------------------------------------
# Loop
# ---------------------------------------------------------------------------

def run_resilience_loop(cfg: ResilienceConfig) -> list[CycleResult]:
    """Run the resilience loop for up to `cfg.max_cycles` iterations."""
    run_dir = Path(cfg.output_dir) / f"resilience_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=True)
    log.info(f"=== resilience loop start — output {run_dir} ===")

    results: list[CycleResult] = []

    for cycle in range(1, cfg.max_cycles + 1):
        log.info(f"--- cycle {cycle}/{cfg.max_cycles} ---")
        result = CycleResult(
            cycle=cycle,
            started_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
        results.append(result)

        try:
            # --- 1. wait for infection -------------------------------------
            event = _wait_for_infection(cfg)
            if event is None:
                result.error = "no infection detected within timeout"
                log.warning(f"cycle {cycle}: {result.error}")
                result.ended_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                break

            reg = event.all_changes[0]["register"]
            baseline = event.all_changes[0]["baseline"]
            observed = event.all_changes[0]["observed"]
            result.detected_change = f"MW{reg}: {baseline} -> {observed}"
            log.info(f"cycle {cycle}: detected {result.detected_change}")

            # --- 2. pre-eradication snapshot -------------------------------
            pre = capture_pre_eradication(
                cfg.plc_ip,
                infection_snapshot=None,       # no separate infection file in this loop
                output_dir=str(run_dir),
                tcp_port=cfg.s7_port,
            )
            result.pre_snapshot = pre["path"]
            log.info(f"cycle {cycle}: pre_eradication snapshot "
                     f"{Path(pre['path']).name}")

            # --- 3. restore + validate -------------------------------------
            if cfg.trusted_snapshot and Path(cfg.trusted_snapshot).exists():
                try:
                    ok, history, report = restore_with_retry(
                        cfg.trusted_snapshot,
                        cfg.plc_ip,
                        tcp_port=cfg.s7_port,
                        max_attempts=3,
                        retry_delay_s=2.0,
                        raise_on_failure=False,
                    )
                except Exception as e:
                    ok = False
                    history = []
                    log.error(f"cycle {cycle}: restore exception: {e}")
                result.restore_ok = ok
                result.restore_attempts = len(history)
                log.info(f"cycle {cycle}: restore ok={ok} "
                         f"attempts={len(history)}")
            else:
                log.warning("cycle %d: no trusted_snapshot — skipping restore"
                            % cycle)
                result.restore_ok = False

            # --- 4. post-eradication snapshot ------------------------------
            post = capture_post_eradication(
                cfg.plc_ip,
                pre_eradication_snapshot=pre["path"],
                output_dir=str(run_dir),
                tcp_port=cfg.s7_port,
            )
            result.post_snapshot = post["path"]
            log.info(f"cycle {cycle}: post_eradication snapshot "
                     f"{Path(post['path']).name}")

        except Exception as e:
            result.error = f"{type(e).__name__}: {e}"
            log.exception(f"cycle {cycle} failed")

        result.ended_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if cfg.inter_cycle_delay_s:
            time.sleep(cfg.inter_cycle_delay_s)

    log.info(f"=== resilience loop done — {len(results)} cycles ===")
    return results


def _wait_for_infection(cfg: ResilienceConfig):
    """Block until a watched register changes from its baseline."""
    w = RegisterWatcher(
        cfg.plc_ip,
        port=cfg.modbus_port,
        baseline=dict(cfg.watch_registers),
        poll_interval=0.2,
        timeout_s=cfg.detect_timeout_s,
    )
    w.start()
    return w.wait()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(
        description="Reinfection resistance loop (Task 25)"
    )
    p.add_argument("--plc", default="127.0.0.1")
    p.add_argument("--modbus-port", type=int, default=502)
    p.add_argument("--s7-port", type=int, default=1102)
    p.add_argument("--trusted-snapshot", required=True,
                   help="Path to the clean snapshot to restore from")
    p.add_argument("--output-dir", default="output")
    p.add_argument("--max-cycles", type=int, default=5)
    p.add_argument("--detect-timeout", type=float, default=30.0)
    args = p.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    cfg = ResilienceConfig(
        plc_ip=args.plc,
        modbus_port=args.modbus_port,
        s7_port=args.s7_port,
        trusted_snapshot=args.trusted_snapshot,
        output_dir=args.output_dir,
        max_cycles=args.max_cycles,
        detect_timeout_s=args.detect_timeout,
    )

    results = run_resilience_loop(cfg)

    print("\n=== Cycle summary ===")
    for r in results:
        print(f"  cycle {r.cycle}: detected={r.detected_change!r} "
              f"restore_ok={r.restore_ok} attempts={r.restore_attempts} "
              f"error={r.error or '-'}")