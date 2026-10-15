"""
Pre-eradication forensic snapshot (Task 24).

Wraps the base `capture()` from Task 6 to add:
    - a `tag` field            ("pre_eradication", "post_eradication", ...)
    - a `linked_to` field      ({file, sha256_hash, tag} of a prior snapshot)
    - a `linked_files` list    for future multi-link scenarios

The tagged snapshot is written alongside the base one so all evidence
lives in the same directory.
"""
import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path

from .snapshot import capture as base_capture


log = logging.getLogger("forensics.pre_eradication")


# ---------------------------------------------------------------------------
# Snapshot linking
# ---------------------------------------------------------------------------

def _load_snapshot_meta(path: str | Path) -> dict:
    """Read just the identifying fields from an existing snapshot."""
    with open(path) as f:
        data = json.load(f)
    return {
        "file": Path(path).name,
        "sha256_hash": data.get("sha256_hash", ""),
        "tag": data.get("tag", "unknown"),
        "timestamp": data.get("timestamp", ""),
    }


def _apply_tag(payload: dict,
               tag: str,
               linked_to: dict | None = None,
               out_dir: Path = Path(".")) -> dict:
    """
    Write a tagged copy of the snapshot payload.

    The tagged copy contains the same `areas` block but adds `tag` and
    `linked_to`; its own `sha256_hash` is recomputed over the payload
    including the new fields, so the hash uniquely identifies this
    tagged snapshot.
    """
    payload = dict(payload)                # shallow copy so we don't mutate
    payload["tag"] = tag
    if linked_to:
        payload["linked_to"] = linked_to

    # Recompute the SHA-256 over the canonical form of the *whole* payload
    # (this covers the areas, the tag, and the link).
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"),
    )
    payload["sha256_hash"] = hashlib.sha256(canonical.encode()).hexdigest()

    out_dir.mkdir(parents=True, exist_ok=True)
    fname = out_dir / (
        f"{tag}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )
    with fname.open("w") as f:
        json.dump(payload, f, indent=2)

    log.info(f"tagged snapshot written: {fname} (tag={tag})")
    return {"path": str(fname), **payload}


# ---------------------------------------------------------------------------
# Public API — pre-eradication
# ---------------------------------------------------------------------------

def capture_pre_eradication(
    plc_ip: str,
    infection_snapshot: str | Path | None = None,
    output_dir: str | Path = "output",
    tcp_port: int = 1102,
    db1_size: int = 100,
    db2_size: int = 100,
    merker_size: int = 100,
) -> dict:
    """
    Take a snapshot tagged `pre_eradication` immediately before an
    eradication command is issued.

    Parameters
    ----------
    plc_ip               : target PLC
    infection_snapshot   : path to the snapshot taken when the infection
                           was first detected — linked into the output
    output_dir           : where to write the tagged snapshot
    tcp_port / sizes     : passed through to `base_capture()`

    Returns
    -------
    dict with the tagged snapshot payload (path, hash, areas, link).
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. capture the current (still-compromised) state
    log.info(f"capturing pre-eradication snapshot for {plc_ip}")
    base = base_capture(
        plc_ip,
        tcp_port=tcp_port,
        db1_size=db1_size,
        db2_size=db2_size,
        merker_size=merker_size,
        output_dir=str(out_dir),
    )

    # 2. build the link to the infection snapshot, if provided
    linked_to = None
    if infection_snapshot:
        inf_path = Path(infection_snapshot)
        if inf_path.exists():
            linked_to = _load_snapshot_meta(inf_path)
            log.info(
                f"linked pre_eradication -> infection "
                f"({linked_to['file']} @ {linked_to['sha256_hash'][:12]}...)"
            )
        else:
            log.warning(f"infection snapshot not found: {inf_path}")

    # 3. write the tagged copy with recomputed hash
    tagged = _apply_tag(
        {
            "timestamp": base["timestamp"],
            "plc_ip": base["plc_ip"],
            "areas": base["areas"],
        },
        tag="pre_eradication",
        linked_to=linked_to,
        out_dir=out_dir,
    )

    # delete the base untagged file to keep the evidence directory clean
    try:
        Path(base["path"]).unlink()
        log.info(f"removed untagged duplicate: {base['path']}")
    except Exception as e:
        log.warning(f"could not remove untagged duplicate: {e}")

    return tagged


# ---------------------------------------------------------------------------
# Public API — post-eradication
# ---------------------------------------------------------------------------

def capture_post_eradication(
    plc_ip: str,
    pre_eradication_snapshot: str | Path,
    output_dir: str | Path = "output",
    tcp_port: int = 1102,
    db1_size: int = 100,
    db2_size: int = 100,
    merker_size: int = 100,
) -> dict:
    """
    Companion helper — snapshot after eradication, linked to the
    pre-eradication snapshot.
    """
    out_dir = Path(output_dir)

    base = base_capture(
        plc_ip,
        tcp_port=tcp_port,
        db1_size=db1_size,
        db2_size=db2_size,
        merker_size=merker_size,
        output_dir=str(out_dir),
    )

    linked = _load_snapshot_meta(pre_eradication_snapshot)
    tagged = _apply_tag(
        {
            "timestamp": base["timestamp"],
            "plc_ip": base["plc_ip"],
            "areas": base["areas"],
        },
        tag="post_eradication",
        linked_to=linked,
        out_dir=out_dir,
    )

    try:
        Path(base["path"]).unlink()
    except Exception:
        pass

    return tagged


# ---------------------------------------------------------------------------
# CLI — pre-eradication
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(
        description="Pre-eradication forensic snapshot (Task 24)"
    )
    p.add_argument("plc_ip")
    p.add_argument("--infection", default=None,
                   help="Path to the infection snapshot to link")
    p.add_argument("--output-dir", default="output")
    p.add_argument("--port", type=int, default=1102)
    args = p.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    result = capture_pre_eradication(
        args.plc_ip,
        infection_snapshot=args.infection,
        output_dir=args.output_dir,
        tcp_port=args.port,
    )

    print(f"\nPre-eradication snapshot written:")
    print(f"  path     : {result['path']}")
    print(f"  tag      : {result['tag']}")
    print(f"  sha256   : {result['sha256_hash']}")
    if result.get("linked_to"):
        lt = result["linked_to"]
        print(f"  linked to: {lt['file']} ({lt['sha256_hash'][:16]}...)")