"""
Remote trigger API for attack variants (Task 13).

Exposes a small Flask app for starting/stopping attacks over HTTP.

Endpoints
---------
POST /attack/<name>/start     start one attack (timer|counter|flag)
POST /attack/<name>/stop      stop one attack
POST /attack/all/start        start all three
POST /attack/all/stop         stop all three
GET  /attack/status           running state of every attack
GET  /attack/logs?n=50        last n lines of the central log
GET  /health                  liveness check

Example
-------
    curl -X POST http://127.0.0.1:5000/attack/timer/start
    curl -X POST http://127.0.0.1:5000/attack/all/stop
    curl http://127.0.0.1:5000/attack/status
"""
import argparse
from flask import Flask, jsonify, request

from .logger import get_attack_logger, read_log_tail
from .variants import ATTACK_REGISTRY, get_attack_class

log = get_attack_logger("attack.api")

app = Flask(__name__)

# --- Runtime state ---
_instances = {}          # name -> PersistentAttack instance
_plc_ip = "127.0.0.1"    # overridden by CLI / config


def _get_or_create(name: str):
    if name not in ATTACK_REGISTRY:
        raise KeyError(name)
    if name not in _instances:
        cls = get_attack_class(name)
        _instances[name] = cls(_plc_ip)
    return _instances[name]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return jsonify({"ok": True})


@app.post("/attack/<name>/start")
def start_one(name):
    try:
        atk = _get_or_create(name)
    except KeyError:
        return jsonify({"error": f"unknown attack '{name}'"}), 404
    atk.start()
    return jsonify({"attack": name, "running": atk.is_running()})


@app.post("/attack/<name>/stop")
def stop_one(name):
    if name not in _instances:
        return jsonify({"attack": name, "running": False, "note": "not started"})
    _instances[name].stop()
    return jsonify({"attack": name, "running": _instances[name].is_running()})


@app.post("/attack/all/start")
def start_all():
    started = []
    for name in ATTACK_REGISTRY:
        atk = _get_or_create(name)
        atk.start()
        started.append(name)
    return jsonify({"started": started})


@app.post("/attack/all/stop")
def stop_all():
    stopped = []
    for name, atk in _instances.items():
        atk.stop()
        stopped.append(name)
    return jsonify({"stopped": stopped})


@app.get("/attack/status")
def status():
    return jsonify({
        name: {
            "running": atk.is_running(),
            "rounds": atk._rounds,
            "interval": atk.interval,
        }
        for name, atk in _instances.items()
    })


@app.get("/attack/logs")
def logs():
    n = int(request.args.get("n", 50))
    return jsonify({"lines": read_log_tail(n)})


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def run(plc_ip="127.0.0.1", host="0.0.0.0", port=5000, debug=False):
    global _plc_ip
    _plc_ip = plc_ip
    log.info(f"attack API listening on {host}:{port}, target PLC={plc_ip}")
    app.run(host=host, port=port, debug=debug, use_reloader=False)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Remote attack trigger API")
    p.add_argument("--plc", default="127.0.0.1", help="PLC IP address")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=5000)
    p.add_argument("--debug", action="store_true")
    args = p.parse_args()

    run(args.plc, args.host, args.port, args.debug)