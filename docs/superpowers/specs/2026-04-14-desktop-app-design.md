# pies-alac-rip Desktop App — Design Spec

**Date:** 2026-04-14
**Goal:** Wrap the working Apple Music sync pipeline in a modern Tauri desktop app with a dark, music-first UI. The core downloader/sync pipeline is MVP — this spec adds a GUI layer on top without touching it.

---

## Constraint

> **Do not modify any existing Python module** (`downloader.py`, `sync.py`, `state.py`, `organizer.py`, `metadata.py`, `config.py`). All new Python code lives in `alac_rip/server.py`. The working sync pipeline is the minimum viable product.

---

## Architecture

```
User
 └─► Tauri Window (native desktop app)
       ├─ Svelte + Tailwind UI  ──HTTP/SSE──►  Python FastAPI (sidecar)
       └─ Rust core                               └─► existing modules (unchanged)
            ├─ spawns Python on open
            ├─ reads port from temp file
            └─ kills Python on close
```

**Python sidecar pattern:** Tauri's Rust core spawns `python -m alac_rip.server` as a subprocess on app open. Python picks a free port, writes it to a temp file (`/tmp/pies-alac-rip.port`). Rust reads that file and exposes the port to Svelte via a Tauri command (`get_api_port`). On app close, Rust kills the subprocess. All communication between Svelte and Python is plain HTTP on localhost — no Tauri IPC needed beyond that one command.

---

## File Map

| Path | Status | Responsibility |
|------|--------|----------------|
| `alac_rip/server.py` | **NEW** | FastAPI server — thin wrapper over existing modules |
| `app/src-tauri/src/main.rs` | **NEW** | Spawn/kill Python sidecar, expose port via Tauri command |
| `app/src-tauri/tauri.conf.json` | **NEW** | Tauri config — app name, window size, bundle settings |
| `app/src/App.svelte` | **NEW** | Root layout — sidebar + router |
| `app/src/lib/Sidebar.svelte` | **NEW** | Nav links, playlist list, Sync All button |
| `app/src/lib/Library.svelte` | **NEW** | Cover art grid for a playlist's tracks |
| `app/src/lib/SyncProgress.svelte` | **NEW** | Live SSE progress display |
| `app/src/lib/Settings.svelte` | **NEW** | Config editor (music dir, token, credentials) |
| `app/src/api.ts` | **NEW** | All HTTP calls centralised — never scattered across components |
| `app/package.json` | **NEW** | Svelte + Tailwind + Vite dependencies |

---

## Python: `alac_rip/server.py`

FastAPI app. Reads config on startup. Exposes these endpoints:

### Endpoints

| Method | Path | Action |
|--------|------|--------|
| `GET` | `/playlists` | `state.get_playlists()` → list |
| `POST` | `/playlists` | `state.add_playlist(name, url)` |
| `DELETE` | `/playlists/{name}` | remove playlist from DB |
| `POST` | `/sync/{name}` | run `SyncEngine.sync()` in a thread, stream progress via SSE |
| `POST` | `/sync` | sync all tracked playlists sequentially, stream progress |
| `GET` | `/library` | all tracks across all playlists, keyed by playlist name |
| `GET` | `/config` | return safe config fields (no password in response) |
| `PUT` | `/config` | write updated fields back to `config.yaml` |
| `GET` | `/health` | `{"status": "ok"}` — Rust polls this to confirm Python is up |
| `GET` | `/track-art/{track_id}` | extract and return the `covr` tag bytes from the track's `.m4a` file |

### Sync progress via SSE

`SyncEngine.sync()` is synchronous and blocking. **No changes to `sync.py`.**

Progress streaming approach:

1. `POST /sync/{name}` records the pre-sync track count from `state.get_downloaded_count()`, then spawns a thread running `SyncEngine.sync()`
2. The SSE generator loop polls `state.get_downloaded_count()` every second while the thread is alive, yielding `{current: int, total: int, status: "running"}` events
3. When the thread finishes, yield a final `{result: {new, skipped, errors}, status: "done"}` event and close the stream
4. Svelte uses `EventSource` to consume the stream — shows a live incrementing counter and progress bar

The total track count comes from the downloader reporting it in stdout — `server.py` captures this at sync start by calling `state.get_playlist_tracks()` after a brief delay, or simply shows an indeterminate progress bar until the first tracks land. This is a known approximation; exact per-track streaming is a future enhancement.

### Port selection

```python
import socket, pathlib
sock = socket.socket(); sock.bind(("127.0.0.1", 0))
port = sock.getsockname()[1]; sock.close()
pathlib.Path("/tmp/pies-alac-rip.port").write_text(str(port))
uvicorn.run(app, host="127.0.0.1", port=port)
```

---

## Rust: `src-tauri/src/main.rs`

Three responsibilities only:

1. **Spawn sidecar** — `std::process::Command` to run `python -m alac_rip.server` with the project venv activated. Poll `/health` (up to 10s) before showing the window.
2. **Expose port** — Tauri command `get_api_port()` reads `/tmp/pies-alac-rip.port` and returns the port number to the frontend.
3. **Kill on exit** — store the child `pid`, kill on `on_window_event(CloseRequested)`.

---

## Svelte Frontend

**Stack:** Svelte 5 + Tailwind CSS + Vite (via `create-tauri-app --template svelte`)

**Layout** (`App.svelte`):
- Persistent left sidebar (180px): app title, nav (Library / Settings), playlist list, Sync All button, active sync progress strip
- Main content area: swaps between `Library`, `SyncProgress`, `Settings` based on selected nav item

**Component responsibilities:**

- `Sidebar.svelte` — fetches playlist list on mount (`GET /playlists`), renders each as a clickable item, shows inline sync progress strip when a sync is active
- `Library.svelte` — receives selected playlist name, fetches tracks (`GET /library`), renders cover art grid (cover from embedded `covr` tag — served via `GET /track-art/{track_id}` endpoint)
- `SyncProgress.svelte` — opens `EventSource` to `/sync/{name}`, renders live track-by-track list with status icons, auto-dismisses when stream closes
- `Settings.svelte` — `GET /config` on mount, form fields for music dir, token, email (password field hidden/masked), `PUT /config` on save

**`api.ts`** — single module with typed functions wrapping `fetch`. All base URL logic here (reads port from `invoke("get_api_port")`). No raw `fetch` calls in components.

---

## Error Handling

- **Python fails to start:** Rust shows a native error dialog before the window opens. User sees actionable message (check venv, check config).
- **Sync error (individual track):** SSE stream emits `{status: "error"}` for that track. UI shows it in red inline — sync continues for remaining tracks.
- **Config write failure:** `PUT /config` returns 500 with message. Settings UI shows inline error toast.
- **Wrapper login failure:** `DownloadError` from `start_wrapper()` is caught in `SyncEngine.sync()`, emitted as a terminal SSE error event. UI shows the container log output so the user knows it's a credential issue.

---

## v1 Scope (explicit exclusions)

**In:** Library view, live sync progress, add/remove playlists, manual sync trigger, settings UI.

**Out (future):** Recommendations, search, audio playback, auto-sync scheduling UI (systemd timer handles this already), multi-account support.

---

## Tech Versions

- Python: 3.12+ (existing)
- FastAPI: `>=0.111`
- uvicorn: `>=0.29`
- Tauri: 2.x
- Svelte: 5.x
- Tailwind CSS: 3.x
- Node: 20+
- Rust: stable (via `rustup`)
