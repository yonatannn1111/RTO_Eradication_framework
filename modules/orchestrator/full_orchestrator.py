"""
Full incident-response orchestrator (Task 27).

Listens for forensic alerts on every configured PLC, queries the safety
scheduler for a safe window, and executes the eradication cycle when the
scheduler says NOW. Runs all PLCs in parallel via asyncio tasks and logs
every event to SQLite.
"""
import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .events_db import EventsDB


LOG = logging.getLogger("orchestrator.full")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class PLCConfig:
    plc_id: str
    modbus_port: int = 502
    s7_port: int = 1102
    trusted_snapshot: str = ""
    watch_registers: dict = field(default_factory=dict)


@dataclass
class OrchestratorConfig:
    plc_ip: str = "127.0.0.1"
    safety_url: str = "http://127.0.0.1:5003"
    output_dir: str = "output"
    db_path: str = "output/orchestrator_events.db"
    poll_interval_s: float = 5.0
    detect_timeout_s: float = 60.0
    max_cycles_per_plc: int = 3
    plcs: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Alert listener
# ---------------------------------------------------------------------------

class AlertListener:
    """
    Background thread that watches one or more PLCs for register changes
    and pushes alerts onto an asyncio queue via a thread-safe bridge.
    """

    def __init__(self, cfg: OrchestratorConfig, loop: asyncio.AbstractEventLoop):
        self.cfg = cfg
        self.loop = loop
        self.queue: asyncio.Queue = asyncio.Queue()
        self._tasks = []
        self._stop = False

    def start_all(self):
        """Start one watcher thread per PLC."""
        import threading
        from modules.forensics.watcher import RegisterWatcher, DEFAULT_WATCH

        for plc in self.cfg.plcs:
            baseline = dict(plc.watch_registers or DEFAULT_WATCH)

            def make_runner(plc=plc, baseline=baseline):
                def run():
                    LOG.info(f"[{plc.plc_id}] alert listener started")
                    while not self._stop:
                        w = RegisterWatcher(
                            self.cfg.plc_ip,
                            port=plc.modbus_port,
                            baseline=baseline,
                            poll_interval=0.2,
                            timeout_s=self.cfg.detect_timeout_s,
                        )
                        w.start()
                        event = w.wait()
                        if event is None:
                            continue
                        alert = {
                            "plc_id": plc.plc_id,
                            "detected_at": event.detected_at,
                            "elapsed_s": event.elapsed_s,
                            "changes": event.all_changes,
                        }
                        # thread-safe push into the event loop's queue
                        self.loop.call_soon_threadsafe(
                            self.queue.put_nowait, alert,
                        )
                        LOG.info(f"[{plc.plc_id}] alert queued: "
                                 f"{event.all_changes[0]}")
                return run

            t = threading.Thread(target=make_runner(), daemon=True)
            t.start()
            self._tasks.append(t)

    def stop(self):
        self._stop = True
        for t in self._tasks:
            t.join(timeout=1)


# ---------------------------------------------------------------------------
# Per-PLC incident response cycle
# ---------------------------------------------------------------------------

async def incident_response_cycle(
    plc: PLCConfig,
    alert: dict,
    cfg: OrchestratorConfig,
    db: EventsDB,
) -> dict:
    """
    One full cycle for one PLC. Runs as an asyncio task so multiple PLCs
    proceed in parallel.
    """
    plc_id = plc.plc_id
    cycle_result = {
        "plc_id": plc_id,
        "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "outcome": "unknown",
    }

    # --- 0. alert received -------------------------------------------------
    raw_changes = alert.get("changes", [])
    
    # THE FIX: Format changes exactly how the Streamlit dashboard expects them
    formatted_changes = [
        {
            "register": c["register"],
            "baseline": c["baseline"],
            "observed": c["observed"]
        }
        for c in raw_changes
    ]

    db.log(plc_id, "alert_received",
           {"changes": formatted_changes,
            "detected_at": alert.get("detected_at")})
    LOG.info(f"[{plc_id}] cycle start — alert: {formatted_changes}")

    # Save the detection log for the Streamlit dashboard to read
    try:
        # Create a run directory in output/ for the dashboard to find
        run_dir = Path(cfg.output_dir) / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        run_dir.mkdir(parents=True, exist_ok=True)
        
        detection_payload = {
            "status": "detected",
            "detected_at": alert.get("detected_at"),
            "elapsed_s": alert.get("elapsed_s"),
            "changes": formatted_changes,
        }
        (run_dir / "detection.json").write_text(json.dumps(detection_payload, indent=2, default=str))
        
        # We also need a comparison.json for the dashboard to show severity
        comparison_payload = {
            "total_changes": len(formatted_changes),
            "changes": [{"offset": c["register"] * 2, "severity": "high"} for c in formatted_changes],
            "changes_by_severity": {"high": len(formatted_changes)},
            "changes_by_area": {"DB1": len(formatted_changes)}
        }
        (run_dir / "comparison.json").write_text(json.dumps(comparison_payload, indent=2, default=str))
    except Exception as e:
        LOG.warning(f"failed to write dashboard alert files: {e}")

    # --- 1. pre-snapshot (before any changes) ------------------------------
    try:
        from modules.forensics import capture_pre_eradication
        loop = asyncio.get_event_loop()
        pre = await loop.run_in_executor(
            None,
            lambda: capture_pre_eradication(
                cfg.plc_ip,
                infection_snapshot=None,
                output_dir=str(cfg.output_dir),
                tcp_port=plc.s7_port,
            ),
        )
        db.log(plc_id, "snapshot_before",
               {"path": pre["path"], "sha256": pre["sha256_hash"]}, ok=True)
        LOG.info(f"[{plc_id}] pre snapshot: {Path(pre['path']).name}")
    except Exception as e:
        db.log(plc_id, "snapshot_before", {"error": str(e)}, ok=False)
        cycle_result["outcome"] = "snapshot_before_failed"
        return cycle_result

    # --- 2. query scheduler ------------------------------------------------
    try:
        from modules.safety import compute_safe_window  # fallback
        from modules.orchestrator.scheduler_connector import fetch_decisions
        from modules.orchestrator.scheduler_connector import ConnectorConfig

        loop = asyncio.get_event_loop()
        connector_cfg = ConnectorConfig(
            safety_url=cfg.safety_url,
            plc_ip=cfg.plc_ip,
            plc_s7_port=plc.s7_port,
            trusted_snapshot=plc.trusted_snapshot,
        )
        decision_payload = await loop.run_in_executor(
            None, lambda: fetch_decisions(connector_cfg),
        )
        if not decision_payload.get("ok"):
            raise RuntimeError(decision_payload.get("error", "unknown"))

        belts = decision_payload.get("belts", {})
        decision = belts.get(plc_id) or {}
        window_action = decision.get("action", "DELAY")
        window_minutes = decision.get("minutes")
        window_reason = decision.get("reason", "")

        db.log(plc_id, "safe_window_decision",
               {"action": window_action, "minutes": window_minutes,
                "reason": window_reason})
        LOG.info(f"[{plc_id}] scheduler says {window_action} "
                 f"({window_minutes} min): {window_reason}")
    except Exception as e:
        db.log(plc_id, "safe_window_decision", {"error": str(e)}, ok=False)
        cycle_result["outcome"] = "scheduler_query_failed"
        return cycle_result

    # --- 3. act on the verdict ---------------------------------------------
    if window_action == "WAIT":
        wait_min = window_minutes or 1
        # cap for demo purposes — in production, wait the full time
        wait_s = min(wait_min * 60, 30.0)
        LOG.info(f"[{plc_id}] WAIT {wait_min} min — sleeping {wait_s}s "
                 f"(capped for demo)")
        await asyncio.sleep(wait_s)
        # re-trigger a cycle with a synthetic alert so we re-query
        return await incident_response_cycle(
            plc, {"changes": [], "detected_at": "retry"}, cfg, db,
        )

    if window_action == "DELAY":
        LOG.info(f"[{plc_id}] DELAY — skipping this cycle")
        cycle_result["outcome"] = "delayed"
        db.log(plc_id, "cycle_complete", {"outcome": "delayed"})
        return cycle_result

    # window_action == "NOW"
    # --- 4. final snapshot ------------------------------------------------
    try:
        from modules.forensics import capture_post_eradication
        loop = asyncio.get_event_loop()
        post = await loop.run_in_executor(
            None,
            lambda: capture_post_eradication(
                cfg.plc_ip,
                pre_eradication_snapshot=pre["path"],
                output_dir=str(cfg.output_dir),
                tcp_port=plc.s7_port,
            ),
        )
        db.log(plc_id, "snapshot_final",
               {"path": post["path"], "sha256": post["sha256_hash"]}, ok=True)
    except Exception as e:
        db.log(plc_id, "snapshot_final", {"error": str(e)}, ok=False)
        cycle_result["outcome"] = "snapshot_final_failed"
        return cycle_result

    # --- 5. restore --------------------------------------------------------
    db.log(plc_id, "restore_start",
           {"trusted": plc.trusted_snapshot})
    try:
        from modules.forensics import restore_with_retry
        loop = asyncio.get_event_loop()
        ok, history, report = await loop.run_in_executor(
            None,
            lambda: restore_with_retry(
                plc.trusted_snapshot, cfg.plc_ip,
                tcp_port=plc.s7_port,
                max_attempts=3,
                retry_delay_s=2.0,
                raise_on_failure=False,
            ),
        )
        db.log(plc_id, "restore_end",
               {"ok": ok, "attempts": len(history)}, ok=ok)
        LOG.info(f"[{plc_id}] restore ok={ok} attempts={len(history)}")
    except Exception as e:
        db.log(plc_id, "restore_end", {"error": str(e)}, ok=False)
        cycle_result["outcome"] = "restore_failed"
        return cycle_result

    # --- 6. validate -------------------------------------------------------
    try:
        from modules.forensics import validate
        loop = asyncio.get_event_loop()
        valid, report = await loop.run_in_executor(
            None,
            lambda: validate(plc.trusted_snapshot, cfg.plc_ip,
                             tcp_port=plc.s7_port),
        )
        db.log(plc_id, "validate_result",
               {"valid": valid, "overall": report.get("overall")}, ok=valid)
        LOG.info(f"[{plc_id}] validation: "
                 f"{'PASS' if valid else 'FAIL'}")
        cycle_result["outcome"] = "restored" if valid else "validation_failed"
    except Exception as e:
        db.log(plc_id, "validate_result", {"error": str(e)}, ok=False)
        cycle_result["outcome"] = "validation_error"

    db.log(plc_id, "cycle_complete", {"outcome": cycle_result["outcome"]})
    cycle_result["ended_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return cycle_result


# ---------------------------------------------------------------------------
# Main runner — one worker per PLC
# ---------------------------------------------------------------------------

async def run_full_orchestrator(cfg: OrchestratorConfig) -> list[dict]:
    """
    Start the alert listener, dispatch per-PLC workers in parallel, wait
    until every PLC has completed `max_cycles_per_plc` cycles or the
    listener is stopped.
    """
    db = EventsDB(cfg.db_path)
    LOG.info(f"=== orchestrator start — {len(cfg.plcs)} PLC(s) ===")
    LOG.info(f"    db: {cfg.db_path}")

    loop = asyncio.get_event_loop()
    listener = AlertListener(cfg, loop)
    listener.start_all()

    # per-PLC cycle counters
    cycles: dict[str, int] = {p.plc_id: 0 for p in cfg.plcs}
    results: list[dict] = []

    # worker per PLC that drains alerts for its own ID
    async def worker(plc: PLCConfig):
        while cycles[plc.plc_id] < cfg.max_cycles_per_plc:
            try:
                alert = await asyncio.wait_for(
                    listener.queue.get(),
                    timeout=cfg.detect_timeout_s * 2,
                )
            except asyncio.TimeoutError:
                LOG.info(f"[{plc.plc_id}] no alerts within timeout — exiting")
                return

            # filter to this PLC's alerts
            if alert["plc_id"] != plc.plc_id:
                # re-queue for the right worker
                await listener.queue.put(alert)
                await asyncio.sleep(0.05)
                continue

            cycles[plc.plc_id] += 1
            LOG.info(f"[{plc.plc_id}] cycle "
                     f"{cycles[plc.plc_id]}/{cfg.max_cycles_per_plc}")

            result = await incident_response_cycle(plc, alert, cfg, db)
            results.append(result)

    try:
        await asyncio.gather(*(worker(p) for p in cfg.plcs))
    except KeyboardInterrupt:
        LOG.info("orchestrator interrupted")
    finally:
        listener.stop()
        db.close()

    LOG.info(f"=== orchestrator done — {len(results)} cycles ===")
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _default_plcs(cfg_plc_ip: str, trusted: str) -> list:
    from modules.forensics.watcher import DEFAULT_WATCH
    return [
        PLCConfig(
            plc_id="plc_a",
            trusted_snapshot=trusted,
            watch_registers=dict(DEFAULT_WATCH),
        ),
    ]


def _parse_args():
    import argparse
    p = argparse.ArgumentParser(
        description="Full incident-response orchestrator (Task 27)"
    )
    p.add_argument("--plc", default="127.0.0.1")
    p.add_argument("--safety-url", default="http://127.0.0.1:5003")
    p.add_argument("--trusted-snapshot", required=True)
    p.add_argument("--output-dir", default="output")
    p.add_argument("--db", default="output/orchestrator_events.db")
    p.add_argument("--poll-interval", type=float, default=5.0)
    p.add_argument("--detect-timeout", type=float, default=60.0)
    p.add_argument("--max-cycles", type=int, default=3)
    p.add_argument("--verbose", "-v", action="store_true")
    return p.parse_args()


def main():
    args = _parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    cfg = OrchestratorConfig(
        plc_ip=args.plc,
        safety_url=args.safety_url,
        output_dir=args.output_dir,
        db_path=args.db,
        poll_interval_s=args.poll_interval,
        detect_timeout_s=args.detect_timeout,
        max_cycles_per_plc=args.max_cycles,
        plcs=_default_plcs(args.plc, args.trusted_snapshot),
    )

    results = asyncio.run(run_full_orchestrator(cfg))

    print("\n=== Per-PLC outcomes ===")
    for r in results:
        print(f"  {r['plc_id']}: {r['outcome']} "
              f"({r.get('started_at')} → {r.get('ended_at', '-')})")


if __name__ == "__main__":
    main()