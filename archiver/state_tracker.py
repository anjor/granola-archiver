"""SQLite-based state tracker for archived documents."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class StateTracker:
    """Tracks which documents have been archived using SQLite."""

    def __init__(self, db_path: str):
        """Initialize the state tracker.

        Args:
            db_path: Path to the SQLite database file
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        """Initialize the database schema."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # Create archived_documents table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS archived_documents (
                    document_id TEXT PRIMARY KEY,
                    title TEXT,
                    created_at TEXT,
                    updated_at TEXT,
                    archived_at TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    commit_sha TEXT
                )
            """)

            # Create archive_runs table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS archive_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_at TEXT NOT NULL,
                    documents_processed INTEGER DEFAULT 0,
                    documents_archived INTEGER DEFAULT 0,
                    documents_failed INTEGER DEFAULT 0
                )
            """)

            # Create pending_documents table: documents that were fetched but
            # not successfully archived. They are retried on every run,
            # independent of the fetch watermark, so a transient failure (e.g.
            # a stale git lock) never causes a document to be lost.
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pending_documents (
                    document_id TEXT PRIMARY KEY,
                    updated_at TEXT NOT NULL,
                    first_failed_at TEXT NOT NULL,
                    last_error TEXT,
                    attempts INTEGER DEFAULT 1
                )
            """)

            # Create run_health table: tracks runs that failed outright, before
            # any document could be queued. pending_documents cannot represent
            # those, so without this an auth or network break stays invisible.
            # Single row, pinned to id = 1.
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS run_health (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    consecutive_failures INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    last_failure_at TEXT,
                    last_alert_at TEXT
                )
            """)
            cursor.execute("INSERT OR IGNORE INTO run_health (id) VALUES (1)")

            conn.commit()

    def is_archived(self, document_id: str, updated_at: datetime) -> bool:
        """Check if a document has already been archived.

        Args:
            document_id: The document ID
            updated_at: The document's last updated timestamp

        Returns:
            True if document is already archived with same or later update time
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT updated_at FROM archived_documents
                WHERE document_id = ?
                """,
                (document_id,),
            )
            row = cursor.fetchone()

            if not row:
                return False

            archived_updated_at = datetime.fromisoformat(row[0])
            return archived_updated_at >= updated_at

    def mark_archived(
        self,
        document_id: str,
        title: str,
        created_at: datetime,
        updated_at: datetime,
        file_path: str,
        commit_sha: Optional[str] = None,
    ):
        """Mark a document as archived.

        Args:
            document_id: The document ID
            title: Document title
            created_at: When the document was created
            updated_at: When the document was last updated
            file_path: Path to the archived file
            commit_sha: Git commit SHA (if available)
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO archived_documents
                (document_id, title, created_at, updated_at, archived_at, file_path, commit_sha)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document_id,
                    title,
                    created_at if isinstance(created_at, str) else created_at.isoformat(),
                    updated_at if isinstance(updated_at, str) else updated_at.isoformat(),
                    datetime.now(timezone.utc).isoformat(),
                    file_path,
                    commit_sha,
                ),
            )
            conn.commit()
            logger.info(f"Marked document {document_id} as archived at {file_path}")

    def get_last_run_timestamp(self) -> Optional[datetime]:
        """Get the timestamp of the most recent run (the fetch watermark).

        Note: this is the last run of *any* kind, not the last *successful* one.
        Failed documents are not lost despite the watermark advancing — they are
        tracked in the pending_documents retry queue and re-fetched by ID.

        Returns:
            The last run timestamp, or None if no previous runs
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT run_at FROM archive_runs
                ORDER BY run_at DESC
                LIMIT 1
                """)
            row = cursor.fetchone()

            if row:
                ts = datetime.fromisoformat(row[0])
                # Legacy rows were written with naive local time. Convert them
                # to tz-aware UTC so the fetcher's comparison against UTC
                # document timestamps is correct.
                if ts.tzinfo is None:
                    ts = ts.astimezone(timezone.utc)
                return ts
            return None

    def record_run_failure(self, error: str, when: Optional[datetime] = None) -> int:
        """Record that an entire run failed, and return the new streak length.

        Args:
            error: The error that killed the run.
            when: Failure time; defaults to now.

        Returns:
            The number of consecutive failed runs, including this one.
        """
        when = when or datetime.now(timezone.utc)
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE run_health
                SET consecutive_failures = consecutive_failures + 1,
                    last_error = ?,
                    last_failure_at = ?
                WHERE id = 1
                """,
                (error, when.isoformat()),
            )
            conn.commit()
            cursor.execute("SELECT consecutive_failures FROM run_health WHERE id = 1")
            return cursor.fetchone()[0]

    def clear_run_failures(self):
        """Reset run health after a run completes. Safe to call when healthy."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                UPDATE run_health
                SET consecutive_failures = 0,
                    last_error = NULL,
                    last_failure_at = NULL,
                    last_alert_at = NULL
                WHERE id = 1
                """)
            conn.commit()

    def mark_run_alert_sent(self, when: Optional[datetime] = None):
        """Record that a run-failure alert was delivered, for cooldown purposes."""
        when = when or datetime.now(timezone.utc)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE run_health SET last_alert_at = ? WHERE id = 1", (when.isoformat(),)
            )
            conn.commit()

    def get_run_health(self) -> dict:
        """Return the current run-failure streak.

        Returns:
            Dict with ``consecutive_failures``, ``last_error``,
            ``last_failure_at`` and ``last_alert_at``.
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT consecutive_failures, last_error, last_failure_at, last_alert_at
                FROM run_health WHERE id = 1
                """)
            row = cursor.fetchone()

        if row is None:  # pragma: no cover - the row is seeded at init
            return {
                "consecutive_failures": 0,
                "last_error": None,
                "last_failure_at": None,
                "last_alert_at": None,
            }

        def _parse(value: Optional[str]) -> Optional[datetime]:
            return datetime.fromisoformat(value) if value else None

        return {
            "consecutive_failures": row[0],
            "last_error": row[1],
            "last_failure_at": _parse(row[2]),
            "last_alert_at": _parse(row[3]),
        }

    def update_last_run(
        self, documents_processed: int = 0, documents_archived: int = 0, documents_failed: int = 0
    ):
        """Update the last run timestamp and statistics.

        Args:
            documents_processed: Number of documents processed
            documents_archived: Number of documents successfully archived
            documents_failed: Number of documents that failed to archive
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO archive_runs
                (run_at, documents_processed, documents_archived, documents_failed)
                VALUES (?, ?, ?, ?)
                """,
                (
                    datetime.now(timezone.utc).isoformat(),
                    documents_processed,
                    documents_archived,
                    documents_failed,
                ),
            )
            conn.commit()
            logger.info(f"Updated last run: {documents_archived}/{documents_processed} archived")

    def mark_pending(self, document_id: str, updated_at: datetime, error: Optional[str] = None):
        """Record a document that failed to archive so it is retried later.

        Idempotent per document: re-recording the same document increments its
        attempt count and updates the last error rather than duplicating it.

        Args:
            document_id: The document ID
            updated_at: The document's last updated timestamp
            error: A short description of why archiving failed
        """
        updated_at_str = updated_at if isinstance(updated_at, str) else updated_at.isoformat()
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO pending_documents
                    (document_id, updated_at, first_failed_at, last_error, attempts)
                VALUES (?, ?, ?, ?, 1)
                ON CONFLICT(document_id) DO UPDATE SET
                    updated_at = excluded.updated_at,
                    last_error = excluded.last_error,
                    attempts = attempts + 1
                """,
                (document_id, updated_at_str, now, error),
            )
            conn.commit()
            logger.warning(f"Document {document_id} pending retry: {error}")

    def clear_pending(self, document_id: str):
        """Remove a document from the retry queue (after a successful archive).

        Args:
            document_id: The document ID
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM pending_documents WHERE document_id = ?", (document_id,))
            conn.commit()

    def get_pending_documents(self) -> list[dict]:
        """Get documents awaiting retry.

        Returns:
            A list of dicts with keys: document_id, updated_at, first_failed_at,
            last_error, attempts. Ordered oldest-failure-first.
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT document_id, updated_at, first_failed_at, last_error, attempts
                FROM pending_documents
                ORDER BY first_failed_at ASC
                """)
            return [
                {
                    "document_id": row[0],
                    "updated_at": row[1],
                    "first_failed_at": row[2],
                    "last_error": row[3],
                    "attempts": row[4],
                }
                for row in cursor.fetchall()
            ]

    def get_archived_count(self) -> int:
        """Get the total number of archived documents.

        Returns:
            Count of archived documents
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM archived_documents")
            return cursor.fetchone()[0]
