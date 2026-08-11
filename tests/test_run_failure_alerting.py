"""Tests for alerting when a whole run dies.

Reproduces the August 2026 outage: the archiver ran every 30 minutes for six
days, failed at the auth step every time, and never told anyone. The run never
reached maybe_alert_failures, and pending_documents stayed empty, so the
existing alerting could not have fired.
"""

import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from archiver.main import alert_run_failure, run_with_health_tracking
from archiver.state_tracker import StateTracker

NOW = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)
AUTH_ERROR = "GranolaAuthError: Granola token file not found"


@pytest.fixture
def tracker():
    temp_dir = tempfile.mkdtemp()
    yield StateTracker(str(Path(temp_dir) / "test.db"))
    shutil.rmtree(temp_dir)


class RecordingNotifier:
    """Stands in for the macOS notifier, capturing what would be shown."""

    def __init__(self):
        self.calls = []

    def __call__(self, title, message):
        self.calls.append((title, message))


def test_first_failure_alerts_immediately(tracker):
    notifier = RecordingNotifier()

    alerted = alert_run_failure(tracker, AUTH_ERROR, notifier=notifier, now=NOW)

    assert alerted is True
    assert len(notifier.calls) == 1
    title, message = notifier.calls[0]
    assert "archiver" in title.lower()
    assert "GranolaAuthError" in message


def test_repeat_failures_are_throttled(tracker):
    notifier = RecordingNotifier()

    # The real outage: six days of half-hourly runs, every one failing.
    runs = 6 * 24 * 2
    for i in range(runs):
        alert_run_failure(
            tracker, AUTH_ERROR, notifier=notifier, now=NOW + timedelta(minutes=30 * i)
        )

    assert tracker.get_run_health()["consecutive_failures"] == runs
    # One per 6h cooldown over six days — noticeable, not 288 notifications.
    assert len(notifier.calls) == 24


def test_alerts_again_after_cooldown(tracker):
    notifier = RecordingNotifier()

    alert_run_failure(tracker, AUTH_ERROR, notifier=notifier, now=NOW)
    alert_run_failure(tracker, AUTH_ERROR, notifier=notifier, now=NOW + timedelta(hours=7))

    assert len(notifier.calls) == 2


def test_failure_is_recorded_even_when_throttled(tracker):
    notifier = RecordingNotifier()

    alert_run_failure(tracker, AUTH_ERROR, notifier=notifier, now=NOW)
    alert_run_failure(tracker, "different boom", notifier=notifier, now=NOW + timedelta(minutes=30))

    health = tracker.get_run_health()
    assert health["consecutive_failures"] == 2
    assert health["last_error"] == "different boom"


def test_streak_length_reaches_the_message(tracker):
    notifier = RecordingNotifier()

    alert_run_failure(tracker, AUTH_ERROR, notifier=notifier, now=NOW)
    alert_run_failure(tracker, AUTH_ERROR, notifier=notifier, now=NOW + timedelta(hours=7))

    assert "2 consecutive" in notifier.calls[-1][1]


def test_a_broken_notifier_does_not_break_the_run(tracker):
    def exploding_notifier(title, message):
        raise RuntimeError("osascript is unavailable")

    # Best-effort: notification problems must not add a second failure mode.
    alert_run_failure(tracker, AUTH_ERROR, notifier=exploding_notifier, now=NOW)

    assert tracker.get_run_health()["consecutive_failures"] == 1


def test_successful_run_clears_the_streak(tracker):
    notifier = RecordingNotifier()
    alert_run_failure(tracker, AUTH_ERROR, notifier=notifier, now=NOW)

    result = run_with_health_tracking(tracker, lambda: "summary", notifier=notifier, now=NOW)

    assert result == "summary"
    assert tracker.get_run_health()["consecutive_failures"] == 0


def test_failing_run_alerts_and_reraises(tracker):
    notifier = RecordingNotifier()

    def boom():
        raise ValueError("git is wedged")

    with pytest.raises(ValueError, match="git is wedged"):
        run_with_health_tracking(tracker, boom, notifier=notifier, now=NOW)

    assert len(notifier.calls) == 1
    assert "git is wedged" in notifier.calls[0][1]
    # The exception type is the most useful triage hint.
    assert "ValueError" in notifier.calls[0][1]
    assert tracker.get_run_health()["consecutive_failures"] == 1


def test_recovery_after_outage_resets_cooldown(tracker):
    notifier = RecordingNotifier()
    alert_run_failure(tracker, AUTH_ERROR, notifier=notifier, now=NOW)

    run_with_health_tracking(tracker, lambda: "ok", notifier=notifier, now=NOW)
    # A fresh failure after recovery should alert at once, not wait out a
    # cooldown left over from the previous outage.
    alert_run_failure(tracker, AUTH_ERROR, notifier=notifier, now=NOW + timedelta(minutes=30))

    assert len(notifier.calls) == 2


def test_keyboard_interrupt_is_not_treated_as_a_failure(tracker):
    notifier = RecordingNotifier()

    def interrupted():
        raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        run_with_health_tracking(tracker, interrupted, notifier=notifier, now=NOW)

    # You pressed Ctrl-C; that is not an outage.
    assert notifier.calls == []
    assert tracker.get_run_health()["consecutive_failures"] == 0
