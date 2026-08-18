# Handoff — Pies Pear Music (`pies-alac-rip-tool`)

**Last Updated:** 2026-08-17  
**Current Branch:** `release/2`  
**Status:** Phases 1–7 + v2.1 Roadmap (Smart Dynamic Playlists, Audio Waveform Visualizer & Scrubber, and Batch Metadata Mass-Tagging & Cover Art Replacer) Fully Completed, Audited & Verified (298 passing backend tests, 0 Svelte errors/warnings, full Vite production build, 2 passing Tauri Cargo tests). Ready for Release Merge / Package Distribution.

---

## 1. Project Overview & Core Architecture
* **Frontend**: Svelte 5 (Runes `$state`, `$derived`, `$props`, `$effect`) / SvelteKit / Vite desktop interface (`app/src/lib/`).
* **Desktop Shell**: Tauri v2 desktop wrapper (`app/src-tauri/`) with native Linux and Windows support.
* **Backend**: FastAPI sidecar (`alac_rip/server.py`) communicating with Tauri via ephemeral 256-bit stdin capability token (`X-Pies-Api-Token` & query token auth `?token=...`).
* **Downloader**: External Go binary (`apple-music-downloader`), deployed at `~/.local/share/pies-alac-rip/amd-main`.
* **Database State**: SQLite (`~/.local/share/pies-alac-rip/downloaded.db`), managed via `alac_rip/state.py`.
* **Audio Engine**: Range-capable local audio streaming (`/api/v1/stream?track_id=...`) and downsampled waveform peak extraction (`/api/v1/waveform?track_id=...`).
* **Tagging Engine**: Mutagen-based atomic metadata & cover art editor (`alac_rip/metadata_editor.py`) for FLAC, ALAC/M4A, AAC, and MP3.

---

## 2. Completed Features & Accomplishments

1. **Batch Metadata Mass-Tagging & Cover Art Replacer (`v2.1 Feature 3`)**:
   - **Atomic Multi-Format Tagging Engine (`alac_rip/metadata_editor.py`)**: Mutagen integration supporting title, artist, album, album artist, genre, year/date, track/disc numbers, lyrics, comments, and cover artwork replacement/removal across ALAC/M4A (`MP4Cover`), FLAC (`Picture`), and MP3 (`APIC`).
   - **Safe File Reorganization & DB Sync**: Moves files on disk to canonical `artists/Artist/Album/` paths when artist/album tags change, and synchronizes SQLite `tracks` records.
   - **REST Endpoints (`alac_rip/server.py`)**: `POST /api/v1/tracks/batch-tag` and `GET /api/v1/tracks/cover?track_id=...` with strict path isolation safety checks.
   - **Svelte 5 Batch Inspector UI (`BatchTagModal.svelte`)**: Multi-track selection support in `VirtualTrackTable.svelte` with sticky floating action toolbar, field update checkboxes with `[Keep Existing Values]` preservation, drag-and-drop cover art image dropzone with live preview, and one-click removal.
2. **Interactive Audio Waveform Visualizer & Scrubber (`v2.1 Feature 2`)**:
   - **Waveform Peak Extractor (`alac_rip/waveform.py`)**: Subprocess FFmpeg pipeline decoding audio streams into mono 8000Hz 16-bit PCM, downsampling into bucketed peak amplitudes normalized between `[0.0, 1.0]`.
   - **SQLite Persistent Caching (`alac_rip/state.py`)**: `audio_waveforms` table storing downsampled peak arrays, points resolution, duration, and timestamps for instant retrieval.
   - **Canvas Interactive Scrubber (`PlayerBar.svelte`)**: High-DPI responsive canvas visualizer rendering vertical rounded amplitude bars, played portion accent highlighting, live playhead cursor, pointer drag seeking, and hover time tooltip indicator.
3. **Smart Dynamic Playlists Engine & Rule Builder UI (`v2.1 Feature 1`)**:
   - **Database Persistence**: `smart_playlists` table in `alac_rip/state.py` with CRUD methods.
   - **Evaluation Engine (`alac_rip/smart_playlists.py`)**: Multi-condition dynamic evaluator supporting `ALL` (AND) / `ANY` (OR) matching across `title`, `artist`, `album`, `playlist`, `format`, `downloaded_at`, and `local_path`, with 12 operators, sorting, and limits.
   - **Modal Builder (`SmartPlaylistModal.svelte`) & Library Tab**: Dedicated "⚡ Smart Playlists" tab with dual-pane layout, live query editing, deletion, and DAP export.
4. **Playlist Creator Workstation & AI Assistant (`PlaylistCreator.svelte`)**:
   - Dual-pane playlist studio with multi-select across Tracks, Albums, Artists, Existing Playlists, and **✨ AI Assistant**.
   - Gemini AI mix generator with prompt, target track count, and direct 1-click "Stage Mix" integration.
   - Native OS destination folder selection on `.m3u8` export using `saveDialog` from `@tauri-apps/plugin-dialog`.
5. **Core Foundations (Phases 1–7)**:
   - Incremental sync engine with SHA256 integrity checks, missing track detection, auto-retry queue.
   - Multi-tier lyrics search on LRCLIB with synchronized karaoke highlighting.
   - Bit-perfect original lossless and transcode (Opus/AAC) DAP exports.
   - Jellyfin, Navidrome, Strawberry SQLite integrations, and masked Last.fm credentials.

---

## 3. Verification Suite Results

All tests passing cleanly:
- `.venv/bin/pytest`: **298 passing tests** (12.52s).
- `cd app && npm run check`: **0 errors, 0 warnings**.
- `cd app && npm run build`: **Vite production build completed successfully**.
- `cd app/src-tauri && cargo test --locked`: **2 passing tests**.

---

## 4. Packaging & Distribution Commands

- **To run in development mode:**
  ```bash
  cd app && npm run tauri dev
  ```
- **To build production installer bundles (.deb / .AppImage / .msi):**
  ```bash
  cd app && npm run tauri build
  ```
