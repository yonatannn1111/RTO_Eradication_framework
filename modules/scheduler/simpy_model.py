"""SimPy model of a conveyor belt (from Task 8)."""
import random
import statistics
from dataclasses import dataclass, field

import simpy


@dataclass
class SimConfig:
    duration: float = 3600.0
    arrival_rate: float = 0.5
    service_time: float = 1.5
    capacity: int = 1
    sample_interval: float = 1.0
    seed: int = 42


@dataclass
class SimStats:
    queue: list = field(default_factory=list)
    processed: int = 0
    arrived: int = 0


def _arrivals(env, conveyor, cfg, stats):
    while True:
        yield env.timeout(random.expovariate(cfg.arrival_rate))
        stats.arrived += 1
        env.process(_bag(env, conveyor, cfg, stats))


def _bag(env, conveyor, cfg, stats):
    with conveyor.request() as req:
        yield req
        yield env.timeout(cfg.service_time)
        stats.processed += 1


def _monitor(env, conveyor, cfg, stats):
    while True:
        stats.queue.append((env.now, len(conveyor.queue)))
        yield env.timeout(cfg.sample_interval)


def run(cfg: SimConfig | None = None) -> dict:
    cfg = cfg or SimConfig()
    random.seed(cfg.seed)
    env = simpy.Environment()
    conveyor = simpy.Resource(env, capacity=cfg.capacity)
    stats = SimStats()
    env.process(_arrivals(env, conveyor, cfg, stats))
    env.process(_monitor(env, conveyor, cfg, stats))
    env.run(until=cfg.duration)

    ql = [q for _, q in stats.queue]
    return {
        "bags_arrived": stats.arrived,
        "bags_processed": stats.processed,
        "bags_per_hour": stats.processed / (cfg.duration / 3600),
        "avg_queue_length": statistics.mean(ql) if ql else 0.0,
        "max_queue_length": max(ql) if ql else 0,
    }
