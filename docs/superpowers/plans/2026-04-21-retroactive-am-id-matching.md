# Retroactive AM ID Matching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Populate `am_track_id` for pre-1.5 DB tracks by matching them to the AM API response by normalized title + artist during pre-flight, so they appear in the skip list and are never re-downloaded.

**Architecture:** `fetch_playlist_track_ids` is replaced by `fetch_playlist_tracks` which returns full `{id, title, artist}` dicts. A new `state.get_playlist_tracks_without_am_id` query finds unmatched DB tracks. A retroactive matching pass in `server.py`'s pre-flight block normalizes and matches them before computing the skip list.

**Tech Stack:** Python, SQLite, Apple Music catalog API

---

## File Map

| File | Change |
|------|--------|
| `alac_rip/am_api.py` | Replace `fetch_playlist_track_ids` → `fetch_playlist_tracks` returning `list[dict]` |
| `alac_rip/state.py` | Add `get_playlist_tracks_without_am_id` after `update_track_am_id` |
| `alac_rip/server.py` | Add `_normalize` helper; replace call site; add retroactive matching block; add `log_retention_days` to `ConfigUpdate` |
| `tests/test_am_api.py` | Update mock helper and all assertions for new return shape |
| `tests/test_incremental.py` | Add 4 new tests for the new state method and matching logic |

---

### Task 1: Replace `fetch_playlist_track_ids` with `fetch_playlist_tracks` in `am_api.py`

**Files:**
- Modify: `alac_rip/am_api.py:50-109`
- Modify: `tests/test_am_api.py`

- [ ] **Step 1: Update `_mock_get` and `_make_tracks_response` in `tests/test_am_api.py` to include `attributes`**

In `tests/test_am_api.py`, update the mock helpers so they return the full shape the real API returns:

```python
# Replace _make_tracks_response:
def _make_tracks_response(ids_titles_artists, next_url=None):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.status_code = 200
    body = {
        "data": [
            {"id": id_, "attributes": {"name": title, "artistName": artist}}
            for id_, title, artist in ids_titles_artists
        ]
    }
    if next_url:
        body["next"] = next_url
    resp.json.return_value = body
    return resp
```

- [ ] **Step 2: Update every test that calls `fetch_playlist_track_ids` to call `fetch_playlist_tracks` and assert on dicts**

```python
# test_fetch_playlist_track_ids_returns_ids → rename and update:
def test_fetch_playlist_tracks_returns_dicts():
    resp = _make_tracks_response([("111", "Song A", "Artist A"), ("222", "Song B", "Artist B")])
    with patch("alac_rip.am_api.requests.get", return_value=resp):
        tracks = fetch_playlist_tracks(
            "https://music.apple.com/us/playlist/test/pl.abc123",
            media_user_token="fake-mut",
            bearer_token="fake-bearer",
        )
    assert tracks == [
        {"id": "111", "title": "Song A", "artist": "Artist A"},
        {"id": "222", "title": "Song B", "artist": "Artist B"},
    ]

# test_fetch_playlist_track_ids_paginates → rename and update:
def test_fetch_playlist_tracks_paginates():
    call_count = 0
    def mock_get(url, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _make_tracks_response(
                [("111", "A", "X"), ("222", "B", "X")],
                next_url="/v1/catalog/us/playlists/pl.abc/tracks?offset=2"
            )
        else:
            return _make_tracks_response([("333", "C", "X")])
    with patch("alac_rip.am_api.requests.get", side_effect=mock_get):
        tracks = fetch_playlist_tracks(
            "https://music.apple.com/us/playlist/test/pl.abc123",
            media_user_token="fake-mut",
            bearer_token="fake-bearer",
        )
    assert [t["id"] for t in tracks] == ["111", "222", "333"]
    assert call_count == 2

# test_fetch_playlist_track_ids_raises_on_bad_url → rename only (no logic change):
def test_fetch_playlist_tracks_raises_on_bad_url():
    with pytest.raises(AMApiError, match="playlist ID"):
        fetch_playlist_tracks(
            "https://music.apple.com/us/album/not-a-playlist/12345",
            media_user_token="fake-mut",
            bearer_token="fake-bearer",
        )

# test_fetch_playlist_track_ids_raises_on_api_error → rename and update mock:
def test_fetch_playlist_tracks_raises_on_api_error():
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.status_code = 401
    with patch("alac_rip.am_api.requests.get", return_value=resp):
        with pytest.raises(AMApiError, match="401"):
            fetch_playlist_tracks(
                "https://music.apple.com/us/playlist/test/pl.abc123",
                media_user_token="fake-mut",
                bearer_token="fake-bearer",
            )

# test_fetch_playlist_track_ids_defaults_storefront_placeholder → rename and update:
def test_fetch_playlist_tracks_defaults_storefront_placeholder():
    resp = _make_tracks_response([("111", "A", "X")])
    with patch("alac_rip.am_api.requests.get", return_value=resp) as mock_get:
        fetch_playlist_tracks(
            "https://music.apple.com/us/playlist/test/pl.abc123",
            media_user_token="fake-mut",
            bearer_token="fake-bearer",
            storefront="enter your account storefront",
        )
    called_url = mock_get.call_args[0][0]
    assert "/v1/catalog/us/" in called_url
```

Also update the import at the top of the test file:
```python
from alac_rip.am_api import AMApiError, fetch_bearer_token, fetch_playlist_tracks
```

- [ ] **Step 3: Run tests to confirm they all fail with `ImportError` / `name not defined`**

```
.venv/bin/pytest tests/test_am_api.py -v
```
Expected: FAIL on import of `fetch_playlist_tracks`

- [ ] **Step 4: Replace `fetch_playlist_track_ids` with `fetch_playlist_tracks` in `alac_rip/am_api.py`**

Replace lines 50–109 in `alac_rip/am_api.py` with:

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
    match = re.search(r"/(pl\.[A-Za-z0-9]+)", playlist_url)
    if not match:
        raise AMApiError(f"Could not extract playlist ID from URL: {playlist_url}")
    playlist_id = match.group(1)

    if not storefront or storefront == "enter your account storefront":
        storefront = "us"

    headers = {
        "Authorization": f"Bearer {bearer_token}",
        "Music-User-Token": media_user_token,
    }

    tracks: list[dict] = []
    url: str | None = (
        f"https://api.music.apple.com/v1/catalog/{storefront}"
        f"/playlists/{playlist_id}/tracks"
    )

    while url:
        try:
            r = requests.get(url, headers=headers, timeout=15)
        except requests.RequestException as e:
            raise AMApiError(f"Request failed: {e}") from e

        if r.status_code != 200:
            if r.status_code == 401:
                global _bearer_token_cache
                _bearer_token_cache = None
            raise AMApiError(
                f"Apple Music API returned {r.status_code} for {url}"
            )

        data = r.json()
        for item in data.get("data", []):
            attrs = item.get("attributes", {})
            tracks.append({
                "id": item["id"],
                "title": attrs.get("name", ""),
                "artist": attrs.get("artistName", ""),
            })

        next_path = data.get("next")
        if next_path:
            url = (
                next_path
                if next_path.startswith("http")
                else f"https://api.music.apple.com{next_path}"
            )
        else:
            url = None

    return tracks
```

- [ ] **Step 5: Run tests to confirm they pass**

```
.venv/bin/pytest tests/test_am_api.py -v
```
Expected: 9 PASS

- [ ] **Step 6: Commit**

```bash
git add alac_rip/am_api.py tests/test_am_api.py
git commit -m "feat: replace fetch_playlist_track_ids with fetch_playlist_tracks returning full metadata"
```

---

### Task 2: Add `get_playlist_tracks_without_am_id` to `state.py`

**Files:**
- Modify: `alac_rip/state.py:185` (after `update_track_am_id`)
- Modify: `tests/test_incremental.py`

- [ ] **Step 1: Write 2 failing tests in `tests/test_incremental.py`**

Add at the end of the file:

```python
def test_get_playlist_tracks_without_am_id_returns_only_null(tmp_path):
    state = StateManager(tmp_path / "test.db")
    state.add_playlist("My PL", "https://example.com")
    state.add_track(Track(
        track_id="a/track.flac", title="Song A", artist="Artist",
        album="Album", local_path="/music/a.flac", downloaded_at="2026-01-01",
    ))
    state.add_track(Track(
        track_id="b/track.flac", title="Song B", artist="Artist",
        album="Album", local_path="/music/b.flac", downloaded_at="2026-01-01",
    ))
    state.add_track_to_playlist("My PL", "a/track.flac")
    state.add_track_to_playlist("My PL", "b/track.flac")
    state.update_track_am_id("a/track.flac", "am-111")  # has AM ID

    result = state.get_playlist_tracks_without_am_id("My PL")

    assert len(result) == 1
    assert result[0].track_id == "b/track.flac"


def test_get_playlist_tracks_without_am_id_empty_when_all_matched(tmp_path):
    state = StateManager(tmp_path / "test.db")
    state.add_playlist("My PL", "https://example.com")
    state.add_track(Track(
        track_id="a/track.flac", title="Song A", artist="Artist",
        album="Album", local_path="/music/a.flac", downloaded_at="2026-01-01",
    ))
    state.add_track_to_playlist("My PL", "a/track.flac")
    state.update_track_am_id("a/track.flac", "am-111")

    result = state.get_playlist_tracks_without_am_id("My PL")

    assert result == []
```

- [ ] **Step 2: Run tests to confirm they fail**

```
.venv/bin/pytest tests/test_incremental.py::test_get_playlist_tracks_without_am_id_returns_only_null tests/test_incremental.py::test_get_playlist_tracks_without_am_id_empty_when_all_matched -v
```
Expected: FAIL with `AttributeError: 'StateManager' object has no attribute 'get_playlist_tracks_without_am_id'`

- [ ] **Step 3: Add the method to `alac_rip/state.py` after `update_track_am_id` (line 185)**

```python
    def get_playlist_tracks_without_am_id(self, playlist_name: str) -> list[Track]:
        """Return tracks in a playlist that have no AM track ID yet."""
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT t.track_id, t.title, t.artist, t.album,
                       t.local_path, t.downloaded_at
                FROM tracks t
                JOIN playlist_tracks pt ON t.track_id = pt.track_id
                WHERE pt.playlist_name = ? AND t.am_track_id IS NULL
                """,
                (playlist_name,),
            ).fetchall()
            return [Track(*r) for r in rows]
```

- [ ] **Step 4: Run tests to confirm they pass**

```
.venv/bin/pytest tests/test_incremental.py::test_get_playlist_tracks_without_am_id_returns_only_null tests/test_incremental.py::test_get_playlist_tracks_without_am_id_empty_when_all_matched -v
```
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add alac_rip/state.py tests/test_incremental.py
git commit -m "feat: add get_playlist_tracks_without_am_id to StateManager"
```

---

### Task 3: Retroactive matching in `server.py` pre-flight

**Files:**
- Modify: `alac_rip/server.py:1-30` (imports/module level) and `398-427` (pre-flight block)
- Modify: `tests/test_incremental.py`

- [ ] **Step 1: Write 2 failing tests in `tests/test_incremental.py`**

Add at the end of the file:

```python
def test_retroactive_matching_populates_am_id(tmp_path):
    """Pre-flight with an existing DB track (null AM ID) matches it by title/artist."""
    import re as _re
    from alac_rip.server import _normalize

    state = StateManager(tmp_path / "test.db")
    state.add_playlist("My PL", "https://example.com")
    state.add_track(Track(
        track_id="Artist/Album/01 - Song.flac", title="Song", artist="Artist",
        album="Album", local_path="/music/song.flac", downloaded_at="2026-01-01",
    ))
    state.add_track_to_playlist("My PL", "Artist/Album/01 - Song.flac")

    am_tracks = [{"id": "am-999", "title": "Song", "artist": "Artist"}]
    unmatched = state.get_playlist_tracks_without_am_id("My PL")
    am_by_key = {
        (_normalize(t["title"]), _normalize(t["artist"])): t["id"]
        for t in am_tracks
    }
    for db_track in unmatched:
        key = (_normalize(db_track.title), _normalize(db_track.artist))
        if key in am_by_key:
            state.update_track_am_id(db_track.track_id, am_by_key[key])

    owned = state.get_playlist_am_ids("My PL")
    assert "am-999" in owned


def test_normalize_strips_punctuation_and_lowercases():
    from alac_rip.server import _normalize
    assert _normalize("Don't Stop Me Now!") == "dont stop me now"
    assert _normalize("  Bohemian  Rhapsody  ") == "bohemian rhapsody"
    assert _normalize("SONG (feat. Artist)") == "song feat artist"
```

- [ ] **Step 2: Run tests to confirm they fail**

```
.venv/bin/pytest tests/test_incremental.py::test_retroactive_matching_populates_am_id tests/test_incremental.py::test_normalize_strips_punctuation_and_lowercases -v
```
Expected: FAIL with `ImportError: cannot import name '_normalize' from 'alac_rip.server'`

- [ ] **Step 3: Add `_normalize` helper at module level in `alac_rip/server.py`**

Add after the imports block (after line ~32, before the FastAPI `app` definition):

```python
import re as _re


def _normalize(s: str) -> str:
    s = s.lower()
    s = _re.sub(r"[^\w\s]", "", s)
    return _re.sub(r"\s+", " ", s).strip()
```

- [ ] **Step 4: Run the `test_normalize` test to confirm it passes**

```
.venv/bin/pytest tests/test_incremental.py::test_normalize_strips_punctuation_and_lowercases -v
```
Expected: PASS

- [ ] **Step 5: Update the pre-flight block in `alac_rip/server.py` (lines 404–427)**

Replace the existing pre-flight `try` block:

```python
    if playlist_name:
        try:
            emit_log("preflight", "Checking playlist for new tracks…")
            bearer = am_api.fetch_bearer_token()
            storefront = amd_cfg.get("storefront", "us")
            media_user_token = amd_cfg.get("media-user-token", "")
            am_tracks = am_api.fetch_playlist_tracks(url, media_user_token, bearer, storefront)
            am_ids_set = {t["id"] for t in am_tracks}

            # Retroactive: populate am_track_id for pre-1.5 tracks
            unmatched = state.get_playlist_tracks_without_am_id(playlist_name)
            if unmatched:
                am_by_key = {
                    (_normalize(t["title"]), _normalize(t["artist"])): t["id"]
                    for t in am_tracks
                }
                matched_count = sum(
                    1 for db_track in unmatched
                    if (_normalize(db_track.title), _normalize(db_track.artist)) in am_by_key
                    and not state.update_track_am_id(
                        db_track.track_id,
                        am_by_key[(_normalize(db_track.title), _normalize(db_track.artist))]
                    )
                )
                if matched_count:
                    emit_log("preflight", f"Matched {matched_count} existing tracks to AM IDs")

            owned = state.get_playlist_am_ids(playlist_name)
            new_ids = am_ids_set - owned
            skip_ids = owned & am_ids_set

            skip_file_path = Path(_tmp) / "skip.json"
            skip_file_path.write_text(json.dumps({"skip_ids": list(skip_ids)}))

            emit_log("preflight",
                f"Pre-flight: {len(am_tracks)} tracks in playlist, "
                f"{len(new_ids)} new, {len(skip_ids)} already owned"
            )
        except Exception as e:
            emit_log("preflight",
                f"Pre-flight check failed ({e}), falling back to full download"
            )
            skip_file_path = None
```

Note: `update_track_am_id` returns `None`, so the `not state.update_track_am_id(...)` idiom evaluates to `True` (since `not None` is `True`) and counts every successful update. This is a compact way to call and count in one pass. If it feels unclear, the alternative explicit loop is equally valid:

```python
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
```

Use the explicit loop — it's clearer.

- [ ] **Step 6: Run all tests**

```
.venv/bin/pytest -v
```
Expected: all PASS (96+ tests)

- [ ] **Step 7: Commit**

```bash
git add alac_rip/am_api.py alac_rip/state.py alac_rip/server.py tests/test_am_api.py tests/test_incremental.py
git commit -m "feat: retroactive AM ID matching for pre-1.5 tracks in pre-flight"
```
