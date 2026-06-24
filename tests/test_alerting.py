"""Tests for failure alerting."""

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import shutil

import pytest

from archiver.main import documents_needing_alert, maybe_alert_failures
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
