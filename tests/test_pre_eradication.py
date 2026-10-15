"""Pre-eradication snapshot tests — mocked capture, no PLC."""
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest


def _fake_base_capture(tmp_path):
    """Return a mock that writes a base snapshot and returns its path."""
    def _fake(plc_ip, tcp_port=1102, db1_size=100, db2_size=100,
              merker_size=100, output_dir="."):
        out = Path(output_dir); out.mkdir(parents=True, exist_ok=True)
        path = out / "snapshot_base.json"
        payload = {
            "timestamp": "2026-10-13 10:00:00",
            "plc_ip": plc_ip,
            "areas": {
                "DB1": [1] * 100,
                "DB2": [2] * 100,
                "Merker": [3] * 100,
            },
        }
        path.write_text(json.dumps(payload, indent=2))
        return {"path": str(path), **payload}
    return _fake


def test_pre_eradication_writes_tagged_snapshot(tmp_path):
    from modules.forensics.pre_eradication import capture_pre_eradication

    with patch("modules.forensics.pre_eradication.base_capture",
               side_effect=_fake_base_capture(tmp_path)):
        result = capture_pre_eradication(
            "127.0.0.1",
            output_dir=str(tmp_path),
        )

    assert result["tag"] == "pre_eradication"
    assert Path(result["path"]).exists()
    assert result["sha256_hash"]
    # filename should start with the tag
    assert Path(result["path"]).name.startswith("pre_eradication_")


def test_pre_eradication_links_to_infection(tmp_path):
    from modules.forensics.pre_eradication import capture_pre_eradication

    # create a fake infection snapshot
    infection = tmp_path / "infection_20261013_100000.json"
    infection.write_text(json.dumps({
        "timestamp": "2026-10-13 09:55:00",
        "plc_ip": "127.0.0.1",
        "tag": "infection",
        "sha256_hash": "abc123",
        "areas": {"DB1": [0]},
    }))

    with patch("modules.forensics.pre_eradication.base_capture",
               side_effect=_fake_base_capture(tmp_path)):
        result = capture_pre_eradication(
            "127.0.0.1",
            infection_snapshot=infection,
            output_dir=str(tmp_path),
        )

    assert "linked_to" in result
    assert result["linked_to"]["file"] == "infection_20261013_100000.json"
    assert result["linked_to"]["sha256_hash"] == "abc123"


def test_pre_eradication_missing_infection_link(tmp_path):
    from modules.forensics.pre_eradication import capture_pre_eradication

    with patch("modules.forensics.pre_eradication.base_capture",
               side_effect=_fake_base_capture(tmp_path)):
        result = capture_pre_eradication(
            "127.0.0.1",
            infection_snapshot=tmp_path / "does_not_exist.json",
            output_dir=str(tmp_path),
        )

    # no link, but tagged snapshot still written
    assert result["tag"] == "pre_eradication"
    assert "linked_to" not in result


def test_pre_eradication_hash_is_recomputable(tmp_path):
    from modules.forensics.pre_eradication import capture_pre_eradication

    with patch("modules.forensics.pre_eradication.base_capture",
               side_effect=_fake_base_capture(tmp_path)):
        result = capture_pre_eradication(
            "127.0.0.1",
            output_dir=str(tmp_path),
        )

    # re-read the file and recompute the hash — should match
    on_disk = json.loads(Path(result["path"]).read_text())
    stored_hash = on_disk.pop("sha256_hash")
    canonical = json.dumps(on_disk, sort_keys=True, separators=(",", ":"))
    recomputed = hashlib.sha256(canonical.encode()).hexdigest()
    assert stored_hash == recomputed


def test_base_untagged_file_is_removed(tmp_path):
    from modules.forensics.pre_eradication import capture_pre_eradication

    with patch("modules.forensics.pre_eradication.base_capture",
               side_effect=_fake_base_capture(tmp_path)):
        capture_pre_eradication(
            "127.0.0.1",
            output_dir=str(tmp_path),
        )

    # only the tagged snapshot should remain
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    assert files[0].name.startswith("pre_eradication_")


def test_post_eradication_links_to_pre(tmp_path):
    from modules.forensics.pre_eradication import (
        capture_pre_eradication, capture_post_eradication,
    )

    with patch("modules.forensics.pre_eradication.base_capture",
               side_effect=_fake_base_capture(tmp_path)):
        pre = capture_pre_eradication("127.0.0.1", output_dir=str(tmp_path))
        post = capture_post_eradication(
            "127.0.0.1",
            pre_eradication_snapshot=pre["path"],
            output_dir=str(tmp_path),
        )

    assert post["tag"] == "post_eradication"
    assert post["linked_to"]["file"] == Path(pre["path"]).name
    assert post["linked_to"]["sha256_hash"] == pre["sha256_hash"]