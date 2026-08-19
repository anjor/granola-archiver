"""Lightweight local notifications for archiver failures."""

import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


def notify_macos(title: str, message: str) -> None:
    """Display a macOS notification via osascript.

    Best-effort: any failure (non-macOS, osascript missing) is logged and
    swallowed so notification problems never break an archiver run.

    Args:
        title: Notification title.
        message: Notification body.
    """
    # Escape double quotes for the AppleScript string literals.
    safe_title = title.replace('"', '\\"')
    safe_message = message.replace('"', '\\"')
    script = f'display notification "{safe_message}" with title "{safe_title}"'
    try:
        subprocess.run(["osascript", "-e", script], check=True, capture_output=True)
    except Exception as e:  # pragma: no cover - environment dependent
        logger.warning(f"Could not send macOS notification: {e}")


# A run that dies before any document is fetched (auth, config, network) never
# populates the retry queue, so the per-document alert cannot fire. Without the
# marker below such a failure is only visible by reading the log, which is how
# the archiver came to sit broken for two weeks without anyone noticing.
DEFAULT_FAILURE_MARKER = Path.home() / ".local" / "state" / "granola-archiver" / "LAST_FAILURE"


def record_run_failure(
    error: BaseException | str,
    notifier=None,
    marker_path: Path = DEFAULT_FAILURE_MARKER,
) -> Path:
    """Alert on a run that failed before archiving anything.

    Fires the same macOS notification the retry queue uses and writes a
    one-line marker file so the failure is visible without reading the log.

    Args:
        error: The exception (or message) that ended the run.
        notifier: Callable ``(title, message)``; defaults to a macOS notification.
        marker_path: File to write the one-line marker to.

    Returns:
        The path the marker was written to.
    """
    if notifier is None:
        notifier = notify_macos

    summary = str(error).strip().replace("\n", " ") or error.__class__.__name__
    timestamp = datetime.now(timezone.utc).isoformat()

    try:
        marker_path.parent.mkdir(parents=True, exist_ok=True)
        marker_path.write_text(f"{timestamp} {summary}\n", encoding="utf-8")
    except Exception as e:  # pragma: no cover - filesystem dependent
        logger.warning(f"Could not write failure marker {marker_path}: {e}")

    notifier("Granola archiver: run failed", summary[:200])
    logger.error(f"Archiver run failed: {summary}")
    return marker_path


def clear_run_failure(marker_path: Path = DEFAULT_FAILURE_MARKER) -> bool:
    """Remove the failure marker after a run completes.

    The marker means "the last run failed", so a later success must clear it;
    otherwise it would report a problem that has already been fixed.

    Args:
        marker_path: File to remove.

    Returns:
        True if a marker was present and removed, False otherwise.
    """
    try:
        if marker_path.exists():
            marker_path.unlink()
            logger.info(f"Cleared failure marker {marker_path}")
            return True
    except Exception as e:  # pragma: no cover - filesystem dependent
        logger.warning(f"Could not clear failure marker {marker_path}: {e}")
    return False
