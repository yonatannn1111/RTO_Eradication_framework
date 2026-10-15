"""Scenario 1 — timer manipulation attack."""
import logging

from modules.forensics.watcher import DEFAULT_WATCH
from scenarios.runner import run_scenario, _write_register


LOG = logging.getLogger("scenarios.timer")


def trigger():
    """Attacker changes T1 preset from 500 ms to 12000 ms."""
    _write_register(1, 12000, _cfg)


def run(cfg):
    global _cfg
    _cfg = cfg
    baseline = dict(DEFAULT_WATCH)
    return run_scenario(
        name="1 - Timer Attack",
        trigger_fn=trigger,
        baseline=baseline,
        cfg=cfg,
    )
    