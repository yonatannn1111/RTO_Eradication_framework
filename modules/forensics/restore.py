"""
Restore a snapshot to the PLC with automatic validation and retry.

Task 15 additions:
    - restore_with_retry()  — write → validate → retry up to N times
    - RestoreFailedError    — raised when every attempt fails
    - structured log via the forensics logger

Backward compatible:
    - restore()   — single attempt, no retry (unchanged behaviour)
    - validate()  — read back and compare (unchanged)
"""
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from snap7 import Client

try:
    from snap7.type import Area
except ImportError:
    from snap7.types import Areas
    Area = Areas


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_DIR = Path("logs")
LOG_FILE = LOG_DIR / "restore.log"
_configured = False


def _get_logger():
    global _configured
    logger = logging.getLogger("forensics.restore")
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
# Exception
# ---------------------------------------------------------------------------

class RestoreFailedError(Exception):
    """Raised when restore + validate fails after all retry attempts."""

    def __init__(self, attempts: int, last_report: dict, snapshot_file: str):
        self.attempts = attempts
        self.last_report = last_report
        self.snapshot_file = snapshot_file
        super().__init__(
            f"Restore failed after {attempts} attempts "
            f"(snapshot={snapshot_file})"
        )


# ---------------------------------------------------------------------------
# Low-level area I/O
# ---------------------------------------------------------------------------

def _read(plc, name, size):
    if name == "DB1":    return list(plc.db_read(1, 0, size))
    if name == "DB2":    return list(plc.db_read(2, 0, size))
    if name == "Merker": return list(plc.read_area(Area.MK, 0, 0, size))
    raise ValueError(f"Unknown area: {name}")


def _write(plc, name, data):
    b = bytes(data)
    if name == "DB1":     plc.db_write(1, 0, b)
    elif name == "DB2":   plc.db_write(2, 0, b)
    elif name == "Merker": plc.write_area(Area.MK, 0, 0, b)
    else: raise ValueError(f"Unknown area: {name}")


# ---------------------------------------------------------------------------
# Attempt result record
# ---------------------------------------------------------------------------

@dataclass
class AttemptResult:
    attempt: int
    started_at: str
    duration_s: float
    ok: bool
    report: dict = field(default_factory=dict)
    error: str = ""

    def as_log(self) -> str:
        status = "PASS" if self.ok else "FAIL"
        base = (
            f"attempt {self.attempt}: {status} "
            f"({self.duration_s:.3f}s)"
        )
        if not self.ok:
            # summarise which areas mismatched
            mismatched = [
                k for k, v in self.report.get("areas", {}).items()
                if v.get("status") == "mismatch"
            ]
            if mismatched:
                base += f" mismatched={mismatched}"
            if self.error:
                base += f" error={self.error}"
        return base


# ---------------------------------------------------------------------------
# Core restore + validate
# ---------------------------------------------------------------------------

def _write_all(snapshot: dict, plc_ip: str, tcp_port: int):
    plc = Client()
    plc.connect(plc_ip, 0, 1, tcp_port=tcp_port)
    try:
        for name, values in snapshot["areas"].items():
            if values is None:
                continue
            _write(plc, name, values)
    finally:
        plc.disconnect()


def _read_and_compare(snapshot: dict, plc_ip: str, tcp_port: int) -> dict:
    report = {"areas": {}}
    plc = Client()
    plc.connect(plc_ip, 0, 1, tcp_port=tcp_port)
    try:
        for name, exp in snapshot["areas"].items():
            if exp is None:
                report["areas"][name] = {"status": "skipped"}
                continue
            act = _read(plc, name, len(exp))
            if act == exp:
                report["areas"][name] = {"status": "match", "bytes": len(exp)}
            else:
                mismatches = [
                    {"offset": i, "expected": e, "actual": a}
                    for i, (e, a) in enumerate(zip(exp, act)) if e != a
                ]
                report["areas"][name] = {
                    "status": "mismatch",
                    "bytes": len(exp),
                    "count": len(mismatches),
                    "first_10": mismatches[:10],
                }
    finally:
        plc.disconnect()

    ok = all(
        v["status"] in ("match", "skipped")
        for v in report["areas"].values()
    )
    report["overall"] = "PASS" if ok else "FAIL"
    return report


# ---------------------------------------------------------------------------
# Public API — single attempt (kept for compatibility)
# ---------------------------------------------------------------------------

def restore(snapshot_file: str, plc_ip: str, tcp_port: int = 1102):
    """Single restore + validate. Returns (ok, report). No retries."""
    with open(snapshot_file) as f:
        snapshot = json.load(f)
    _write_all(snapshot, plc_ip, tcp_port)
    report = _read_and_compare(snapshot, plc_ip, tcp_port)
    ok = report["overall"] == "PASS"
    return ok, report


def validate(snapshot_file: str, plc_ip: str, tcp_port: int = 1102):
    """Read back and compare. Returns (ok, report). No writes."""
    with open(snapshot_file) as f:
        snapshot = json.load(f)
    report = _read_and_compare(snapshot, plc_ip, tcp_port)
    ok = report["overall"] == "PASS"
    return ok, report


# ---------------------------------------------------------------------------
# Task 15 — restore with retry
# ---------------------------------------------------------------------------

def restore_with_retry(
    snapshot_file: str,
    plc_ip: str,
    tcp_port: int = 1102,
    max_attempts: int = 3,
    retry_delay_s: float = 2.0,
    raise_on_failure: bool = True,
):
    """
    Restore the snapshot, validate, and retry on mismatch.

    Parameters
    ----------
    snapshot_file      : path to the JSON snapshot
    plc_ip             : PLC address
    tcp_port           : S7 TCP port
    max_attempts       : total attempts (default 3)
    retry_delay_s      : sleep between attempts (default 2.0 s)
    raise_on_failure   : if True, raise RestoreFailedError when all attempts fail

    Returns
    -------
    (ok: bool, history: list[AttemptResult], last_report: dict)
    """
    with open(snapshot_file) as f:
        snapshot = json.load(f)

    log.info(
        f"restore start: snapshot={snapshot_file} plc={plc_ip}:{tcp_port} "
        f"max_attempts={max_attempts} retry_delay={retry_delay_s}s"
    )

    history: list[AttemptResult] = []
    last_report: dict = {}

    for n in range(1, max_attempts + 1):
        started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        t0 = time.time()
        error = ""

        try:
            _write_all(snapshot, plc_ip, tcp_port)
            last_report = _read_and_compare(snapshot, plc_ip, tcp_port)
            ok = last_report["overall"] == "PASS"
        except Exception as e:
            ok = False
            error = str(e)
            last_report = {"overall": "FAIL", "areas": {}, "exception": error}

        duration = time.time() - t0
        result = AttemptResult(
            attempt=n,
            started_at=started,
            duration_s=duration,
            ok=ok,
            report=last_report,
            error=error,
        )
        history.append(result)
        log.info(result.as_log())

        if ok:
            log.info(f"restore succeeded on attempt {n}/{max_attempts}")
            return True, history, last_report

        if n < max_attempts:
            log.warning(f"retrying in {retry_delay_s}s...")
            time.sleep(retry_delay_s)

    log.error(f"restore FAILED after {max_attempts} attempts")

    if raise_on_failure:
        raise RestoreFailedError(max_attempts, last_report, snapshot_file)

    return False, history, last_report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import sys

    p = argparse.ArgumentParser(description="Restore a snapshot with retry.")
    p.add_argument("snapshot", help="Path to the JSON snapshot file")
    p.add_argument("--plc", default="127.0.0.1")
    p.add_argument("--port", type=int, default=1102)
    p.add_argument("--attempts", type=int, default=3)
    p.add_argument("--delay", type=float, default=2.0)
    p.add_argument("--no-raise", action="store_true",
                   help="Return status instead of raising on failure")
    args = p.parse_args()

    try:
        ok, history, report = restore_with_retry(
            args.snapshot, args.plc, args.port,
            max_attempts=args.attempts,
            retry_delay_s=args.delay,
            raise_on_failure=not args.no_raise,
        )
    except RestoreFailedError as e:
        print(f"\nRestoreFailedError: {e}")
        print(f"Attempts made: {e.attempts}")
        print(f"Last report: {json.dumps(e.last_report, indent=2)[:400]} ...")
        sys.exit(2)

    print(f"\nOK — succeeded in {len(history)} attempt(s)")
    for h in history:
        print(f"  {h.as_log()}")
    sys.exit(0)