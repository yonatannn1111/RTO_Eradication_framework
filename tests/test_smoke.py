"""Smoke tests — every module imports cleanly."""

def test_modules_import():
    import modules.ot_infrastructure
    import modules.forensics
    import modules.attack_simulation
    import modules.scheduler
    import modules.orchestrator


def test_orchestrator_has_pipeline():
    from modules.orchestrator import run_pipeline
    assert callable(run_pipeline)
