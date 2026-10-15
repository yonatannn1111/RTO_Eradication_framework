"""
Metrics collection for attack scenario testing.

For each scenario we record:
    - forensic_recovery_pct : % of expected state restored (0–100)
    - downtime_s            : wall-clock from detection to validated clean
    - mis_sorted_bags       : bags that went out of spec during downtime
    - notes                 : free-form context
"""
import csv
import json
import statistics
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

@dataclass
class ScenarioResult:
    scenario: str
    started_at: str
    ended_at: str = ""
    forensic_recovery_pct: float = 0.0
    downtime_s: float = 0.0
    mis_sorted_bags: int = 0
    restore_attempts: int = 0
    validation_pass: bool = False
    notes: str = ""
    details: dict = field(default_factory=dict)

    def as_dict(self):
        return asdict(self)


# ---------------------------------------------------------------------------
# Stopwatch
# ---------------------------------------------------------------------------

class Stopwatch:
    """Simple wall-clock stopwatch for downtime measurement."""

    def __init__(self):
        self._t0 = None
        self._t1 = None

    def start(self):
        self._t0 = time.time()
        self._t1 = None
        return self

    def stop(self):
        self._t1 = time.time()
        return self.elapsed

    @property
    def elapsed(self) -> float:
        if self._t0 is None:
            return 0.0
        end = self._t1 if self._t1 is not None else time.time()
        return end - self._t0


# ---------------------------------------------------------------------------
# Mis-sorted bag estimation
# ---------------------------------------------------------------------------

def estimate_mis_sorted_bags(downtime_s: float,
                             bags_per_second: float,
                             reject_rate: float = 0.0) -> int:
    """
    Estimate how many bags were mis-sorted during the outage.

    With a healthy pipeline, the framework restores the PLC to a known
    state — so the reject rate during recovery is 0 by design. The
    parameter exists so operators can plug in a real rejection rate
    from their conveyor if needed.
    """
    if downtime_s <= 0 or bags_per_second <= 0:
        return 0
    throughput = downtime_s * bags_per_second
    return int(throughput * reject_rate)


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------

class MetricsCollector:
    """Accumulates ScenarioResults and exports them."""

    def __init__(self, output_dir: str | Path = "output/scenarios"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.results: list[ScenarioResult] = []

    def add(self, result: ScenarioResult):
        self.results.append(result)
        self._write_individual(result)

    def _write_individual(self, r: ScenarioResult):
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        slug = r.scenario.lower().replace(" ", "_")
        path = self.output_dir / f"{slug}_{stamp}.json"
        path.write_text(json.dumps(r.as_dict(), indent=2, default=str))

    # --- aggregate exports -------------------------------------------------

    def to_csv(self, path: str | Path | None = None) -> str:
        out = Path(path or (self.output_dir / "summary_table.csv"))
        with out.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow([
                "scenario",
                "forensic_recovery_pct",
                "downtime_s",
                "mis_sorted_bags",
                "restore_attempts",
                "validation_pass",
                "notes",
            ])
            for r in self.results:
                w.writerow([
                    r.scenario,
                    f"{r.forensic_recovery_pct:.1f}",
                    f"{r.downtime_s:.2f}",
                    r.mis_sorted_bags,
                    r.restore_attempts,
                    "PASS" if r.validation_pass else "FAIL",
                    r.notes,
                ])
        return str(out)

    def to_markdown(self, path: str | Path | None = None) -> str:
        out = Path(path or (self.output_dir / "summary_table.md"))
        lines = [
            "# Attack Scenario Test Results",
            "",
            f"_Generated at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_",
            "",
            "| Scenario | Forensic Recovery (%) | Downtime (s) | Mis-sorted Bags | Attempts | Result |",
            "|---|---|---|---|---|---|",
        ]
        for r in self.results:
            lines.append(
                f"| {r.scenario} "
                f"| {r.forensic_recovery_pct:.1f}% "
                f"| {r.downtime_s:.2f} "
                f"| {r.mis_sorted_bags} "
                f"| {r.restore_attempts} "
                f"| {'PASS' if r.validation_pass else 'FAIL'} |"
            )
        out.write_text("\n".join(lines) + "\n")
        return str(out)

    def summary(self) -> dict:
        if not self.results:
            return {}
        r = [x.forensic_recovery_pct for x in self.results]
        d = [x.downtime_s for x in self.results]
        m = [x.mis_sorted_bags for x in self.results]
        return {
            "scenarios_run": len(self.results),
            "avg_recovery_pct": round(statistics.mean(r), 2),
            "min_recovery_pct": round(min(r), 2),
            "avg_downtime_s": round(statistics.mean(d), 2),
            "max_downtime_s": round(max(d), 2),
            "total_mis_sorted_bags": sum(m),
            "all_validation_passed": all(x.validation_pass for x in self.results),
        }