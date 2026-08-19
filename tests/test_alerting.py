"""Tests for failure alerting."""

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import shutil

import pytest

from granola_client.errors import GranolaAuthError

from archiver.main import documents_needing_alert, maybe_alert_failures
from archiver.notifications import clear_run_failure, record_run_failure
from archiver.state_tracker import StateTracker


@pytest.fixture
def temp_db():
    temp_dir = tempfile.mkdtemp()
    db_path = Path(temp_dir) / "test.db"
    yield str(db_path)
    shutil.rmtree(temp_dir)


# --- documents_needing_alert (pure) --------------------------------------


def test_no_alert_below_threshold():
    """A document that has only failed once is not yet alert-worthy."""
    pending = [{"document_id": "a", "attempts": 1, "last_error": "x"}]
    assert documents_needing_alert(pending, attempt_threshold=3) == []


def test_alert_at_threshold():
    """A document that has failed >= threshold times is alert-worthy."""
    pending = [
        {"document_id": "a", "attempts": 3, "last_error": "lock"},
        {"document_id": "b", "attempts": 1, "last_error": "x"},
    ]
    alerting = documents_needing_alert(pending, attempt_threshold=3)
    assert [d["document_id"] for d in alerting] == ["a"]


# --- maybe_alert_failures (dispatch) -------------------------------------


def test_maybe_alert_invokes_notifier_when_threshold_reached(temp_db):
    """When a document crosses the threshold, the notifier is called once."""
    tracker = StateTracker(temp_db)
    updated_at = datetime.now(timezone.utc)
    for _ in range(3):
        tracker.mark_pending("doc_123", updated_at, error="commit failed")

    calls = []
    alerted = maybe_alert_failures(
        tracker, notifier=lambda title, message: calls.append((title, message)),
        attempt_threshold=3,
    )

    assert [d["document_id"] for d in alerted] == ["doc_123"]
    assert len(calls) == 1
    title, message = calls[0]
    assert "doc_123" in message


def test_maybe_alert_does_not_notify_below_threshold(temp_db):
    """No notification while failures are still below the threshold."""
    tracker = StateTracker(temp_db)
    tracker.mark_pending("doc_123", datetime.now(timezone.utc), error="commit failed")

    calls = []
    alerted = maybe_alert_failures(
        tracker, notifier=lambda title, message: calls.append((title, message)),
        attempt_threshold=3,
    )

    assert alerted == []
    assert calls == []


# --- run-level failure alerting ------------------------------------------


def test_record_run_failure_writes_marker_and_notifies(tmp_path):
    """An auth-level failure must alert even though the retry queue is empty."""
    marker = tmp_path / "state" / "LAST_FAILURE"
    calls = []

    returned = record_run_failure(
        GranolaAuthError("Granola token file not found: /x/supabase.json"),
        notifier=lambda title, message: calls.append((title, message)),
        marker_path=marker,
    )

    assert returned == marker
    assert marker.exists()
    assert len(calls) == 1
    title, message = calls[0]
    assert "failed" in title.lower()
    assert "supabase.json" in message


def test_marker_is_a_single_line_with_timestamp_and_error(tmp_path):
    """The marker is meant to be readable with `cat`, so keep it to one line."""
    marker = tmp_path / "LAST_FAILURE"

    record_run_failure(
        RuntimeError("line one\nline two"), notifier=lambda t, m: None, marker_path=marker
    )

    content = marker.read_text()
    assert content.count("\n") == 1  # trailing newline only
    line = content.strip()
    assert line.startswith(str(datetime.now(timezone.utc).year))
    assert "line one line two" in line


def test_record_run_failure_creates_parent_directory(tmp_path):
    """The state directory may not exist on a fresh machine."""
    marker = tmp_path / "deeply" / "nested" / "LAST_FAILURE"

    record_run_failure(RuntimeError("boom"), notifier=lambda t, m: None, marker_path=marker)

    assert marker.exists()


def test_notification_still_fires_if_marker_cannot_be_written(tmp_path):
    """A read-only state dir must not swallow the alert."""
    marker = tmp_path / "file" / "LAST_FAILURE"
    (tmp_path / "file").write_text("not a directory")
    calls = []

    record_run_failure(
        RuntimeError("boom"), notifier=lambda t, m: calls.append(m), marker_path=marker
    )

    assert not marker.exists()
    assert calls == ["boom"]


def test_clear_run_failure_removes_marker(tmp_path):
    """A later success must retract the failure signal."""
    marker = tmp_path / "LAST_FAILURE"
    marker.write_text("2026-08-19T00:00:00+00:00 boom\n")

    assert clear_run_failure(marker) is True
    assert not marker.exists()


def test_clear_run_failure_is_a_noop_when_absent(tmp_path):
    """Clearing when healthy is harmless and reports nothing was cleared."""
    assert clear_run_failure(tmp_path / "LAST_FAILURE") is False
