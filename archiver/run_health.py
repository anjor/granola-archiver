"""Alerting for failures that kill an entire archiver run.

``maybe_alert_failures`` in ``main`` watches the per-document retry queue. It
cannot see a run that dies before any document is enqueued — expired
credentials, no network, a wedged git repo. Those failures used to be visible
only in the log, which nobody reads until they notice missing notes.

This module decides *when* to speak up. Runs happen every 30 minutes, so
alerting on each failure would mean ~48 notifications a day; instead we alert
on the first failure and then at most once per cooldown while it persists.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

DEFAULT_ALERT_COOLDOWN = timedelta(hours=6)

# macOS notification bodies are silently truncated when overlong.
_MAX_MESSAGE_LEN = 400
_MAX_ERROR_LEN = 200


def should_alert(
    consecutive_failures: int,
    last_alert_at: Optional[datetime],
    now: datetime,
    cooldown: timedelta = DEFAULT_ALERT_COOLDOWN,
) -> bool:
    """Whether to raise an alert for the current failure streak.

    Args:
        consecutive_failures: Runs that have failed back-to-back.
        last_alert_at: When we last alerted, or ``None`` if not yet.
        now: Current time.
        cooldown: Minimum gap between repeat alerts.

    Returns:
        True if an alert should be delivered now.
    """
    if consecutive_failures <= 0:
        return False
    if last_alert_at is None:
        return True
    return now - last_alert_at >= cooldown


def _humanize(delta: timedelta) -> str:
    """Render a duration compactly, e.g. ``6d 2h``."""
    total_minutes = int(delta.total_seconds() // 60)
    days, remainder = divmod(total_minutes, 60 * 24)
    hours, minutes = divmod(remainder, 60)

    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def format_failure_message(
    consecutive_failures: int,
    error: str,
    last_success: Optional[datetime],
    now: datetime,
) -> str:
    """Build the alert body.

    Leads with how long archiving has actually been down, which is the part
    that tells you whether this is a blip or a hole in the archive.
    """
    if last_success is None:
        window = "never succeeded"
    else:
        window = f"last success {_humanize(now - last_success)} ago"

    error = error.strip() or "unknown error"
    if len(error) > _MAX_ERROR_LEN:
        error = error[: _MAX_ERROR_LEN - 1].rstrip() + "…"

    message = f"{consecutive_failures} consecutive failed run(s), {window}. {error}"
    if len(message) > _MAX_MESSAGE_LEN:
        message = message[: _MAX_MESSAGE_LEN - 1].rstrip() + "…"
    return message
