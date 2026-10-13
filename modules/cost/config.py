"""Load and validate the cost function config."""
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class CostConfig:
    weights: dict = field(default_factory=dict)
    thresholds: dict = field(default_factory=dict)
    criticality_levels: dict = field(default_factory=dict)
    time_of_day: dict = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path = "config/cost.yaml") -> "CostConfig":
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"cost config not found: {path}")
        data = yaml.safe_load(path.read_text()) or {}
        return cls(
            weights=data.get("weights", {}),
            thresholds=data.get("thresholds", {"immediate": 50, "wait": 20}),
            criticality_levels=data.get("criticality_levels",
                                        {"low": 1, "medium": 3,
                                         "high": 5, "critical": 10}),
            time_of_day=data.get("time_of_day",
                                 {"peak_hours": [7, 8, 9, 16, 17, 18, 19],
                                  "peak_multiplier": 1.0,
                                  "off_peak_multiplier": 0.3}),
        )