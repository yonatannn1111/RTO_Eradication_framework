"""Snapshot diff — no external dependencies."""


def diff(snapshot_a: dict, snapshot_b: dict) -> dict:
    """Compare two snapshots and return per-area byte diffs."""
    result = {"areas": {}}
    for name in snapshot_a.get("areas", {}):
        a = snapshot_a["areas"].get(name) or []
        b = snapshot_b["areas"].get(name) or []
        changes = [
            {"offset": i, "from": x, "to": y}
            for i, (x, y) in enumerate(zip(a, b)) if x != y
        ]
        result["areas"][name] = {
            "count": len(changes),
            "changes": changes[:50],
        }
    return result