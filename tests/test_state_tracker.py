"""Tests for state_tracker module."""

import pytest
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import shutil

from archiver.state_tracker import StateTracker


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    temp_dir = tempfile.mkdtemp()
    db_path = Path(temp_dir) / "test.db"
    yield str(db_path)
    shutil.rmtree(temp_dir)


def test_init_creates_tables(temp_db):
    """Test that initialization creates required tables."""
    tracker = StateTracker(temp_db)
    assert Path(temp_db).exists()


def test_is_archived_returns_false_for_new_document(temp_db):
    """Test that is_archived returns False for new documents."""
    tracker = StateTracker(temp_db)
    assert not tracker.is_archived("doc_123", datetime.now())


def test_mark_archived_records_document(temp_db):
    """Test that mark_archived records a document."""
    tracker = StateTracker(temp_db)
    now = datetime.now()

    tracker.mark_archived(
        document_id="doc_123",
        title="Test Meeting",
        created_at=now,
        updated_at=now,
        file_path="2026/01/test.md",
        commit_sha="abc123"
    )

    assert tracker.is_archived("doc_123", now)


def test_is_archived_handles_updates(temp_db):
    """Test that is_archived detects updated documents."""
    tracker = StateTracker(temp_db)
    old_time = datetime.now() - timedelta(hours=1)
    new_time = datetime.now()

    # Archive with old timestamp
    tracker.mark_archived(
        document_id="doc_123",
        title="Test Meeting",
        created_at=old_time,
        updated_at=old_time,
        file_path="2026/01/test.md"
    )

    # Should return False for newer update time
    assert not tracker.is_archived("doc_123", new_time)


def test_get_last_run_timestamp_returns_none_initially(temp_db):
    """Test that get_last_run_timestamp returns None initially."""
    tracker = StateTracker(temp_db)
    assert tracker.get_last_run_timestamp() is None


def test_update_last_run_records_timestamp(temp_db):
    """Test that update_last_run records a timestamp."""
    tracker = StateTracker(temp_db)
    before = datetime.now(timezone.utc)

    tracker.update_last_run(
        documents_processed=5,
        documents_archived=4,
        documents_failed=1
    )

    last_run = tracker.get_last_run_timestamp()
    assert last_run is not None
    assert last_run >= before


def test_last_run_timestamp_is_utc_aware(temp_db):
    """Last run timestamp must be timezone-aware UTC.

    Regression test: previously stored naive local time, which the fetcher
    then incorrectly interpreted as UTC — causing new docs to be filtered out
    whenever the system's local offset was not zero (e.g. BST).
    """
    tracker = StateTracker(temp_db)
    tracker.update_last_run(documents_processed=0, documents_archived=0)

    last_run = tracker.get_last_run_timestamp()
    assert last_run.tzinfo is not None, "last run timestamp must be tz-aware"
    assert last_run.utcoffset() == timedelta(0), "last run timestamp must be in UTC"


def test_last_run_timestamp_matches_utc_now(temp_db):
    """Stored timestamp should reflect UTC wall-clock, not local time."""
    tracker = StateTracker(temp_db)
    before = datetime.now(timezone.utc)
    tracker.update_last_run()
    after = datetime.now(timezone.utc)

    last_run = tracker.get_last_run_timestamp()
    assert before <= last_run <= after


def test_legacy_naive_last_run_is_interpreted_as_local(temp_db):
    """Existing DBs may contain naive timestamps written before the fix.

    Those were written via datetime.now() (local time) and must be converted
    to UTC on read, not mis-interpreted as UTC.
    """
    import sqlite3

    tracker = StateTracker(temp_db)
    # Simulate a legacy row: naive local-time isoformat string
    naive_local = datetime(2026, 4, 22, 15, 0, 0)  # 15:00 local
    with sqlite3.connect(temp_db) as conn:
        conn.execute(
            "INSERT INTO archive_runs (run_at, documents_processed, documents_archived, documents_failed) VALUES (?, 0, 0, 0)",
            (naive_local.isoformat(),),
        )
        conn.commit()

    last_run = tracker.get_last_run_timestamp()
    assert last_run.tzinfo is not None, "legacy naive rows must be converted to tz-aware"
    # The UTC equivalent of 15:00 local equals naive_local.astimezone(UTC)
    expected = naive_local.astimezone(timezone.utc)
    assert last_run == expected


def test_get_pending_documents_empty_initially(temp_db):
    """No documents are pending on a fresh database."""
    tracker = StateTracker(temp_db)
    assert tracker.get_pending_documents() == []


def test_mark_pending_records_document(temp_db):
    """A failed document is recorded in the pending queue for retry."""
    tracker = StateTracker(temp_db)
    updated_at = datetime.now(timezone.utc)

    tracker.mark_pending("doc_123", updated_at, error="commit failed")

    pending = tracker.get_pending_documents()
    assert [p["document_id"] for p in pending] == ["doc_123"]
    assert pending[0]["attempts"] == 1
    assert pending[0]["last_error"] == "commit failed"


def test_mark_pending_increments_attempts(temp_db):
    """Re-failing the same document increments its attempt count."""
    tracker = StateTracker(temp_db)
    updated_at = datetime.now(timezone.utc)

    tracker.mark_pending("doc_123", updated_at, error="first failure")
    tracker.mark_pending("doc_123", updated_at, error="second failure")

    pending = tracker.get_pending_documents()
    assert len(pending) == 1
    assert pending[0]["attempts"] == 2
    assert pending[0]["last_error"] == "second failure"


def test_clear_pending_removes_document(temp_db):
    """Once successfully archived, a document is removed from the queue."""
    tracker = StateTracker(temp_db)
    updated_at = datetime.now(timezone.utc)
    tracker.mark_pending("doc_123", updated_at, error="commit failed")

    tracker.clear_pending("doc_123")

    assert tracker.get_pending_documents() == []


def test_clear_pending_is_safe_for_unknown_document(temp_db):
    """Clearing a document that was never pending is a no-op, not an error."""
    tracker = StateTracker(temp_db)
    tracker.clear_pending("never_seen")  # should not raise
    assert tracker.get_pending_documents() == []


def test_get_archived_count(temp_db):
    """Test that get_archived_count returns correct count."""
    tracker = StateTracker(temp_db)
    now = datetime.now()

    assert tracker.get_archived_count() == 0

    tracker.mark_archived("doc_1", "Meeting 1", now, now, "path1.md")
    tracker.mark_archived("doc_2", "Meeting 2", now, now, "path2.md")

    assert tracker.get_archived_count() == 2
