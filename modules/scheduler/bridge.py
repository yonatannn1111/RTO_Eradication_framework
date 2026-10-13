"""
Forensic-to-Scheduler bridge — server side.

Receives infection events from the forensic engine, enqueues them, and
processes them one at a time on a background worker thread. If the
worker is busy, tasks queue instead of being rejected.

Endpoints
---------
POST /tasks/submit      submit an infection event
GET  /tasks/status      queue + worker state
GET  /tasks/<task_id>   single task details
GET  /health            liveness

Run
---
    python -m modules.scheduler.bridge --port 5002
"""
import argparse
import logging
import queue
import threading
import time
import uuid
import heapq
from dataclasses import dataclass, field, asdict
from datetime import datetime

from flask import Flask, jsonify, request


log = logging.getLogger("scheduler.bridge")


# ---------------------------------------------------------------------------
# Task model
# ---------------------------------------------------------------------------

@dataclass
class Task:
    task_id: str
    plc_id: str
    infection_type: str
    detected_at: str
    received_at: str
    cost_score: float = 0.0             # higher = more urgent
    decision: str = ""                  # IMMEDIATE | WAIT | DELAY
    status: str = "queued"
    started_at: str = ""
    finished_at: str = ""
    result: str = ""

    def as_dict(self):
        return asdict(self)


class TaskWorker:
    """
    Priority worker — tasks with higher cost_score are processed first.
    Uses a heap so urgent tasks jump the queue.
    """

    def __init__(self, handler=None, poll_interval: float = 0.2):
        self.q: queue.Queue[Task] = queue.Queue()
        self.tasks: dict[str, Task] = {}
        self.lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._handler = handler or self._default_handler
        self._poll = poll_interval
        self._heap: list[tuple[float, str, Task]] = []   # (-score, task_id, task)
        self._heap_lock = threading.Lock()

    # ...

    def submit(self, plc_id, infection_type, detected_at,
               cost_score: float = 0.0, decision: str = "") -> Task:
        task = Task(
            task_id=str(uuid.uuid4())[:8],
            plc_id=plc_id,
            infection_type=infection_type,
            detected_at=detected_at,
            received_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            cost_score=float(cost_score),
            decision=decision,
        )
        with self.lock:
            self.tasks[task.task_id] = task

        with self._heap_lock:
            # heapq is a min-heap; use negative score for max-first
            heapq.heappush(self._heap, (-task.cost_score, task.task_id, task))

        log.info(f"queued task {task.task_id}: plc={plc_id} "
                 f"type={infection_type} cost={task.cost_score} "
                 f"decision={decision} (heap={len(self._heap)})")
        return task

    def snapshot(self):
        with self.lock:
            counts = {}
            for t in self.tasks.values():
                counts[t.status] = counts.get(t.status, 0) + 1
        with self._heap_lock:
            heap_size = len(self._heap)
        return {
            "worker_alive": bool(self._thread and self._thread.is_alive()),
            "queue_size": heap_size,
            "task_counts": counts,
            "total_tasks": len(self.tasks),
        }

    def _run(self):
        while not self._stop.is_set():
            task = None
            with self._heap_lock:
                if self._heap:
                    _, _, task = heapq.heappop(self._heap)
            if task is None:
                time.sleep(self._poll)
                continue

            task.status = "processing"
            task.started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log.info(f"processing task {task.task_id} (plc={task.plc_id} "
                     f"cost={task.cost_score} decision={task.decision})")
            try:
                result = self._handler(task)
                task.status = "done"
                task.result = str(result)
            except Exception as e:
                task.status = "failed"
                task.result = f"{type(e).__name__}: {e}"
                log.error(f"task {task.task_id} failed: {e}")
            finally:
                task.finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _default_handler(task: Task) -> str:
        log.info(f"   default handler: would eradicate {task.plc_id} "
                 f"(cost={task.cost_score} decision={task.decision})")
        time.sleep(1.0)
        return "simulated eradication complete"



# ---------------------------------------------------------------------------
# Worker — processes tasks one at a time
# ---------------------------------------------------------------------------

class TaskWorker:
    """
    Single-threaded worker consuming from a thread-safe queue.

    The queue has no size limit — if the worker is busy, tasks accumulate.
    This is the "queue mechanism when scheduler is busy" requirement.
    """

    def __init__(self, handler=None, poll_interval: float = 0.2):
        self.q: queue.Queue[Task] = queue.Queue()
        self.tasks: dict[str, Task] = {}     # task_id -> Task
        self.lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._handler = handler or self._default_handler
        self._poll = poll_interval

    # --- lifecycle ---------------------------------------------------------

    def start(self):
        if self._thread and self._thread.is_alive():
            return False
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        log.info("worker started")
        return True

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    # --- submission --------------------------------------------------------

    @app.post("/tasks/submit")
    def submit():
        data = request.get_json(silent=True) or {}
        missing = [k for k in ("plc_id", "infection_type", "detected_at")
                   if not data.get(k)]
        if missing:
            return jsonify({"error": f"missing fields: {missing}"}), 400

        task = worker.submit(
            plc_id=data["plc_id"],
            infection_type=data["infection_type"],
            detected_at=data["detected_at"],
            cost_score=data.get("cost_score", 0.0),
            decision=data.get("decision", ""),
        )
        return jsonify({
            "ack": True,
            "task_id": task.task_id,
            "queued_at": task.received_at,
            "queue_size": worker.q.qsize(),
            "cost_score": task.cost_score,
            "decision": task.decision,
        }), 202

    def snapshot(self) -> dict:
        with self.lock:
            counts = {}
            for t in self.tasks.values():
                counts[t.status] = counts.get(t.status, 0) + 1
        return {
            "worker_alive": bool(self._thread and self._thread.is_alive()),
            "queue_size": self.q.qsize(),
            "task_counts": counts,
            "total_tasks": len(self.tasks),
        }

    def get(self, task_id: str) -> Task | None:
        with self.lock:
            return self.tasks.get(task_id)

    # --- worker loop -------------------------------------------------------

    def _run(self):
        while not self._stop.is_set():
            try:
                task = self.q.get(timeout=self._poll)
            except queue.Empty:
                continue

            task.status = "processing"
            task.started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log.info(f"processing task {task.task_id} (plc={task.plc_id})")

            try:
                result = self._handler(task)
                task.status = "done"
                task.result = str(result)
                log.info(f"task {task.task_id} done")
            except Exception as e:
                task.status = "failed"
                task.result = f"{type(e).__name__}: {e}"
                log.error(f"task {task.task_id} failed: {e}")
            finally:
                task.finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self.q.task_done()

    # --- default handler ---------------------------------------------------

    @staticmethod
    def _default_handler(task: Task) -> str:
        """
        Placeholder work. In a real deployment this is where the scheduler
        triggers eradication (Task 15's restore_with_retry) against the
        infected PLC.
        """
        log.info(f"   default handler: would eradicate {task.plc_id} "
                 f"(infection={task.infection_type})")
        time.sleep(1.0)   # simulate work
        return "simulated eradication complete"


# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------

def create_app(worker: TaskWorker):
    app = Flask(__name__)

    @app.post("/tasks/submit")
    def submit():
        data = request.get_json(silent=True) or {}
        missing = [k for k in ("plc_id", "infection_type", "detected_at")
                   if not data.get(k)]
        if missing:
            return jsonify({"error": f"missing fields: {missing}"}), 400

        task = worker.submit(
            plc_id=data["plc_id"],
            infection_type=data["infection_type"],
            detected_at=data["detected_at"],
        )
        return jsonify({
            "ack": True,
            "task_id": task.task_id,
            "queued_at": task.received_at,
            "queue_size": worker.q.qsize(),
        }), 202

    @app.get("/tasks/status")
    def status():
        return jsonify(worker.snapshot())

    @app.get("/tasks/<task_id>")
    def task_detail(task_id):
        t = worker.get(task_id)
        if t is None:
            return jsonify({"error": f"unknown task '{task_id}'"}), 404
        return jsonify(t.as_dict())

    @app.get("/health")
    def health():
        return jsonify({"ok": True})

    return app


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def run(host="0.0.0.0", port=5002, debug=False):
    worker = TaskWorker()
    worker.start()
    app = create_app(worker)
    log.info(f"scheduler bridge on http://{host}:{port}")
    try:
        app.run(host=host, port=port, debug=debug, use_reloader=False)
    finally:
        worker.stop()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    p = argparse.ArgumentParser(description="Scheduler bridge")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=5002)
    p.add_argument("--debug", action="store_true")
    args = p.parse_args()
    run(args.host, args.port, args.debug)


    def submit_to_scheduler(
    plc_id, infection_type,
    scheduler_url=DEFAULT_SCHEDULER_URL,
    detected_at=None, timeout_s=5.0,
    cost_score: float = 0.0,
    decision: str = "",
):
     payload = {
        "plc_id": plc_id,
        "infection_type": infection_type,
        "detected_at": detected_at or
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "cost_score": cost_score,
        "decision": decision,
    }
    # ... rest unchanged