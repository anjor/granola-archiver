"""Tests for Granola token resolution."""

import pytest

from archiver.auth import (
    ArchiverAuthError,
    ArchiverGranolaClient,
    describe_local_token_state,
    resolve_token,
)
from archiver.models import ArchiverConfig


def granola_config(auto_detect: bool, token_env: str = "GRANOLA_TOKEN"):
    return ArchiverConfig.GranolaConfig(auto_detect_token=auto_detect, token_env=token_env)


# --- describe_local_token_state ------------------------------------------


def test_diagnosis_names_encryption_when_enc_file_present(tmp_path):
    """The encrypted-session case is the real cause and must be named as such."""
    encrypted = tmp_path / "supabase.json.enc"
    encrypted.write_bytes(b"\x00" * 16)

    message = describe_local_token_state(tmp_path / "supabase.json", encrypted)

    assert "encrypted" in message.lower()
    assert "supabase.json.enc" in message
    # Must not repeat upstream's misleading advice, which is a no-op here.
    assert "sign in" not in message.lower()


def test_diagnosis_asks_for_sign_in_when_nothing_present(tmp_path):
    """With no session file at all, signing in genuinely is the fix."""
    message = describe_local_token_state(
        tmp_path / "supabase.json", tmp_path / "supabase.json.enc"
    )

    assert "sign in" in message.lower()


def test_diagnosis_distinguishes_unreadable_plaintext(tmp_path):
    """A present-but-unusable plaintext file is a different failure again."""
    plaintext = tmp_path / "supabase.json"
    plaintext.write_text("{}")

    message = describe_local_token_state(plaintext, tmp_path / "supabase.json.enc")

    assert "exists but could not be used" in message


# --- resolve_token --------------------------------------------------------


def test_env_token_is_used_when_set(monkeypatch):
    """An explicitly supplied token removes any dependency on the local file."""
    monkeypatch.setenv("GRANOLA_TOKEN", "tok_abc")

    assert resolve_token(granola_config(auto_detect=True)) == "tok_abc"


def test_env_token_wins_over_auto_detect(monkeypatch):
    """Setting the env var must not be silently ignored."""
    monkeypatch.setenv("GRANOLA_TOKEN", "tok_abc")

    assert resolve_token(granola_config(auto_detect=True)) == "tok_abc"


def test_missing_token_with_auto_detect_disabled_raises(monkeypatch):
    """The old code silently fell back to the broken auto-detect path here."""
    monkeypatch.delenv("GRANOLA_TOKEN", raising=False)

    with pytest.raises(ArchiverAuthError) as excinfo:
        resolve_token(granola_config(auto_detect=False))

    assert "GRANOLA_TOKEN" in str(excinfo.value)


def test_blank_token_is_treated_as_missing(monkeypatch):
    """An empty env var is a misconfiguration, not a token."""
    monkeypatch.setenv("GRANOLA_TOKEN", "   ")

    with pytest.raises(ArchiverAuthError):
        resolve_token(granola_config(auto_detect=False))


def test_auto_detect_returns_none_without_token(monkeypatch):
    """With auto-detect on, the client is left to find the token itself."""
    monkeypatch.delenv("GRANOLA_TOKEN", raising=False)

    assert resolve_token(granola_config(auto_detect=True)) is None


def test_custom_token_env_is_honoured(monkeypatch):
    """token_env is configurable and must be respected."""
    monkeypatch.setenv("MY_GRANOLA", "tok_xyz")

    assert resolve_token(granola_config(auto_detect=False, token_env="MY_GRANOLA")) == "tok_xyz"


# --- ArchiverGranolaClient ------------------------------------------------


def test_local_read_failure_is_reframed(monkeypatch):
    """The library's misleading error is replaced with an actionable one."""
    monkeypatch.setattr(
        "archiver.auth.GranolaClient._read_local_workos_tokens",
        staticmethod(lambda: (_ for _ in ()).throw(_auth_error("token file not found"))),
    )

    with pytest.raises(ArchiverAuthError):
        ArchiverGranolaClient._read_local_workos_tokens()


def _auth_error(message):
    from granola_client.errors import GranolaAuthError

    return GranolaAuthError(message)
