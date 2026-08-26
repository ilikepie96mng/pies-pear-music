# Pies Pear Music (ALAC Rip Tool) — Project Handoff

## 1. Project Overview & Current State
**Pies Pear Music** is a high-performance lossless music downloader, library sync manager, and Apple Music catalog explorer built with **Tauri v2 + Svelte 5 (Frontend)** and **FastAPI + Python 3.14 + Go (`apple-music-downloader`) + Wine/Podman Wrapper (Backend)**.

### Key Milestones Completed:
- **Persistent SQLite Server-Side Download Queue**:
  - Full persistence in `.state/downloaded.db` (`download_queue` table).
  - Background worker loop in `server.py` pulls jobs autonomously from SQLite.
  - Recovers from crashes / restarts via `state.reset_interrupted_jobs()`.
  - Rich REST endpoints: `/api/v1/queue/add`, `/api/v1/queue`, `/api/v1/queue/cancel`, `/api/v1/queue/retry`, `/api/v1/queue/clear`, `/api/v1/queue/stream`.
  - Batch discography and album queues push directly to server SQLite queue.
- **Dynamic Multi-Source Artwork Resolver**:
  - Embedded FLAC/M4A tags extraction.
  - Directory cover artwork inspection (`cover.jpg`, `folder.jpg`, `cover.png`).
  - Automatic Apple Music CDN fallback redirect (HTTP 307) if audio is remote or unreadable.
  - Svelte dynamic error fallback to local cover extraction endpoint.
- **Headless Docker Media Server & SPA Web Serving**:
  - Multi-stage `Dockerfile` and `docker-compose.yml` for self-hosting on Unraid, TrueNAS, and home Linux servers.
  - Built-in static SPA frontend serving directly from FastAPI at root (`/`) with client-side history navigation fallback.
  - Frontend `app/src/api.ts` transparently auto-detects browser vs Tauri runtime with token support.
- **Headless Automation & Webhook Dispatchers**:
  - `BackgroundSyncScheduler` in `alac_rip/scheduler.py` for automated library sync and playlist refreshes.
  - Rich webhook dispatchers in `alac_rip/integrations.py` for **Discord**, **Telegram**, **Gotify**, **Jellyfin**, and **Navidrome**.
  - REST endpoints for scheduler control (`/api/v1/scheduler/status`, `/trigger`, `/config`) and testing (`/api/v1/integrations/test-webhook`).
  - API Token authentication protection for multi-device network deployment.
- **Web UI Settings Integration for Scheduler & Notifications**:
  - Full **Background Sync Scheduler** configuration card in `Settings.svelte` (interval slider 5m-720m, enable toggle, live daemon status badge, and immediate "Run Sync Now" action).
  - Dedicated **Completion Webhooks & Push Notifications** cards with live test delivery buttons for **Discord** (rich embeds), **Telegram** (bot token & chat ID), and **Gotify** (server URL & token).
  - **Security & Multi-Device Access** token configuration for remote Docker access.
  - Theme consistency refactor: semantic CSS tokens applied across Sidebar and Settings.
- **Live Ripping & Decryption**:
  - Updated Go `apple-music-downloader` flags (`--manifest-out`, `--skip-ids-file`).
  - Modern token scraping regex for latest Apple Music web bundle layouts.
  - Standalone binary compiled at `~/.local/share/pies-alac-rip/amd-main`.
- **Subsonic / Navidrome and Jellyfin Integration Fixes**:
  - Unmasked stored credential handling on backend connection test endpoints (`/integrations/jellyfin/test`, `/integrations/navidrome/test`, and `/api/v1/integrations/test-webhook`).
  - Added dual-header authentication (`X-Emby-Token` & `Authorization: MediaBrowser Token="..."`) and query parameters for modern Jellyfin servers.
  - Added multi-endpoint fallback (`/rest/ping.view` and `/ping.view`) with support for token/salt auth and password fallback for Navidrome/Subsonic servers.
- **Library Health Check & SMB Mount Path Self-Healing**:
  - Implemented dynamic path normalization in `alac_rip/audit.py` (`_normalize_track_file_path`) and `resolve_kio_fuse_path`.
  - Stale session mount paths in SQLite (e.g. `/run/user/1000/kio-fuse-zQhoJw/...`) now dynamically re-anchor against active `cfg.music_dir` and self-heal in the database instead of being falsely reported as 894 missing files and 6,203 untracked files.
- **Multi-Source Album Artwork Resolver & Fallbacks**:
  - Multi-tier `/track-art` resolution in `alac_rip/server.py`: embedded audio tags (FLAC, MP4, MP3), directory cover files (`cover.jpg`, `folder.jpg`, `cover.webp`), and SQLite Apple Music CDN redirect.
  - Enhanced `_run_artwork_resync` with expanded multi-query catalog matching (`artist + title`, `artist + album`, stripped collab queries) and local cover scanning.
  - Frontend fallback in `VirtualTrackTable.svelte` and `Library.svelte` album grid seamlessly displays local track/album art for discography downloads and manual imports.
- **Verification**:
  - 331 automated pytest tests passing (`.venv/bin/pytest`).
  - Frontend compiled cleanly with Svelte 5 + Vite (`npm run build` and `npm run check`).
  - PyInstaller backend sidecar compiled (`./scripts/build-backend-sidecar.sh`).

---

## 2. Directory Structure & Key Files
- `alac_rip/`
  - `state.py`: SQLite `StateManager` (schema, queue methods, playlists, tracks, sync runs).
  - `server.py`: FastAPI backend, persistent queue worker, REST routes, SSE streams, SPA static serving.
  - `scheduler.py`: Background interval sync and playlist refresh scheduler.
  - `config.py`: Configuration loader, env overrides, dynamic `kio-fuse` SMB path resolver.
  - `sync.py`: `SyncEngine` for moving staging audio files to destination library and organizing tags.
  - `metadata_editor.py` & `metadata.py`: Mutagen tag reading/writing and cover embedding/extraction.
  - `am_api.py`: Apple Music catalog search, artist discography scraper, token handling.
  - `integrations.py`: Webhooks for Discord, Telegram, Gotify, Jellyfin, Navidrome, Last.fm, Gemini AI curation.
- `app/`
  - `src/api.ts`: Dual-mode (Tauri + Browser) TypeScript client with typed API routes and queue management.
  - `src/lib/Download.svelte`: Catalog Explorer, Discography Browser, and SQLite Queue UI.
  - `src/lib/Home.svelte`: Library dashboard, recent tracks, sync status.
  - `src/lib/Settings.svelte`: Appearance, Storage/SMB resolver, Media server integrations, Sync scheduler, and Notification webhooks.
  - `src/lib/PlaylistDetail.svelte`: Playlist track inspector, sorting, lyrics modal.
  - `src/lib/Diagnostics.svelte`: System health, storage test, artwork resync tool.
  - `src/lib/themes.ts`: 10 curated WCAG AA themes and wallpaper engine.
- `tests/`
  - `test_persistent_queue.py`: SQLite queue unit tests and FastAPI queue endpoint lifecycle tests.
  - `test_scheduler.py`: Background synchronization scheduler lifecycle tests.
  - `test_webhook_notifications.py`: Discord, Telegram, Gotify notification tests.
  - `test_docker_static_routes.py`: SPA static file serving and API token security tests.
  - `test_server.py`, `test_library_paths.py`, `test_metadata_editor.py`, `test_sync.py`, etc.
- `Dockerfile` & `docker-compose.yml`: Production container deployment definitions.

---

## 3. Next Steps & Planned Work (For Upcoming Sessions)
1. **Public Testing Regime & Standalone Packaging**:
   - Package standalone AppImage, Flatpak, or native `.deb` for Ubuntu/Debian laptop testing (`./scripts/build-packages.sh`).
   - Run manual verification checklist defined in `docs/public-release-plan.md`.
2. **Multi-Arch Docker Images**:
   - Build ARM64 (Raspberry Pi / Apple Silicon) and AMD64 container images for broad homelab architecture support.

---

## 4. Useful Commands for Verification
```bash
# Run backend test suite
.venv/bin/pytest -v

# Run frontend build
cd app && npm run build

# Build standalone backend binary
./scripts/build-backend-sidecar.sh

# Run backend server directly
.venv/bin/uvicorn alac_rip.server:app --port 10025 --reload
```
