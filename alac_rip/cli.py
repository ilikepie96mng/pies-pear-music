from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from alac_rip.config import load_config, DEFAULT_CONFIG_PATH
from alac_rip.github_sync import push_state, GitSyncError
from alac_rip.organizer import sanitize
from alac_rip.state import StateManager
from alac_rip.sync import SyncEngine

app = typer.Typer(
    name="music-sync",
    help="pies-alac-rip-tool — local music library sync",
    no_args_is_help=True,
)
console = Console()


def _get_state(cfg) -> StateManager:
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    return StateManager(cfg.state_dir / "downloaded.db")


@app.command("add")
def music_add(
    url: str = typer.Argument(..., help="Playlist URL or identifier"),
    name: str = typer.Option(..., "--name", "-n", prompt="Playlist name"),
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c"),
):
    """Start tracking a new playlist."""
    raise NotImplementedError("CLI has been superseded by the desktop app pipeline. Use the web UI instead.")


@app.command("status")
def music_status(
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c"),
):
    """Show tracked playlists and library stats."""
    raise NotImplementedError("CLI has been superseded by the desktop app pipeline. Use the web UI instead.")


@app.command("sync")
def music_sync(
    playlist_name: Optional[str] = typer.Argument(
        None, help="Sync a specific playlist by name (syncs all if omitted)"
    ),
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c"),
):
    """Process staged .m4a files into the music library."""
    raise NotImplementedError("CLI has been superseded by the desktop app pipeline. Use the web UI instead.")
