"""
Real-time SimPy digital twin of the conveyor.

Consumes live queue-length readings from OpenPLC and:
    1. Mirrors the queue in a SimPy environment (real-time or accelerated)
    2. Logs every sample to CSV
    3. Predicts future queue length from the observed arrival/service rates
"""
import csv
import statistics
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import simpy

from .plc_source import PLCReader, PLCReading


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class TwinConfig:
    plc_ip: str = "127.0.0.1"
    modbus_port: int = 502
    sample_interval: float = 0.5          # seconds between PLC polls
    mode: str = "realtime"                # "realtime" | "accelerated"
    speedup: float = 10.0                 # only used in accelerated mode
    prediction_horizon: float = 60.0      # seconds ahead to predict
    output_dir: str = "output"


# ---------------------------------------------------------------------------
# Sample record
# ---------------------------------------------------------------------------

@dataclass
class TwinSample:
    time_s: float
    wall_time: str
    queue_length: int
    motor: int
    bag_count: int
    speed_ms: int


@dataclass
class TwinState:
    samples: list = field(default_factory=list)
    started_at: str = ""

    # Rolling rates, computed from samples
    def arrival_rate(self, window_s: float = 30.0) -> float:
        """
        Estimate bag arrival rate (bags/s) from recent bag_count deltas.
        """
        if len(self.samples) < 2:
            return 0.0
        recent = [s for s in self.samples if s.time_s >= self.samples[-1].time_s - window_s]
        if len(recent) < 2:
            recent = self.samples[-2:]
        dc = recent[-1].bag_count - recent[0].bag_count
        dt = recent[-1].time_s - recent[0].time_s
        return max(0.0, dc / dt) if dt > 0 else 0.0

    def service_rate(self) -> float:
        """
        Service rate = 1 / processing_time. Derived from SpeedSet (MW1).
        """
        if not self.samples:
            return 0.0
        speed_ms = self.samples[-1].speed_ms
        if speed_ms <= 0:
            return 0.0
        return 1000.0 / speed_ms     # bags per second


# ---------------------------------------------------------------------------
# Predictor — queueing theory (M/D/1 approximation)
# ---------------------------------------------------------------------------

def predict_queue(current_queue: int,
                  arrival_rate: float,
                  service_rate: float,
                  horizon_s: float) -> dict:
    """
    Predict queue length at `horizon_s` in the future.

    Uses a simple fluid approximation:
        dQ/dt = arrival_rate - service_rate (if server busy, else 0)
        Q(t + h) = max(0, Q(t) + (lambda - mu) * h)

    Returns dict with prediction, expected growth, and stability flag.
    """
    if service_rate <= 0:
        growth = arrival_rate * horizon_s
        return {
            "predicted_queue": current_queue + growth,
            "net_rate_per_s": arrival_rate,
            "stable": False,
            "reason": "server not running",
        }

    net = arrival_rate - service_rate
    predicted = max(0, current_queue + net * horizon_s)
    utilisation = arrival_rate / service_rate if service_rate else 0.0

    if net > 0:
        reason = f"unstable (utilisation ρ={utilisation:.2f} > 1)"
    elif net == 0:
        reason = "marginal (arrival = service)"
    else:
        reason = f"stable (utilisation ρ={utilisation:.2f} < 1)"

    return {
        "predicted_queue": round(predicted, 2),
        "net_rate_per_s": round(net, 4),
        "utilisation": round(utilisation, 3),
        "stable": net <= 0,
        "reason": reason,
    }


# ---------------------------------------------------------------------------
# Digital twin
# ---------------------------------------------------------------------------

class ConveyorTwin:
    def __init__(self, cfg: TwinConfig):
        self.cfg = cfg
        self.state = TwinState(started_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        self._reader = PLCReader(cfg.plc_ip, cfg.modbus_port)
        self._env = simpy.Environment()

    # --- Lifecycle ---------------------------------------------------------

    def _open_csv(self):
        out = Path(self.cfg.output_dir)
        out.mkdir(parents=True, exist_ok=True)
        fname = out / f"twin_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        f = fname.open("w", newline="")
        w = csv.writer(f)
        w.writerow([
            "timestamp", "time_s", "queue_length",
            "motor", "bag_count", "speed_ms",
        ])
        return f, w, fname

    def run(self, duration_s: float):
        """Run the twin for duration_s seconds of wall time."""
        self._reader.connect()
        f, w, csv_path = self._open_csv()
        print(f"[twin] mode={self.cfg.mode} duration={duration_s}s "
              f"→ {csv_path}")

        try:
            t0 = time.time()
            sample_interval = self.cfg.sample_interval
            if self.cfg.mode == "accelerated":
                sample_interval = self.cfg.sample_interval / self.cfg.speedup

            while time.time() - t0 < duration_s:
                r = self._reader.read()
                sample = TwinSample(
                    time_s=r.time_s,
                    wall_time=r.timestamp,
                    queue_length=r.queue_length,
                    motor=r.motor,
                    bag_count=r.bag_count,
                    speed_ms=r.speed_ms,
                )
                self.state.samples.append(sample)
                w.writerow([
                    sample.wall_time,
                    f"{sample.time_s:.3f}",
                    sample.queue_length,
                    sample.motor,
                    sample.bag_count,
                    sample.speed_ms,
                ])
                f.flush()

                # Update SimPy environment so downstream code can hook events
                self._env.run(until=self._env.now + sample_interval)
                time.sleep(sample_interval)

        finally:
            f.close()
            self._reader.close()
            print(f"[twin] wrote {len(self.state.samples)} samples to {csv_path}")

        return csv_path

    # --- Prediction --------------------------------------------------------

    def predict(self) -> dict:
        """Predict queue length at cfg.prediction_horizon seconds ahead."""
        if not self.state.samples:
            return {"error": "no samples collected"}

        current = self.state.samples[-1].queue_length
        lam = self.state.arrival_rate()
        mu  = self.state.service_rate()

        return {
            "current_queue": current,
            "arrival_rate_bags_per_s": round(lam, 4),
            "service_rate_bags_per_s": round(mu, 4),
            "horizon_s": self.cfg.prediction_horizon,
            **predict_queue(current, lam, mu, self.cfg.prediction_horizon),
        }

    def summary(self) -> dict:
        ql = [s.queue_length for s in self.state.samples]
        return {
            "samples": len(ql),
            "avg_queue": round(statistics.mean(ql), 3) if ql else 0,
            "max_queue": max(ql) if ql else 0,
            "current_queue": ql[-1] if ql else 0,
            "started_at": self.state.started_at,
        }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="SimPy digital twin of the conveyor")
    p.add_argument("--plc", default="127.0.0.1")
    p.add_argument("--modbus-port", type=int, default=502)
    p.add_argument("--duration", type=float, default=60.0,
                   help="Wall-clock seconds to run")
    p.add_argument("--interval", type=float, default=0.5,
                   help="Sample interval in seconds")
    p.add_argument("--mode", choices=["realtime", "accelerated"],
                   default="realtime")
    p.add_argument("--speedup", type=float, default=10.0)
    p.add_argument("--predict-horizon", type=float, default=60.0)
    args = p.parse_args()

    cfg = TwinConfig(
        plc_ip=args.plc,
        modbus_port=args.modbus_port,
        sample_interval=args.interval,
        mode=args.mode,
        speedup=args.speedup,
        prediction_horizon=args.predict_horizon,
    )
    twin = ConveyorTwin(cfg)
    twin.run(args.duration)

    print("\n=== Summary ===")
    for k, v in twin.summary().items():
        print(f"  {k:16s} {v}")

    print("\n=== Prediction ===")
    for k, v in twin.predict().items():
        print(f"  {k:24s} {v}")