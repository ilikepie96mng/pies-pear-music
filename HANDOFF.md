# Handoff — Pies Pear Music (`pies-alac-rip-tool`)

**Last Updated:** 2026-08-17  
**Current Branch:** `release/2`  
**Latest Commit Baseline:** `ffc77c8`  
**Status:** Phases 1–7 Completed + v2.1 Feature 1 (Smart Dynamic Playlists) Fully Implemented, Audited & Verified (283 passing backend tests, 0 Svelte errors/warnings, full Vite production build, 2 passing Tauri Cargo tests).

---

## 1. Project Overview & Core Architecture
* **Frontend**: Svelte 5 (Runes `$state`, `$derived`, `$props`, `$effect`) / SvelteKit / Vite desktop interface (`app/src/lib/`).
* **Desktop Shell**: Tauri v2 desktop wrapper (`app/src-tauri/`) with native Linux and Windows support.
* **Backend**: FastAPI sidecar (`alac_rip/server.py`) communicating with Tauri via ephemeral 256-bit stdin capability token (`X-Pies-Api-Token` & query token auth `?token=...`).
* **Downloader**: External Go binary (`apple-music-downloader`), deployed at `~/.local/share/pies-alac-rip/amd-main`.
* **Database State**: SQLite (`~/.local/share/pies-alac-rip/downloaded.db`), managed via `alac_rip/state.py`.
* **Audio Engine**: Range-capable local audio streaming (`/api/v1/stream?track_id=...`) supporting ALAC, FLAC, AAC, and MP3 with dynamic capability URLs.

---

## 2. Recent Implementation & Accomplishments

1. **Smart Dynamic Playlists Engine & Rule Builder UI (`v2.1 Feature 1`)**:
   - **Database Persistence**: Added `smart_playlists` table in `alac_rip/state.py` with CRUD methods (`create_smart_playlist`, `get_smart_playlists`, `get_smart_playlist`, `update_smart_playlist`, `delete_smart_playlist`).
   - **Evaluation Engine (`alac_rip/smart_playlists.py`)**: Multi-condition dynamic evaluator supporting `ALL` (AND) / `ANY` (OR) matching across `title`, `artist`, `album`, `playlist`, `format`, `downloaded_at`, and `local_path`, with operators (`equals`, `not_equals`, `contains`, `not_contains`, `starts_with`, `ends_with`, `regex`, `in_past_days`, `before_date`, `after_date`, `is_empty`, `is_not_empty`), sorting, and limits.
   - **REST API (`alac_rip/server.py`) & Client (`app/src/api.ts`)**: `GET /smart-playlists`, `POST /smart-playlists`, `GET /smart-playlists/{id}`, `PATCH /smart-playlists/{id}`, `DELETE /smart-playlists/{id}`, and `POST /smart-playlists/preview`.
   - **Modal Builder (`SmartPlaylistModal.svelte`)**: Rule generator with live debounced track preview, count badges, and dynamic condition inputs.
   - **Library Tab Integration (`Library.svelte`)**: Dedicated "⚡ Smart Playlists" tab with dual-pane layout, track list rendering via `VirtualTrackTable`, live query editing, deletion, and DAP export.
2. **Playlist Creator Workstation & AI Assistant (`PlaylistCreator.svelte`)**:
   - Dual-pane playlist studio with multi-select across Tracks, Albums, Artists, Existing Playlists, and **✨ AI Assistant**.
   - Gemini AI mix generator with prompt, target track count, and direct 1-click "Stage Mix" integration.
   - Native OS destination folder selection on `.m3u8` export using `saveDialog` from `@tauri-apps/plugin-dialog`.
3. **Audio Streaming & Lyrics Routing Refactor**:
   - Routes updated in `alac_rip/server.py` to support path converters and query parameters (`/api/v1/stream?track_id=...&token=...`, `/api/v1/tracks/lyrics?track_id=...`).
4. **Multi-Tier Resilient Lyrics Search & Karaoke Mode**:
   - 3-Tier LRCLIB fallback and Karaoke view mode with active line glow and auto-scrolling synced to `player.currentTime`.
5. **DAP Export Bit-Perfect Lossless Copy Mode**:
   - `format="original"` mode in `dap_export.py` using `shutil.copy2` for bit-perfect export without transcoding.

---

## 3. Verification Suite Results

All tests passing cleanly:
- `.venv/bin/pytest`: **283 passing tests** (10.82s).
- `cd app && npm run check`: **0 errors, 0 warnings**.
- `cd app && npm run build`: **Vite production build completed successfully**.
- `cd app/src-tauri && cargo test --locked`: **2 passing tests**.

---

## 4. Next Roadmap Objectives (v2.1+)

1. **Interactive Audio Waveform Visualizer**: Server-side peak downsampling / audio waveform extraction with Canvas scrubber.
2. **Batch Metadata Mass-Tagging & Cover Art Replacer**: Mutagen/FFmpeg atomic multi-track tag editor in Library.
