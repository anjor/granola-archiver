"""Token resolution for the Granola API.

Granola 7.x encrypts the desktop app's session file: the plaintext
``supabase.json`` that ``granola-client`` reads was replaced by
``supabase.json.enc``. Automatic token extraction therefore fails, and the
library's own error ("Granola token file not found ... Open the desktop app to
sign in") sends the user in a circle when the app *is* signed in.

This module owns the archiver's token decision so that:

* an explicitly configured token is honoured without touching the desktop
  app's files at all, and
* when automatic detection fails, the error names the real cause and the
  supported way out.

The local read is wrapped by subclassing ``GranolaClient`` rather than by
patching the installed library, so the behaviour survives ``uv sync``.
"""

import logging
import os
from pathlib import Path
from typing import Optional

from granola_client import GranolaClient
from granola_client.errors import GranolaAuthError

logger = logging.getLogger(__name__)

GRANOLA_SUPPORT_DIR = Path.home() / "Library" / "Application Support" / "Granola"
PLAINTEXT_TOKEN_FILE = GRANOLA_SUPPORT_DIR / "supabase.json"
ENCRYPTED_TOKEN_FILE = GRANOLA_SUPPORT_DIR / "supabase.json.enc"

_DOCS_HINT = (
    "See the 'Authentication' section of the README for how to supply a token "
    "explicitly (granola.auto_detect_token: false plus the token env var)."
)


class ArchiverAuthError(Exception):
    """The archiver could not determine a usable Granola token."""


def describe_local_token_state(
    plaintext: Path = PLAINTEXT_TOKEN_FILE,
    encrypted: Path = ENCRYPTED_TOKEN_FILE,
) -> str:
    """Explain why automatic token detection cannot work right now.

    Args:
        plaintext: Path granola-client reads the session token from.
        encrypted: Path the desktop app writes when it encrypts the session.

    Returns:
        A human-readable diagnosis naming the actual cause.
    """
    if plaintext.exists():
        return (
            f"{plaintext} exists but could not be used. The desktop app may have "
            f"written a session this version of granola-client cannot parse. {_DOCS_HINT}"
        )
    if encrypted.exists():
        return (
            f"The Granola desktop app has encrypted its session file: {encrypted} exists "
            f"but the plaintext {plaintext} that granola-client reads does not. Signing in "
            f"again will not recreate the plaintext file, so automatic token detection "
            f"cannot work on this Granola version. {_DOCS_HINT}"
        )
    return (
        f"No Granola session file found at {plaintext} (and no encrypted {encrypted.name} "
        f"either). Open the Granola desktop app and sign in. {_DOCS_HINT}"
    )


class ArchiverGranolaClient(GranolaClient):
    """GranolaClient whose local token read fails with an actionable message.

    Wraps rather than replaces the upstream read: the parent implementation
    still does the work, and only its error is re-framed.
    """

    @staticmethod
    def _read_local_workos_tokens() -> dict:
        try:
            return GranolaClient._read_local_workos_tokens()
        except GranolaAuthError as e:
            raise ArchiverAuthError(describe_local_token_state()) from e


def resolve_token(granola_config) -> Optional[str]:
    """Determine the token to hand to the Granola client.

    An explicitly configured token always wins, so the archiver never depends
    on the desktop app's storage format when one is supplied. When automatic
    detection is switched off and no token is available, this fails loudly
    instead of silently falling back to the (broken) auto-detect path.

    Args:
        granola_config: The ``granola`` section of the archiver config.

    Returns:
        The token string, or None to let the client auto-detect.

    Raises:
        ArchiverAuthError: auto-detection is disabled but no token was found.
    """
    env_name = granola_config.token_env
    token = (os.getenv(env_name) or "").strip()

    if token:
        logger.info(f"Using Granola token from ${env_name}")
        return token

    if not granola_config.auto_detect_token:
        raise ArchiverAuthError(
            f"granola.auto_detect_token is false but ${env_name} is unset or empty, "
            f"so there is no token to use. Set ${env_name}, or re-enable "
            f"auto_detect_token. {_DOCS_HINT}"
        )

    logger.info("No explicit token configured; falling back to local token detection")
    return None
