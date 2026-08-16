# Phase 6 Technical Specification: Performance, AI Intelligence, Media Ecosystem & Customization

## Goal
Implement Phase 6 of `pies-alac-rip-tool`, transforming the application into a high-performance, intelligent desktop music workstation:
1. **Virtual Windowing & 60fps Library Performance**: Implement virtual DOM row recycling in `Library.svelte` so libraries with 10,000+ tracks scroll and filter with zero lag.
2. **Visual Contrast Overhaul & Custom Wallpaper Engine**: Elevate theme presets to strict WCAG AAA contrast and support user wallpaper uploads with real-time blur and dimming sliders.
3. **Embedded Audio Mini-Player & Fallback Synchronized Lyrics**: Persistent bottom audio playback bar for local ALAC auditioning, plus automated fallback fetching for missing `.lrc` synchronized lyrics (via LRCLIB API).
4. **Media Server Integrations (Jellyfin, Navidrome) & DAP Hub**: Auto-refresh webhooks for Jellyfin/Navidrome upon sync completion, direct Library DAP export toolbar access, M3U8-only export, and a local download request inbox.
5. **Universal Playlist Importer (Match-and-Rip)**: Parse playlist share URLs and export files (Spotify, Tidal, Qobuz, CSV, M3U8), resolve track ISRCs/metadata against Apple Music, and download bit-perfect Lossless ALAC.
6. **Gemini AI Music Intelligence Engine**: Deep library taste profiling, natural-language playlist generation (e.g. "25-track late-night moody ambient synthwave mix"), and 1-click Apple Lossless ripping.

---

## Architectural Details & Components

### 1. UI Virtual Windowing & Performance (`app/src/lib/VirtualTrackTable.svelte` [NEW], `app/src/lib/Library.svelte`)
* **Problem**: Rendering thousands of rows and artwork thumbnails simultaneously causes DOM thrashing and high RAM consumption.
* **Architecture**:
  - Implement a lightweight Svelte 5 `$state`-driven virtual scrolling component (`VirtualTrackTable.svelte`).
  - Calculate total container height based on track count `tracks.length * rowHeight`.
  - Slice visible window `[startIndex, endIndex]` based on `scrollTop` with a 5-row buffer above/below.
  - Recycle table rows in real-time (< 1ms per frame).
  - Use `IntersectionObserver` for lazy loading cover art thumbnails.

---

### 2. Visual Contrast & Custom Wallpaper Engine (`app/src/lib/themes.ts`, `app/src/lib/Settings.svelte`, `app/src/app.css`)
* **Theme Contrast Enhancements**:
  - Refine color tokens in `themes.ts` to ensure all 10 presets meet WCAG AAA contrast (minimum 7:1 for normal text, 4.5:1 for large text).
  - Boost `--text-muted` from low opacity (`0.38`) up to readable high-contrast (`0.70`).
  - Ensure table borders, active tabs, and input focus outlines have crisp visual separation.
* **Custom Wallpaper Engine**:
  - Support uploading custom `.png`, `.jpg`, `.webp` background images stored in local state.
  - Add **Background Dimming Slider** (0% to 80% dark overlay) and **Glassmorphism Blur Slider** (0px to 20px).
  - Apply backdrop styling to the root desktop container in `+layout.svelte`.

---

### 3. Embedded Audio Mini-Player & Lyrics Engine (`alac_rip/server.py`, `alac_rip/lyrics.py`, `app/src/lib/PlayerBar.svelte` [NEW], `app/src/lib/LyricsModal.svelte`)
* **Local Audio Streaming Endpoint (`GET /api/v1/stream/{track_id}`)**:
  - Serves local `.m4a` / `.flac` files with HTTP range header support for instant seeking and low memory buffer overhead.
* **Player Bar Component (`PlayerBar.svelte` [NEW])**:
  - Global bottom bar: Play/Pause, Seek scrubber, Volume, Track Title, Artist, Album thumbnail, Quality badge (`ALAC 24/96`, `FLAC 16/44.1`).
  - Double-click any row in `Library.svelte` or `PlaylistDetail.svelte` to play.
  - Media Session API bindings for hardware keyboard media keys.
* **Synchronized Lyrics Fallback Fetcher (`alac_rip/lyrics.py` & `LyricsModal.svelte`)**:
  - First checks local `.lrc` and embedded tags.
  - If missing, queries [LRCLIB](https://lrclib.net/api/get) with track title, artist, album, and duration.
  - Saves retrieved synchronized `.lrc` alongside the audio file for persistent offline use.

---

### 4. Home Media Ecosystem & Archival Hub (`alac_rip/integrations.py` [NEW], `alac_rip/config.py`, `alac_rip/server.py`, `alac_rip/requests.py` [NEW])
* **Jellyfin & Navidrome Webhook Dispatcher**:
  - Configurable under `integrations:` in `config.yaml` and Settings UI:
    ```yaml
    integrations:
      jellyfin:
        enabled: true
        server_url: "http://192.168.1.100:8096"
        api_key: "your_key"
        auto_refresh: true
      navidrome:
        enabled: false
        server_url: "http://192.168.1.100:4533"
        user: "admin"
        token: "token"
        salt: "salt"
        auto_refresh: true
    ```
  - Upon sync completion, asynchronously triggers `POST /Library/Refresh` (Jellyfin) or `GET /rest/startScan.view` (Navidrome/Subsonic).
  - Includes a **"Test Connection"** button in Settings with live server status feedback.
* **DAP Toolbar Access**: Add direct "Export to DAP" action button in `Library.svelte` header toolbar.
* **Archival Download Request Inbox (`POST /api/v1/requests`)**:
  - Lightweight endpoint enabling LAN/household submission of playlist URLs or album links into a pending review queue.
* **M3U8 Generator Mode**: Generate portable playlist files referencing local library paths without re-downloading files.

---

### 5. Universal Playlist Matcher (`alac_rip/playlist_import.py` [NEW], `alac_rip/am_api.py`, `app/src/lib/PlaylistImportModal.svelte` [NEW])
* Ingests Spotify share links, Tidal URLs, Qobuz links, CSV, and M3U files.
* Resolves track metadata and ISRCs against Apple Music catalog API (`alac_rip/am_api.py`).
* Presents a visual match confirmation card with match percentages, allowing 1-click lossless ALAC batch downloading.

---

### 6. Gemini AI Music Intelligence Engine (`alac_rip/gemini_ai.py` [NEW], `alac_rip/server.py`, `app/src/lib/GeminiCurator.svelte` [NEW])
* **Configuration**: `gemini_api_key` stored in `config.yaml` (`0600` permissions) with masked input in Settings.
* **Library Taste Analysis**: Scans `downloaded.db` track metadata to profile user preferences.
* **Smart Playlist Generator**: Accepts natural-language prompts and returns structured playlist mixes with detailed musical rationale.
* **1-Click Lossless Ingestion**: Automatically resolves generated song recommendations to Apple Music catalog IDs for instant preview or ALAC ripping.

---

## Edge Cases, Invariants & Security Guardrails

1. **Security & API Key Isolation**:
   - `gemini_api_key` and Jellyfin tokens are stored with mode `0600` in `config.yaml` and never logged or exposed in client error payloads.
2. **Audio File Streaming Safety**:
   - `/api/v1/stream/{track_id}` strictly validates canonical file paths against configured music directory roots to prevent directory traversal.
3. **Graceful Network Degradation**:
   - If external services (Jellyfin, LRCLIB, Gemini, Spotify scraper) are unreachable or rate-limited, local ripping and playback continue without interruption.
4. **Zero Main-Thread Blocking**:
   - All external HTTP calls and AI queries execute asynchronously on background thread pools.

---

## Verification Plan

### Automated Tests
1. **Backend Integration Tests**:
   - `tests/test_virtual_stream.py`: Streaming range requests and security path boundary tests.
   - `tests/test_integrations.py`: Jellyfin and Navidrome webhook triggers and connection testing.
   - `tests/test_gemini_ai.py`: Gemini prompt construction, mock JSON response parsing, and Apple Music resolution.
   - `tests/test_playlist_import.py`: Spotify/Tidal/CSV parsing and ISRC matching.
   - `tests/test_lyrics_fallback.py`: LRCLIB fallback query and `.lrc` file persistence.
   - Full suite run: `.venv/bin/pytest` (target: 100% passing).
2. **Frontend Typechecks & Diagnostics**:
   - `cd app && npm run check` (target: 0 errors, 0 warnings).

### Manual Verification
1. **Virtual List**: Load 1,000+ tracks in Library and scroll rapidly; verify 60fps responsiveness and zero DOM bloat.
2. **Appearance & Background**: Upload custom wallpaper, adjust blur and dimming sliders; verify text remains high contrast and legible.
3. **Mini-Player**: Double-click a track; verify audio plays smoothly with seek controls and media keys.
4. **Lyrics**: Open a track without lyrics; verify LRCLIB automatically retrieves synchronized `.lrc`.
5. **Jellyfin / Navidrome**: Configure test URL; verify "Test Connection" returns green status and sync completion triggers refresh webhook.
6. **Gemini Curator**: Generate a thematic smart playlist via natural language prompt and queue matched tracks for download.

---

## Self-Contained Starter Prompt for Session 2 Implementer

```markdown
You are the AI Assistant implementing Phase 6 of pies-alac-rip-tool according to docs/agent-workflow.md and docs/plans/phase-6-spec.md.

Phase 6 Scope:
1. Virtual Windowing & 60fps Library Performance (app/src/lib/VirtualTrackTable.svelte, Library.svelte)
2. Visual Contrast Overhaul & Custom Wallpaper Engine (themes.ts, Settings.svelte, app.css)
3. Embedded Audio Mini-Player & LRCLIB Lyrics Fallback (alac_rip/server.py, alac_rip/lyrics.py, PlayerBar.svelte, LyricsModal.svelte)
4. Home Media Integrations (Jellyfin/Navidrome webhooks in alac_rip/integrations.py, DAP toolbar button in Library.svelte, M3U8 exporter, download request inbox)
5. Universal Playlist Matcher (Spotify/Tidal/Qobuz/CSV -> Apple Lossless ALAC in alac_rip/playlist_import.py, PlaylistImportModal.svelte)
6. Gemini AI Music Intelligence Engine (alac_rip/gemini_ai.py, GeminiCurator.svelte)

Tasks:
- Read docs/plans/phase-6-spec.md.
- Implement the backend and frontend components with comprehensive unit tests in tests/.
- Run `.venv/bin/pytest` and `cd app && npm run check` to verify all tests pass with zero diagnostics.
- Update HANDOFF.md with completed Phase 6 highlights and provide the Session 3 audit starter prompt.
```
