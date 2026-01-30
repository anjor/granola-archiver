"""Tests for markdown_formatter module."""

import pytest
from datetime import datetime

from archiver.markdown_formatter import MarkdownFormatter


class MockDocument:
    """Mock document for testing."""

    def __init__(self, **kwargs):
        self.id = kwargs.get('id', 'doc_123')
        self.title = kwargs.get('title', 'Test Meeting')
        self.created_at = kwargs.get('created_at', datetime(2026, 1, 30, 14, 0, 0))
        self.updated_at = kwargs.get('updated_at', datetime(2026, 1, 30, 15, 0, 0))
        self.workspace_id = kwargs.get('workspace_id', 'ws_test')


def test_format_document_basic():
    """Test basic document formatting."""
    formatter = MarkdownFormatter()
    doc = MockDocument()
    transcript = "Test transcript content"
    metadata = {}

    markdown = formatter.format_document(doc, transcript, metadata)

    assert "# Test Meeting" in markdown
    assert "document_id: doc_123" in markdown
    assert "Test transcript content" in markdown


def test_format_document_with_attendees():
    """Test formatting with attendees."""
    formatter = MarkdownFormatter()
    doc = MockDocument()
    metadata = {
        'attendees': [
            {'name': 'Alice', 'email': 'alice@example.com'},
            {'name': 'Bob', 'email': 'bob@example.com'}
        ]
    }

    markdown = formatter.format_document(doc, "transcript", metadata)

    assert 'Alice' in markdown
    assert 'Bob' in markdown
    assert 'alice@example.com' in markdown


def test_compute_file_path():
    """Test file path computation."""
    formatter = MarkdownFormatter()
    doc = MockDocument(
        title="Team Standup Meeting",
        created_at=datetime(2026, 1, 30, 14, 0, 0)
    )

    path = formatter.compute_file_path(doc)
    assert path == "2026/01/2026-01-30-team-standup-meeting.md"


def test_sanitize_filename():
    """Test filename sanitization."""
    formatter = MarkdownFormatter()

    # Test spaces and special characters
    assert formatter._sanitize_filename("Test Meeting!") == "test-meeting"

    # Test consecutive hyphens
    assert formatter._sanitize_filename("Test  --  Meeting") == "test-meeting"

    # Test max length
    long_title = "A" * 100
    result = formatter._sanitize_filename(long_title)
    assert len(result) <= 50

    # Test empty/invalid
    assert formatter._sanitize_filename("!!!") == "untitled"


def test_format_attendees_yaml():
    """Test attendees YAML formatting."""
    formatter = MarkdownFormatter()

    attendees = [
        {'name': 'Alice', 'email': 'alice@example.com'},
        {'name': 'Bob', 'email': ''}
    ]

    yaml = formatter._format_attendees_yaml(attendees)

    assert 'attendees:' in yaml
    assert 'name: "Alice"' in yaml
    assert 'email: "alice@example.com"' in yaml
    assert 'name: "Bob"' in yaml


def test_format_attendees_list():
    """Test attendees list formatting."""
    formatter = MarkdownFormatter()

    attendees = [
        {'name': 'Alice'},
        {'name': 'Bob'},
        {'name': 'Charlie'}
    ]

    result = formatter._format_attendees_list(attendees)
    assert result == "Alice, Bob, Charlie"
