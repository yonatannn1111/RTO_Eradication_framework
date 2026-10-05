"""Event scheduler — periodically runs tasks (attacks, snapshots, checks)."""
import time
import threading
from datetime import datetime
from typing import Callable


class Scheduler:
    """Simple fixed-interval scheduler for one or more named tasks."""

    def __init__(self):
        self._tasks = []           # (name, interval_s, callable)
        self._stop = threading.Event()
        self._thread = None

    def add(self, name: str, interval_s: float, fn: Callable):
        self._tasks.append((name, interval_s, fn))

    def _run(self):
        next_at = {name: time.time() for name, _, _ in self._tasks}
        while not self._stop.is_set():
            now = time.time()
            for name, interval, fn in self._tasks:
                if now >= next_at[name]:
                    try:
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] "
                              f"scheduler: running '{name}'")
                        fn()
                    except Exception as e:
                        print(f"  task '{name}' failed: {e}")
                    next_at[name] = now + interval
            time.sleep(0.1)

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)


if __name__ == "__main__":
    s = Scheduler()
    s.add("heartbeat", 3.0, lambda: print("  tick"))
    s.start()
    try:
        time.sleep(10)
    finally:
        s.stop()
