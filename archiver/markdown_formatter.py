"""Formats Granola documents as Markdown."""

from datetime import datetime
from typing import List
import logging

logger = logging.getLogger(__name__)


class MarkdownFormatter:
    """Formats Granola documents as well-structured Markdown."""

    def format_document(self, document, transcript: str, metadata: dict) -> str:
        """Format a Granola document as Markdown.

        Args:
            document: The document object from granola-client
            transcript: The document transcript
            metadata: Additional metadata

        Returns:
            Formatted Markdown string
        """
        logger.info(f"Formatting document: {document.title}")

        # Extract metadata
        title = document.title or "Untitled Meeting"
        created_at = document.created_at
        updated_at = document.updated_at
        document_id = document.id
        workspace_id = getattr(document, "workspace_id", None)

        # Format attendees if available
        attendees_yaml = self._format_attendees_yaml(metadata.get("attendees", []))
        attendees_list = self._format_attendees_list(metadata.get("attendees", []))

        # Format creator if available
        creator = metadata.get("creator", {})
        creator_yaml = ""
        if creator:
            creator_yaml = f"""creator:
  name: "{creator.get('name', 'Unknown')}"
  email: "{creator.get('email', '')}\""""

        # Build YAML frontmatter
        frontmatter = f"""---
title: "{title}"
date: {created_at.isoformat()}
document_id: {document_id}"""

        if workspace_id:
            frontmatter += f"\nworkspace_id: {workspace_id}"

        frontmatter += f"""
created_at: {created_at.isoformat()}
updated_at: {updated_at.isoformat()}
archived_at: {datetime.now().isoformat()}"""

        if attendees_yaml:
            frontmatter += f"\n{attendees_yaml}"

        if creator_yaml:
            frontmatter += f"\n{creator_yaml}"

        frontmatter += "\n---"

        # Build document body
        body = f"""
# {title}

**Date**: {created_at.strftime('%B %d, %Y')}"""

        if attendees_list:
            body += f"\n**Attendees**: {attendees_list}"

        # Add overview if available
        overview = metadata.get("overview") or getattr(document, "overview", None)
        if overview:
            body += f"""

## Overview

{overview}"""

        # Add transcript
        if transcript:
            body += f"""

## Transcript

{self._format_transcript(transcript)}"""

        # Add notes if available
        notes = metadata.get("notes_markdown") or metadata.get("notes")
        if notes:
            body += f"""

## Notes

{notes}"""

        # Add footer
        body += f"""

---
*Archived: {datetime.now().strftime('%Y-%m-%d')}*
"""

        return frontmatter + body

    def _format_attendees_yaml(self, attendees: List[dict]) -> str:
        """Format attendees for YAML frontmatter."""
        if not attendees:
            return ""

        yaml = "attendees:"
        for attendee in attendees:
            name = attendee.get("name", "Unknown")
            email = attendee.get("email", "")
            yaml += f'\n  - name: "{name}"'
            if email:
                yaml += f'\n    email: "{email}"'

        return yaml

    def _format_attendees_list(self, attendees: List[dict]) -> str:
        """Format attendees as a comma-separated list."""
        if not attendees:
            return ""

        names = [a.get("name", "Unknown") for a in attendees]
        return ", ".join(names)

    def _format_transcript(self, transcript: str) -> str:
        """Format transcript with timestamps.

        Args:
            transcript: Raw transcript text

        Returns:
            Formatted transcript
        """
        # If transcript already has formatting, return as-is
        if transcript.startswith("**[") or transcript.startswith("["):
            return transcript

        # Otherwise, wrap in a code block or return as-is
        # The granola client should provide properly formatted transcripts
        return transcript

    def compute_file_path(self, document, base_path: str = "") -> str:
        """Compute the archive file path for a document.

        Args:
            document: The document object
            base_path: Base directory path

        Returns:
            Relative path like YYYY/MM/YYYY-MM-DD-title.md
        """
        created_at = document.created_at
        title = document.title or "untitled"

        # Sanitize title for filename
        safe_title = self._sanitize_filename(title)

        # Build path: YYYY/MM/YYYY-MM-DD-title.md
        year = created_at.strftime("%Y")
        month = created_at.strftime("%m")
        date_prefix = created_at.strftime("%Y-%m-%d")
        filename = f"{date_prefix}-{safe_title}.md"

        if base_path:
            return f"{base_path}/{year}/{month}/{filename}"
        else:
            return f"{year}/{month}/{filename}"

    def _sanitize_filename(self, title: str, max_length: int = 50) -> str:
        """Sanitize a title for use in a filename.

        Args:
            title: The title to sanitize
            max_length: Maximum length for the filename component

        Returns:
            Sanitized filename string
        """
        # Convert to lowercase and replace spaces with hyphens
        safe = title.lower().replace(" ", "-")

        # Remove unsafe characters
        safe = "".join(c for c in safe if c.isalnum() or c in "-_")

        # Remove consecutive hyphens
        while "--" in safe:
            safe = safe.replace("--", "-")

        # Trim hyphens from ends
        safe = safe.strip("-")

        # Truncate if too long
        if len(safe) > max_length:
            safe = safe[:max_length].rstrip("-")

        return safe or "untitled"
