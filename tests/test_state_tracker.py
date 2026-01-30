"""Tests for state_tracker module."""

import pytest
from datetime import datetime, timedelta
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
    before = datetime.now()

    tracker.update_last_run(
        documents_processed=5,
        documents_archived=4,
        documents_failed=1
    )

    last_run = tracker.get_last_run_timestamp()
    assert last_run is not None
    assert last_run >= before


def test_get_archived_count(temp_db):
    """Test that get_archived_count returns correct count."""
    tracker = StateTracker(temp_db)
    now = datetime.now()

    assert tracker.get_archived_count() == 0

    tracker.mark_archived("doc_1", "Meeting 1", now, now, "path1.md")
    tracker.mark_archived("doc_2", "Meeting 2", now, now, "path2.md")

    assert tracker.get_archived_count() == 2
