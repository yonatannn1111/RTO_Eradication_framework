"""
SQLite event log for the orchestrator (Task 27).

One table (`events`) captures every meaningful step:
    - alert_received
    - scheduler_query
    - safe_window_decision
    - snapshot_before
    - snapshot_final
    - restore_start
    - restore_end
    - validate_result
    - cycle_complete
    - error

SQLite is used because it needs no server, supports WAL (so multiple
writers don't block readers), and is easy to ship as part of the repo.
"""
import json
import logging
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

LOG = logging.getLogger("orchestrator.events_db")


SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT NOT NULL,
    plc_id      TEXT NOT NULL,
    event_type  TEXT NOT NULL,
    details     TEXT,
    ok          INTEGER
);

CREATE INDEX IF NOT EXISTS idx_events_plc
    ON events(plc_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_events_type
    ON events(event_type, timestamp);
"""


class EventsDB:
    """
    Thread-safe SQLite writer. Uses WAL mode so readers don't block.

    Note: `check_same_thread=False` lets us share one connection across
    asyncio tasks that may run on different threads. Writes are serialized
    by Python's GIL + SQLite's own locking.
    """

    def __init__(self, path: str | Path = "output/orchestrator_events.db"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.path),
                                     check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    # --- writes ------------------------------------------------------------

    def log(self, plc_id: str, event_type: str,
            details: dict | None = None,
            ok: bool | None = None):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        details_json = json.dumps(details or {}, default=str)
        ok_int = None if ok is None else (1 if ok else 0)
        with self._lock:
            self._conn.execute(
                "INSERT INTO events (timestamp, plc_id, event_type, "
                "details, ok) VALUES (?, ?, ?, ?, ?)",
                (ts, plc_id, event_type, details_json, ok_int),
            )
            self._conn.commit()
        LOG.debug(f"event: {plc_id} {event_type} ok={ok}")

    # --- reads -------------------------------------------------------------

    def query(self, plc_id: str | None = None,
              event_type: str | None = None,
              limit: int = 200) -> list[dict]:
        q = "SELECT timestamp, plc_id, event_type, details, ok FROM events"
        clauses, params = [], []
        if plc_id:
            clauses.append("plc_id = ?"); params.append(plc_id)
        if event_type:
            clauses.append("event_type = ?"); params.append(event_type)
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        q += " ORDER BY id DESC LIMIT ?"
        params.append(limit)

        with self._lock:
            cur = self._conn.execute(q, params)
            rows = cur.fetchall()

        return [
            {
                "timestamp": r[0],
                "plc_id": r[1],
                "event_type": r[2],
                "details": json.loads(r[3]) if r[3] else {},
                "ok": None if r[4] is None else bool(r[4]),
            }
            for r in rows
        ]

    def close(self):
        with self._lock:
            self._conn.close()