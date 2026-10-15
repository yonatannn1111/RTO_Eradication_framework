"""Scenario 3 — flag manipulation attack."""
import logging

from modules.forensics.watcher import DEFAULT_WATCH
from scenarios.runner import run_scenario, _write_register


LOG = logging.getLogger("scenarios.flag")


def trigger():
    """Attacker forces the motor and status flags to 0."""
    _write_register(0, 0, _cfg)
    _write_register(4, 0, _cfg)


def run(cfg):
    global _cfg
    _cfg = cfg
    baseline = dict(DEFAULT_WATCH)
    return run_scenario(
        name="3 - Flag Attack",
        trigger_fn=trigger,
        baseline=baseline,
        cfg=cfg,
    )