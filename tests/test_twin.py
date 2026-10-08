"""Digital twin tests — no PLC needed."""

from modules.scheduler.twin import predict_queue, TwinConfig, ConveyorTwin


def test_predict_stable_when_service_exceeds_arrival():
    r = predict_queue(current_queue=5, arrival_rate=0.4,
                     service_rate=1.0, horizon_s=60)
    assert r["stable"] is True
    # net rate negative → queue should shrink to 0 (floored)
    assert r["predicted_queue"] == 0


def test_predict_unstable_when_arrival_exceeds_service():
    r = predict_queue(current_queue=0, arrival_rate=2.0,
                     service_rate=1.0, horizon_s=10)
    assert r["stable"] is False
    assert r["predicted_queue"] == 20       # (2 - 1) * 10


def test_predict_requires_running_server():
    r = predict_queue(current_queue=3, arrival_rate=0.5,
                     service_rate=0.0, horizon_s=60)
    assert r["stable"] is False
    assert "server not running" in r["reason"]


def test_twin_config_defaults():
    c = TwinConfig()
    assert c.mode in ("realtime", "accelerated")
    assert c.sample_interval > 0