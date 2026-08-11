"""Tests for run-level failure tracking in StateTracker.

Persisting the failure streak is what lets alerting survive across the
separate processes launchd spawns every 30 minutes.
"""

import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from archiver.state_tracker import StateTracker

NOW = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def temp_db():
    temp_dir = tempfile.mkdtemp()
    db_path = Path(temp_dir) / "test.db"
    yield str(db_path)
    shutil.rmtree(temp_dir)


def test_starts_with_a_clean_bill_of_health(temp_db):
    health = StateTracker(temp_db).get_run_health()

    assert health["consecutive_failures"] == 0
    assert health["last_alert_at"] is None
    assert health["last_error"] is None


def test_records_a_failure(temp_db):
    tracker = StateTracker(temp_db)

    tracker.record_run_failure("GranolaAuthError: token file not found", NOW)

    health = tracker.get_run_health()
    assert health["consecutive_failures"] == 1
    assert "GranolaAuthError" in health["last_error"]


def test_failures_accumulate(temp_db):
    tracker = StateTracker(temp_db)

    for i in range(3):
        tracker.record_run_failure(f"boom {i}", NOW + timedelta(minutes=30 * i))

    health = tracker.get_run_health()
    assert health["consecutive_failures"] == 3
    # The most recent error is the useful one.
    assert health["last_error"] == "boom 2"


def test_success_resets_the_streak(temp_db):
    tracker = StateTracker(temp_db)
    tracker.record_run_failure("boom", NOW)
    tracker.record_run_failure("boom", NOW)

    tracker.clear_run_failures()

    health = tracker.get_run_health()
    assert health["consecutive_failures"] == 0
    assert health["last_error"] is None
    assert health["last_alert_at"] is None


def test_alert_timestamp_persists(temp_db):
    tracker = StateTracker(temp_db)
    tracker.record_run_failure("boom", NOW)

    tracker.mark_run_alert_sent(NOW)

    assert tracker.get_run_health()["last_alert_at"] == NOW


def test_state_survives_a_new_process(temp_db):
    # Each launchd invocation is a fresh process against the same file.
    StateTracker(temp_db).record_run_failure("boom", NOW)
    StateTracker(temp_db).record_run_failure("boom again", NOW)

    assert StateTracker(temp_db).get_run_health()["consecutive_failures"] == 2


def test_clearing_when_already_healthy_is_harmless(temp_db):
    tracker = StateTracker(temp_db)

    tracker.clear_run_failures()

    assert tracker.get_run_health()["consecutive_failures"] == 0


def test_adds_table_to_a_preexisting_database(temp_db):
    # The live DB predates this feature; opening it must not fail.
    old = StateTracker(temp_db)
    old.update_last_run(documents_processed=1, documents_archived=1, documents_failed=0)

    assert StateTracker(temp_db).get_run_health()["consecutive_failures"] == 0
