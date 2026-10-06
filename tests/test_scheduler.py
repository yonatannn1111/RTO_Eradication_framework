"""SimPy model smoke test (no PLC needed)."""

def test_simulation_runs():
    from modules.scheduler import run_simulation, SimConfig
    cfg = SimConfig(duration=60, arrival_rate=0.5, service_time=0.5, seed=1)
    result = run_simulation(cfg)
    assert result["bags_arrived"] > 0
    assert result["bags_processed"] > 0
