# Handoff — Pies Pear Music (`pies-alac-rip-tool`)

**Last Updated:** 2026-08-17  
**Current Branch:** `release/2`  
**Latest Commit:** `e4eda4d` (`feat(phase7): finalize playlist creator studio, audio routing, and UI contrast polish`)  
**Status:** Phases 1–7 Completed, Fully Implemented, Security Audited & Verified (277 passing backend tests, 0 Svelte errors, full Vite production build, 2 passing Cargo tests). Ready for Release Merge / Package Distribution.

---

## 1. Project Overview & Core Architecture
* **Frontend**: Svelte 5 (Runes `$state`, `$derived`, `$props`, `$effect`) / SvelteKit / Vite desktop interface (`app/src/lib/`).
* **Desktop Shell**: Tauri v2 desktop wrapper (`app/src-tauri/`) with native Linux and Windows support.
* **Backend**: FastAPI sidecar (`alac_rip/server.py`) communicating with Tauri via ephemeral 256-bit stdin capability token (`X-Pies-Api-Token` & query token auth `?token=...`).
* **Downloader**: External Go binary (`apple-music-downloader`), deployed at `~/.local/share/pies-alac-rip/amd-main`.
* **Database State**: SQLite (`~/.local/share/pies-alac-rip/downloaded.db`), managed via `alac_rip/state.py`.
* **Audio Engine**: Range-capable local audio streaming (`/api/v1/stream?track_id=...`) supporting ALAC, FLAC, AAC, and MP3 with dynamic capability URLs.

---

## 2. Phase Accomplishments & Completed Features

1. **Playlist Creator Workstation & AI Assistant (`PlaylistCreator.svelte`)**:
   - Dual-pane playlist studio with multi-select across Tracks, Albums, Artists, Existing Playlists, and **✨ AI Assistant**.
   - Gemini AI mix generator with prompt, target track count, and direct 1-click "Stage Mix" integration.
   - Native OS destination folder selection on `.m3u8` export using `saveDialog` from `@tauri-apps/plugin-dialog`.
   - Batch selection with "Skip Duplicates & Add", track re-ordering (↑ / ↓ / ✕), estimated duration & size, and Save to Library via `api.saveGeminiPlaylist`.
2. **Audio Streaming & Lyrics Routing Refactor**:
   - Routes updated in `alac_rip/server.py` to support path converters and query parameters (`{track_id:path}`, `/api/v1/tracks/lyrics?track_id=...`, `/api/v1/stream?track_id=...&token=...`).
   - Dynamic URL generation in `app/src/api.ts` utilizing `?track_id=...` parameters to prevent slash-encoding 404s.
3. **Playlist Duplicate Engine & Cleanup**:
   - Backend `GET /playlists/{name}/duplicates` & `POST /playlists/{name}/deduplicate` in `server.py` and `state.py`.
   - "🔍 Check Duplicates" modal in `PlaylistDetail.svelte` with track preview, count badges, and 1-click duplicate removal (keeping the first occurrence).
4. **Multi-Tier Resilient Lyrics Search & Real-Time Karaoke Mode**:
   - 3-Tier LRCLIB fallback in `lyrics.py` (strict metadata $\rightarrow$ tag query $\rightarrow$ fuzzy search `/api/search`).
   - Real-time Karaoke view mode in `LyricsModal.svelte` with active line glow, past line dimming, and smooth auto-scrolling synced to `player.currentTime`.
5. **Configurable Dashboard & Live Integration Health Status**:
   - `GET /system/integrations-health` endpoint reporting real-time status of Gemini AI, Last.fm, Jellyfin, Navidrome, and Strawberry.
   - Configurable widget card visibility in `Dashboard.svelte` persisted to `localStorage`.
6. **Last.fm Shared Secret & Secure Settings Display**:
   - Added `lastfm_shared_secret` and `lastfm_username` to `Config` with 0600 file protection.
   - Stored credentials rendered with masked bullet dots (`••••••••••••••••••••••••••••••••`) and green "✓ Stored Securely" badge.
7. **Streaming Service Discovery & Intelligence Controls**:
   - Direct sidebar navigation items for "🔀 Playlist Creator" and "⚡ Streaming Import".
   - Music Intelligence engine selector in `DataControls.svelte` (✨ Gemini AI vs 📻 Last.fm Scrobble Graph).
8. **DAP Export Bit-Perfect Lossless Copy Mode**:
   - Added `format="original"` mode in `dap_export.py` using `shutil.copy2` for bit-perfect export without transcoding.
   - 3-column codec selector in `DapExportModal.svelte` (Opus, AAC, Original Lossless).
9. **UI Contrast & Column Truncation Overhaul**:
   - High-contrast button styles (`bg-amber-400 text-black font-bold`) across `PlaylistCreator.svelte`, `Library.svelte`, and `Sidebar.svelte`.
   - Table columns styled with `min-w-0` and `truncate` to guarantee robust layout across all window sizes.

---

## 3. Verification Suite Results

All tests passing cleanly:
- `.venv/bin/pytest`: **277 passing tests** (12.05s).
- `cd app && npm run check`: **0 errors, 0 warnings**.
- `cd app && npm run build`: **Vite production build completed successfully**.
- `cd app/src-tauri && cargo test --locked`: **2 passing tests**.

---

## 4. Approved Future Roadmap (v2.1+)

1. **Smart Dynamic Playlists**: Rule-based dynamic auto-evaluating queries saved in SQLite with live filters.
2. **Interactive Audio Waveform Visualizer**: Server-side peak downsampling with Canvas scrubber.
3. **Batch Metadata Mass-Tagging & Cover Art Replacer**: Mutagen/FFmpeg atomic multi-track tag editor in Library.
