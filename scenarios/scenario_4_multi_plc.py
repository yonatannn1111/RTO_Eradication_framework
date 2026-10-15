"""
Scenario 4 — multi-PLC simultaneous attack.

Attacks two registers in one shot (simulating an attacker with access
to multiple belts). Since our test bench exposes one Modbus endpoint,
we attack the same PLC on two registers simultaneously.
"""
import logging
import threading

from modules.forensics.watcher import DEFAULT_WATCH
from scenarios.runner import run_scenario, _write_register


LOG = logging.getLogger("scenarios.multi_plc")


def trigger():
    """Fire two attacks in parallel threads."""
    def a(): _write_register(1, 12000, _cfg)      # timer
    def b(): _write_register(3, 65535, _cfg)      # counter
    t1 = threading.Thread(target=a)
    t2 = threading.Thread(target=b)
    t1.start(); t2.start()
    t1.join(); t2.join()


def run(cfg):
    global _cfg
    _cfg = cfg
    baseline = dict(DEFAULT_WATCH)
    return run_scenario(
        name="4 - Multi-PLC",
        trigger_fn=trigger,
        baseline=baseline,
        cfg=cfg,
    )