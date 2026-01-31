"""Main orchestrator for the Granola archiver."""

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

from .cli import get_user_config_path, init_config
from .models import ArchiverConfig, ArchiveResult, ArchiveSummary
from .state_tracker import StateTracker
from .granola_fetcher import GranolaFetcher
from .markdown_formatter import MarkdownFormatter
from .git_manager import GitManager

# Load environment variables
load_dotenv()

console = Console()


def setup_logging(config: ArchiverConfig):
    """Setup logging configuration."""
    log_level = getattr(logging, config.logging.level.upper(), logging.INFO)

    # Create log directory if needed
    log_file = Path(config.logging.file)
    log_file.parent.mkdir(parents=True, exist_ok=True)

    # Configure logging
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            RichHandler(console=console, rich_tracebacks=True),
            logging.FileHandler(config.logging.file),
        ],
    )


def find_config_path(explicit_path: Optional[str] = None) -> Path:
    """Find config file using search order.

    Search order:
    1. Explicit path from --config flag
    2. GRANOLA_ARCHIVER_CONFIG environment variable
    3. ~/.config/granola-archiver/config.yaml (XDG user config)
    4. ./config.yaml (current directory, for development)

    Args:
        explicit_path: Explicit path provided via --config flag

    Returns:
        Path to the config file

    Raises:
        FileNotFoundError: If no config file is found
    """
    # 1. Explicit path from --config
    if explicit_path:
        path = Path(explicit_path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {explicit_path}")
        return path

    # 2. Environment variable
    env_path = os.getenv("GRANOLA_ARCHIVER_CONFIG")
    if env_path:
        path = Path(env_path)
        if not path.exists():
            raise FileNotFoundError(
                f"Config file from GRANOLA_ARCHIVER_CONFIG not found: {env_path}"
            )
        return path

    # 3. XDG config directory
    xdg_config = get_user_config_path()
    if xdg_config.exists():
        return xdg_config

    # 4. Current directory
    local_config = Path("config.yaml")
    if local_config.exists():
        return local_config

    raise FileNotFoundError(
        "No config file found. Run 'archiver init' to create one, "
        "or specify with --config or GRANOLA_ARCHIVER_CONFIG"
    )


def load_config(config_path: Optional[str] = None) -> ArchiverConfig:
    """Load configuration from YAML file.

    Args:
        config_path: Optional explicit path to configuration file

    Returns:
        ArchiverConfig object
    """
    config_file = find_config_path(config_path)
    console.print(f"[dim]Using config: {config_file}[/dim]")

    with open(config_file, "r") as f:
        config_dict = yaml.safe_load(f)

    return ArchiverConfig(**config_dict)


async def archive_document(
    document,
    granola_fetcher: GranolaFetcher,
    formatter: MarkdownFormatter,
    git_manager: GitManager,
    state_tracker: StateTracker,
    dry_run: bool = False,
) -> ArchiveResult:
    """Archive a single document.

    Args:
        document: The document to archive
        granola_fetcher: Granola API client
        formatter: Markdown formatter
        git_manager: Git manager
        state_tracker: State tracker
        dry_run: If True, don't actually commit or update state

    Returns:
        ArchiveResult with success/failure info
    """
    logger = logging.getLogger(__name__)

    try:
        # Fetch full document details
        logger.info(f"Fetching details for {document.id}")
        details = await granola_fetcher.fetch_document_details(document.id)

        # Generate markdown
        markdown = formatter.format_document(details.document, details.transcript, details.metadata)

        # Compute file path
        file_path = formatter.compute_file_path(document)

        if dry_run:
            console.print(f"[yellow]DRY RUN: Would archive to {file_path}[/yellow]")
            return ArchiveResult(success=True, doc_id=document.id, file_path=file_path)

        # Write and commit
        commit_message = f"""Archive: {document.title}

Document ID: {document.id}
Date: {document.created_at.strftime('%Y-%m-%d')}
"""
        commit_sha = git_manager.write_and_commit(file_path, markdown, commit_message)

        if not commit_sha:
            raise Exception("Failed to commit document")

        # Track success
        state_tracker.mark_archived(
            document_id=document.id,
            title=document.title,
            created_at=document.created_at,
            updated_at=document.updated_at,
            file_path=file_path,
            commit_sha=commit_sha,
        )

        logger.info(f"Successfully archived {document.id} to {file_path}")
        return ArchiveResult(
            success=True, doc_id=document.id, file_path=file_path, commit_sha=commit_sha
        )

    except Exception as e:
        logger.error(f"Failed to archive {document.id}: {e}", exc_info=True)
        return ArchiveResult(success=False, doc_id=document.id, error=str(e))


async def run_archiver(
    config: ArchiverConfig,
    dry_run: bool = False,
    document_id: Optional[str] = None,
    backfill: bool = False,
    since_date: Optional[str] = None,
) -> ArchiveSummary:
    """Run the archiver.

    Args:
        config: Archiver configuration
        dry_run: If True, don't actually commit or update state
        document_id: If provided, only archive this specific document
        backfill: If True, fetch ALL documents regardless of last run timestamp
        since_date: If provided, fetch documents updated since this date (ISO format)

    Returns:
        ArchiveSummary with results
    """
    logger = logging.getLogger(__name__)
    logger.info("Starting archiver run")

    # Initialize components
    token = os.getenv(config.granola.token_env) if not config.granola.auto_detect_token else None
    granola_fetcher = GranolaFetcher(token=token)
    state_tracker = StateTracker("state/archive_state.db")
    git_manager = GitManager(
        config.archive.repo_path, config.archive.remote_name, config.archive.default_branch
    )
    formatter = MarkdownFormatter()

    # Ensure git repo is up to date (unless dry run)
    if not dry_run:
        git_manager.ensure_up_to_date()

    # Fetch documents
    if document_id:
        # Archive specific document
        logger.info(f"Archiving specific document: {document_id}")
        doc = await granola_fetcher.fetch_document_details(document_id)
        documents = [doc.document]
    else:
        # Determine the 'since' timestamp
        if backfill:
            # Backfill mode: fetch ALL documents
            logger.info("Backfill mode - fetching ALL documents from Granola")
            fetch_since = None
        elif since_date:
            # Use provided custom date
            try:
                fetch_since = datetime.fromisoformat(since_date)
                logger.info(f"Fetching documents since {fetch_since}")
            except ValueError:
                raise ValueError(
                    f"Invalid date format: {since_date}. "
                    "Use ISO format (e.g., 2024-01-01 or 2024-01-01T10:00:00)"
                )
        else:
            # Normal mode: use last run timestamp
            fetch_since = state_tracker.get_last_run_timestamp()
            if not fetch_since:
                # First run - look back configured hours
                lookback = timedelta(hours=config.polling.lookback_hours)
                fetch_since = datetime.now() - lookback
                logger.info(f"First run - looking back {config.polling.lookback_hours} hours")

        # Fetch documents
        workspace_ids = config.filters.workspace_ids if config.filters.workspace_ids else None
        documents = await granola_fetcher.fetch_new_documents(
            since=fetch_since, workspace_ids=workspace_ids
        )

    # Process documents
    results = []
    skipped_count = 0

    for doc in documents:
        # Check if already archived with same update time
        if state_tracker.is_archived(doc.id, doc.updated_at):
            logger.info(f"Skipping {doc.id} - already archived")
            skipped_count += 1
            continue

        # Apply duration filter if configured
        if config.filters.min_duration_minutes > 0:
            duration = getattr(doc, "duration_minutes", 0)
            if duration < config.filters.min_duration_minutes:
                logger.info(f"Skipping {doc.id} - too short ({duration} min)")
                skipped_count += 1
                continue

        # Archive document
        result = await archive_document(
            doc, granola_fetcher, formatter, git_manager, state_tracker, dry_run
        )
        results.append(result)

    # Push commits (unless dry run)
    if not dry_run and any(r.success for r in results):
        success = git_manager.push_to_remote()
        if not success:
            logger.warning("Failed to push commits to remote")

    # Update run statistics
    if not dry_run:
        archived_count = sum(1 for r in results if r.success)
        failed_count = sum(1 for r in results if not r.success)
        state_tracker.update_last_run(
            documents_processed=len(documents),
            documents_archived=archived_count,
            documents_failed=failed_count,
        )

    # Build summary
    summary = ArchiveSummary(
        total_documents=len(documents),
        archived_count=sum(1 for r in results if r.success),
        failed_count=sum(1 for r in results if not r.success),
        skipped_count=skipped_count,
        results=results,
    )

    logger.info(
        f"Archiver run complete: {summary.archived_count} archived, "
        f"{summary.failed_count} failed, {summary.skipped_count} skipped"
    )

    return summary


def print_summary(summary: ArchiveSummary):
    """Print a summary table of the archive run."""
    table = Table(title="Archive Summary")
    table.add_column("Metric", style="cyan")
    table.add_column("Count", style="magenta")

    table.add_row("Total Documents", str(summary.total_documents))
    table.add_row("Archived", str(summary.archived_count))
    table.add_row("Failed", str(summary.failed_count))
    table.add_row("Skipped", str(summary.skipped_count))

    console.print(table)

    # Print failures if any
    if summary.failed_count > 0:
        console.print("\n[red]Failed Documents:[/red]")
        for result in summary.results:
            if not result.success:
                console.print(f"  - {result.doc_id}: {result.error}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Archive Granola transcripts to GitHub")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Init subcommand
    init_parser = subparsers.add_parser(
        "init", help="Create config file in ~/.config/granola-archiver/"
    )
    init_parser.add_argument("--force", action="store_true", help="Overwrite existing config file")

    # Run subcommand (also the default behavior)
    run_parser = subparsers.add_parser("run", help="Run the archiver (default)")
    run_parser.add_argument("--config", help="Path to configuration file")
    run_parser.add_argument(
        "--dry-run", action="store_true", help="Show what would be archived without committing"
    )
    run_parser.add_argument("--document-id", help="Archive a specific document by ID")
    run_parser.add_argument(
        "--backfill",
        action="store_true",
        help="Fetch ALL documents regardless of last run timestamp (skips already-archived)",
    )
    run_parser.add_argument(
        "--since",
        type=str,
        help="Fetch documents updated since this date (ISO format: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)",
    )

    # Also allow running without subcommand for backwards compatibility
    parser.add_argument("--config", help="Path to configuration file")
    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would be archived without committing"
    )
    parser.add_argument("--document-id", help="Archive a specific document by ID")
    parser.add_argument(
        "--backfill",
        action="store_true",
        help="Fetch ALL documents regardless of last run timestamp (skips already-archived)",
    )
    parser.add_argument(
        "--since",
        type=str,
        help="Fetch documents updated since this date (ISO format: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)",
    )

    args = parser.parse_args()

    # Handle init command
    if args.command == "init":
        init_config(force=args.force)
        return

    try:
        # Load configuration
        config = load_config(args.config)

        # Setup logging
        setup_logging(config)

        # Run archiver
        summary = asyncio.run(
            run_archiver(
                config,
                dry_run=args.dry_run,
                document_id=args.document_id,
                backfill=args.backfill,
                since_date=args.since,
            )
        )

        # Print summary
        print_summary(summary)

        # Exit with error code if any documents failed
        sys.exit(0 if summary.failed_count == 0 else 1)

    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user[/yellow]")
        sys.exit(130)
    except Exception as e:
        console.print(f"[red]Fatal error: {e}[/red]")
        logging.exception("Fatal error")
        sys.exit(1)


if __name__ == "__main__":
    main()
