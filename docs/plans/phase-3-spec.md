# Phase 3 Technical Specification: UI Workstation Features (DAP Export, Lyrics Viewer & Preservation Graveyard)

## Goal
Implement Phase 3 of the Archival Music Workstation roadmap, connecting the Phase 1 & Phase 2 backend engines into the desktop UI:
1. **DAP Export Modal & Workflow**: UI for exporting / transcoding playlists to Opus/AAC on external drives or microSD cards with progress and feedback.
2. **Streaming Graveyard & Preservation Hub**: Dedicated view in the UI showing tracks delisted upstream on Apple Music that were preserved locally.
3. **Lyrics Status & Viewer**: Visual indicator for tracks with `.lrc` / embedded lyrics and a slide-out / modal synced lyrics reader.
4. **Fidelity & Diagnostic Indicators**: Surface `flac` stream integrity status and audio format details in Diagnostics and track rows.

---

## Architectural Details & Components

### 1. DAP / Portable Player Export UI (`app/src/lib/DapExportModal.svelte` & `PlaylistDetail.svelte`)
* **Component**: `DapExportModal.svelte`
  - Inputs:
    - Target directory selector / text input (e.g., `/run/media/$USER/DAP_SD`).
    - Format selector (`Opus (160 kbps)` vs `AAC (256 kbps)`).
    - Bitrate override option.
  - Action: Calls `POST /export/dap` via `api.ts`.
  - Displays real-time progress state or transcode completion metrics (`exported_count`, `skipped_count`, `errors`).
* **Integration**: Added to `PlaylistDetail.svelte` actions toolbar ("Export to DAP / Device").

### 2. Streaming Graveyard & Digital Preservation View (`app/src/lib/StreamingGraveyard.svelte`)
* **Component**: `StreamingGraveyard.svelte`
  - Fetches from `GET /streaming-graveyard`.
  - Displays list of delisted/removed Apple Music tracks with delist timestamp, original playlist, artist, and album.
  - Shows preservation badge: `"Preserved Locally in FLAC"`.
  - Allows revealing local file in system file manager (`POST /reveal-track`).
* **Integration**: Added as a section / view accessible from `Sidebar.svelte` and `Home.svelte`.

### 3. Lyrics Viewer & Track Indicators (`app/src/lib/LyricsModal.svelte` & `PlaylistDetail.svelte`)
* **Component**: `LyricsModal.svelte`
  - Opens when clicking the lyrics badge/icon on a track row.
  - Fetches lyrics from API or displays local LRC line-by-line with timestamps.
* **Track Row Enhancement**:
  - Adds small badge/indicator icon for tracks containing synced lyrics (`.lrc`).

### 4. API Client Updates (`app/src/api.ts`)
* Add client methods:
  - `exportDap(playlistName: string, targetDir: string, format: string, bitrate?: string)`
  - `getStreamingGraveyard()`
  - `getTrackLyrics(trackId: string)`

---

## Verification Plan

### Automated Checks
* Frontend typechecking and diagnostics:
  ```bash
  cd app && npm run check
  ```
* Backend regression tests:
  ```bash
  .venv/bin/pytest
  ```

### Manual Verification Flow
1. Open a playlist in the UI -> Click "Export to DAP" -> Verify modal parameters and submission.
2. Navigate to "Streaming Graveyard" -> Verify listing of preserved delisted tracks.
3. Open track with lyrics -> Verify lyrics modal rendering.
