"""SQLite-based state tracker for archived documents."""

import sqlite3
from datetime import datetime
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
                    created_at.isoformat(),
                    updated_at.isoformat(),
                    datetime.now().isoformat(),
                    file_path,
                    commit_sha,
                ),
            )
            conn.commit()
            logger.info(f"Marked document {document_id} as archived at {file_path}")

    def get_last_run_timestamp(self) -> Optional[datetime]:
        """Get the timestamp of the last successful run.

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
                return datetime.fromisoformat(row[0])
            return None

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
                    datetime.now().isoformat(),
                    documents_processed,
                    documents_archived,
                    documents_failed,
                ),
            )
            conn.commit()
            logger.info(f"Updated last run: {documents_archived}/{documents_processed} archived")

    def get_archived_count(self) -> int:
        """Get the total number of archived documents.

        Returns:
            Count of archived documents
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM archived_documents")
            return cursor.fetchone()[0]
