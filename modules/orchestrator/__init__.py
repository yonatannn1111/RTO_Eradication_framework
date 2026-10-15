"""
Orchestrator package.

Note: the package-level `main` name would collide with the submodule
`modules.orchestrator.main`, which breaks `import modules.orchestrator.main as m`.
We export the CLI function as `main_cli` instead.
"""

from .main import run_pipeline, main as main_cli
from .dashboard import build_dashboard
from .scheduler_connector import run_connector, ConnectorConfig
from .full_orchestrator import (
    run_full_orchestrator,
    OrchestratorConfig,
    PLCConfig,
    AlertListener,
    incident_response_cycle,
)
from .events_db import EventsDB

__all__ = [
    # main pipeline
    "run_pipeline", "main_cli",
    # dashboard
    "build_dashboard",
    # scheduler connector (Task 26)
    "run_connector", "ConnectorConfig",
    # full orchestrator (Task 27)
    "run_full_orchestrator", "OrchestratorConfig",
    "PLCConfig", "AlertListener", "incident_response_cycle",
    # database
    "EventsDB",
]