"""Restore a snapshot to the PLC and validate."""
import json
from pathlib import Path

from snap7 import Client

try:
    from snap7.type import Area
except ImportError:
    from snap7.types import Areas
    Area = Areas


def _read(plc, name, size):
    if name == "DB1":    return list(plc.db_read(1, 0, size))
    if name == "DB2":    return list(plc.db_read(2, 0, size))
    if name == "Merker": return list(plc.read_area(Area.MK, 0, 0, size))
    raise ValueError(name)


def _write(plc, name, data):
    b = bytes(data)
    if name == "DB1":    plc.db_write(1, 0, b)
    elif name == "DB2":  plc.db_write(2, 0, b)
    elif name == "Merker": plc.write_area(Area.MK, 0, 0, b)
    else: raise ValueError(name)


def restore(snapshot_file: str, plc_ip: str, tcp_port: int = 1102):
    """Write every area back to the PLC, then validate. Returns (ok, report)."""
    snap = json.load(open(snapshot_file))

    plc = Client()
    plc.connect(plc_ip, 0, 1, tcp_port=tcp_port)
    try:
        for name, values in snap["areas"].items():
            if values is None:
                continue
            _write(plc, name, values)
    finally:
        plc.disconnect()

    return validate(snapshot_file, plc_ip, tcp_port)


def validate(snapshot_file: str, plc_ip: str, tcp_port: int = 1102):
    """Read back and compare. Returns (ok, report)."""
    snap = json.load(open(snapshot_file))
    report = {"areas": {}}

    plc = Client()
    plc.connect(plc_ip, 0, 1, tcp_port=tcp_port)
    try:
        for name, exp in snap["areas"].items():
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
    return ok, report