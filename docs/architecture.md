# Architecture

Pies Pear Music is a Linux desktop application with three distinct layers:

1. **Svelte frontend** — the desktop user interface in `app/src/`.
2. **Tauri shell** — launches the packaged Python sidecar and exposes the
   loopback API port to the frontend in `app/src-tauri/`.
3. **Python backend** — manages local state, sync jobs, diagnostics, library
   records, and integrations in `alac_rip/`.

## Structure review

The frontend and Tauri lifecycle boundaries are small and explicit. SQLite
ownership is centralized in `state.py`, and media organization remains in
`sync.py`. The main structural debt is `server.py`, which currently combines
API routing, wrapper/auth process management, queue orchestration, diagnostics,
and third-party integrations. It should eventually be split along those
boundaries after the release behavior is stable. Auth extraction must happen
last and preserve the fixture-driven contract in `docs/auth-contract.md`.

Legacy CLI, Git-backed state sync, installer, and systemd files remain only in
the private development history. The public snapshot verifier excludes them;
they are not part of the desktop architecture or supported product surface.

## Packaged and external components

The Tauri bundle embeds a PyInstaller-built `pies-backend` sidecar. This means
the desktop package does not need a source checkout or a project virtual
environment at runtime.

The downloader, wrapper, Bento4/MP4Box, FFmpeg, Podman, Go, and optional
`mp4decrypt` remain external user-installed dependencies. They are not bundled,
downloaded, or updated by the application. Diagnostics checks their availability
and the configured downloader/wrapper source directories.

## Data ownership

The backend owns the local SQLite state database, sync logs, and library
metadata. Music, state, logs, and credentials are user data and must not be
committed or included in a support bundle. The state database records playlists,
track paths, and sync history; deleting a playlist removes only that playlist's
links and history, not the underlying downloaded-track record.

Apple/wrapper credentials persist through the desktop Secret Service when it is
available. Without it, they exist only in backend memory for the active session;
the application never reads or writes a plaintext credential fallback file.

## Desktop/backend boundary

The desktop shell allocates a loopback port and generates a fresh per-launch
capability, then passes both to the bundled sidecar over its stdin handshake
pipe. It proves the handshake with an authenticated health check. The frontend
receives the connection data through a Tauri command; every API request,
including artwork and streamed sync output, uses a request header. Artwork is
fetched as an authenticated blob and the former `EventSource` consumers use
authenticated `fetch` streaming.

CSP permits only bundled assets, HTTPS artwork, and the loopback backend
connection; CORS permits the Tauri webview and the local development origin.
Direct backend development runs without the sidecar-handshake argument remain
unauthenticated, while every packaged sidecar launch uses the handshake.

## Sync path

Manual syncs run one at a time. The backend records status and bounded recent
history, validates playlist URLs/formats/names, and only serves artwork or
reveal operations for known records below the configured music directory.
Strawberry export uses a bounded SQLite lock and creates a backup after it has
acquired a write reservation.
