"""Tests for run-level failure alerting.

The retry-queue alerting in ``maybe_alert_failures`` only ever sees documents
that were fetched and then failed to archive. A run that dies before that
point — expired credentials, network down, git trouble — enqueues nothing and
alerts nobody. That is how the August 2026 auth break went unnoticed for six
days. These cover the run-level path.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from archiver.run_health import DEFAULT_ALERT_COOLDOWN, format_failure_message, should_alert

NOW = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)


def test_no_alert_when_nothing_has_failed():
    assert should_alert(consecutive_failures=0, last_alert_at=None, now=NOW) is False


def test_alerts_immediately_on_first_failure():
    # The whole point: don't wait for a threshold before saying anything.
    assert should_alert(consecutive_failures=1, last_alert_at=None, now=NOW) is True


def test_stays_quiet_during_cooldown():
    recent = NOW - timedelta(minutes=30)
    assert should_alert(consecutive_failures=5, last_alert_at=recent, now=NOW) is False


def test_alerts_again_once_cooldown_elapses():
    stale = NOW - DEFAULT_ALERT_COOLDOWN
    assert should_alert(consecutive_failures=5, last_alert_at=stale, now=NOW) is True


def test_cooldown_boundary_is_inclusive():
    just_under = NOW - DEFAULT_ALERT_COOLDOWN + timedelta(seconds=1)
    assert should_alert(consecutive_failures=2, last_alert_at=just_under, now=NOW) is False


def test_respects_custom_cooldown():
    last = NOW - timedelta(hours=2)
    assert should_alert(2, last, NOW, cooldown=timedelta(hours=1)) is True
    assert should_alert(2, last, NOW, cooldown=timedelta(hours=3)) is False


def test_message_names_the_error_and_the_streak():
    message = format_failure_message(
        consecutive_failures=139,
        error="GranolaAuthError: Granola token file not found",
        last_success=datetime(2026, 8, 5, 17, 41, tzinfo=timezone.utc),
        now=NOW,
    )

    assert "139" in message
    assert "GranolaAuthError" in message
    # A duration is what makes the alert actionable at a glance.
    # 5 Aug 17:41 -> 11 Aug 12:00 is 5d 18h.
    assert "5d" in message


def test_message_handles_never_having_succeeded():
    message = format_failure_message(
        consecutive_failures=1, error="boom", last_success=None, now=NOW
    )

    assert "boom" in message
    assert "never" in message.lower()


def test_message_truncates_a_huge_error():
    message = format_failure_message(
        consecutive_failures=1, error="x" * 5000, last_success=None, now=NOW
    )

    # macOS notifications silently drop overlong bodies.
    assert len(message) < 500
