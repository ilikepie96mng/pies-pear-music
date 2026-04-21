# Incremental Download — Design Spec

**Release:** 1.5 (branch: `release/1.5`)
**Date:** 2026-04-20

---

## Goal

Before triggering a sync, fetch the current Apple Music playlist track list, compare it against locally-owned tracks, and pass a skip list to the Go downloader so only genuinely new tracks are downloaded. This makes subsequent syncs fast and avoids redundant re-downloads.

---

## Architecture Overview

Python server is the orchestrator. It owns the diff logic and state updates. The Go downloader remains responsible for all Apple Music HLS download mechanics — it gains two new flags (`--skip-ids-file`, `--manifest-out`) but otherwise runs unchanged.

```
_run_job (server.py)
  │
  ├── 1. Pre-flight: am_api.fetch_playlist_track_ids()
  ├── 2. Diff: am_ids_in_playlist - owned_am_ids_in_db
  ├── 3. Write skip.json → temp dir
  │
  ├── 4. go run main.go --skip-ids-file=skip.json ...
  │       └── writes manifest.json to staging folder
  │
  ├── 5. Read manifest.json → update am_track_id in DB
  └── 6. SyncEngine.sync() → organize files as normal
```

---

## Section 1: Data Model

### `tracks` table — new column

```sql
ALTER TABLE tracks ADD COLUMN am_track_id TEXT;
```

- Nullable. Existing tracks (downloaded before this release) have `NULL`.
- Populated after each sync via the Go-written manifest.
- `track_id` (relative local path, primary key) is unchanged.

### Migration

Added alongside existing migrations in `StateManager._init_db`:

```python
cols = {r[1] for r in conn.execute("PRAGMA table_info(tracks)")}
if "am_track_id" not in cols:
    conn.execute("ALTER TABLE tracks ADD COLUMN am_track_id TEXT")
```

### New `StateManager` methods

```python
def get_playlist(self, name: str) -> Playlist:
    """Return a single Playlist by name. Raises KeyError if not found."""

def get_playlist_am_ids(self, playlist_name: str) -> set[str]:
    """Return all non-null AM track IDs already owned for a playlist."""

def update_track_am_id(self, track_id: str, am_track_id: str) -> None:
    """Set am_track_id on a track record matched by track_id (primary key)."""
```

---

## Section 2: Apple Music API Client (`alac_rip/am_api.py`)

New module. Two public functions, nothing else.

### `fetch_bearer_token() -> str`

Fetches Apple's public bearer token (no auth required):

1. GET `https://music.apple.com`
2. Find `<script src="...index-*.js">` in the HTML
3. GET that JS bundle
4. Extract JWT from `"authorization":"Bearer <token>"` pattern

Token is cached in a module-level variable for the process lifetime. Raises `AMApiError` on failure.

### `fetch_playlist_track_ids(playlist_url, media_user_token, bearer_token, storefront="us") -> list[str]`

1. Extract playlist ID from URL (regex on `apple.com/.*/playlist/.*/pl.` pattern)
2. GET `https://api.music.apple.com/v1/catalog/{storefront}/playlists/{id}/tracks`
   - Headers: `Authorization: Bearer {bearer_token}`, `Music-User-Token: {media_user_token}`
3. Paginate through all `next` links
4. Return list of track `id` strings (e.g. `"1234567890"`)

Raises `AMApiError` on HTTP error or unparseable response.

### Error type

```python
class AMApiError(Exception):
    pass
```

---

## Section 3: Pre-flight Diff Flow (`server.py` — `_run_job`)

Runs before the Go downloader is invoked.

```python
skip_file: Path | None = None
preflight_summary: str = ""

try:
    self._emit("Checking playlist for new tracks…", "preflight")
    bearer = am_api.fetch_bearer_token()
    pl = state.get_playlist(playlist_name)
    am_ids = am_api.fetch_playlist_track_ids(pl.url, config.media_user_token, bearer)
    owned = state.get_playlist_am_ids(playlist_name)
    new_ids = set(am_ids) - owned
    skip_ids = owned & set(am_ids)  # owned tracks that are still in the playlist

    skip_file = tmp_dir / "skip.json"
    skip_file.write_text(json.dumps({"skip_ids": list(skip_ids)}))
    preflight_summary = (
        f"Pre-flight: {len(am_ids)} tracks in playlist, "
        f"{len(new_ids)} new, {len(skip_ids)} already owned"
    )
    self._emit(preflight_summary, "preflight")

except AMApiError as e:
    self._emit(f"Pre-flight check failed ({e}), falling back to full download", "warning")
    skip_file = None
```

The Go downloader is then invoked with `--skip-ids-file={skip_file}` when `skip_file` is not None.

### Phase label

`"preflight"` is a new phase string emitted to the job event stream. `SyncProgress.svelte` maps it to `"Checking playlist…"`.

---

## Section 4: Go Downloader Changes (`main.go`)

### New flags

```go
var skipIdsFile = flag.String("skip-ids-file", "", "JSON file with AM track IDs to skip")
var manifestOut = flag.String("manifest-out", "", "Path to write downloaded track manifest JSON")
```

### Skip list

At the start of `ripPlaylist`:

```go
skipIds := map[string]bool{}
if *skipIdsFile != "" {
    data, err := os.ReadFile(*skipIdsFile)
    if err == nil {
        var payload struct{ SkipIds []string `json:"skip_ids"` }
        if json.Unmarshal(data, &payload) == nil {
            for _, id := range payload.SkipIds {
                skipIds[id] = true
            }
        }
    }
}
```

At the start of `ripTrack`, before any download work:

```go
if skipIds[track.ID] {
    fmt.Printf("Skipping (already owned): %s\n", track.Resp.Attributes.Name)
    counter.Skipped++
    return
}
```

### Manifest output

At the end of `ripPlaylist`, after all tracks are processed:

```go
type ManifestEntry struct {
    AMTrackID string `json:"am_track_id"`
    LocalPath string `json:"local_path"`
}

if *manifestOut != "" {
    entries := []ManifestEntry{}
    for _, track := range playlist.Tracks {
        if track.SavePath != "" {
            entries = append(entries, ManifestEntry{
                AMTrackID: track.ID,
                LocalPath: track.SavePath,  // relative path within staging
            })
        }
    }
    data, _ := json.MarshalIndent(entries, "", "  ")
    os.WriteFile(*manifestOut, data, 0644)
}
```

The manifest `local_path` is the full absolute path to the file in the staging folder (the value of `track.SavePath`). Python derives the `track_id` from this by stripping the staging dir prefix and normalising to `.flac` extension — matching exactly how `SyncEngine` computes `track_id`.

Only tracks with a non-empty `SavePath` (i.e. successfully downloaded) appear in the manifest.

---

## Section 5: Post-sync Manifest Processing (`server.py` — `_run_job`)

After `SyncEngine.sync()` completes (so track rows exist in the DB), read the manifest and update AM IDs:

```python
manifest_path = staging_dir / "manifest.json"
if manifest_path.exists():
    try:
        entries = json.loads(manifest_path.read_text())
        for entry in entries:
            # Derive track_id the same way SyncEngine does:
            # strip staging dir prefix, normalise extension to .flac
            rel = Path(entry["local_path"]).relative_to(staging_dir)
            track_id = str(rel.with_suffix(".flac"))
            state.update_track_am_id(track_id, entry["am_track_id"])
        manifest_path.unlink()
    except Exception as e:
        self._emit(f"Warning: could not process manifest ({e})", "warning")
```

If the manifest is missing or malformed, the sync continues normally — AM IDs for this run will be null, and the next sync will fall back to full download for those tracks.

---

## Section 6: UI Changes

### `SyncProgress.svelte` — new phase

Add `"preflight"` to the phase display map:

```
preflight   → "Checking playlist…"
downloading → "Downloading…"
organizing  → "Organizing…"
done        → "Done"
```

### Sync result summary

The done state shows two counters sourced from the pre-flight log (parsed from job events):

- **New:** tracks actually downloaded this run
- **Already owned:** tracks skipped by pre-flight

These are display-only — they come from the pre-flight summary string already emitted to the event stream, not from a new API field.

---

## Graceful Fallback

If any pre-flight step fails (network, bad token, API error):
- A warning is logged to the job stream
- `skip.json` is not written
- The Go downloader runs without `--skip-ids-file` (full download, same as Release 1)
- Manifest is still written (AM IDs are still captured for future syncs)

This means the first sync after upgrade behaves identically to Release 1. Subsequent syncs are incremental.

---

## Branch and Release Strategy

- All implementation on branch `release/1.5`
- `main` stays at v1.0.0 until the release is stable
- Merge to `main` and tag `v1.5.0` when complete
- DB migration is additive (new nullable column) — no data loss if rolled back; the column is simply unused on v1.0.0

---

## Files Created or Modified

| File | Change |
|------|--------|
| `alac_rip/am_api.py` | **Create** — bearer token fetch, playlist track ID fetch |
| `alac_rip/state.py` | **Modify** — `am_track_id` migration, `get_playlist_am_ids`, `update_track_am_id` |
| `alac_rip/server.py` | **Modify** — pre-flight in `_run_job`, manifest processing, `"preflight"` phase |
| `apple-music-downloader/main.go` | **Modify** — `--skip-ids-file`, `--manifest-out`, skip logic, manifest write |
| `app/src/lib/SyncProgress.svelte` | **Modify** — add `"preflight"` phase display |
| `tests/test_am_api.py` | **Create** — unit tests for bearer token parsing, playlist ID extraction |
| `tests/test_sync_incremental.py` | **Create** — integration tests for pre-flight diff, manifest processing |
