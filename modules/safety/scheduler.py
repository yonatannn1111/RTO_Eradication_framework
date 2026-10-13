"""
Continuous scheduler — runs SimPy forecasts for every PLC every 30 s
and stores the latest safe-window recommendation for each.
"""
import logging
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime

from pymodbus.client import ModbusTcpClient

from .window import (
    SafeWindow, WindowThresholds, compute_safe_window,
)
from ..scheduler.twin import ConveyorTwin, TwinConfig


log = logging.getLogger("safety.scheduler")


# Register map (same as conveyor program)
MW_MOTOR  = 0
MW_SPEED  = 1
MW_TIMER  = 2
MW_COUNT  = 3
MW_STATUS = 4
MW_SENSOR = 5


# ---------------------------------------------------------------------------
# Belt descriptor
# ---------------------------------------------------------------------------

@dataclass
class BeltTarget:
    belt_id: str
    plc_ip: str
    modbus_port: int = 502
    belt_criticality: str = "medium"


@dataclass
class BeltStatusEntry:
    belt_id: str
    plc_ip: str
    updated_at: str
    window: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)
    error: str = ""


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

class SafetyScheduler:
    """
    Continuously polls each belt, runs a SimPy forecast, and stores
    the resulting safe window.
    """

    def __init__(
        self,
        belts: list[BeltTarget],
        interval_s: float = 30.0,
        thresholds: WindowThresholds | None = None,
        sample_window_s: float = 10.0,
    ):
        self.belts = belts
        self.interval_s = interval_s
        self.thresholds = thresholds or WindowThresholds()
        self.sample_window_s = sample_window_s
        self.results: dict[str, BeltStatusEntry] = {}
        self.lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None

    # --- lifecycle ---------------------------------------------------------

    def start(self):
        if self._thread and self._thread.is_alive():
            return False
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        log.info(f"safety scheduler started ({len(self.belts)} belt(s), "
                 f"interval={self.interval_s}s)")
        return True

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)

    def is_running(self):
        return bool(self._thread and self._thread.is_alive())

    # --- inspection --------------------------------------------------------

    def snapshot(self):
        with self.lock:
            return {
                "running": self.is_running(),
                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "belts": {k: v.window for k, v in self.results.items()},
                "details": {k: asdict(v) for k, v in self.results.items()},
            }

    def get(self, belt_id: str):
        with self.lock:
            return self.results.get(belt_id)

    # --- main loop ---------------------------------------------------------

    def _run(self):
        while not self._stop.is_set():
            start = time.time()
            for belt in self.belts:
                try:
                    self._update_belt(belt)
                except Exception as e:
                    log.error(f"{belt.belt_id}: update failed: {e}")
                    with self.lock:
                        self.results[belt.belt_id] = BeltStatusEntry(
                            belt_id=belt.belt_id,
                            plc_ip=belt.plc_ip,
                            updated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            window={"action": "UNKNOWN", "reason": str(e)},
                            error=str(e),
                        )

            # sleep the remainder of the interval
            elapsed = time.time() - start
            wait = max(0.5, self.interval_s - elapsed)
            if self._stop.wait(wait):
                break

    # --- per-belt update ---------------------------------------------------

    def _update_belt(self, belt: BeltTarget):
        # 1. Read live registers
        client = ModbusTcpClient(belt.plc_ip, port=belt.modbus_port)
        client.connect()
        if not client.connected:
            raise ConnectionError(f"cannot reach {belt.plc_ip}:{belt.modbus_port}")

        try:
            rr = client.read_holding_registers(address=0, count=6).registers
        finally:
            client.close()

        motor   = rr[MW_MOTOR]
        speed   = rr[MW_SPEED]
        timer   = rr[MW_TIMER]
        count   = rr[MW_COUNT]
        sensor  = rr[MW_SENSOR]

        # 2. Derive queue and rates
        queue_now = 1 if sensor > 0 else 0
        service_rate = 1000.0 / speed if speed > 0 else 0.0   # bags / second

        # Arrival rate is not directly available — approximate.
        # If the PLC exposes a rolling count, we could compute dCount/dt.
        # For now, assume arrivals ≥ service so the forecast is conservative.
        arrival_rate = service_rate * 1.1

        # 3. SimPy forecast → safe window
        window: SafeWindow = compute_safe_window(
            queue_now=queue_now,
            arrival_rate=arrival_rate,
            service_rate=service_rate,
            belt_criticality=belt.belt_criticality,
            thresholds=self.thresholds,
        )

        # 4. Store
        with self.lock:
            self.results[belt.belt_id] = BeltStatusEntry(
                belt_id=belt.belt_id,
                plc_ip=belt.plc_ip,
                updated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                window=window.as_dict(),
                raw={
                    "motor": motor,
                    "speed_ms": speed,
                    "timer_ms": timer,
                    "bag_count": count,
                    "sensor": sensor,
                    "queue_now": queue_now,
                    "arrival_rate": round(arrival_rate, 3),
                    "service_rate": round(service_rate, 3),
                },
            )

        log.info(f"{belt.belt_id}: {window.action}"
                 + (f" ({window.minutes} min)" if window.minutes else ""))