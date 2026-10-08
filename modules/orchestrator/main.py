"""
End-to-end orchestrator (Task 16).

Pipeline stages
---------------
1. Infrastructure — verify PLC reachable
2. Snapshot       — capture clean baseline
3. Detection      — watch for register change
4. Dirty snapshot — captured within 1 s of detection
5. Diff           — compare clean vs dirty
6. Report         — write JSON + PDF
7. Dashboard      — build dashboard.json + dashboard.html
"""
import argparse
import json
import logging
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

LOG = logging.getLogger("orchestrator")


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def setup_logging(level=logging.INFO, log_file: Path | None = None):
    handlers = [logging.StreamHandler()]
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file))

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
        force=True,
    )


# ---------------------------------------------------------------------------
# Run directory
# ---------------------------------------------------------------------------

def make_run_dir(base: str = "output") -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    d = Path(base) / f"run_{ts}"
    (d / "snapshots").mkdir(parents=True, exist_ok=True)
    (d / "reports").mkdir(parents=True, exist_ok=True)
    LOG.info(f"run directory: {d}")
    return d


def _dump(path: Path, payload):
    path.write_text(json.dumps(payload, indent=2, default=str))


# ---------------------------------------------------------------------------
# Stages
# ---------------------------------------------------------------------------

def stage_infrastructure(config, run_dir):
    from modules.ot_infrastructure import verify_plc
    status = verify_plc(
        config["plc"]["ip"],
        modbus_port=config["plc"]["modbus_port"],
        s7_port=config["plc"]["s7_port"],
        https_port=config["plc"].get("https_port", 8443),
    )
    LOG.info(f"infrastructure: modbus={status.modbus_open} s7={status.s7_open} "
             f"https={status.https_open}")
    _dump(run_dir / "infrastructure.json", {
        "modbus_open": status.modbus_open,
        "s7_open": status.s7_open,
        "https_open": status.https_open,
        "errors": status.errors,
    })
    return {"status": status}


def stage_clean_snapshot(config, run_dir):
    from modules.forensics import capture
    snap = capture(
        config["plc"]["ip"],
        tcp_port=config["plc"].get("s7_port", 1102),
        db1_size=config["snapshot"]["db1_size"],
        db2_size=config["snapshot"]["db2_size"],
        merker_size=config["snapshot"]["merker_size"],
        output_dir=str(run_dir / "snapshots"),
    )
    # rename to clean_snapshot.json for the pipeline
    src = Path(snap["path"])
    dst = run_dir / "clean_snapshot.json"
    shutil.copy(src, dst)
    LOG.info(f"clean snapshot: {dst}")
    return {"path": str(dst)}


def stage_detect(config, run_dir, timeout_s=30):
    """Wait for a register change; timeout triggers a skip."""
    from modules.forensics.watcher import RegisterWatcher, DEFAULT_WATCH

    baseline = dict(DEFAULT_WATCH)
    w = RegisterWatcher(
        config["plc"]["ip"],
        port=config["plc"]["modbus_port"],
        baseline=baseline,
        poll_interval=0.05,
        timeout_s=timeout_s,
    )
    w.start()
    LOG.info(f"detection: watching for change (timeout {timeout_s}s)")
    event = w.wait()

    if event is None:
        LOG.warning("detection: no change within timeout — skipping rest")
        _dump(run_dir / "detection.json", {"status": "timeout"})
        return {"event": None}

    _dump(run_dir / "detection.json", {
        "status": "detected",
        "detected_at": event.detected_at,
        "elapsed_s": event.elapsed_s,
        "changes": event.all_changes,
    })
    return {"event": event}


def stage_dirty_snapshot(config, run_dir, detection):
    """Capture a fresh snapshot immediately after detection (<1 s)."""
    from modules.forensics import capture
    t0 = time.time()
    snap = capture(
        config["plc"]["ip"],
        tcp_port=config["plc"].get("s7_port", 1102),
        output_dir=str(run_dir / "snapshots"),
    )
    dt = time.time() - t0
    src = Path(snap["path"])
    dst = run_dir / "dirty_snapshot.json"
    shutil.copy(src, dst)
    LOG.info(f"dirty snapshot: {dst} (captured in {dt:.3f}s)")
    return {"path": str(dst), "capture_time_s": dt}


def stage_diff(run_dir, clean, dirty):
    from modules.forensics import compare, export_json, export_pdf
    report = compare(str(clean["path"]), str(dirty["path"]))

    json_path = run_dir / "comparison.json"
    pdf_path  = run_dir / "comparison.pdf"
    export_json(report, str(json_path))
    export_pdf(report, str(pdf_path))
    LOG.info(f"diff: {report.total_changes} changes -> "
             f"{json_path} + {pdf_path}")
    return {"report": report, "json": str(json_path), "pdf": str(pdf_path)}


def stage_dashboard(run_dir, results):
    from modules.orchestrator.dashboard import build_dashboard
    payload = build_dashboard(run_dir)
    LOG.info(f"dashboard: {run_dir}/dashboard.html")
    return payload


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def run_pipeline(config, detect_timeout=30):
    LOG.info("=== pipeline start ===")
    run_dir = make_run_dir(config.get("output_dir", "output"))

    results = {"run_dir": str(run_dir)}

    # 1. infrastructure
    results["infrastructure"] = stage_infrastructure(config, run_dir)

    # 2. clean snapshot
    results["clean"] = stage_clean_snapshot(config, run_dir)

    # 3. detection
    results["detection"] = stage_detect(config, run_dir, timeout_s=detect_timeout)

    # 4–5. only continue if detection fired
    if results["detection"].get("event") is not None:
        results["dirty"] = stage_dirty_snapshot(
            config, run_dir, results["detection"]
        )
        results["diff"] = stage_diff(
            run_dir, results["clean"], results["dirty"]
        )
    else:
        results["dirty"] = None
        results["diff"] = None
        LOG.warning("pipeline: skipping dirty/diff (no detection)")

    # 6. dashboard
    results["dashboard"] = stage_dashboard(run_dir, results)

    LOG.info(f"=== pipeline done — run dir: {run_dir} ===")
    return results


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--config", default="config/config.yaml")
    p.add_argument("--detect-timeout", type=float, default=30.0,
                   help="Seconds to wait for a register change")
    p.add_argument("--verbose", "-v", action="store_true")
    return p.parse_args()


def main():
    args = parse_args()
    setup_logging(logging.DEBUG if args.verbose else logging.INFO)

    try:
        import yaml
        with open(args.config) as f:
            config = yaml.safe_load(f)
    except Exception as e:
        LOG.error(f"failed to load config: {e}")
        return 1

    run_pipeline(config, detect_timeout=args.detect_timeout)
    return 0


if __name__ == "__main__":
    sys.exit(main())