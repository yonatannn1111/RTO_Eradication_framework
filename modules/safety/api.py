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

from flask import Flask, jsonify, request

from .scheduler import BeltTarget, SafetyScheduler
from .window import WindowThresholds


log = logging.getLogger("safety.api")


def create_app(scheduler: SafetyScheduler):
    app = Flask(__name__)
    @app.post("/dispatch")
    def dispatch():
        """
        Task 22 — synchronous dispatch.

        Accepts a forensic alert, computes the safe window for the named
        belt immediately, logs the interaction, and returns the window.

        Request body:
            {
                "belt_id": "plc_a",
                "infection_type": "timer-manipulation",
                "detected_at": "2026-10-13 10:00:00",
                "queue_now": 5,             # optional — uses live PLC otherwise
                "arrival_rate": 1.0,        # optional
                "service_rate": 0.5,        # optional
                "criticality": "medium"     # optional
            }
        """
        from datetime import datetime
        from .window import compute_safe_window
        from .scheduler import BeltTarget

        data = request.get_json(silent=True) or {}
        belt_id = data.get("belt_id")
        if not belt_id:
            return jsonify({"error": "missing belt_id"}), 400

        # log the request
        log.info(f"dispatch received: belt={belt_id} "
                 f"type={data.get('infection_type')} "
                 f"at={data.get('detected_at')}")

        # --- find the belt in the scheduler's registry -------------------
        belt = next((b for b in scheduler.belts if b.belt_id == belt_id), None)
        if belt is None:
            # create a temporary target if the belt isn't registered
            belt = BeltTarget(
                belt_id=belt_id,
                plc_ip=data.get("plc_ip", "127.0.0.1"),
                belt_criticality=data.get("criticality", "medium"),
            )

        # --- gather inputs ------------------------------------------------
        # If the caller supplied numbers, use them. Otherwise read live.
        if all(k in data for k in ("queue_now", "arrival_rate", "service_rate")):
            queue_now    = int(data["queue_now"])
            arrival_rate = float(data["arrival_rate"])
            service_rate = float(data["service_rate"])
        else:
            try:
                scheduler._update_belt(belt)
                entry = scheduler.get(belt_id)
                if entry is None:
                    raise RuntimeError("no live data available")
                raw = entry.raw
                queue_now    = raw["queue_now"]
                arrival_rate = raw["arrival_rate"]
                service_rate = raw["service_rate"]
            except Exception as e:
                log.error(f"dispatch: live read failed: {e}")
                return jsonify({
                    "error": "could not read PLC",
                    "detail": str(e),
                }), 503

        # --- compute the safe window --------------------------------------
        window = compute_safe_window(
            queue_now=queue_now,
            arrival_rate=arrival_rate,
            service_rate=service_rate,
            belt_criticality=belt.belt_criticality,
            thresholds=scheduler.thresholds,
        )

        response = {
            "belt_id": belt_id,
            "window": window.as_dict(),
            "inputs": {
                "queue_now": queue_now,
                "arrival_rate": arrival_rate,
                "service_rate": service_rate,
                "criticality": belt.belt_criticality,
            },
            "handled_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        log.info(f"dispatch response: belt={belt_id} "
                 f"action={window.action} "
                 f"minutes={window.minutes}")
        return jsonify(response), 200
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