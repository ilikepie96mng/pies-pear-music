# One-Off Download Feature Design

**Date:** 2026-04-18
**Status:** Approved

## Problem

The app is playlist-centric — you can't download an album or individual song without creating a named playlist. The user wants a fire-and-forget download flow: paste an Apple Music URL (album or song), it downloads and organizes to `Artist/Album/`, done.

## Scope

- New "Download" sidebar section with its own page
- Accepts any Apple Music URL (album, song, playlist)
- Downloads and organizes files to `music_dir/Artist/Album/` with no playlist association
- Live streaming log output during download and organize phases
- Library view integration is out of scope (future release)

## Data Flow

```
User pastes URL → POST /download/one-off → SSE stream opens
  Phase 1 (downloading): Go downloader runs, log lines stream to client
  Phase 2 (organizing):  SyncEngine walks output dir, copies files to
                         music_dir/Artist/Album/, records in tracks DB
                         (no playlist association, no M3U8 written)
  Phase 3 (done/error):  SSE sends final event, stream closes
```

## Backend Changes

### `alac_rip/sync.py` — optional playlist mode

Make `playlist_name` optional (`str | None`). When `None`:
- Skip `add_track_to_playlist()`
- Skip `_write_m3u8()`
- Everything else runs normally: tag-read, copy to `music_dir/Artist/Album/`, record in tracks DB (dedup still works for future playlist syncs that include the same track)

### `alac_rip/server.py` — new endpoint

`POST /download/one-off` — body: `{url: str, format: str = "ALAC"}`

Behavior:
1. Validate wrapper is running, no download already in progress
2. Start Go downloader subprocess (same logic as existing `/download`)
3. Stream downloader stdout as SSE `{status: "running", phase: "downloading", message: "..."}` events
4. On downloader exit:
   - If non-zero exit code → send `{status: "error", message: "..."}` and close
   - If success → enter phase 2
5. Run `SyncEngine` with `playlist_name=None` on the downloader's output directory — read from `alac-save-folder` (or `aac-save-folder` / `atmos-save-folder` depending on format) in `apple-music-downloader/config.yaml`. This is `/home/ilikepie/Music/Music Staging` in the current config, distinct from `cfg.staging_dir`. SyncEngine's dedup (`is_downloaded`) skips files already recorded in the DB, so walking the full save folder is safe.
6. Stream organize log lines as SSE `{status: "running", phase: "organizing", message: "..."}`
7. On completion → send `{status: "done", new: N, skipped: N, errors: N}` and close

Existing `/download` and `/download/logs` endpoints are unchanged.

### SSE event schema

```json
// running
{"status": "running", "phase": "downloading|organizing", "message": "..."}

// done
{"status": "done", "new": 3, "skipped": 0, "errors": 0}

// error
{"status": "error", "message": "..."}
```

## Frontend Changes

### `Sidebar.svelte`

Add a "Download" nav item after the Playlists section, using the same styling as existing items.

### `Download.svelte` (new page)

Three states:

**Idle**
- URL text input
- Format selector: ALAC (default) / AAC / ATMOS
- Download button
- No log output shown

**Running**
- URL input and button disabled
- Phase label: "Downloading…" or "Organizing…" (updates as SSE phase changes)
- Scrolling log output (`<pre>` block, same pattern as SyncProgress)

**Done / Error**
- Input re-enables
- Summary line: "Downloaded successfully — 3 new tracks" or error message in red
- Log output remains visible
- User can start another download immediately

No cancel button in this release.

### `api.ts`

Add `downloadOneOff(url: string, format: string): string` that returns the SSE endpoint URL (same pattern as `syncPlaylistUrl`).

## Out of Scope

- Cancel/stop mid-download
- Download history persistence across sessions
- Library page showing one-off downloads
- Multiple concurrent downloads
