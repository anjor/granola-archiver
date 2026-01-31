"""Pydantic models for the archiver."""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


class ArchiverConfig(BaseModel):
    """Configuration for the archiver."""

    class GranolaConfig(BaseModel):
        auto_detect_token: bool = True
        token_env: str = "GRANOLA_TOKEN"

    class ArchiveConfig(BaseModel):
        repo_path: str
        remote_name: str = "origin"
        default_branch: str = "main"

    class PollingConfig(BaseModel):
        interval_minutes: int = 30
        lookback_hours: int = 24

    class FiltersConfig(BaseModel):
        workspace_ids: List[str] = Field(default_factory=list)
        min_duration_minutes: int = 0

    class LoggingConfig(BaseModel):
        level: str = "INFO"
        file: str = "/tmp/granola-archiver.log"

    granola: GranolaConfig
    archive: ArchiveConfig
    polling: PollingConfig
    filters: FiltersConfig
    logging: LoggingConfig


class DocumentMetadata(BaseModel):
    """Metadata for a Granola document."""

    document_id: str
    title: str
    created_at: datetime
    updated_at: datetime
    workspace_id: Optional[str] = None


class ArchiveResult(BaseModel):
    """Result of archiving a single document."""

    success: bool
    doc_id: str
    error: Optional[str] = None
    file_path: Optional[str] = None
    commit_sha: Optional[str] = None


class ArchiveSummary(BaseModel):
    """Summary of an archive run."""

    total_documents: int
    archived_count: int
    failed_count: int
    skipped_count: int
    results: List[ArchiveResult]
