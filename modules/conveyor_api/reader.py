"""
Live conveyor state reader with a 1-second cache.

Polls OpenPLC Modbus registers, derives belt status, and caches the
result so multiple HTTP requests within the same second reuse one read.
"""
import logging
import threading
import time
from dataclasses import dataclass, asdict
from datetime import datetime

from pymodbus.client import ModbusTcpClient


log = logging.getLogger("conveyor_api.reader")


# --- Register map (matches the conveyor program) ---
MW_MOTOR   = 0
MW_SPEED   = 1
MW_TIMER   = 2
MW_COUNT   = 3
MW_STATUS  = 4
MW_SENSOR  = 5

CACHE_TTL_S = 1.0


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class BeltStatus:
    belt_id: str
    queue: int
    speed: float
    status: str            # "running" | "stopped" | "error"
    motor: int
    timer_ms: int
    bags_processed: int
    updated_at: str
    error: str = ""        # populated when the PLC is unreachable


# ---------------------------------------------------------------------------
# Reader
# ---------------------------------------------------------------------------

class ConveyorReader:
    """
    Polls OpenPLC and returns BeltStatus.

    Caches the last successful read for CACHE_TTL_S seconds so that
    multiple requests per second do not hammer the PLC.
    """

    def __init__(self, plc_ip: str = "127.0.0.1",
                 modbus_port: int = 502,
                 belt_id: str = "belt_a"):
        self.plc_ip = plc_ip
        self.modbus_port = modbus_port
        self.belt_id = belt_id
        self._lock = threading.Lock()
        self._cache: BeltStatus | None = None
        self._cached_at = 0.0
        self._client = None

    # --- connection --------------------------------------------------------

    def _ensure_client(self):
        if self._client is None:
            self._client = ModbusTcpClient(self.plc_ip, port=self.modbus_port)
            self._client.connect()
        return self._client

    def close(self):
        if self._client:
            self._client.close()
            self._client = None

    # --- public API --------------------------------------------------------

    def get_status(self, force=False) -> BeltStatus:
        """Return BeltStatus, using the cache unless it has expired."""
        with self._lock:
            now = time.time()
            if not force and self._cache and (now - self._cached_at) < CACHE_TTL_S:
                return self._cache

            status = self._read_plc()
            self._cache = status
            self._cached_at = now
            return status

    # --- internal ----------------------------------------------------------

    def _read_plc(self) -> BeltStatus:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            client = self._ensure_client()
            rr = client.read_holding_registers(address=0, count=6).registers
            motor   = rr[MW_MOTOR]
            speed   = rr[MW_SPEED]
            timer   = rr[MW_TIMER]
            count   = rr[MW_COUNT]
            status  = rr[MW_STATUS]
            sensor  = rr[MW_SENSOR]

            # Derive queue length: bag waiting on the sensor + running deficit
            queue = (1 if sensor > 0 else 0)

            belt_state = "running" if motor > 0 else "stopped"
            # If bit0 of StatusReg is 0 but motor is on, treat as error
            if motor > 0 and (status & 0x01) == 0:
                belt_state = "error"

            return BeltStatus(
                belt_id=self.belt_id,
                queue=queue,
                speed=round(1000.0 / speed, 3) if speed > 0 else 0.0,
                status=belt_state,
                motor=motor,
                timer_ms=timer,
                bags_processed=count,
                updated_at=ts,
            )
        except Exception as e:
            log.warning(f"PLC read failed: {e}")
            self._client = None   # force reconnect next time
            return BeltStatus(
                belt_id=self.belt_id,
                queue=0, speed=0.0, status="error",
                motor=0, timer_ms=0, bags_processed=0,
                updated_at=ts, error=str(e),
            )


# ---------------------------------------------------------------------------
# Module-level singleton (used by the Flask app)
# ---------------------------------------------------------------------------

_reader: ConveyorReader | None = None


def get_reader(plc_ip="127.0.0.1", port=502, belt_id="belt_a") -> ConveyorReader:
    global _reader
    if _reader is None:
        _reader = ConveyorReader(plc_ip, port, belt_id)
    return _reader