from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from alac_rip.config import load_config, DEFAULT_CONFIG_PATH
from alac_rip.downloader import Downloader
from alac_rip.github_sync import push_state, GitSyncError
from alac_rip.state import StateManager
from alac_rip.sync import SyncEngine

app = typer.Typer(
    name="music-sync",
    help="pies-alac-rip-tool — Apple Music lossless sync for Linux",
    no_args_is_help=True,
)
console = Console()


def _get_state(cfg) -> StateManager:
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    return StateManager(cfg.state_dir / "downloaded.db")


@app.command("add")
def music_add(
    url: str = typer.Argument(..., help="Apple Music playlist URL"),
    name: str = typer.Option(..., "--name", "-n", prompt="Playlist name"),
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c"),
):
    """Start tracking a new playlist."""
    cfg = load_config(config)
    state = _get_state(cfg)
    state.add_playlist(name, url)
    console.print(f"[green]Added playlist:[/green] {name}")
    console.print(f"  URL: {url}")
    console.print("  Run [bold]music-sync sync[/bold] to download it.")


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


@app.command("clean")
def music_clean(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """Uninstall: run uninstall.sh from the project root."""
    import subprocess
    from pathlib import Path as P

    if not yes:
        typer.confirm(
            "This will remove all installed binaries and systemd units. Continue?",
            abort=True,
        )

    uninstall_script = P(__file__).parent.parent / "uninstall.sh"
    if not uninstall_script.exists():
        console.print(f"[red]uninstall.sh not found at {uninstall_script}[/red]")
        raise typer.Exit(1)

    subprocess.run(["bash", str(uninstall_script)], check=True)


@app.command("sync")
def music_sync(
    playlist_name: Optional[str] = typer.Argument(
        None, help="Sync a specific playlist by name (syncs all if omitted)"
    ),
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c"),
):
    """Sync tracked playlists — download new tracks only."""
    cfg = load_config(config)
    state = _get_state(cfg)

    playlists = state.get_playlists()
    if not playlists:
        console.print(
            "[yellow]No playlists tracked yet. Run:[/yellow] music-sync add <url>"
        )
        raise typer.Exit()

    if playlist_name:
        playlists = [p for p in playlists if p.name == playlist_name]
        if not playlists:
            console.print(
                f"[red]No playlist named '{playlist_name}'. "
                "Run music-sync status to list tracked playlists.[/red]"
            )
            raise typer.Exit(1)

    downloader = Downloader(
        downloader_repo=cfg.downloader_repo,
        wrapper_bin=cfg.wrapper_bin,
        media_user_token=cfg.media_user_token,
    )

    total_new = 0

    for playlist in playlists:
        console.rule(f"[bold]{playlist.name}[/bold]")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task(f"Downloading {playlist.name}...", total=None)

            engine = SyncEngine(
                downloader=downloader,
                state=state,
                music_dir=cfg.music_dir,
                playlist_name=playlist.name,
            )

            try:
                result = engine.sync(playlist.url)
                state.update_playlist_synced(playlist.name)
                total_new += result.new_count
                progress.update(
                    task,
                    description=(
                        f"Done — {result.new_count} new, "
                        f"{result.skipped_count} skipped"
                    ),
                )
            except Exception as e:
                progress.update(task, description=f"[red]Error: {e}[/red]")
                console.print_exception()

    # Push state to GitHub
    if cfg.github_remote:
        try:
            repo_root = Path(__file__).parent.parent
            push_state(repo_root, cfg.state_dir, total_new)
            console.print("[dim]State pushed to GitHub.[/dim]")
        except GitSyncError as e:
            console.print(f"[yellow]GitHub push failed (non-fatal): {e}[/yellow]")

    console.print(
        f"\n[bold green]Sync complete.[/bold green] "
        f"{total_new} new track(s) downloaded."
    )
