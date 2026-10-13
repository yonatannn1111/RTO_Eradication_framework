"""
Flask API serving real-time conveyor load data.

Endpoints
---------
GET /conveyor/status           all belts, JSON
GET /conveyor/status/<belt>    one belt
GET /health                    liveness
GET /                          API index

Run
---
    python -m modules.conveyor_api.app --plc 127.0.0.1 --port 5001
"""
import argparse
import logging

from flask import Flask, jsonify, request

from .reader import get_reader


log = logging.getLogger("conveyor_api")


def create_app(plc_ip="127.0.0.1", modbus_port=502, belts=None):
    """
    Build the Flask app. `belts` is a dict { belt_id: plc_ip } — in this
    project every belt is the same PLC, but the shape allows multi-PLC
    deployments later.
    """
    belts = belts or {"belt_a": plc_ip}
    app = Flask(__name__)

    # --- endpoints ---------------------------------------------------------

    @app.get("/")
    def index():
        return jsonify({
            "service": "conveyor-load-api",
            "endpoints": [
                "/conveyor/status",
                "/conveyor/status/<belt_id>",
                "/health",
            ],
            "belts": list(belts.keys()),
        })

    @app.get("/health")
    def health():
        return jsonify({"ok": True})

    @app.get("/conveyor/status")
    def all_belts():
        """Return status of every belt in one JSON object."""
        out = {}
        for belt_id, ip in belts.items():
            reader = get_reader(ip, modbus_port, belt_id)
            # force=True if caller asks for a fresh read
            force = request.args.get("force") == "1"
            out[belt_id] = reader.get_status(force=force).__dict__
        return jsonify({
            "updated_at": out[list(out)[0]]["updated_at"] if out else None,
            "belts": out,
        })

    @app.get("/conveyor/status/<belt_id>")
    def one_belt(belt_id):
        if belt_id not in belts:
            return jsonify({"error": f"unknown belt '{belt_id}'"}), 404
        reader = get_reader(belts[belt_id], modbus_port, belt_id)
        force = request.args.get("force") == "1"
        return jsonify(reader.get_status(force=force).__dict__)

    # --- error handlers ----------------------------------------------------
    # Catch-all so that any internal failure still returns JSON, never HTML.

    @app.errorhandler(Exception)
    def unhandled(e):
        log.exception("unhandled error")
        return jsonify({
            "error": str(e),
            "type": type(e).__name__,
        }), 500

    return app


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description="Conveyor Load API")
    p.add_argument("--plc", default="127.0.0.1", help="PLC IP address")
    p.add_argument("--modbus-port", type=int, default=502)
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=5001)
    p.add_argument("--belt-id", default="belt_a")
    p.add_argument("--debug", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    app = create_app(args.plc, args.modbus_port, {args.belt_id: args.plc})
    log.info(f"conveyor API on http://{args.host}:{args.port} → PLC {args.plc}")
    app.run(host=args.host, port=args.port, debug=args.debug, use_reloader=False)


if __name__ == "__main__":
    main()