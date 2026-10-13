"""
Real-time SimPy digital twin of the conveyor.

Task 14 — forecasts queue behaviour from live PLC data.
Task 23 — survives PLC outages (restorations) with gap markers and
          restoration events logged to a separate CSV.
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
    sample_interval: float = 0.5
    mode: str = "realtime"                  # "realtime" | "accelerated"
    speedup: float = 10.0
    prediction_horizon: float = 60.0
    output_dir: str = "output"
    max_attempts: int = 6                   # Task 23 — retry budget
    max_backoff_s: float = 5.0              # Task 23 — cap on exponential backoff


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

    def arrival_rate(self, window_s: float = 30.0) -> float:
        if len(self.samples) < 2:
            return 0.0
        recent = [s for s in self.samples
                  if s.time_s >= self.samples[-1].time_s - window_s]
        if len(recent) < 2:
            recent = self.samples[-2:]
        dc = recent[-1].bag_count - recent[0].bag_count
        dt = recent[-1].time_s - recent[0].time_s
        return max(0.0, dc / dt) if dt > 0 else 0.0

    def service_rate(self) -> float:
        if not self.samples:
            return 0.0
        speed_ms = self.samples[-1].speed_ms
        if speed_ms <= 0:
            return 0.0
        return 1000.0 / speed_ms


# ---------------------------------------------------------------------------
# Predictor (Task 14)
# ---------------------------------------------------------------------------

def predict_queue(current_queue: int, arrival_rate: float,
                  service_rate: float, horizon_s: float) -> dict:
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
# Digital twin (Task 23 — resilient)
# ---------------------------------------------------------------------------

class ConveyorTwin:
    def __init__(self, cfg: TwinConfig):
        self.cfg = cfg
        self.state = TwinState(
            started_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
        self._reader = PLCReader(cfg.plc_ip, cfg.modbus_port)
        self._env = simpy.Environment()

        # event log
        self.events: list[dict] = []
        self._outage_started_at: str | None = None
        self._outage_started_t: float | None = None
        self._gap_count = 0

    # --- CSVs -------------------------------------------------------------

    def _open_csvs(self):
        out = Path(self.cfg.output_dir)
        out.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        sample_path = out / f"twin_{stamp}.csv"
        events_path = out / f"twin_events_{stamp}.csv"

        sample_f = sample_path.open("w", newline="")
        sample_w = csv.writer(sample_f)
        sample_w.writerow([
            "timestamp", "time_s", "queue_length",
            "motor", "bag_count", "speed_ms",
        ])

        events_f = events_path.open("w", newline="")
        events_w = csv.writer(events_f)
        events_w.writerow(["timestamp", "time_s", "event", "detail"])

        return (sample_f, sample_w, sample_path,
                events_f, events_w, events_path)

    def _log_event(self, writer, event, detail, t=None):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        writer.writerow([ts, f"{t if t is not None else 0.0:.3f}",
                         event, detail])
        self.events.append({"timestamp": ts, "event": event, "detail": detail})

    # --- resilient read (Task 23) -----------------------------------------

    def _read_resilient(self, max_attempts: int | None = None):
        """
        Try to read the PLC. On failure, back off exponentially and retry
        up to `max_attempts` (defaults to config value). Backoff is
        capped at config.max_backoff_s.

        Returns (reading | None, recovered_after_outage: bool).
        """
        if max_attempts is None:
            max_attempts = self.cfg.max_attempts

        delay = 0.2
        attempt = 0

        # force reconnect attempt on next try
        if self._reader._client is not None:
            try:
                self._reader.close()
            except Exception:
                pass

        while attempt < max_attempts:
            attempt += 1
            try:
                if self._reader._client is None:
                    self._reader.connect()
                reading = self._reader.read()
                recovered = self._outage_started_at is not None
                return reading, recovered
            except Exception:
                if self._outage_started_at is None:
                    self._outage_started_at = datetime.now().strftime(
                        "%Y-%m-%d %H:%M:%S.%f"
                    )[:-3]
                    self._outage_started_t = time.time()
                try:
                    self._reader.close()
                except Exception:
                    pass
                time.sleep(min(delay, self.cfg.max_backoff_s))
                delay *= 2

        return None, False

    # --- run (Task 23 resilient loop) -------------------------------------

    def run(self, duration_s: float):
        # best-effort initial connect — don't crash if PLC is down
        try:
            self._reader.connect()
        except Exception as e:
            print(f"[twin] initial connect failed: {e} (will retry)")

        (sample_f, sample_w, sample_path,
         events_f, events_w, events_path) = self._open_csvs()

        print(f"[twin] mode={self.cfg.mode} duration={duration_s}s")
        print(f"[twin] samples → {sample_path}")
        print(f"[twin] events  → {events_path}")

        t0 = time.time()
        interval = self.cfg.sample_interval
        if self.cfg.mode == "accelerated":
            interval = interval / self.cfg.speedup

        self._log_event(events_w, "twin_started", "initial connect ok")

        try:
            while time.time() - t0 < duration_s:
                reading, recovered = self._read_resilient()

                if reading is None:
                    self._gap_count += 1
                    self._log_event(
                        events_w, "outage_ongoing",
                    )
                    sample_w.writerow([
                        datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                        f"{time.time() - t0:.3f}",
                        "-1", "-1", "-1", "-1",
                    ])
                    sample_f.flush()
                    events_f.flush()
                    time.sleep(interval)
                    continue

                if recovered and self._outage_started_at is not None:
                    outage_s = time.time() - (self._outage_started_t or time.time())
                    self._log_event(
                        events_w, "plc_restored",
                        f"outage lasted {outage_s:.2f}s",
                        t=time.time() - t0,
                    )
                    self._outage_started_at = None
                    self._outage_started_t = None

                sample = TwinSample(
                    time_s=reading.time_s,
                    wall_time=reading.timestamp,
                    queue_length=reading.queue_length,
                    motor=reading.motor,
                    bag_count=reading.bag_count,
                    speed_ms=reading.speed_ms,
                )
                self.state.samples.append(sample)
                sample_w.writerow([
                    sample.wall_time,
                    f"{sample.time_s:.3f}",
                    sample.queue_length,
                    sample.motor,
                    sample.bag_count,
                    sample.speed_ms,
                ])
                sample_f.flush()
                events_f.flush()

                self._env.run(until=self._env.now + interval)
                time.sleep(interval)

        finally:
            sample_f.close()
            self._log_event(events_w, "twin_stopped",
                            f"wrote {len(self.state.samples)} samples")
            events_f.close()
            try:
                self._reader.close()
            except Exception:
                pass
            print(f"[twin] wrote {len(self.state.samples)} samples to {sample_path}")
            print(f"[twin] wrote {len(self.events)} events to {events_path}")

        return sample_path

    # --- summaries --------------------------------------------------------

    def summary(self) -> dict:
        ql = [s.queue_length for s in self.state.samples if s.queue_length >= 0]
        return {
            "samples": len(self.state.samples),
            "avg_queue": round(statistics.mean(ql), 3) if ql else 0,
            "max_queue": max(ql) if ql else 0,
            "current_queue": ql[-1] if ql else 0,
            "started_at": self.state.started_at,
            **self.resilience_summary(),
        }

        def resilience_summary(self) -> dict:
         outages = [e for e in self.events if e["event"] == "outage_ongoing"]
        restores = [e for e in self.events if e["event"] == "plc_restored"]
        return {
            "total_samples": len(self.state.samples),
            "gap_samples": self._gap_count,
            "outage_ticks": len(outages),
            "restoration_events": len(restores),
            "restorations": [e["detail"] for e in restores],
        }

    def predict(self) -> dict:
        if not self.state.samples:
            return {"error": "no samples collected"}
        # skip gap markers when predicting
        good = [s for s in self.state.samples if s.queue_length >= 0]
        if not good:
            return {"error": "no valid samples"}
        current = good[-1].queue_length
        lam = self.state.arrival_rate()
        mu = self.state.service_rate()
        return {
            "current_queue": current,
            "arrival_rate_bags_per_s": round(lam, 4),
            "service_rate_bags_per_s": round(mu, 4),
            "horizon_s": self.cfg.prediction_horizon,
            **predict_queue(current, lam, mu, self.cfg.prediction_horizon),
        }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="SimPy digital twin (resilient)")
    p.add_argument("--plc", default="127.0.0.1")
    p.add_argument("--modbus-port", type=int, default=502)
    p.add_argument("--duration", type=float, default=60.0)
    p.add_argument("--interval", type=float, default=0.5)
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
        print(f"  {k:20s} {v}")

    print("\n=== Prediction ===")
    for k, v in twin.predict().items():
        print(f"  {k:24s} {v}")