"""Wrapper around granola-py-client for fetching documents."""

import logging
from datetime import datetime
from typing import List, Optional

from dateutil.parser import parse as parse_datetime

try:
    from granola_client import GranolaClient, Document
except ImportError:
    raise ImportError("granola-client not found. Install with: uv add granola-client")

logger = logging.getLogger(__name__)


class DocumentDetails:
    """Container for complete document information."""

    def __init__(self, document: Document, transcript: str, metadata: dict):
        self.document = document
        self.transcript = transcript
        self.metadata = metadata


class GranolaFetcher:
    """Fetches documents from Granola API using granola-py-client."""

    def __init__(self, token: Optional[str] = None):
        """Initialize the Granola fetcher.

        Args:
            token: Optional API token. If not provided, will auto-detect.
        """
        if token:
            self.client = GranolaClient(token=token)
        else:
            # Auto-detect token from environment or credentials file
            self.client = GranolaClient()

        logger.info("Initialized Granola client")

    async def fetch_new_documents(
        self, since: Optional[datetime] = None, workspace_ids: Optional[List[str]] = None
    ) -> List[Document]:
        """Fetch documents updated since a given timestamp.

        Args:
            since: Only return documents updated after this time
            workspace_ids: Optional list of workspace IDs to filter by

        Returns:
            List of Document objects
        """
        logger.info(f"Fetching documents since {since}")

        # Fetch all documents (list_all_documents returns an async generator)
        all_documents = [doc async for doc in self.client.list_all_documents()]

        # Filter by update time if specified
        if since:
            # Make since timezone-aware if it isn't already
            if since.tzinfo is None:
                from datetime import timezone

                since = since.replace(tzinfo=timezone.utc)
            all_documents = [
                doc for doc in all_documents if parse_datetime(doc.updated_at) >= since
            ]

        # Filter by workspace if specified
        if workspace_ids:
            all_documents = [doc for doc in all_documents if doc.workspace_id in workspace_ids]

        logger.info(f"Found {len(all_documents)} documents matching criteria")
        return all_documents

    async def fetch_document_details(self, document: Document) -> DocumentDetails:
        """Fetch complete details for a document.

        Args:
            document: The Document object (already fetched from list_all_documents)

        Returns:
            DocumentDetails with document, transcript, and metadata
        """
        document_id = document.document_id
        logger.info(f"Fetching details for document {document_id}")

        # Get transcript (returns list of TranscriptSegment objects)
        transcript_segments = await self.client.get_document_transcript(document_id)
        transcript = self._format_transcript_segments(transcript_segments)

        # Get additional metadata (convert Pydantic model to dict)
        metadata_obj = await self.client.get_document_metadata(document_id)
        metadata = metadata_obj.model_dump() if hasattr(metadata_obj, "model_dump") else {}

        return DocumentDetails(document=document, transcript=transcript, metadata=metadata)

    def _format_transcript_segments(self, segments: list) -> str:
        """Format transcript segments into a readable string.

        Args:
            segments: List of TranscriptSegment objects

        Returns:
            Formatted transcript string
        """
        if not segments:
            return ""

        lines = []
        for segment in segments:
            text = segment.text if hasattr(segment, "text") else str(segment)
            lines.append(text)

        return "\n\n".join(lines)

    async def fetch_document_by_id(self, document_id: str) -> Optional[Document]:
        """Fetch a single document by its ID.

        Args:
            document_id: The document ID to fetch

        Returns:
            Document object if found, None otherwise
        """
        logger.info(f"Searching for document {document_id}")

        async for doc in self.client.list_all_documents():
            if doc.document_id == document_id:
                return doc

        logger.warning(f"Document {document_id} not found")
        return None
