# UI Reskin Design

## Goal

Overhaul the visual design of the desktop app to a warm editorial aesthetic — amber/gold on near-black — with album artwork prominently displayed throughout.

## Visual Language

| Token | Value |
|---|---|
| Background | `#12100e` |
| Surface (sidebar, cards) | `rgba(255,255,255,0.03)` |
| Border | `rgba(255,255,255,0.06)` |
| Accent | `#f59e0b` (amber) |
| Accent hover | `#fbbf24` |
| Accent dim | `rgba(245,158,11,0.12)` |
| Text primary | `#ffffff` |
| Text secondary | `rgba(255,255,255,0.5)` |
| Text muted | `rgba(255,255,255,0.25)` |
| Active nav indicator | 2px left border, `#f59e0b` |

All existing Spotify-green (`#1db954`) references replaced with amber.

## Artwork Storage

Album artwork URLs are already returned by `fetch_public_playlist_tracks` in `attributes.artwork.url` (a template string with `{w}x{h}` placeholders). These are not currently stored.

**Change:** Add `artwork_url TEXT` column to the `tracks` table in `downloaded.db`. Populate it during the pre-flight sync when processing playlist tracks. Serve it via the existing tracks API response.

**URL resolution:** Replace `{w}x{h}` with the required size at render time in the frontend — e.g. `40x40bb` for track rows, `300x300bb` for mosaic headers. No backend resizing needed.

## Components

### Sidebar (`Sidebar.svelte`)

- Background: `#12100e`, border-right: `rgba(255,255,255,0.06)`
- App title amber, no subtitle
- Nav items: active state = amber left border + `rgba(245,158,11,0.12)` background
- Playlist list: each entry shows an 18×18px artwork thumbnail (from `artwork_url` of the first track in the playlist, fetched via existing API). Fallback: `#1e1e1e` square.
- "Add playlist" button: amber text
- Sync All button: amber background, black text
- Connection indicator: unchanged

### Playlist Detail (`PlaylistDetail.svelte`)

**Header:**
- 2×2 mosaic of the first four distinct album art thumbnails from the playlist (64×64 total, each quadrant 32×32, `object-fit: cover`). Fallback quadrants: `#1e1e1e`.
- Beside mosaic: playlist name (large, bold white), track count + last synced (muted), amber Sync button.

**Track rows:**
- 28×28px artwork thumbnail, border-radius 4px. Fallback: `#1e1e1e` square.
- Title (white), artist (muted), right-aligned status: amber `✓` for downloaded, amber-bordered `new` badge for new tracks.
- Hover: `rgba(245,158,11,0.05)` background.
- Active/selected: `rgba(245,158,11,0.07)` background.

### All other screens

Reskin to amber/gold system colours with no structural changes:
- `Dashboard.svelte` — amber accents, connection status dot colours unchanged
- `Settings.svelte` — amber focus rings, amber save button
- `Download.svelte` — amber progress, amber action buttons
- `SyncProgress.svelte` — amber timeline steps, amber progress bar
- `Diagnostics.svelte` — amber section headings
- `SetupWizard.svelte` — amber step indicators, amber continue buttons

### `app.css`

Add CSS custom properties for the token set above so all components reference variables rather than hardcoded hex values.

## Data Flow

1. `fetch_public_playlist_tracks` returns `attributes.artwork.url` per track
2. Pre-flight stores it in `tracks.artwork_url` via `StateManager.update_track_artwork` (new method, upsert on `am_track_id`)
3. Backend exposes `artwork_url` in the tracks list API response
4. Frontend constructs sized URLs client-side: `artworkUrl.replace('{w}x{h}', '40x40bb')`

## Error Handling

- Missing artwork URL: render `#1e1e1e` placeholder square, no broken image icon
- Failed image load (`onerror`): swap to placeholder square
- Mosaic with fewer than 4 tracks: fill remaining quadrants with placeholder

## Testing

- Visual: start dev server, verify all screens render correctly in amber theme
- Artwork: verify thumbnails appear in sidebar and playlist detail after a sync
- Fallback: verify placeholder renders for tracks without artwork
- Regression: all 113 existing tests must continue to pass (no backend logic changed beyond `artwork_url` storage)
