"""Git operations for archiving documents."""

import logging
from pathlib import Path
from typing import Optional

try:
    from git import Repo, GitCommandError
except ImportError:
    raise ImportError("GitPython not installed. Install with: pip install gitpython")

logger = logging.getLogger(__name__)


class GitManager:
    """Manages Git operations for the archive repository."""

    def __init__(self, repo_path: str, remote_name: str = "origin", default_branch: str = "main"):
        """Initialize the Git manager.

        Args:
            repo_path: Path to the archive repository
            remote_name: Name of the remote (default: origin)
            default_branch: Default branch name (default: main)
        """
        self.repo_path = Path(repo_path)
        self.remote_name = remote_name
        self.default_branch = default_branch

        if not self.repo_path.exists():
            raise ValueError(f"Repository path does not exist: {repo_path}")

        try:
            self.repo = Repo(self.repo_path)
        except Exception as e:
            raise ValueError(f"Invalid git repository at {repo_path}: {e}")

        logger.info(f"Initialized Git manager for {repo_path}")

    def ensure_up_to_date(self):
        """Ensure the repository is on the default branch and up-to-date."""
        try:
            # Check out default branch
            if self.repo.active_branch.name != self.default_branch:
                logger.info(f"Switching to {self.default_branch} branch")
                self.repo.git.checkout(self.default_branch)

            # Pull latest changes
            logger.info(f"Pulling latest changes from {self.remote_name}/{self.default_branch}")
            origin = self.repo.remote(name=self.remote_name)
            origin.pull(self.default_branch)

        except GitCommandError as e:
            logger.warning(f"Failed to update repository: {e}")
            # Continue anyway - we'll handle conflicts if they occur

    def write_and_commit(self, file_path: str, content: str, commit_message: str) -> Optional[str]:
        """Write a file and commit it to the repository.

        Args:
            file_path: Relative path within the repository (e.g., "2026/01/2026-01-30-meeting.md")
            content: File content
            commit_message: Git commit message

        Returns:
            Commit SHA if successful, None if failed
        """
        try:
            # Build full path
            full_path = self.repo_path / file_path
            full_path.parent.mkdir(parents=True, exist_ok=True)

            # Write file
            full_path.write_text(content, encoding="utf-8")
            logger.info(f"Wrote file: {file_path}")

            # Stage file
            self.repo.index.add([file_path])

            # Commit
            commit = self.repo.index.commit(commit_message)
            commit_sha = commit.hexsha
            logger.info(f"Committed {file_path} with SHA {commit_sha[:8]}")

            return commit_sha

        except Exception as e:
            logger.error(f"Failed to write and commit {file_path}: {e}")
            return None

    def push_to_remote(self) -> bool:
        """Push all commits to the remote repository.

        Returns:
            True if push successful, False otherwise
        """
        try:
            logger.info(f"Pushing to {self.remote_name}/{self.default_branch}")
            origin = self.repo.remote(name=self.remote_name)
            origin.push(self.default_branch)
            logger.info("Push successful")
            return True

        except GitCommandError as e:
            logger.error(f"Failed to push to remote: {e}")
            return False

    def has_uncommitted_changes(self) -> bool:
        """Check if there are uncommitted changes.

        Returns:
            True if there are uncommitted changes
        """
        return self.repo.is_dirty()

    def get_commit_count_since_last_push(self) -> int:
        """Get the number of unpushed commits.

        Returns:
            Number of commits ahead of remote
        """
        try:
            origin = self.repo.remote(name=self.remote_name)
            origin.fetch()

            # Count commits ahead
            commits_ahead = list(
                self.repo.iter_commits(
                    f"{self.remote_name}/{self.default_branch}..{self.default_branch}"
                )
            )
            return len(commits_ahead)

        except Exception as e:
            logger.warning(f"Failed to count unpushed commits: {e}")
            return 0
