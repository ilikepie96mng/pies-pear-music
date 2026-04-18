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
    cfg = load_config(config)
    state = _get_state(cfg)
    state.add_playlist(name, url)
    console.print(f"[green]Added playlist:[/green] {name}")
    console.print(f"  URL: {url}")
    staging = cfg.staging_dir / sanitize(name)
    console.print(f"  Place downloaded .m4a files in: [bold]{staging}[/bold]")
    console.print("  Then run [bold]music-sync sync[/bold] to process them.")


@app.command("status")
def music_status(
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c"),
):
    """Show tracked playlists and library stats."""
    cfg = load_config(config)
    state = _get_state(cfg)

    playlists = state.get_playlists()
    total = state.get_downloaded_count()

    table = Table(title="Tracked Playlists")
    table.add_column("Name", style="cyan")
    table.add_column("Last Synced", style="green")
    table.add_column("URL")

    for pl in playlists:
        table.add_row(
            pl.name,
            pl.last_synced or "[dim]never[/dim]",
            pl.url[:60] + "..." if len(pl.url) > 60 else pl.url,
        )

    console.print(table)
    console.print(f"\n[bold]Total downloaded tracks:[/bold] {total}")
    console.print(f"[bold]Music directory:[/bold] {cfg.music_dir}")
    console.print(f"[bold]Staging directory:[/bold] {cfg.staging_dir}")


@app.command("sync")
def music_sync(
    playlist_name: Optional[str] = typer.Argument(
        None, help="Sync a specific playlist by name (syncs all if omitted)"
    ),
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c"),
):
    """Process staged .m4a files into the music library."""
    cfg = load_config(config)
    state = _get_state(cfg)

    playlists = state.get_playlists()
    if not playlists:
        console.print("[yellow]No playlists tracked yet. Run:[/yellow] music-sync add <url>")
        raise typer.Exit()

    if playlist_name:
        playlists = [p for p in playlists if p.name == playlist_name]
        if not playlists:
            console.print(f"[red]No playlist named '{playlist_name}'.[/red]")
            raise typer.Exit(1)

    total_new = 0

    for playlist in playlists:
        console.rule(f"[bold]{playlist.name}[/bold]")
        staging_dir = cfg.staging_dir / sanitize(playlist.name)

        if not staging_dir.exists() or not any(staging_dir.rglob("*.m4a")):
            console.print(f"[yellow]No files in {staging_dir} — skipping.[/yellow]")
            continue

        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:
            task = progress.add_task(f"Processing {playlist.name}...", total=None)

            engine = SyncEngine(
                state=state,
                music_dir=cfg.music_dir,
                playlist_name=playlist.name,
            )

            try:
                result = engine.sync(staging_dir)
                state.update_playlist_synced(playlist.name)
                total_new += result.new_count
                progress.update(task, description=f"Done — {result.new_count} new, {result.skipped_count} skipped")
            except Exception as e:
                progress.update(task, description=f"[red]Error: {e}[/red]")
                console.print_exception()

    if cfg.github_remote:
        try:
            repo_root = Path(__file__).parent.parent
            push_state(repo_root, cfg.state_dir, total_new)
            console.print("[dim]State pushed to GitHub.[/dim]")
        except GitSyncError as e:
            console.print(f"[yellow]GitHub push failed (non-fatal): {e}[/yellow]")

    console.print(f"\n[bold green]Done.[/bold green] {total_new} new track(s) processed.")
