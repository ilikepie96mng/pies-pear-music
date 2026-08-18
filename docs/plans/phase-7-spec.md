# Phase 7 Polish Specification: Audio Stream & Lyrics URL Hardening, Merged AI Creator, Native M3U8 Dialog, High-Contrast UI & SVG Icon Suite

**Target Branch:** `release/2`  
**Protocol:** Follow [`docs/agent-workflow.md`](file:///var/home/ilikepie/Documents/VS-Projects/pies-alac-rip-tool/docs/agent-workflow.md) Session 2 (Implementation & Verification).

---

## 1. Root Cause Analysis & Requirements

### A. Audio Stream & Lyrics "Not Found" 404 Bug
- **Bug**: `track_id` in database contains slashes (`Apple Music/Liked Songs/Way 2 U.flac`). When queried as `/tracks/{track_id}/lyrics` or `/api/v1/stream/{track_id}`, Starlette's standard string path converter treats `/` as path separators and returns `404 Not Found`.
- **Fix**:
  1. In `alac_rip/server.py`, change routes to `{track_id:path}` AND add query param endpoints:
     - `@app.get("/tracks/{track_id:path}/lyrics")`
     - `@app.get("/api/v1/tracks/lyrics")` (accepts `?track_id=...`)
     - `@app.get("/api/v1/stream/{track_id:path}")`
     - `@app.get("/api/v1/stream")` (accepts `?track_id=...&token=...`)
     - `@app.get("/stream/{track_id:path}")`
  2. In `app/src/api.ts`, update `getStreamUrl` and `getTrackLyrics` to query via `?track_id=${encodeURIComponent(trackId)}`.

---

### B. Merge AI Playlist Creator into Playlist Creator Workstation
- In `app/src/lib/PlaylistCreator.svelte`:
  - Add an **`✨ AI Assistant`** tab alongside `Tracks`, `Albums`, `Artists`, `Playlists`.
  - Let users enter natural language prompt + song count + mood presets.
  - Generates mix via Gemini and stages tracks directly into the right workstation pane.

---

### C. Native M3U8 File Save Dialog
- In `PlaylistCreator.svelte` and `PlaylistDetail.svelte`:
  - Use `saveDialog` from `@tauri-apps/plugin-dialog` to let user pick custom save location or 1-click save to the default `Playlists/` directory.

---

### D. High-Contrast Theme & Cohesive SVG Icon System
- In `themes.ts`, `Library.svelte`, `PlayerBar.svelte`, `Sidebar.svelte`:
  - Fix tab button contrast: replace bright neon green with dark text on warm gold/amber (`bg-amber-400 text-black font-bold`).
  - Standardize all icons to clean SVG icons instead of mismatched emojis.

---

## 2. Verification Commands

```bash
.venv/bin/pytest
cd app && npm run check
cd app && npm run build
cd app/src-tauri && cargo test --locked
```
