"""CLI commands for the Granola archiver."""

from pathlib import Path

from rich.console import Console

console = Console()

DEFAULT_CONFIG_TEMPLATE = """# Granola Archiver Configuration

granola:
  auto_detect_token: true
  token_env: GRANOLA_TOKEN

archive:
  repo_path: ~/path/to/your/notes-repo  # UPDATE THIS
  remote_name: origin
  default_branch: main

polling:
  interval_minutes: 30
  lookback_hours: 24

filters:
  workspace_ids: []
  min_duration_minutes: 0

logging:
  level: INFO
  file: ~/.local/state/granola-archiver/archiver.log
"""


def get_user_config_path() -> Path:
    """Get the path to the user config file."""
    return Path.home() / ".config" / "granola-archiver" / "config.yaml"


def init_config(force: bool = False) -> None:
    """Create config file in ~/.config/granola-archiver/.

    Args:
        force: If True, overwrite existing config file.
    """
    config_dir = Path.home() / ".config" / "granola-archiver"
    config_file = config_dir / "config.yaml"

    if config_file.exists() and not force:
        console.print(f"[yellow]Config already exists: {config_file}[/yellow]")
        console.print("[dim]Use --force to overwrite[/dim]")
        return

    config_dir.mkdir(parents=True, exist_ok=True)
    config_file.write_text(DEFAULT_CONFIG_TEMPLATE)

    console.print(f"[green]Created config: {config_file}[/green]")
    console.print("[yellow]Please edit the config and set your archive repo_path[/yellow]")
