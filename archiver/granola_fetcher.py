"""Wrapper around granola-py-client for fetching documents."""

import logging
from datetime import datetime
from typing import List, Optional

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

        # Fetch all documents
        all_documents = await self.client.list_all_documents()

        # Filter by update time if specified
        if since:
            all_documents = [doc for doc in all_documents if doc.updated_at >= since]

        # Filter by workspace if specified
        if workspace_ids:
            all_documents = [doc for doc in all_documents if doc.workspace_id in workspace_ids]

        logger.info(f"Found {len(all_documents)} documents matching criteria")
        return all_documents

    async def fetch_document_details(self, document_id: str) -> DocumentDetails:
        """Fetch complete details for a document.

        Args:
            document_id: The document ID

        Returns:
            DocumentDetails with document, transcript, and metadata
        """
        logger.info(f"Fetching details for document {document_id}")

        # Get document metadata
        document = await self.client.get_document(document_id)

        # Get transcript
        transcript = await self.client.get_document_transcript(document_id)

        # Get additional metadata
        metadata = await self.client.get_document_metadata(document_id)

        return DocumentDetails(document=document, transcript=transcript, metadata=metadata)
