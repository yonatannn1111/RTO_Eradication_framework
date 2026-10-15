"""
Shared fixtures for E2E tests.

Two modes:
    - Real-PLC mode   : runs against a live OpenPLC + safety scheduler
    - Mock mode       : uses in-process fakes so the suite runs in CI

Set `E2E_MODE=real` to use the live stack. Default is mock.
"""
import os
import socket
from pathlib import Path

import pytest


E2E_MODE = os.environ.get("E2E_MODE", "mock")


def _port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "real_plc: test requires a running OpenPLC (skipped in mock mode)",
    )


@pytest.fixture(scope="session")
def real_plc_available():
    """Session-scoped check for a running OpenPLC + scheduler."""
    plc_up = _port_open("127.0.0.1", 502)
    sched_up = _port_open("127.0.0.1", 5003)
    if not (plc_up and sched_up):
        pytest.skip(
            "real PLC or scheduler not available "
            "(OpenPLC on :502, scheduler on :5003)"
        )
    return True


@pytest.fixture
def tmp_snapshot(tmp_path):
    """
    Write a small trusted snapshot to a temp file for restore testing.
    Structure matches what `capture()` produces.
    """
    import json
    snap = {
        "timestamp": "2026-10-15 10:00:00",
        "plc_ip": "127.0.0.1",
        "areas": {
            "DB1": [0] * 100,
            "DB2": [0] * 100,
            "Merker": [0] * 100,
        },
    }
    p = tmp_path / "trusted_baseline.json"
    p.write_text(json.dumps(snap, indent=2))
    return str(p)