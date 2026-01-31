# Granola Transcript Archiver

Automated system to archive Granola meeting transcripts to a GitHub repository. The archiver fetches new documents from Granola's API, formats them as Markdown, and commits them to a dedicated archive repository with proper organization and metadata.

## Features

- **Automatic archiving**: Polls Granola API for new/updated documents
- **Smart state tracking**: SQLite database prevents duplicate archives
- **Date-based organization**: Files organized as `YYYY/MM/YYYY-MM-DD-title.md`
- **Rich metadata**: YAML frontmatter with document details, attendees, timestamps
- **Scheduled execution**: macOS launchd integration for automatic runs
- **Idempotent**: Safe to run multiple times - only archives new/updated documents
- **Dry-run mode**: Preview what would be archived without committing

## Project Structure

```
granola-archiver/
├── archiver/               # Main package
│   ├── main.py            # Orchestration and CLI
│   ├── state_tracker.py   # SQLite state management
│   ├── granola_fetcher.py # Granola API wrapper
│   ├── markdown_formatter.py  # Markdown generation
│   ├── git_manager.py     # Git operations
│   └── models.py          # Pydantic models
├── state/                 # SQLite database (git-ignored)
├── scripts/               # Automation scripts
├── config.yaml            # Configuration
└── README.md
```

## Prerequisites

1. **Python 3.13+**
2. **uv**: Fast Python package manager - [Install uv](https://github.com/astral-sh/uv)
3. **Granola API access**: The archiver uses [granola-py-client](https://github.com/anjor/granola-py-client)
4. **Git repository**: A separate GitHub repository for storing archives

## Installation

### 1. Install uv (if not already installed)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. Install the archiver

```bash
cd granola-archiver
uv sync
```

The granola-client dependency will be installed automatically from PyPI.

### 4. Create archive repository

Create a new GitHub repository for storing transcripts:

```bash
# Create repo on GitHub, then clone locally
gh repo create granola-transcripts --private
git clone https://github.com/yourusername/granola-transcripts.git ~/granola-transcripts

# Initialize with README
cd ~/granola-transcripts
echo "# Granola Meeting Transcripts Archive" > README.md
git add README.md
git commit -m "Initial commit"
git push origin main
```

### 5. Configure the archiver

Copy the example configuration and update paths:

```bash
cp config.yaml config.yaml.local
# Edit config.yaml with your archive repo path
```

Example `config.yaml`:

```yaml
archive:
  repo_path: /Users/yourusername/granola-transcripts
  remote_name: origin
  default_branch: main

granola:
  auto_detect_token: true  # Uses ~/.granola/credentials.json

polling:
  interval_minutes: 30
  lookback_hours: 24  # On first run

filters:
  workspace_ids: []  # Empty = all workspaces
  min_duration_minutes: 0

logging:
  level: INFO
  file: /tmp/granola-archiver.log
```

## Usage

### Manual Execution

```bash
# Normal run - archive new documents
uv run archiver

# Dry run - preview what would be archived
uv run archiver --dry-run

# Archive a specific document
uv run archiver --document-id doc_abc123

# Use custom config file
uv run archiver --config /path/to/config.yaml

# Backfill: archive ALL historical documents
uv run archiver --backfill

# Backfill with dry-run to preview
uv run archiver --backfill --dry-run

# Archive documents since a specific date
uv run archiver --since 2024-01-01

# Archive documents since a specific datetime
uv run archiver --since 2024-01-01T10:00:00
```

### Automatic Execution (macOS)

Set up a launchd job to run the archiver every 30 minutes:

```bash
./scripts/setup_launchd.sh
```

This creates `~/Library/LaunchAgents/com.granola.archiver.plist` and loads it.

**Useful commands:**

```bash
# View status
launchctl list | grep granola

# View logs
tail -f /tmp/granola-archiver.log

# View errors
tail -f /tmp/granola-archiver.error.log

# Unload job
launchctl unload ~/Library/LaunchAgents/com.granola.archiver.plist

# Reload job (after config changes)
launchctl unload ~/Library/LaunchAgents/com.granola.archiver.plist
launchctl load ~/Library/LaunchAgents/com.granola.archiver.plist
```

## Archive Format

Documents are archived as Markdown with YAML frontmatter:

```markdown
---
title: "Team Standup"
date: 2026-01-30T14:00:00Z
document_id: doc_abc123
workspace_id: ws_engineering
created_at: 2026-01-30T14:00:00Z
updated_at: 2026-01-30T15:30:00Z
archived_at: 2026-01-30T16:00:00Z
attendees:
  - name: "Alice"
    email: "alice@example.com"
  - name: "Bob"
    email: "bob@example.com"
---

# Team Standup

**Date**: January 30, 2026
**Attendees**: Alice, Bob

## Overview

Quick daily standup to sync on project progress.

## Transcript

**[00:00:00]** Alice: Good morning everyone...

## Notes

- Alice: Working on feature X
- Bob: Investigating bug Y

---
*Archived: 2026-01-30*
```

Files are organized by date:

```
granola-transcripts/
├── 2026/
│   ├── 01/
│   │   ├── 2026-01-30-team-standup.md
│   │   ├── 2026-01-30-client-meeting.md
│   │   └── 2026-01-31-brainstorm-session.md
│   └── 02/
│       └── 2026-02-01-quarterly-review.md
```

## How It Works

1. **State Check**: Reads last run timestamp from SQLite database
2. **Fetch Documents**: Queries Granola API for new/updated documents since last run
3. **Filter**: Skips already-archived documents (checks document ID + updated_at)
4. **Process Each Document**:
   - Fetch full details (transcript, metadata)
   - Format as Markdown with YAML frontmatter
   - Compute file path based on creation date
   - Write file and create git commit
   - Mark as archived in database
5. **Push**: Push all commits to remote repository
6. **Update State**: Record run statistics and timestamp

## Configuration Options

### Granola API

```yaml
granola:
  auto_detect_token: true  # Auto-detect from ~/.granola/credentials.json
  token_env: GRANOLA_TOKEN  # Or use environment variable
```

### Filtering

```yaml
filters:
  workspace_ids: ["ws_eng", "ws_product"]  # Specific workspaces only
  min_duration_minutes: 5  # Skip meetings shorter than 5 minutes
```

### Polling

```yaml
polling:
  interval_minutes: 30  # How often launchd runs (in setup script)
  lookback_hours: 24  # On first run, how far back to look
```

## State Management

The archiver maintains state in `state/archive_state.db` (SQLite):

**archived_documents table:**
- Tracks which documents have been archived
- Prevents duplicate archives
- Records file paths and commit SHAs

**archive_runs table:**
- Logs each archiver run
- Tracks success/failure statistics
- Used to determine last successful run time

To reset state and re-archive everything:

```bash
rm state/archive_state.db
```

## Error Handling

The archiver is designed to be resilient:

- **Authentication failures**: Aborts run immediately with clear error
- **API errors**: Logs error, skips document, continues with others
- **Git conflicts**: Logs error, skips document, continues
- **Network issues**: Handled by granola-client's retry logic

Errors are logged to both console and `/tmp/granola-archiver.log`.

## Troubleshooting

### "Configuration file not found"

Make sure `config.yaml` exists in the working directory or specify path with `--config`.

### "Repository path does not exist"

The archive repository path in `config.yaml` must point to an existing git repository.

### "granola-client not found"

Reinstall dependencies:

```bash
uv sync
```

### "Authentication failed"

Ensure Granola credentials exist at `~/.granola/credentials.json` or set `GRANOLA_TOKEN` environment variable.

### Launchd job not running

Check if loaded:

```bash
launchctl list | grep granola
```

Check error logs:

```bash
tail -f /tmp/granola-archiver.error.log
```

## Development

### Running tests

```bash
uv sync --all-extras
uv run pytest
```

### Code formatting

```bash
uv run black archiver/
uv run ruff check archiver/
```

## Future Enhancements

### Claude API Integration (Optional)

The plan includes an optional enhancement plugin to improve notes using Claude API:

```python
# Future feature - not yet implemented
from archiver.enhancement_plugin import ClaudeEnhancementPlugin

enhancer = ClaudeEnhancementPlugin()
enhanced_markdown = await enhancer.enhance(document, markdown)
```

This would:
- Extract action items clearly
- Highlight key decisions
- Improve formatting
- Generate executive summaries

To enable, add to config:

```yaml
enhancement:
  enabled: true
  model: claude-sonnet-4-5-20250929
```

## License

MIT

## Contributing

Contributions welcome! Please open an issue or pull request.
