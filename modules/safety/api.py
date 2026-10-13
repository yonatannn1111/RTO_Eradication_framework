"""
Flask API exposing the safety scheduler's latest results.

Endpoints
---------
GET  /safety/status        all belts' safe windows
GET  /safety/status/<belt> one belt
GET  /safety/health        liveness
GET  /                     index
"""
import argparse
import logging

from flask import Flask, jsonify

from .scheduler import BeltTarget, SafetyScheduler
from .window import WindowThresholds


log = logging.getLogger("safety.api")


def create_app(scheduler: SafetyScheduler):
    app = Flask(__name__)

    @app.get("/")
    def index():
        return jsonify({
            "service": "safety-window-api",
            "endpoints": [
                "/safety/status",
                "/safety/status/<belt_id>",
                "/safety/health",
            ],
            "belts": [b.belt_id for b in scheduler.belts],
            "interval_s": scheduler.interval_s,
        })

    @app.get("/safety/health")
    def health():
        return jsonify({
            "ok": True,
            "scheduler_running": scheduler.is_running(),
        })

    @app.get("/safety/status")
    def status_all():
        return jsonify(scheduler.snapshot())

    @app.get("/safety/status/<belt_id>")
    def status_one(belt_id):
        entry = scheduler.get(belt_id)
        if entry is None:
            return jsonify({"error": f"unknown belt '{belt_id}'"}), 404
        return jsonify({
            "belt_id": entry.belt_id,
            "plc_ip": entry.plc_ip,
            "updated_at": entry.updated_at,
            "window": entry.window,
            "raw": entry.raw,
            "error": entry.error,
        })

    return app


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description="Safety-window scheduler")
    p.add_argument("--plc", default="127.0.0.1", help="PLC IP")
    p.add_argument("--belt-id", default="plc_a")
    p.add_argument("--interval", type=float, default=30.0,
                   help="Seconds between refreshes")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=5003)
    p.add_argument("--debug", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    belts = [
        BeltTarget(belt_id=args.belt_id, plc_ip=args.plc, belt_criticality="medium"),
    ]
    scheduler = SafetyScheduler(
        belts=belts,
        interval_s=args.interval,
        thresholds=WindowThresholds(),
    )
    scheduler.start()

    app = create_app(scheduler)
    log.info(f"safety API on http://{args.host}:{args.port}")
    try:
        app.run(host=args.host, port=args.port, debug=args.debug, use_reloader=False)
    finally:
        scheduler.stop()


if __name__ == "__main__":
    main()