"""Dashboard configuration — API endpoints and refresh interval."""
from dataclasses import dataclass


@dataclass
class DashboardConfig:
    conveyor_url: str = "http://127.0.0.1:5001"
    scheduler_url: str = "http://127.0.0.1:5002"
    safety_url: str = "http://127.0.0.1:5003"
    refresh_seconds: int = 5
    http_timeout_s: float = 2.0