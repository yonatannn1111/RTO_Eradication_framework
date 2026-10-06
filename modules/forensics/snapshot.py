
"""
Forensics — capture, restore, and validate PLC snapshots.
"""
import hashlib
import json
import os
from datetime import datetime

from snap7 import Client

try:
    from snap7.type import Area
except ImportError:
    from snap7.types import Areas
    Area = Areas


def capture(plc_ip: str, tcp_port: int = 1102,
            db1_size: int = 100, db2_size: int = 100,
            merker_size: int = 100, output_dir: str = "snapshots") -> dict:
    """Read DB1, DB2, Merker and save a JSON snapshot with SHA-256."""
    plc = Client()
    try:
        plc.connect(plc_ip, 0, 1, tcp_port=tcp_port)
        if not plc.get_connected():
            raise ConnectionError(f"Cannot connect to {plc_ip}:{tcp_port}")

        areas = {
            "DB1":    list(plc.db_read(1, 0, db1_size)),
            "DB2":    list(plc.db_read(2, 0, db2_size)),
            "Merker": list(plc.read_area(Area.MK, 0, 0, merker_size)),
        }
    finally:
        if plc.get_connected():
            plc.disconnect()

    payload = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "plc_ip": plc_ip,
        "areas": areas,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    payload["sha256_hash"] = hashlib.sha256(canonical.encode()).hexdigest()

    os.makedirs(output_dir, exist_ok=True)
    fname = os.path.join(
        output_dir,
        f"snapshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
    )
    with open(fname, "w") as f:
        json.dump(payload, f, indent=2)

    return {"path": fname, **payload}


