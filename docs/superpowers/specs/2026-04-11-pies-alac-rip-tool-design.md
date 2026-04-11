# Design Spec: pies-alac-rip-tool
**Date:** 2026-04-11
**Status:** Approved

---

## Overview

A Python CLI application that orchestrates lossless Apple Music downloads on Linux (Bazzite), organized for clean playback in Strawberry. Built on top of zhaarey's Go-based `apple-music-downloader` and `wrapper` binary — the proven download core from `alac-rip`. Adds playlist state tracking, file organization, metadata tagging, daily auto-sync via systemd, and GitHub-backed state persistence.

Designed to be largely hands-off: sync runs daily automatically, and `music-sync` is available for instant manual updates. A TUI (Textual) is scaffolded for v2.

---

## Goals

- Download ALAC lossless files from Apple Music subscription playlists on Linux
- Organize files in a Strawberry-compatible directory structure with full metadata and embedded album art
- Track playlist state so only new/missing tracks are downloaded on each sync
- Run daily via systemd user service (no root required)
- Push library state to a private GitHub repo (`pies-alac-rip-tool`) after each sync
- Support clean install and uninstall via a single script

---

## Non-Goals (v1)

- Tauri/desktop GUI (planned for v2/v3)
- Artist-based recommendations (planned for a future milestone)
- Full library sync (playlists first)
- Replacing the zhaarey download core

---

## Architecture

```
┌─────────────────────────────────────────┐
│         pies-alac-rip-tool              │
│  ┌─────────┐  ┌──────────┐  ┌───────┐  │
│  │   CLI   │  │  Sync    │  │  TUI  │  │
│  │ (Typer) │  │  Engine  │  │(v2)   │  │
│  └────┬────┘  └────┬─────┘  └───┬───┘  │
│       └────────────┴────────────┘       │
│            State Manager (SQLite)        │
│            Metadata Layer (mutagen)      │
│            File Organizer                │
└──────────────────┬──────────────────────┘
                   │ shells out via subprocess
┌──────────────────▼──────────────────────┐
│         Download Core (untouched)        │
│   zhaarey apple-music-downloader (Go)    │
│   wrapper binary (decryption service)    │
│   Bento4 / MP4Box                        │
└─────────────────────────────────────────┘
```

The Python app shells out to the Go downloader with Apple Music URLs, exactly as `alac-rip`'s Flask server does. No modifications to the download core.

---

## File Structure

### Music Library (Strawberry-compatible)

```
~/Music/Apple Music/
├── Artist Name/
│   └── Album Name/
│       ├── 01 - Track Title.m4a
│       ├── 02 - Track Title.m4a
│       └── cover.jpg
└── .state/
    ├── playlists.json      # tracked playlists: name, Apple Music URL, last synced
    └── downloaded.db       # SQLite: track_id, title, artist, album, local_path, date_downloaded
```

- Album art is embedded in each `.m4a` file via `mutagen` AND saved as `cover.jpg` alongside tracks — Strawberry reads both formats.
- `.state/` is hidden from Strawberry's scanner but committed to GitHub (excluding auth tokens).
- Music files are `.gitignore`d — only state and source code sync to GitHub.

### Project / Repo Structure

```
pies-alac-rip-tool/
├── alac_rip/
│   ├── __init__.py
│   ├── cli.py              # Typer CLI entrypoint
│   ├── sync.py             # playlist diffing + download orchestration
│   ├── state.py            # SQLite read/write for downloaded tracks
│   ├── metadata.py         # mutagen tagging + cover art embedding
│   ├── organizer.py        # file path construction + directory creation
│   ├── downloader.py       # subprocess wrapper around Go binary
│   └── github_sync.py      # git commit + push state after sync
├── systemd/
│   └── pies-alac-rip.timer
│   └── pies-alac-rip.service
├── install.sh              # full clean install (brew deps, Go binary, venv, systemd)
├── uninstall.sh            # full clean removal
├── config.yaml.example     # template: music dir, token path, github remote
├── .gitignore
├── requirements.txt
└── README.md
```

---

## Commands

```bash
music-sync                              # sync all tracked playlists, download new tracks
music-sync "My Mega Playlist"           # sync one specific playlist by name
music-add <apple-music-playlist-url>    # start tracking a new playlist
music-status                            # show tracked playlists, last sync time, pending count
music-clean                             # uninstall: remove binaries, venv, systemd units
```

All commands produce Rich-formatted terminal output with progress bars during download.

---

## Sync Engine Logic

On each `music-sync` run:

1. Invoke the Go downloader with the playlist URL, directing output to a staging directory (`~/Music/.staging/`)
2. The downloader fetches all tracks in the playlist; files that already exist on disk are either skipped by the downloader or overwritten into staging
3. Compare files produced in staging against `downloaded.db` by track ID / filename
4. For new tracks (not in the DB): move from staging to final library location, tag metadata via `mutagen`, embed album art
5. For tracks already in the DB with a valid path: discard the staging copy
6. Update `downloaded.db` with newly downloaded tracks
7. Commit and push `.state/` to GitHub

**Note on track listing:** The zhaarey downloader does not have a confirmed "list only" mode. The staging approach above avoids needing a separate list API call — we let the downloader run against the playlist URL and treat staging as the source of truth for what Apple Music currently has. This means the downloader touches all tracks on each sync, but only *new* files get moved and tagged. We will investigate during implementation whether a `--dry-run` or metadata-only flag exists that could make this more efficient for large playlists.

---

## Scheduling

A `systemd` user service (no root) runs `music-sync` once daily:

```
~/.config/systemd/user/pies-alac-rip.service
~/.config/systemd/user/pies-alac-rip.timer
```

Enabled via `systemctl --user enable --now pies-alac-rip.timer`. The timer fires daily at a configurable time (default: 3:00 AM). No daemon runs between syncs.

---

## Authentication

Authentication is unchanged from `alac-rip` / zhaarey's downloader:

1. Log into Apple Music in a browser
2. Open DevTools → Application → Cookies → copy `media-user-token`
3. Paste into `config.yaml` (this file is `.gitignore`d — never pushed to GitHub)

The Go downloader reads `config.yaml` directly. Our Python layer reads the config to locate the token path but never handles the token itself.

---

## GitHub Sync

After each successful `music-sync`:

- `git add .state/` → `git commit -m "sync: <date> — N new tracks"` → `git push`
- Handled by `github_sync.py` via `subprocess` (no additional GitHub library needed)
- Requires `gh auth login` to be completed once during install
- Music files and `config.yaml` are in `.gitignore`

---

## Dependency List

| Tool | Install method | Purpose |
|------|---------------|---------|
| `go` | `brew` | Build zhaarey's downloader |
| `gh` | `brew` | GitHub CLI for repo creation and auth |
| `ffmpeg` | `brew` | Audio processing |
| `gpac` | `brew` | MP4Box (required by zhaarey downloader) |
| `wget` | `brew` | Fetch wrapper binary and Bento4 |
| `python3` | `brew` | Runtime |
| `typer` | `pip` (venv) | CLI framework |
| `rich` | `pip` (venv) | Terminal output and progress bars |
| `mutagen` | `pip` (venv) | ALAC/M4A metadata tagging |
| `requests` | `pip` (venv) | HTTP |
| `textual` | `pip` (venv) | TUI (scaffolded, used in v2) |
| zhaarey downloader | compiled by install.sh | Core download engine |
| wrapper binary | fetched by install.sh | Decryption service |
| Bento4 SDK | fetched by install.sh | MP4Box |

No Docker. No Node.js. No npm. No root.

---

## Milestones

### v1 — Core (this spec)
- `install.sh` + `uninstall.sh`
- Working `music-sync` for one playlist
- File organization + metadata tagging
- `music-add`, `music-status` commands
- Daily systemd timer
- GitHub state sync

### v2 — TUI + Improvements
- Textual TUI: browse library, trigger syncs, view status
- Full library sync option
- Improved error handling and retry logic

### v3 — Desktop GUI
- Tauri desktop app reusing the Python backend
- Artist-based recommendation playlists
- GNOME tray integration

---

## Open Questions / Risks

- **Go downloader playlist behavior**: The staging-based sync approach means the downloader runs against the full playlist each time. For a 2000+ song playlist, this may be slow or trigger rate limiting. We will investigate `--select` or dry-run flags during implementation and optimize if needed.
- **Track ID stability**: Apple Music track IDs are assumed stable. If Apple changes these, the diff logic would need adjustment.
- **wrapper binary updates**: The `wrapper` binary is a pre-built artifact from the alac-rip ecosystem. If it goes stale, downloads break. The install script pins a known-good version.
