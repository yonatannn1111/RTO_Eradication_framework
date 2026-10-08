"""
Register-change watcher.

Polls OpenPLC registers at a configurable interval and fires a callback
the first time ANY monitored register differs from the baseline values.
"""
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime

from pymodbus.client import ModbusTcpClient


log = logging.getLogger("forensics.watcher")


# Default registers to watch (matches conveyor map)
DEFAULT_WATCH = {
    0: 0,     # MW0 MotorCmd
    1: 500,   # MW1 SpeedSet
    3: 0,     # MW3 BagCount
    4: 0,     # MW4 StatusReg
    5: 0,     # MW5 BagSensor
}


@dataclass
class ChangeEvent:
    detected_at: str
    elapsed_s: float
    register: int
    baseline: int
    observed: int
    all_changes: list


class RegisterWatcher:
    """
    Polls Modbus holding registers and triggers a callback on first change.
    """

    def __init__(self, plc_ip: str, port: int = 502,
                 baseline: dict | None = None,
                 poll_interval: float = 0.1,
                 timeout_s: float | None = None):
        self.plc_ip = plc_ip
        self.port = port
        self.baseline = dict(baseline or DEFAULT_WATCH)
        self.poll_interval = poll_interval
        self.timeout_s = timeout_s
        self._stop = threading.Event()
        self._thread = None
        self.event: ChangeEvent | None = None
        self._callback = None

    def on_change(self, fn):
        """Register a callback fired with the ChangeEvent."""
        self._callback = fn
        return self

    # --- lifecycle ---------------------------------------------------------

    def start(self):
        if self._thread and self._thread.is_alive():
            return False
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return True

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def wait(self) -> ChangeEvent | None:
        """Block until a change is detected or timeout expires."""
        self._thread.join(timeout=self.timeout_s)
        return self.event

    # --- main loop ---------------------------------------------------------

    def _run(self):
        client = ModbusTcpClient(self.plc_ip, port=self.port)
        client.connect()
        if not client.connected:
            log.error(f"watcher: cannot connect to {self.plc_ip}:{self.port}")
            return

        start = time.time()
        log.info(f"watcher: polling every {self.poll_interval}s "
                 f"baseline={self.baseline}")

        try:
            while not self._stop.is_set():
                try:
                    rr = client.read_holding_registers(
                        address=min(self.baseline),
                        count=max(self.baseline) - min(self.baseline) + 1,
                    ).registers
                except Exception as e:
                    log.warning(f"watcher: read failed: {e}")
                    time.sleep(self.poll_interval)
                    continue

                base = min(self.baseline)
                changes = []
                for reg, expected in self.baseline.items():
                    observed = rr[reg - base]
                    if observed != expected:
                        changes.append({
                            "register": reg,
                            "baseline": expected,
                            "observed": observed,
                        })

                if changes:
                    self.event = ChangeEvent(
                        detected_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        elapsed_s=time.time() - start,
                        register=changes[0]["register"],
                        baseline=changes[0]["baseline"],
                        observed=changes[0]["observed"],
                        all_changes=changes,
                    )
                    log.warning(
                        f"watcher: CHANGE detected at t={self.event.elapsed_s:.3f}s "
                        f"register MW{self.event.register} "
                        f"{self.event.baseline} -> {self.event.observed}"
                    )
                    if self._callback:
                        try:
                            self._callback(self.event)
                        except Exception as e:
                            log.error(f"watcher: callback failed: {e}")
                    return

                time.sleep(self.poll_interval)
        finally:
            client.close()