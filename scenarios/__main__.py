"""
Run all 5 attack scenarios end-to-end and print the metrics table.

Usage:
    python -m scenarios --trusted-snapshot snapshots/trusted_baseline.json
    python -m scenarios --trusted-snapshot ... --only 1 3
    python -m scenarios --trusted-snapshot ... --plc 127.0.0.1
"""
import argparse
import logging
import sys

from scenarios.metrics import MetricsCollector
from scenarios.runner import ScenarioConfig


SCENARIO_MODULES = {
    1: "scenarios.scenario_1_timer",
    2: "scenarios.scenario_2_counter",
    3: "scenarios.scenario_3_flag",
    4: "scenarios.scenario_4_multi_plc",
    5: "scenarios.scenario_5_reinfection",
}


def parse_args():
    p = argparse.ArgumentParser(description="Attack scenario test harness")
    p.add_argument("--plc", default="127.0.0.1")
    p.add_argument("--modbus-port", type=int, default=502)
    p.add_argument("--s7-port", type=int, default=1102)
    p.add_argument("--trusted-snapshot", required=True,
                   help="Clean baseline to restore from")
    p.add_argument("--detection-timeout", type=float, default=30.0)
    p.add_argument("--bags-per-second", type=float, default=2.0)
    p.add_argument("--reject-rate", type=float, default=0.0)
    p.add_argument("--output-dir", default="output/scenarios")
    p.add_argument("--only", type=int, nargs="+",
                   help="Run only these scenario numbers (default: all)")
    p.add_argument("--verbose", "-v", action="store_true")
    return p.parse_args()


def main():
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    cfg = ScenarioConfig(
        plc_ip=args.plc,
        modbus_port=args.modbus_port,
        s7_port=args.s7_port,
        trusted_snapshot=args.trusted_snapshot,
        detection_timeout_s=args.detection_timeout,
        bags_per_second=args.bags_per_second,
        reject_rate_during_outage=args.reject_rate,
    )

    collector = MetricsCollector(args.output_dir)

    scenarios = args.only or sorted(SCENARIO_MODULES.keys())
    for n in scenarios:
        module_path = SCENARIO_MODULES.get(n)
        if not module_path:
            logging.warning(f"unknown scenario {n}")
            continue
        import importlib
        mod = importlib.import_module(module_path)
        result = mod.run(cfg)
        collector.add(result)

    # --- summary ----------------------------------------------------------
    csv_path = collector.to_csv()
    md_path = collector.to_markdown()
    summary = collector.summary()

    print("\n=== Attack Scenario Metrics ===")
    print(f"{'Scenario':<24}{'Recovery':>10}{'Downtime':>12}"
          f"{'Mis-sorted':>12}")
    print("-" * 60)
    for r in collector.results:
        print(f"{r.scenario:<24}"
              f"{r.forensic_recovery_pct:>9.1f}%"
              f"{r.downtime_s:>11.2f}s"
              f"{r.mis_sorted_bags:>12}")
    print()
    print(f"Average recovery:   {summary['avg_recovery_pct']:.1f}%")
    print(f"Average downtime:   {summary['avg_downtime_s']:.2f}s")
    print(f"Total mis-sorted:   {summary['total_mis_sorted_bags']}")
    print(f"All validated:      {summary['all_validation_passed']}")
    print()
    print(f"CSV  → {csv_path}")
    print(f"MD   → {md_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())