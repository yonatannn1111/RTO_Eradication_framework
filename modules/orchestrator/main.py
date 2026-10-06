"""Main orchestrator — wires all modules into one pipeline."""
import argparse
import logging
import sys
from pathlib import Path

LOG = logging.getLogger("orchestrator")


def setup_logging(level=logging.INFO):
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def stage_infrastructure(config):
    from modules.ot_infrastructure import verify_plc
    status = verify_plc(config["plc"]["ip"],
                        config["plc"]["modbus_port"],
                        config["plc"]["s7_port"])
    LOG.info(f"infrastructure: modbus={status.modbus_open} s7={status.s7_open}")
    return {"status": status}


def stage_snapshot(config):
    from modules.forensics import capture
    snap = capture(
        config["plc"]["ip"],
        tcp_port=1102,
        db1_size=config["snapshot"]["db1_size"],
        db2_size=config["snapshot"]["db2_size"],
        merker_size=config["snapshot"]["merker_size"],
        output_dir=config["snapshot"]["output_dir"],
    )
    LOG.info(f"snapshot saved: {snap['path']}")
    return {"snapshot": snap}


def stage_attack(config):
    if config.get("dry_run"):
        LOG.info("attack: skipped (dry-run)")
        return {"events": []}
    from modules.attack_simulation import run_attacks
    run_attacks(
        config["plc"]["ip"],
        interval=config["attack"]["interval_seconds"],
        rounds=1,
        scenarios=[s["name"].replace("_manipulation", "").replace("_overflow", "")
                   for s in config["attack"]["scenarios"]],
    )
    return {"events": "see log"}


def stage_detect(config, pre_snapshot):
    from modules.forensics import capture, diff
    post = capture(
        config["plc"]["ip"],
        tcp_port=1102,
        output_dir=config["snapshot"]["output_dir"],
    )
    changes = diff(pre_snapshot, post)
    LOG.info(f"detect: {sum(a['count'] for a in changes['areas'].values())} "
             f"changed bytes")
    return {"changes": changes, "post_snapshot": post["path"]}


def stage_report(config, results):
    import json
    out = Path("output")
    out.mkdir(exist_ok=True)
    report = out / "last_run.json"
    with report.open("w") as f:
        json.dump({
            "infrastructure": str(results["infrastructure"].get("status")),
            "snapshot": results["snapshot"].get("path"),
            "detect": results["detect"].get("changes"),
        }, f, indent=2, default=str)
    LOG.info(f"report written: {report}")
    return {"report": str(report)}


def run_pipeline(config):
    LOG.info("=== orchestrator start ===")
    results = {}
    results["infrastructure"] = stage_infrastructure(config)
    results["snapshot"]       = stage_snapshot(config)
    results["attack"]         = stage_attack(config)
    results["detect"]         = stage_detect(config, results["snapshot"]["snapshot"])
    results["report"]         = stage_report(config, results)
    LOG.info("=== orchestrator done ===")
    return results


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--config", default="config/config.yaml")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--verbose", "-v", action="store_true")
    return p.parse_args()


def main():
    args = parse_args()
    setup_logging(logging.DEBUG if args.verbose else logging.INFO)

    try:
        import yaml
        with open(args.config) as f:
            config = yaml.safe_load(f)
    except Exception as e:
        LOG.error(f"failed to load config: {e}")
        return 1

    config["dry_run"] = args.dry_run
    run_pipeline(config)
    return 0


if __name__ == "__main__":
    sys.exit(main())
