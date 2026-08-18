# Handoff — Pies Pear Music (`pies-alac-rip-tool`)

**Last Updated:** 2026-08-17  
**Current Branch:** `release/2` (Latest Commit: `a0673ca`)  
**Status:** Phases 1–6 Completed, Security Audited & Verified (274 passing backend tests, 0 Svelte diagnostics). Ready for **Phase 7: Full Library Manager Supercharged**.

---

## 1. Project Overview & Core Architecture
* **Frontend**: Svelte 5 (Runes `$state`, `$derived`, `$props`) / SvelteKit / Vite desktop interface (`app/src/lib/`).
* **Desktop Shell**: Tauri v2 desktop wrapper (`app/src-tauri/`) with native Linux and Windows support.
* **Backend**: FastAPI sidecar (`alac_rip/server.py`) communicating with Tauri via ephemeral 256-bit stdin capability token (`X-Pies-Api-Token` & query token auth).
* **Downloader**: External Go binary (`apple-music-downloader`), deployed at `~/.local/share/pies-alac-rip/amd-main`.
* **Database State**: SQLite (`~/.local/share/pies-alac-rip/downloaded.db`), managed via `alac_rip/state.py`.
* **Audio Engine**: Range-capable local audio streaming (`/api/v1/stream/{track_id}`) supporting ALAC, FLAC, AAC, and MP3.

---

## 2. Phase 7: Scope & Blueprint (Ready for Execution)

### Target Feature Set:

1. **Playlist Creator Tab (`PlaylistCreator.svelte`)**:
   - Split-pane creation workstation:
     - **Left Pane (Library Browser)**: Browse and multi-select by Tracks, Albums, Artists, and Existing Playlists. Real-time search and filter. Checkbox batch selection.
     - **Right Pane (Staged Playlist)**: Re-orderable tracklist with duration/size calculations, drag reordering, and duplicate detection.
     - **Actions**: Save to Library, Export M3U8, or 1-Click Sync/Download unripped tracks.
2. **Playlist Duplicate Engine & Cleanup**:
   - Add **"Check Duplicates"** button to all playlist views (`PlaylistDetail.svelte`).
   - Modal prompt: "Remove Duplicates (Keep First)" vs "Keep All".
   - Backend endpoint: `POST /playlists/{name}/deduplicate`.
3. **Audio Player Authentication & Port Fix**:
   - Update `player.svelte.ts` to fetch authenticated dynamic stream URLs via `api.getStreamUrl(trackId)`.
   - Update `require_api_capability` middleware in `server.py` to accept capability tokens via query parameter `?token=...` for native HTML5 `<audio>` playback.
4. **Multi-Tier Resilient Lyrics Search & Karaoke Mode**:
   - 3-Tier LRCLIB fallback in `lyrics.py`: Strict `/api/get` $\rightarrow$ Relaxed tag query $\rightarrow$ Full `/api/search?q={artist} {title}`.
   - **Karaoke View** in `LyricsModal.svelte`: Synchronized line highlighting with real-time playback position, glowing current lyric line, dim past lines, and auto-scrolling.
   - **Strawberry Player MPRIS Support**: Query `org.mpris.MediaPlayer2.strawberry` to track playback position from external Strawberry sessions.
5. **Configurable Dashboard & Integration Health Status**:
   - Live Integration Health Card on Dashboard (`Dashboard.svelte`) showing connection status for Gemini AI, Last.fm, Jellyfin, Navidrome, and Strawberry.
   - Widget Customizer: Toggle card visibility (Stats, Integration Health, Quick Mixes, Sync History, Graveyard Alerts).
6. **Last.fm Shared Secret & Secure Settings Display**:
   - Add `lastfm_shared_secret` and `lastfm_username` to `Config`, `lastfm_api.py`, and `Settings.svelte`.
   - Stored credentials display bullet dots (`••••••••••••••••••••••••••••••••`) and a "Stored Securely" badge.
7. **Streaming Service Discovery**:
   - Promote **"Streaming Import"** (Universal Matcher for Spotify/Tidal/Qobuz/CSV/M3U8) directly to the main Sidebar navigation.
   - Redesign Data & Recs into **"Music Intelligence"** with a direct toggle between **✨ Gemini AI** and **📻 Last.fm Profile**.
8. **DAP Export Uncompressed Mode**:
   - Add **"Original Lossless (Bit-Perfect Copy / No Transcoding)"** to `dap_export.py` and `DapExportModal.svelte`.
9. **UI Contrast & Column Truncation Overhaul**:
   - Fix Cherry/Wine and dark theme contrast to meet WCAG AAA guidelines.
   - Refactor track table grid layout with `min-w-0` and `truncate` to prevent long titles from overlapping adjacent columns.

---

## 3. Key Files & Structure for Phase 7

| Area | Primary Files |
|---|---|
| **Audio & Player** | [`alac_rip/server.py`](file:///var/home/ilikepie/Documents/VS-Projects/pies-alac-rip-tool/alac_rip/server.py), [`app/src/lib/player.svelte.ts`](file:///var/home/ilikepie/Documents/VS-Projects/pies-alac-rip-tool/app/src/lib/player.svelte.ts), [`app/src/lib/PlayerBar.svelte`](file:///var/home/ilikepie/Documents/VS-Projects/pies-alac-rip-tool/app/src/lib/PlayerBar.svelte) |
| **Lyrics & Karaoke** | [`alac_rip/lyrics.py`](file:///var/home/ilikepie/Documents/VS-Projects/pies-alac-rip-tool/alac_rip/lyrics.py), [`app/src/lib/LyricsModal.svelte`](file:///var/home/ilikepie/Documents/VS-Projects/pies-alac-rip-tool/app/src/lib/LyricsModal.svelte) |
| **Playlist Creator & Deduplication** | [`app/src/lib/PlaylistCreator.svelte`](file:///var/home/ilikepie/Documents/VS-Projects/pies-alac-rip-tool/app/src/lib/PlaylistCreator.svelte), [`app/src/lib/PlaylistDetail.svelte`](file:///var/home/ilikepie/Documents/VS-Projects/pies-alac-rip-tool/app/src/lib/PlaylistDetail.svelte), [`alac_rip/state.py`](file:///var/home/ilikepie/Documents/VS-Projects/pies-alac-rip-tool/alac_rip/state.py) |
| **Dashboard & Settings** | [`app/src/lib/Dashboard.svelte`](file:///var/home/ilikepie/Documents/VS-Projects/pies-alac-rip-tool/app/src/lib/Dashboard.svelte), [`app/src/lib/Settings.svelte`](file:///var/home/ilikepie/Documents/VS-Projects/pies-alac-rip-tool/app/src/lib/Settings.svelte), [`alac_rip/config.py`](file:///var/home/ilikepie/Documents/VS-Projects/pies-alac-rip-tool/alac_rip/config.py), [`alac_rip/lastfm_api.py`](file:///var/home/ilikepie/Documents/VS-Projects/pies-alac-rip-tool/alac_rip/lastfm_api.py) |
| **DAP Export & Streaming Import** | [`alac_rip/dap_export.py`](file:///var/home/ilikepie/Documents/VS-Projects/pies-alac-rip-tool/alac_rip/dap_export.py), [`app/src/lib/DapExportModal.svelte`](file:///var/home/ilikepie/Documents/VS-Projects/pies-alac-rip-tool/app/src/lib/DapExportModal.svelte), [`app/src/lib/Sidebar.svelte`](file:///var/home/ilikepie/Documents/VS-Projects/pies-alac-rip-tool/app/src/lib/Sidebar.svelte) |
| **Theme & Tables** | [`app/src/lib/themes.ts`](file:///var/home/ilikepie/Documents/VS-Projects/pies-alac-rip-tool/app/src/lib/themes.ts), [`app/src/lib/VirtualTrackTable.svelte`](file:///var/home/ilikepie/Documents/VS-Projects/pies-alac-rip-tool/app/src/lib/VirtualTrackTable.svelte), [`app/src/app.css`](file:///var/home/ilikepie/Documents/VS-Projects/pies-alac-rip-tool/app/src/app.css) |

---

## 4. Verification Commands

```bash
# Backend pytest suite
.venv/bin/pytest

# Svelte diagnostic check
cd app && npm run check

# Vite static production build
cd app && npm run build

# Tauri Rust native tests
cd app/src-tauri && cargo test --locked
```
