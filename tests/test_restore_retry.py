"""Restore retry engine tests — simulate failures without a real PLC."""
import json
from pathlib import Path
from unittest.mock import patch

import pytest


# --- fixtures --------------------------------------------------------------

@pytest.fixture
def snapshot_file(tmp_path):
    p = tmp_path / "snap.json"
    p.write_text(json.dumps({
        "timestamp": "2026-10-08 10:00:00",
        "plc_ip": "127.0.0.1",
        "areas": {
            "DB1": [1, 2, 3, 4],
            "DB2": [0, 0],
            "Merker": [9],
        },
    }))
    return str(p)


# --- tests -----------------------------------------------------------------

def test_succeeds_on_first_attempt(snapshot_file):
    from modules.forensics.restore import restore_with_retry

    good_report = {
        "overall": "PASS",
        "areas": {
            "DB1": {"status": "match"},
            "DB2": {"status": "match"},
            "Merker": {"status": "match"},
        },
    }
    with patch("modules.forensics.restore._write_all"), \
         patch("modules.forensics.restore._read_and_compare",
               return_value=good_report):
        ok, history, last = restore_with_retry(
            snapshot_file, "127.0.0.1",
            max_attempts=3, retry_delay_s=0,
        )

    assert ok is True
    assert len(history) == 1
    assert history[0].ok is True


def test_succeeds_on_second_attempt(snapshot_file):
    from modules.forensics.restore import restore_with_retry

    bad = {"overall": "FAIL", "areas": {"DB1": {"status": "mismatch"}}}
    good = {"overall": "PASS", "areas": {"DB1": {"status": "match"}}}

    with patch("modules.forensics.restore._write_all"), \
         patch("modules.forensics.restore._read_and_compare",
               side_effect=[bad, good]):
        ok, history, last = restore_with_retry(
            snapshot_file, "127.0.0.1",
            max_attempts=3, retry_delay_s=0,
        )

    assert ok is True
    assert len(history) == 2
    assert history[0].ok is False
    assert history[1].ok is True


def test_raises_after_all_attempts_fail(snapshot_file):
    from modules.forensics.restore import (
        restore_with_retry, RestoreFailedError,
    )

    bad = {"overall": "FAIL", "areas": {"DB1": {"status": "mismatch"}}}

    with patch("modules.forensics.restore._write_all"), \
         patch("modules.forensics.restore._read_and_compare",
               return_value=bad):
        with pytest.raises(RestoreFailedError) as exc:
            restore_with_retry(
                snapshot_file, "127.0.0.1",
                max_attempts=3, retry_delay_s=0,
            )

    assert exc.value.attempts == 3


def test_no_raise_returns_false(snapshot_file):
    from modules.forensics.restore import restore_with_retry

    bad = {"overall": "FAIL", "areas": {"DB1": {"status": "mismatch"}}}

    with patch("modules.forensics.restore._write_all"), \
         patch("modules.forensics.restore._read_and_compare",
               return_value=bad):
        ok, history, last = restore_with_retry(
            snapshot_file, "127.0.0.1",
            max_attempts=2, retry_delay_s=0,
            raise_on_failure=False,
        )

    assert ok is False
    assert len(history) == 2


def test_write_exception_is_caught_and_retried(snapshot_file):
    from modules.forensics.restore import restore_with_retry

    good = {"overall": "PASS", "areas": {"DB1": {"status": "match"}}}

    with patch("modules.forensics.restore._write_all",
               side_effect=[OSError("network down"), None]), \
         patch("modules.forensics.restore._read_and_compare",
               return_value=good):
        ok, history, last = restore_with_retry(
            snapshot_file, "127.0.0.1",
            max_attempts=3, retry_delay_s=0,
        )

    assert ok is True
    assert history[0].ok is False
    assert "network down" in history[0].error
    assert history[1].ok is True