# Phase 7 Specification: Library Manager Supercharged & Music Intelligence Suite

**Target Branch:** `release/2`  
**Protocol:** Follow [`docs/agent-workflow.md`](file:///var/home/ilikepie/Documents/VS-Projects/pies-alac-rip-tool/docs/agent-workflow.md) Session 2 (Implementation & Verification).

---

## 1. Executive Summary & Goals

Transform Pies Pear Music into a complete standalone music workstation and library manager. This phase implements:
1. **Playlist Creator Tab (`PlaylistCreator.svelte`)**: Dual-pane workstation with multi-select across tracks, albums, artists, and existing playlists; duplicate warnings; drag-to-reorder; instant Save/Export/Sync.
2. **Playlist Duplicate Engine**: Duplicate check & 1-click cleanup on all playlist screens (`PlaylistDetail.svelte`).
3. **Audio Player Authentication & Port Fix**: Dynamic stream URL generation via `api.getStreamUrl(trackId)` and capability query-token auth in `require_api_capability` middleware.
4. **Resilient Lyrics & Real-Time Karaoke Mode**: 3-Tier LRCLIB fallback (`/api/get` -> clean query -> `/api/search`) and real-time synchronized line highlighting + auto-scroll in `LyricsModal.svelte` (with optional Strawberry MPRIS bridge).
5. **Configurable Dashboard & Integration Health**: Live connection status indicators for Gemini AI, Last.fm, Jellyfin, Navidrome, and Strawberry; customizable widget cards in `Dashboard.svelte`.
6. **Last.fm Shared Secret & Secure Settings**: Last.fm shared secret & username support; bullet dots (`••••••••`) for stored API keys in `Settings.svelte`.
7. **Streaming Import Discovery**: Direct sidebar navigation item for "Streaming Import" (Universal Matcher) and Gemini vs Last.fm intelligence toggle in `DataControls.svelte`.
8. **DAP Export Uncompressed Mode**: Bit-perfect lossless copy mode in `dap_export.py` and `DapExportModal.svelte`.
9. **UI Contrast & Column Truncation Overhaul**: WCAG AAA theme contrast and strict grid column layout with `min-w-0` / `truncate` to prevent text overlap.

---

## 2. File-by-File Technical Implementation Details

### A. Audio Player & Streaming (`alac_rip/server.py` & `app/src/lib/player.svelte.ts`)
1. In `alac_rip/server.py`:
   - Update `require_api_capability` middleware:
     ```python
     if request.method != "OPTIONS" and _api_capability:
         supplied = request.headers.get(_API_CAPABILITY_HEADER) or request.query_params.get("token")
         if not supplied or not secrets.compare_digest(supplied, _api_capability):
             return Response(status_code=401)
     ```
2. In `app/src/api.ts`:
   - Add helper:
     ```typescript
     async getStreamUrl(trackId: string): Promise<string> {
       const conn = await getConnection();
       return `http://127.0.0.1:${conn.port}/api/v1/stream/${encodeURIComponent(trackId)}?token=${encodeURIComponent(conn.capability)}`;
     }
     ```
3. In `app/src/lib/player.svelte.ts`:
   - In `playTrack(track)`, set `this.audioElement.src = await api.getStreamUrl(track.track_id)`.

---

### B. Multi-Tier Lyrics & Karaoke Engine (`alac_rip/lyrics.py` & `app/src/lib/LyricsModal.svelte`)
1. In `alac_rip/lyrics.py`:
   - Update `fetch_lrclib_lyrics`:
     - Step 1: Query `/api/get` with track, artist, album, duration.
     - Step 2: If 404, query `/api/get` without album/duration.
     - Step 3: If 404, query `https://lrclib.net/api/search?q={urllib.parse.quote(f"{artist_name} {track_title}")}` and return the best match with `syncedLyrics` or `plainLyrics`.
2. In `app/src/lib/LyricsModal.svelte`:
   - Add Karaoke Mode toggle button.
   - When Karaoke mode is active and audio is playing (via `player.currentTime`), calculate the active line index based on timestamps.
   - Apply active glowing style (`font-weight: bold; color: var(--accent); transform: scale(1.04); transition: all 0.2s ease;`) to the current line and smoothly auto-scroll into view (`element.scrollIntoView({ behavior: 'smooth', block: 'center' })`).

---

### C. Playlist Creator (`app/src/lib/PlaylistCreator.svelte` & `alac_rip/server.py`)
1. Create `app/src/lib/PlaylistCreator.svelte`:
   - Left Pane: Library Catalog Browser with tabs `[Tracks]`, `[Albums]`, `[Artists]`, `[Playlists]`.
     - Filter input and multi-select checkboxes.
     - "Add Selected (N tracks)" button.
   - Right Pane: Staged Playlist Tracklist.
     - Displays staged songs in order with drag handles or up/down buttons.
     - Displays summary bar: Total Tracks, Total Duration, Estimated Size.
     - Duplicate Detection: When adding songs that are already in the staged list, show duplicate warning badge and prompt "2 songs already in playlist: [Skip Duplicates] [Add Anyway]".
     - Top Action Bar:
       - Input for Playlist Name & Description.
       - `💾 Save to Library`: Calls `api.addPlaylist` and links tracks.
       - `⬇️ Export M3U8`: Generates `.m3u8` file download.
       - `🔄 Sync Unripped Tracks`: Queues tracks for download.
2. In `alac_rip/server.py` & `alac_rip/state.py`:
   - Add `POST /playlists/{name}/deduplicate`: removes duplicate track IDs from `playlist_tracks` preserving the first occurrence.
   - Add `GET /playlists/{name}/duplicates`: returns list of duplicate tracks in the playlist.
3. In `app/src/lib/PlaylistDetail.svelte`:
   - Add a `🔍 Check Duplicates` button in the action toolbar.
   - Shows modal with count and list of duplicates, offering "Remove Duplicates (Keep First)" or "Keep All".

---

### D. Configurable Dashboard & Integration Health (`app/src/lib/Dashboard.svelte` & `alac_rip/server.py`)
1. In `alac_rip/server.py`:
   - Add `GET /system/integrations-health`:
     ```python
     @app.get("/system/integrations-health")
     def get_integrations_health():
         return {
             "gemini": bool(cfg.gemini_api_key) if cfg else False,
             "lastfm": bool(cfg.lastfm_api_key) if cfg else False,
             "jellyfin": bool(cfg.integrations.get("jellyfin", {}).get("enabled") and cfg.integrations.get("jellyfin", {}).get("api_key")) if cfg else False,
             "navidrome": bool(cfg.integrations.get("navidrome", {}).get("enabled") and cfg.integrations.get("navidrome", {}).get("token")) if cfg else False,
             "strawberry": bool(strawberry_sync.find_strawberry_db() is not None),
         }
     ```
2. In `app/src/lib/Dashboard.svelte`:
   - Add **Integration Health Widget** with status badges and 1-click links to Settings.
   - Add **Widget Visibility Toggles** (stored in `localStorage`): Stats Overview, Integrations Health, Quick Actions, Sync Runs, Graveyard Alerts.

---

### E. Last.fm Shared Secret & Secure Settings Masking (`alac_rip/config.py`, `lastfm_api.py`, `Settings.svelte`)
1. In `alac_rip/config.py`:
   - Add `lastfm_shared_secret: Optional[str] = None` and `lastfm_username: Optional[str] = None` to `Config` dataclass and validation schema.
2. In `alac_rip/server.py`:
   - Add `lastfm_shared_secret` to `_CONFIG_OMIT`.
3. In `app/src/lib/Settings.svelte`:
   - Add inputs for Last.fm API Key, Shared Secret, and Username.
   - For all stored API keys (Gemini, Last.fm, Jellyfin, Navidrome), if the backend returns `configured: true` or masked data, display bullet dots (`••••••••••••••••••••••••••••••••`) with a green "Stored Securely" indicator.

---

### F. Streaming Service Discovery (`app/src/lib/Sidebar.svelte` & `app/src/lib/DataControls.svelte`)
1. In `app/src/lib/Sidebar.svelte`:
   - Add primary navigation links:
     - `🔀 Playlist Creator` -> `onopenPlaylistCreator`
     - `⚡ Streaming Import` -> `onopenStreamingImport` (Universal Matcher)
2. In `app/src/lib/DataControls.svelte`:
   - Rebrand to **"Music Intelligence & Recommendations"**.
   - Add clear tab/toggle: **Recommendation Engine: [✨ Google Gemini AI] vs [📻 Last.fm Profile]**.
   - Add interactive "Generate Recommendations Now" button.

---

### G. DAP Export Uncompressed Mode (`alac_rip/dap_export.py` & `app/src/lib/DapExportModal.svelte`)
1. In `alac_rip/dap_export.py`:
   - Support `format="copy"` / `"original"`.
   - When `"original"`, copy source `.flac` / `.m4a` files directly into target directory with `shutil.copy2` instead of transcoding via ffmpeg.
2. In `app/src/lib/DapExportModal.svelte`:
   - Add radio option: **"Original Lossless (Bit-Perfect Copy / No Transcoding)"**.

---

### H. UI Contrast & Table Column Truncation (`app/src/lib/themes.ts` & `app/src/lib/VirtualTrackTable.svelte`)
1. In `app/src/lib/themes.ts` & `app/src/app.css`:
   - Elevate secondary text contrast across Cherry/Wine and Dark themes (`--text-secondary: #d4d4d8;`).
   - Ensure all `<select>` and `<option>` controls use `color-scheme: dark;` and explicit dark background.
2. In `app/src/lib/VirtualTrackTable.svelte` & `app/src/lib/Library.svelte`:
   - Use fixed grid layout: `grid-template-columns: 40px minmax(0, 1.8fr) minmax(0, 1.2fr) 110px 90px;` with `min-w-0` and `truncate` on every text container to eliminate column overlap.

---

## 3. Verification Commands for Session 2

```bash
# 1. Run all backend unit & security tests
.venv/bin/pytest

# 2. Run Svelte diagnostics & typecheck
cd app && npm run check

# 3. Run production build
cd app && npm run build

# 4. Run native Rust tests
cd app/src-tauri && cargo test --locked
```
