"""Lightweight local notifications for sustained archiver failures."""

import logging
import subprocess

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
