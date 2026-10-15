"""
Scenario 5 — persistent reinfection attack.

The attacker re-corrupts the PLC after every restoration. The scenario
measures the pipeline's ability to keep up until the attacker is
stopped after `n_reinfections` cycles.
"""
import logging
import threading
import time

from modules.forensics.watcher import DEFAULT_WATCH
from scenarios.runner import run_scenario, _write_register


LOG = logging.getLogger("scenarios.reinfection")


N_REINFECTIONS = 2
REINFECT_DELAY_S = 5.0


def trigger():
    """
    Launch a background thread that reinfects the PLC every time the
    register is restored. Returns immediately; the pipeline handles
    the rest.
    """
    def reinfect_loop():
        count = 0
        while count < N_REINFECTIONS:
            time.sleep(REINFECT_DELAY_S)
            # re-fire the timer attack
            _write_register(1, 12000, _cfg)
            count += 1
            LOG.info(f"[reinfection] fired cycle {count}/{N_REINFECTIONS}")

    t = threading.Thread(target=reinfect_loop, daemon=True)
    t.start()


def run(cfg):
    global _cfg
    _cfg = cfg
    baseline = dict(DEFAULT_WATCH)
    return run_scenario(
        name="5 - Reinfection",
        trigger_fn=trigger,
        baseline=baseline,
        cfg=cfg,
    )