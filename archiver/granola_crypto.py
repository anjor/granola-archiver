"""Read Granola's encrypted local credential store.

As of the August 2026 desktop release, Granola no longer writes plaintext
``supabase.json``. Local state is encrypted at rest with a 32-byte data
encryption key (DEK), and each ``*.json.enc`` file is AES-256-GCM encrypted
under it, laid out as ``nonce(12) || ciphertext || tag(16)``.

Where the DEK lives depends on the platform, mirroring the app's own two code
paths in ``app.asar``:

* **macOS, packaged (current)** — the DEK is held directly in the login
  Keychain under ``Granola Safe Storage`` / ``Granola Key``, managed by a
  native ``keychain.node`` module (``getOrCreateDek``). Recent versions
  migrated any existing ``storage.dek`` into the Keychain via ``importDek``
  and then *deleted* the file, so it will not be present.
* **Legacy / unpackaged** — the DEK sat base64-encoded in
  ``<userData>/storage.dek``, itself wrapped with Electron ``safeStorage``.

We try the Keychain first and fall back to the file, so this keeps working on
older installs and if a future release reverses the migration.

We reimplement only the read path rather than fork ``granola-client``, and
inject the result through ``set_token_provider``. Nothing here writes to
Granola's files.
"""

from __future__ import annotations

import base64
import json
import logging
import subprocess
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA1
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives.padding import PKCS7

logger = logging.getLogger(__name__)

GRANOLA_SUPPORT_DIR = Path.home() / "Library" / "Application Support" / "Granola"
DEK_PATH = GRANOLA_SUPPORT_DIR / "storage.dek"
SUPABASE_ENC_PATH = GRANOLA_SUPPORT_DIR / "supabase.json.enc"

KEYCHAIN_SERVICE = "Granola Safe Storage"
KEYCHAIN_ACCOUNT = "Granola Key"

# Chromium/Electron OSCrypt constants for the macOS safeStorage scheme.
_SAFESTORAGE_PREFIX = b"v10"
_SAFESTORAGE_SALT = b"saltysalt"
_SAFESTORAGE_ITERATIONS = 1003
_SAFESTORAGE_KEY_LEN = 16
_SAFESTORAGE_IV = b" " * 16

# Granola's own AES-GCM layout.
_GCM_NONCE_LEN = 12
_GCM_TAG_LEN = 16


class GranolaDecryptionError(RuntimeError):
    """Raised when the local encrypted store cannot be read."""


def _keychain_secret() -> bytes:
    """Fetch the safeStorage password from the login Keychain.

    May prompt for Keychain access on first use, or if the binary invoking it
    is not already trusted for this item.
    """
    try:
        result = subprocess.run(
            [
                "security",
                "find-generic-password",
                "-w",
                "-s",
                KEYCHAIN_SERVICE,
                "-a",
                KEYCHAIN_ACCOUNT,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError as exc:  # pragma: no cover - macOS only
        raise GranolaDecryptionError("`security` not found; this path is macOS-only.") from exc
    except subprocess.CalledProcessError as exc:
        raise GranolaDecryptionError(
            f"Keychain item {KEYCHAIN_SERVICE!r}/{KEYCHAIN_ACCOUNT!r} not readable. "
            "Approve the Keychain prompt, or confirm the item exists."
        ) from exc

    secret = result.stdout.strip()
    if not secret:
        raise GranolaDecryptionError("Keychain returned an empty safeStorage password.")
    return secret.encode("utf-8")


def _safestorage_decrypt(blob: bytes, password: bytes) -> bytes:
    """Reverse Electron safeStorage (macOS): PBKDF2-SHA1 -> AES-128-CBC."""
    if not blob.startswith(_SAFESTORAGE_PREFIX):
        raise GranolaDecryptionError(
            f"storage.dek is missing the {_SAFESTORAGE_PREFIX.decode()!r} prefix; "
            "the safeStorage format may have changed."
        )
    body = blob[len(_SAFESTORAGE_PREFIX) :]

    key = PBKDF2HMAC(
        algorithm=SHA1(),
        length=_SAFESTORAGE_KEY_LEN,
        salt=_SAFESTORAGE_SALT,
        iterations=_SAFESTORAGE_ITERATIONS,
    ).derive(password)

    decryptor = Cipher(algorithms.AES(key), modes.CBC(_SAFESTORAGE_IV)).decryptor()
    padded = decryptor.update(body) + decryptor.finalize()

    unpadder = PKCS7(algorithms.AES.block_size).unpadder()
    try:
        return unpadder.update(padded) + unpadder.finalize()
    except ValueError as exc:
        raise GranolaDecryptionError(
            "Failed to unpad the unwrapped DEK — the Keychain password is most "
            "likely wrong for this item."
        ) from exc


def _coerce_dek(raw: bytes) -> bytes:
    """Interpret a stored DEK, which may be base64, hex, or raw bytes.

    The exact encoding lives inside the closed-source ``keychain.node``, so we
    detect it rather than assume it. Only a 32-byte result is accepted.
    """
    if len(raw) == 32:
        return raw

    text = raw.decode("utf-8", errors="ignore").strip()
    for decode in (lambda s: base64.b64decode(s, validate=True), bytes.fromhex):
        try:
            candidate = decode(text)
        except Exception:
            continue
        if len(candidate) == 32:
            return candidate

    raise GranolaDecryptionError(
        f"Could not interpret the stored DEK as 32 bytes (got {len(raw)} bytes "
        "raw; not valid base64 or hex for a 256-bit key)."
    )


def load_dek(dek_path: Path = DEK_PATH) -> bytes:
    """Return the 32-byte data encryption key.

    Prefers the Keychain (current macOS layout), falling back to the legacy
    ``storage.dek`` file.
    """
    keychain_error: Exception | None = None
    try:
        return _coerce_dek(_keychain_secret())
    except GranolaDecryptionError as exc:
        keychain_error = exc
        logger.debug("Keychain DEK lookup failed, trying %s: %s", dek_path, exc)

    if not dek_path.exists():
        raise GranolaDecryptionError(
            f"Could not read the DEK from the Keychain ({keychain_error}), and "
            f"the legacy {dek_path.name} is absent. Open the Granola desktop "
            "app once to let it provision the encrypted store."
        )

    return _coerce_dek(_safestorage_decrypt(dek_path.read_bytes(), _keychain_secret()))


def decrypt_file(path: Path, dek: bytes) -> str:
    """Decrypt one ``*.json.enc`` file: nonce(12) || ciphertext || tag(16)."""
    blob = path.read_bytes()
    if len(blob) <= _GCM_NONCE_LEN + _GCM_TAG_LEN:
        raise GranolaDecryptionError(f"{path.name} is too short to be a valid GCM payload.")

    nonce = blob[:_GCM_NONCE_LEN]
    tag = blob[-_GCM_TAG_LEN:]
    ciphertext = blob[_GCM_NONCE_LEN:-_GCM_TAG_LEN]

    try:
        plaintext = AESGCM(dek).decrypt(nonce, ciphertext + tag, None)
    except Exception as exc:
        raise GranolaDecryptionError(
            f"AES-256-GCM authentication failed for {path.name}. The DEK may be "
            "stale — reopening the Granola app can rotate it."
        ) from exc
    return plaintext.decode("utf-8")


def load_supabase_state(path: Path = SUPABASE_ENC_PATH) -> dict[str, Any]:
    """Decrypt and parse ``supabase.json.enc``."""
    if not path.exists():
        raise GranolaDecryptionError(f"{path} not found.")
    return json.loads(decrypt_file(path, load_dek()))


def _redact(value: Any, depth: int = 0) -> Any:
    """Describe a structure without revealing secrets."""
    if isinstance(value, dict):
        return {k: _redact(v, depth + 1) for k, v in value.items()}
    if isinstance(value, list):
        return [f"<list of {len(value)}>"] if value else []
    if isinstance(value, str):
        # Nested JSON is common here; describe its shape, not its contents.
        stripped = value.strip()
        if stripped.startswith(("{", "[")):
            try:
                return {"<nested json>": _redact(json.loads(stripped), depth + 1)}
            except ValueError:
                pass
        return f"<str len={len(value)}>"
    if isinstance(value, (int, float)):
        return f"<{type(value).__name__}>"
    return f"<{type(value).__name__}>"


def main() -> int:
    """Diagnostic entry point. Prints structure only — never secret values."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        state = load_supabase_state()
    except GranolaDecryptionError as exc:
        print(f"FAILED: {exc}")
        return 1

    print("Decryption OK. Structure of supabase.json (values redacted):\n")
    print(json.dumps(_redact(state), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
