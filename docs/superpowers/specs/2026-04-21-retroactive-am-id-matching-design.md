# Retroactive AM ID Matching — Design Spec

**Date:** 2026-04-21

---

## Goal

When a pre-flight succeeds for a playlist that has DB tracks with `am_track_id IS NULL` (tracks downloaded before Release 1.5), match those tracks to the AM API response by normalized title + artist and populate their `am_track_id`. This is a one-time operation per track — once stored, the ID persists and the track is skipped on all future syncs.

---

## Root Cause

The Go downloader checks file existence in the staging folder to decide whether to skip a track. Staging is cleared after every sync, so this check always misses. The `--skip-ids-file` mechanism bypasses it, but only for tracks that have `am_track_id` in the database. Tracks downloaded before Release 1.5 have `am_track_id IS NULL` and are therefore never in the skip list — causing a full re-download on every sync until their IDs are populated.

---

## Section 1: `am_api.py` — replace `fetch_playlist_track_ids` with `fetch_playlist_tracks`

### Before

```python
def fetch_playlist_track_ids(playlist_url, media_user_token, bearer_token, storefront="us") -> list[str]:
    ...
    for item in data.get("data", []):
        track_ids.append(item["id"])
    ...
    return track_ids
```

### After

```python
def fetch_playlist_tracks(
    playlist_url: str,
    media_user_token: str,
    bearer_token: str,
    storefront: str = "us",
) -> list[dict]:
    """Return all tracks from a playlist as dicts with 'id', 'title', 'artist'.

    Paginates automatically. Raises AMApiError on invalid URL, network failure,
    or non-200 response.
    """
    ...
    for item in data.get("data", []):
        attrs = item.get("attributes", {})
        tracks.append({
            "id": item["id"],
            "title": attrs.get("name", ""),
            "artist": attrs.get("artistName", ""),
        })
    ...
    return tracks
```

`fetch_playlist_track_ids` is removed. It was only called from `server.py`.

---

## Section 2: `state.py` — new method

```python
def get_playlist_tracks_without_am_id(self, playlist_name: str) -> list[Track]:
    """Return tracks in a playlist that have no AM track ID yet."""
    with self._conn() as conn:
        rows = conn.execute(
            """
            SELECT t.track_id, t.title, t.artist, t.album, t.local_path, t.downloaded_at
            FROM tracks t
            JOIN playlist_tracks pt ON t.track_id = pt.track_id
            WHERE pt.playlist_name = ? AND t.am_track_id IS NULL
            """,
            (playlist_name,),
        ).fetchall()
        return [Track(*r) for r in rows]
```

---

## Section 3: `server.py` — retroactive matching in pre-flight

### Normalization helper (module-level)

```python
import re as _re

def _normalize(s: str) -> str:
    s = s.lower()
    s = _re.sub(r"[^\w\s]", "", s)
    return _re.sub(r"\s+", " ", s).strip()
```

### Updated pre-flight block

```python
am_tracks = am_api.fetch_playlist_tracks(url, media_user_token, bearer, storefront)
am_ids_set = {t["id"] for t in am_tracks}

# Retroactive: populate am_track_id for pre-1.5 tracks by title/artist match
unmatched = state.get_playlist_tracks_without_am_id(playlist_name)
if unmatched:
    am_by_key = {
        (_normalize(t["title"]), _normalize(t["artist"])): t["id"]
        for t in am_tracks
    }
    matched_count = 0
    for db_track in unmatched:
        key = (_normalize(db_track.title), _normalize(db_track.artist))
        if key in am_by_key:
            state.update_track_am_id(db_track.track_id, am_by_key[key])
            matched_count += 1
    if matched_count:
        emit_log("preflight", f"Matched {matched_count} existing tracks to AM IDs")

owned = state.get_playlist_am_ids(playlist_name)
am_ids_set = {t["id"] for t in am_tracks}
new_ids = am_ids_set - owned
skip_ids = owned & am_ids_set
```

The retroactive pass runs on every pre-flight until all tracks for the playlist have an AM ID. After the first successful run against a full playlist, `get_playlist_tracks_without_am_id` returns empty and the pass is a no-op.

---

## Section 4: Tests

### `tests/test_am_api.py` — update for new return shape

`_make_tracks_response` gains `attributes` in each item. `FAKE_HTML` mock response updated accordingly. All existing tests updated to call `fetch_playlist_tracks` and assert on `[{"id": ..., "title": ..., "artist": ...}]`.

### `tests/test_incremental.py` — new tests

- `test_get_playlist_tracks_without_am_id_returns_null_only` — tracks with and without AM IDs; only null ones returned
- `test_retroactive_matching_populates_am_id` — pre-flight with unmatched DB tracks matches and stores IDs
- `test_retroactive_matching_normalizes_case_and_punctuation` — titles differing only in case/punctuation still match
- `test_retroactive_matching_no_false_positives` — track with different artist doesn't match

---

## Matching Accuracy

Normalization (lowercase + strip non-word chars + collapse whitespace) handles:
- Case differences (`Bohemian Rhapsody` vs `bohemian rhapsody`)
- Punctuation differences (`Don't Stop Me Now` vs `Dont Stop Me Now`)
- Extra whitespace

Unmatched tracks (e.g. a re-release where Apple changed the title) are silently skipped — they'll trigger one re-download on the current sync, and the manifest will then populate their AM ID for future syncs.

---

## Files Modified

| File | Change |
|------|--------|
| `alac_rip/am_api.py` | Replace `fetch_playlist_track_ids` with `fetch_playlist_tracks` returning `list[dict]` |
| `alac_rip/state.py` | Add `get_playlist_tracks_without_am_id` |
| `alac_rip/server.py` | Add `_normalize` helper; retroactive matching block in pre-flight; update call site |
| `tests/test_am_api.py` | Update mocks and assertions for new return shape |
| `tests/test_incremental.py` | Add 4 new tests for retroactive matching |
