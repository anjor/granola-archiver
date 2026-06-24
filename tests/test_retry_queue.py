"""Tests for the retry-queue orchestration helpers in main.py."""

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import tempfile
import shutil

import pytest

from archiver.main import pending_ids_to_fetch, record_archive_outcome
from archiver.models import ArchiveResult
from archiver.state_tracker import StateTracker


@pytest.fixture
def temp_db():
    temp_dir = tempfile.mkdtemp()
    db_path = Path(temp_dir) / "test.db"
    yield str(db_path)
    shutil.rmtree(temp_dir)


def _doc(doc_id, updated_at=None):
    return SimpleNamespace(
        document_id=doc_id,
        updated_at=updated_at or datetime.now(timezone.utc),
    )


# --- pending_ids_to_fetch -------------------------------------------------


def test_pending_ids_to_fetch_returns_ids_not_already_fetched():
    """Pending docs outside the watermark window must be re-fetched."""
    fetched = [_doc("a"), _doc("b")]
    pending = [{"document_id": "b"}, {"document_id": "c"}]

    assert pending_ids_to_fetch(fetched, pending) == ["c"]


def test_pending_ids_to_fetch_empty_when_all_present():
    """No extra fetches when every pending doc is already in the window."""
    fetched = [_doc("a"), _doc("b")]
    pending = [{"document_id": "a"}]

    assert pending_ids_to_fetch(fetched, pending) == []


def test_pending_ids_to_fetch_empty_pending():
    assert pending_ids_to_fetch([_doc("a")], []) == []


# --- record_archive_outcome ----------------------------------------------


def test_failed_outcome_marks_document_pending(temp_db):
    """A failed archive is queued for retry."""
    tracker = StateTracker(temp_db)
    doc = _doc("doc_123")
    result = ArchiveResult(success=False, doc_id="doc_123", error="commit failed")

    record_archive_outcome(tracker, doc, result, dry_run=False)

    pending = tracker.get_pending_documents()
    assert [p["document_id"] for p in pending] == ["doc_123"]
    assert pending[0]["last_error"] == "commit failed"


def test_successful_outcome_clears_pending(temp_db):
    """A document that previously failed is removed from the queue on success."""
    tracker = StateTracker(temp_db)
    doc = _doc("doc_123")
    tracker.mark_pending("doc_123", doc.updated_at, error="earlier failure")

    result = ArchiveResult(success=True, doc_id="doc_123", file_path="2026/01/x.md")
    record_archive_outcome(tracker, doc, result, dry_run=False)

    assert tracker.get_pending_documents() == []


def test_dry_run_does_not_touch_pending_queue(temp_db):
    """Dry runs never mutate retry state."""
    tracker = StateTracker(temp_db)
    doc = _doc("doc_123")
    result = ArchiveResult(success=False, doc_id="doc_123", error="boom")

    record_archive_outcome(tracker, doc, result, dry_run=True)

    assert tracker.get_pending_documents() == []
