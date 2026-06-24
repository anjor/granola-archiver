"""Tests for GitManager, focused on stale-lock recovery."""

import os
import time
from pathlib import Path
import tempfile
import shutil

import pytest
from git import Repo

from archiver.git_manager import GitManager, STALE_LOCK_SECONDS


@pytest.fixture
def repo_dir():
    """A real, initialised git repo with one commit so HEAD exists."""
    temp_dir = tempfile.mkdtemp()
    repo = Repo.init(temp_dir, initial_branch="main")
    repo.config_writer().set_value("user", "name", "Test").release()
    repo.config_writer().set_value("user", "email", "test@example.com").release()
    (Path(temp_dir) / "README.md").write_text("seed")
    repo.index.add(["README.md"])
    repo.index.commit("seed")
    yield temp_dir
    shutil.rmtree(temp_dir)


def _lock_path(repo_dir):
    return Path(repo_dir) / ".git" / "index.lock"


def _make_lock(repo_dir, age_seconds):
    lock = _lock_path(repo_dir)
    lock.write_text("")
    mtime = time.time() - age_seconds
    os.utime(lock, (mtime, mtime))
    return lock


def test_write_and_commit_succeeds_normally(repo_dir):
    gm = GitManager(repo_dir)
    sha = gm.write_and_commit("2026/01/note.md", "hello", "Archive: note")
    assert sha
    assert (Path(repo_dir) / "2026/01/note.md").exists()


def test_write_and_commit_recovers_from_stale_lock(repo_dir):
    """A long-dead index.lock is cleared and the commit succeeds."""
    gm = GitManager(repo_dir)
    _make_lock(repo_dir, age_seconds=STALE_LOCK_SECONDS + 60)

    sha = gm.write_and_commit("2026/01/note.md", "hello", "Archive: note")

    assert sha, "commit should succeed after clearing a stale lock"
    assert not _lock_path(repo_dir).exists(), "stale lock should be removed"


def test_write_and_commit_preserves_fresh_lock(repo_dir):
    """A recent lock may belong to a live git process; do not remove it."""
    gm = GitManager(repo_dir)
    fresh_lock = _make_lock(repo_dir, age_seconds=1)

    sha = gm.write_and_commit("2026/01/note.md", "hello", "Archive: note")

    assert sha is None, "should not commit over a fresh lock"
    assert fresh_lock.exists(), "fresh lock must be left intact"
