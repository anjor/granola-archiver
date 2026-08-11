"""Tests for the encrypted-store reader.

These exercise the crypto layout against synthetic data, so they run without
Granola installed and without touching real credentials.
"""

from __future__ import annotations

import base64
import json
import os

import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA1
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives.padding import PKCS7

from archiver import granola_crypto as gc


def _wrap_safestorage(plaintext: bytes, password: bytes) -> bytes:
    """Encrypt the way Electron safeStorage does on macOS."""
    key = PBKDF2HMAC(
        algorithm=SHA1(), length=16, salt=b"saltysalt", iterations=1003
    ).derive(password)
    padder = PKCS7(algorithms.AES.block_size).padder()
    padded = padder.update(plaintext) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(b" " * 16)).encryptor()
    return b"v10" + encryptor.update(padded) + encryptor.finalize()


def _wrap_gcm(plaintext: bytes, dek: bytes) -> bytes:
    """Encrypt the way Granola does: nonce(12) || ciphertext || tag(16)."""
    nonce = os.urandom(12)
    sealed = AESGCM(dek).encrypt(nonce, plaintext, None)
    # AESGCM.encrypt appends the tag, which matches Granola's layout already.
    return nonce + sealed


def test_safestorage_roundtrip():
    password = b"correct horse battery staple"
    dek = os.urandom(32)
    payload = base64.b64encode(dek)

    unwrapped = gc._safestorage_decrypt(_wrap_safestorage(payload, password), password)

    assert base64.b64decode(unwrapped, validate=True) == dek


def test_safestorage_rejects_missing_prefix():
    with pytest.raises(gc.GranolaDecryptionError, match="prefix"):
        gc._safestorage_decrypt(b"nope-no-version-tag", b"pw")


def test_safestorage_wrong_password_is_reported():
    blob = _wrap_safestorage(base64.b64encode(os.urandom(32)), b"right")
    with pytest.raises(gc.GranolaDecryptionError, match="Keychain password"):
        gc._safestorage_decrypt(blob, b"wrong")


def test_decrypt_file_roundtrip(tmp_path):
    dek = AESGCM.generate_key(bit_length=256)
    original = json.dumps({"workos_tokens": {"access_token": "x"}})

    path = tmp_path / "supabase.json.enc"
    path.write_bytes(_wrap_gcm(original.encode(), dek))

    assert gc.decrypt_file(path, dek) == original


def test_decrypt_file_rejects_short_payload(tmp_path):
    path = tmp_path / "tiny.enc"
    path.write_bytes(b"short")
    with pytest.raises(gc.GranolaDecryptionError, match="too short"):
        gc.decrypt_file(path, AESGCM.generate_key(bit_length=256))


def test_decrypt_file_rejects_tampered_payload(tmp_path):
    dek = AESGCM.generate_key(bit_length=256)
    blob = bytearray(_wrap_gcm(b'{"a":1}', dek))
    blob[20] ^= 0xFF  # flip a bit in the ciphertext body

    path = tmp_path / "tampered.enc"
    path.write_bytes(bytes(blob))

    with pytest.raises(gc.GranolaDecryptionError, match="authentication failed"):
        gc.decrypt_file(path, dek)


def test_decrypt_file_rejects_wrong_key(tmp_path):
    path = tmp_path / "x.enc"
    path.write_bytes(_wrap_gcm(b'{"a":1}', AESGCM.generate_key(bit_length=256)))

    with pytest.raises(gc.GranolaDecryptionError, match="authentication failed"):
        gc.decrypt_file(path, AESGCM.generate_key(bit_length=256))


def test_redact_hides_values_but_keeps_shape():
    redacted = gc._redact(
        {
            "workos_tokens": json.dumps({"access_token": "secret", "expires_in": 3600}),
            "user": {"email": "a@b.com"},
            "sessions": [1, 2, 3],
        }
    )

    flat = json.dumps(redacted)
    assert "secret" not in flat
    assert "a@b.com" not in flat
    # Shape survives, including through the nested-JSON string.
    assert "access_token" in flat
    assert "workos_tokens" in flat
    assert "email" in flat


def test_coerce_dek_accepts_raw_bytes():
    dek = os.urandom(32)
    assert gc._coerce_dek(dek) == dek


def test_coerce_dek_accepts_base64():
    dek = os.urandom(32)
    assert gc._coerce_dek(base64.b64encode(dek)) == dek


def test_coerce_dek_accepts_base64_with_trailing_newline():
    # `security find-generic-password -w` emits a trailing newline.
    dek = os.urandom(32)
    assert gc._coerce_dek(base64.b64encode(dek) + b"\n") == dek


def test_coerce_dek_accepts_hex():
    dek = os.urandom(32)
    assert gc._coerce_dek(dek.hex().encode()) == dek


def test_coerce_dek_rejects_wrong_length():
    with pytest.raises(gc.GranolaDecryptionError, match="32 bytes"):
        gc._coerce_dek(base64.b64encode(os.urandom(16)))


def test_load_dek_prefers_keychain(monkeypatch, tmp_path):
    dek = os.urandom(32)
    monkeypatch.setattr(gc, "_keychain_secret", lambda: base64.b64encode(dek))

    # No storage.dek on disk: the Keychain path must satisfy it alone.
    assert gc.load_dek(tmp_path / "absent.dek") == dek


def test_load_dek_falls_back_to_legacy_file(monkeypatch, tmp_path):
    dek = os.urandom(32)
    password = b"pw"

    calls = {"n": 0}

    def fake_secret():
        calls["n"] += 1
        if calls["n"] == 1:
            # First call stands in for "Keychain has no usable DEK".
            raise gc.GranolaDecryptionError("no such item")
        return password

    monkeypatch.setattr(gc, "_keychain_secret", fake_secret)

    dek_path = tmp_path / "storage.dek"
    dek_path.write_bytes(_wrap_safestorage(base64.b64encode(dek), password))

    assert gc.load_dek(dek_path) == dek


def test_load_dek_reports_both_paths_failing(monkeypatch, tmp_path):
    monkeypatch.setattr(
        gc, "_keychain_secret", lambda: (_ for _ in ()).throw(gc.GranolaDecryptionError("nope"))
    )
    with pytest.raises(gc.GranolaDecryptionError, match="absent"):
        gc.load_dek(tmp_path / "absent.dek")
