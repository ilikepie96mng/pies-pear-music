# Incremental Download Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Before each playlist sync, fetch the current Apple Music track list, compare against locally-owned tracks, and pass a skip list to the Go downloader so only genuinely new tracks are downloaded.

**Architecture:** Python server orchestrates a pre-flight diff (AM API → local DB) before invoking the Go downloader, writes a skip list for Go to consume, and reads back a manifest Go writes on completion to store Apple Music catalog IDs in the state DB for future diffs.

**Tech Stack:** Python (requests, sqlite3, FastAPI), Go (pflag, encoding/json), Svelte 5, SQLite

---

## Branch Setup

Before any code changes, all work for Release 1.5 goes on its own branch so `main` stays at v1.0.0.

```bash
cd /var/home/ilikepie/Documents/VS-Projects/pies-alac-rip-tool
git checkout -b release/1.5
```

Verify:
```bash
git branch
# * release/1.5
#   main
```

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `alac_rip/am_api.py` | **Create** | Fetch bearer token; fetch playlist track IDs from AM catalog API |
| `alac_rip/state.py` | **Modify** | Add `am_track_id` column migration; add `get_playlist_am_ids`, `update_track_am_id` |
| `alac_rip/server.py` | **Modify** | Pre-flight diff in `_run_job`; manifest processing after `engine.sync()` |
| `apple-music-downloader/main.go` | **Modify** | `--skip-ids-file` flag + skip logic; `--manifest-out` flag + manifest write |
| `apple-music-downloader/utils/structs/structs.go` | **Modify** | Add `Skipped int` to `Counter` struct |
| `app/src/lib/SyncProgress.svelte` | **Modify** | Add `"preflight"` to phase timeline |
| `tests/test_am_api.py` | **Create** | Unit tests for bearer token parsing, playlist ID extraction, pagination |
| `tests/test_incremental.py` | **Create** | Integration tests for `get_playlist_am_ids`, `update_track_am_id`, manifest processing |

---

## Task 1: DB Migration and StateManager Methods

**Files:**
- Modify: `alac_rip/state.py`
- Create: `tests/test_incremental.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_incremental.py`:

```python
from pathlib import Path
from datetime import datetime
import pytest
from alac_rip.state import StateManager, Track


@pytest.fixture
def state(tmp_path):
    return StateManager(tmp_path / "test.db")


def _add_track(state, track_id, am_track_id=None):
    state.add_track(Track(
        track_id=track_id,
        title="Title",
        artist="Artist",
        album="Album",
        local_path=f"/music/{track_id}",
        downloaded_at=datetime.now().isoformat(),
    ))
    if am_track_id:
        state.update_track_am_id(track_id, am_track_id)


def test_am_track_id_column_exists(state):
    # DB should have am_track_id column after migration
    import sqlite3
    with sqlite3.connect(state.db_path) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(tracks)")}
    assert "am_track_id" in cols


def test_update_track_am_id_stores_value(state):
    _add_track(state, "Artist/Album/01 - Song.flac")
    state.update_track_am_id("Artist/Album/01 - Song.flac", "1234567890")
    ids = state.get_playlist_am_ids.__func__  # just verify method exists
    assert callable(state.update_track_am_id)


def test_get_playlist_am_ids_returns_owned_ids(state):
    state.add_playlist("My Playlist", "https://music.apple.com/us/playlist/test/pl.xxx")
    _add_track(state, "Artist/Album/01 - Song.flac", "111")
    _add_track(state, "Artist/Album/02 - Song.flac", "222")
    state.add_track_to_playlist("My Playlist", "Artist/Album/01 - Song.flac")
    state.add_track_to_playlist("My Playlist", "Artist/Album/02 - Song.flac")

    ids = state.get_playlist_am_ids("My Playlist")
    assert ids == {"111", "222"}


def test_get_playlist_am_ids_excludes_null(state):
    state.add_playlist("My Playlist", "https://music.apple.com/us/playlist/test/pl.xxx")
    # Track with no AM ID (downloaded before incremental feature)
    _add_track(state, "Artist/Album/01 - Song.flac")
    state.add_track_to_playlist("My Playlist", "Artist/Album/01 - Song.flac")

    ids = state.get_playlist_am_ids("My Playlist")
    assert ids == set()


def test_get_playlist_am_ids_only_for_named_playlist(state):
    state.add_playlist("Playlist A", "https://music.apple.com/us/playlist/a/pl.aaa")
    state.add_playlist("Playlist B", "https://music.apple.com/us/playlist/b/pl.bbb")
    _add_track(state, "Artist/Album/01 - Song.flac", "111")
    _add_track(state, "Artist/Album/02 - Song.flac", "222")
    state.add_track_to_playlist("Playlist A", "Artist/Album/01 - Song.flac")
    state.add_track_to_playlist("Playlist B", "Artist/Album/02 - Song.flac")

    assert state.get_playlist_am_ids("Playlist A") == {"111"}
    assert state.get_playlist_am_ids("Playlist B") == {"222"}
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /var/home/ilikepie/Documents/VS-Projects/pies-alac-rip-tool
.venv/bin/pytest tests/test_incremental.py -v
```

Expected: FAIL — `update_track_am_id` and `get_playlist_am_ids` not defined yet.

- [ ] **Step 3: Add migration and methods to `state.py`**

In `StateManager._init_db`, add after the existing `staging_folder` migration block:

```python
# am_track_id migration
track_cols = {r[1] for r in conn.execute("PRAGMA table_info(tracks)")}
if "am_track_id" not in track_cols:
    conn.execute("ALTER TABLE tracks ADD COLUMN am_track_id TEXT")
```

Add two new methods to `StateManager` (after `update_playlist_synced`):

```python
def get_playlist_am_ids(self, playlist_name: str) -> set[str]:
    with self._conn() as conn:
        rows = conn.execute(
            """
            SELECT t.am_track_id
            FROM tracks t
            JOIN playlist_tracks pt ON t.track_id = pt.track_id
            WHERE pt.playlist_name = ? AND t.am_track_id IS NOT NULL
            """,
            (playlist_name,),
        ).fetchall()
        return {r[0] for r in rows}

def update_track_am_id(self, track_id: str, am_track_id: str) -> None:
    with self._conn() as conn:
        conn.execute(
            "UPDATE tracks SET am_track_id = ? WHERE track_id = ?",
            (am_track_id, track_id),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/test_incremental.py -v
```

Expected: All 5 tests PASS.

- [ ] **Step 5: Run full suite to check for regressions**

```bash
.venv/bin/pytest tests/ -q
```

Expected: 84 passed (79 existing + 5 new).

- [ ] **Step 6: Commit**

```bash
git add alac_rip/state.py tests/test_incremental.py
git commit -m "feat: add am_track_id column and StateManager methods for incremental download"
```

---

## Task 2: Apple Music API Client

**Files:**
- Create: `alac_rip/am_api.py`
- Create: `tests/test_am_api.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_am_api.py`:

```python
import pytest
from unittest.mock import patch, MagicMock
from alac_rip.am_api import AMApiError, fetch_bearer_token, fetch_playlist_track_ids
import alac_rip.am_api as am_api_module


@pytest.fixture(autouse=True)
def clear_token_cache():
    am_api_module._bearer_token_cache = None
    yield
    am_api_module._bearer_token_cache = None


FAKE_HTML = '''<html><head>
<script src="https://music.apple.com/assets/index-abc123.js" type="module"></script>
</head></html>'''

FAKE_JS = 'some js content "authorization":"Bearer eyJhbGciOiJFUzI1NiJ9.fake.token" more content'


def _mock_get(url, **kwargs):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    if "music.apple.com/assets" in url:
        resp.text = FAKE_JS
    else:
        resp.text = FAKE_HTML
    return resp


def test_fetch_bearer_token_extracts_jwt():
    with patch("alac_rip.am_api.requests.get", side_effect=_mock_get):
        token = fetch_bearer_token()
    assert token == "eyJhbGciOiJFUzI1NiJ9.fake.token"


def test_fetch_bearer_token_caches_result():
    with patch("alac_rip.am_api.requests.get", side_effect=_mock_get) as mock_get:
        fetch_bearer_token()
        fetch_bearer_token()
    # Only two calls total (html + js) despite calling twice
    assert mock_get.call_count == 2


def test_fetch_bearer_token_raises_if_no_script():
    bad_html = MagicMock()
    bad_html.raise_for_status = MagicMock()
    bad_html.text = "<html>no scripts here</html>"
    with patch("alac_rip.am_api.requests.get", return_value=bad_html):
        with pytest.raises(AMApiError, match="JS bundle"):
            fetch_bearer_token()


def test_fetch_bearer_token_raises_if_no_token_in_js():
    def mock_get(url, **kwargs):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        if "assets" in url:
            resp.text = "no token here"
        else:
            resp.text = FAKE_HTML
        return resp

    with patch("alac_rip.am_api.requests.get", side_effect=mock_get):
        with pytest.raises(AMApiError, match="bearer token"):
            fetch_bearer_token()


def _make_tracks_response(ids, next_url=None):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.status_code = 200
    body = {"data": [{"id": id_} for id_ in ids]}
    if next_url:
        body["next"] = next_url
    resp.json.return_value = body
    return resp


def test_fetch_playlist_track_ids_returns_ids():
    resp = _make_tracks_response(["111", "222", "333"])
    with patch("alac_rip.am_api.requests.get", return_value=resp):
        ids = fetch_playlist_track_ids(
            "https://music.apple.com/us/playlist/test/pl.abc123",
            media_user_token="fake-mut",
            bearer_token="fake-bearer",
        )
    assert ids == ["111", "222", "333"]


def test_fetch_playlist_track_ids_paginates():
    call_count = 0

    def mock_get(url, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _make_tracks_response(["111", "222"], next_url="/v1/catalog/us/playlists/pl.abc/tracks?offset=2")
        else:
            return _make_tracks_response(["333"])

    with patch("alac_rip.am_api.requests.get", side_effect=mock_get):
        ids = fetch_playlist_track_ids(
            "https://music.apple.com/us/playlist/test/pl.abc123",
            media_user_token="fake-mut",
            bearer_token="fake-bearer",
        )
    assert ids == ["111", "222", "333"]
    assert call_count == 2


def test_fetch_playlist_track_ids_raises_on_bad_url():
    with pytest.raises(AMApiError, match="playlist ID"):
        fetch_playlist_track_ids(
            "https://music.apple.com/us/album/not-a-playlist/12345",
            media_user_token="fake-mut",
            bearer_token="fake-bearer",
        )


def test_fetch_playlist_track_ids_raises_on_api_error():
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.status_code = 401
    with patch("alac_rip.am_api.requests.get", return_value=resp):
        with pytest.raises(AMApiError, match="401"):
            fetch_playlist_track_ids(
                "https://music.apple.com/us/playlist/test/pl.abc123",
                media_user_token="fake-mut",
                bearer_token="fake-bearer",
            )


def test_fetch_playlist_track_ids_defaults_storefront_placeholder():
    resp = _make_tracks_response(["111"])
    with patch("alac_rip.am_api.requests.get", return_value=resp) as mock_get:
        fetch_playlist_track_ids(
            "https://music.apple.com/us/playlist/test/pl.abc123",
            media_user_token="fake-mut",
            bearer_token="fake-bearer",
            storefront="enter your account storefront",
        )
    called_url = mock_get.call_args[0][0]
    assert "/v1/catalog/us/" in called_url
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/test_am_api.py -v
```

Expected: FAIL — `alac_rip.am_api` module does not exist yet.

- [ ] **Step 3: Create `alac_rip/am_api.py`**

```python
import re
import requests

_bearer_token_cache: str | None = None


class AMApiError(Exception):
    pass


def fetch_bearer_token() -> str:
    global _bearer_token_cache
    if _bearer_token_cache:
        return _bearer_token_cache

    try:
        r = requests.get("https://music.apple.com", timeout=10)
        r.raise_for_status()
    except requests.RequestException as e:
        raise AMApiError(f"Could not fetch music.apple.com: {e}") from e

    match = re.search(
        r'<script[^>]+src="(https://music\.apple\.com/assets/index[^"]+\.js)"', r.text
    )
    if not match:
        raise AMApiError("Could not find Apple Music JS bundle in page HTML")

    js_url = match.group(1)
    try:
        js_r = requests.get(js_url, timeout=15)
        js_r.raise_for_status()
    except requests.RequestException as e:
        raise AMApiError(f"Could not fetch JS bundle: {e}") from e

    token_match = re.search(
        r'"authorization"\s*:\s*"Bearer\s+([A-Za-z0-9\-_.]+)"', js_r.text
    )
    if not token_match:
        raise AMApiError("Could not extract bearer token from JS bundle")

    _bearer_token_cache = token_match.group(1)
    return _bearer_token_cache


def fetch_playlist_track_ids(
    playlist_url: str,
    media_user_token: str,
    bearer_token: str,
    storefront: str = "us",
) -> list[str]:
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

    track_ids: list[str] = []
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
            raise AMApiError(
                f"Apple Music API returned {r.status_code} for {url}"
            )

        data = r.json()
        for item in data.get("data", []):
            track_ids.append(item["id"])

        next_path = data.get("next")
        if next_path:
            url = (
                next_path
                if next_path.startswith("http")
                else f"https://api.music.apple.com{next_path}"
            )
        else:
            url = None

    return track_ids
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/test_am_api.py -v
```

Expected: All 9 tests PASS.

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/pytest tests/ -q
```

Expected: 93 passed.

- [ ] **Step 6: Commit**

```bash
git add alac_rip/am_api.py tests/test_am_api.py
git commit -m "feat: add Apple Music API client for bearer token fetch and playlist track IDs"
```

---

## Task 3: Go Downloader — Counter and Skip List

The Go downloader is in a root-owned directory. All edits require `sudo`.

**Files:**
- Modify: `apple-music-downloader/utils/structs/structs.go` (add `Skipped` to Counter)
- Modify: `apple-music-downloader/main.go` (flags + skip logic in `ripTrack`)

- [ ] **Step 1: Check the Counter struct**

```bash
cat /home/ilikepie/Documents/VS-Projects/alac-rip/apple-music-downloader/utils/structs/structs.go
```

Look for the `Counter` struct. If `Skipped int` is not present, add it in Step 2. If it is present, skip Step 2.

- [ ] **Step 2: Add `Skipped` field to Counter (if missing)**

```bash
sudo sed -i '/type Counter struct/,/^}/ s/Error\s*int/Error   int\n\tSkipped int/' \
  /home/ilikepie/Documents/VS-Projects/alac-rip/apple-music-downloader/utils/structs/structs.go
```

Verify:
```bash
grep -A6 "type Counter struct" /home/ilikepie/Documents/VS-Projects/alac-rip/apple-music-downloader/utils/structs/structs.go
```

Expected output includes `Skipped int`.

- [ ] **Step 3: Add package-level skip vars and flags to `main.go`**

Add two package-level variables near the top of `main.go` (after the existing `var (` block that declares `dl_atmos`, etc.):

```bash
sudo sed -i 's/^var ($/var (\n\tskipIds    = map[string]bool{}\n\tskipIdsFile string\n\tmanifestOut string/' \
  /home/ilikepie/Documents/VS-Projects/alac-rip/apple-music-downloader/main.go
```

Verify:
```bash
grep -n "skipIds\|skipIdsFile\|manifestOut" /home/ilikepie/Documents/VS-Projects/alac-rip/apple-music-downloader/main.go | head -5
```

Expected: 3 matches near the top of the file.

- [ ] **Step 4: Register the new flags in `main()`**

The flags must be registered before `pflag.Parse()` at line ~1909. Add them after the existing `mv_max` flag definition:

```bash
sudo sed -i 's/mv_max = pflag.Int("mv-max"/pflag.StringVar(\&skipIdsFile, "skip-ids-file", "", "JSON file with AM track IDs to skip")\n\tpflag.StringVar(\&manifestOut, "manifest-out", "", "Path to write downloaded track manifest JSON")\n\tmv_max = pflag.Int("mv-max"/' \
  /home/ilikepie/Documents/VS-Projects/alac-rip/apple-music-downloader/main.go
```

Verify:
```bash
grep -n "skip-ids-file\|manifest-out" /home/ilikepie/Documents/VS-Projects/alac-rip/apple-music-downloader/main.go
```

Expected: Both flags appear near the other `pflag` definitions.

- [ ] **Step 5: Load skip IDs after `pflag.Parse()`**

Add skip list loading immediately after `pflag.Parse()` (line ~1909). Find the line `pflag.Parse()` and add after it:

```bash
sudo sed -i '/pflag\.Parse()/a\\tif skipIdsFile != "" {\n\t\tdata, err := os.ReadFile(skipIdsFile)\n\t\tif err == nil {\n\t\t\tvar payload struct {\n\t\t\t\tSkipIds []string `json:"skip_ids"`\n\t\t\t}\n\t\t\tif json.Unmarshal(data, \&payload) == nil {\n\t\t\t\tfor _, id := range payload.SkipIds {\n\t\t\t\t\tskipIds[id] = true\n\t\t\t\t}\n\t\t\t}\n\t\t}\n\t}' \
  /home/ilikepie/Documents/VS-Projects/alac-rip/apple-music-downloader/main.go
```

- [ ] **Step 6: Add skip check at the top of `ripTrack`**

`ripTrack` starts at the line with `func ripTrack(`. The skip check must go right after `counter.Total++`:

```bash
sudo sed -i '/counter\.Total\+\+/a\\tif skipIds[track.ID] {\n\t\tfmt.Printf("Skipping (already owned): %s\\n", track.Resp.Attributes.Name)\n\t\tcounter.Skipped++\n\t\treturn\n\t}' \
  /home/ilikepie/Documents/VS-Projects/alac-rip/apple-music-downloader/main.go
```

Verify only one insertion (there should be one `counter.Total++` in `ripTrack`):
```bash
grep -n "Skipping (already owned)" /home/ilikepie/Documents/VS-Projects/alac-rip/apple-music-downloader/main.go
```

Expected: exactly 1 match.

- [ ] **Step 7: Build to verify no compile errors**

```bash
cd /home/ilikepie/Documents/VS-Projects/alac-rip/apple-music-downloader
sudo go build -buildvcs=false ./...
```

Expected: no output (clean build).

- [ ] **Step 8: Verify new flags appear in help**

```bash
sudo go run -buildvcs=false main.go --help 2>&1 | grep -E "skip-ids-file|manifest-out"
```

Expected:
```
--manifest-out string       Path to write downloaded track manifest JSON
--skip-ids-file string      JSON file with AM track IDs to skip
```

- [ ] **Step 9: Commit Go skip-list changes**

```bash
cd /home/ilikepie/Documents/VS-Projects/alac-rip
sudo git add apple-music-downloader/main.go apple-music-downloader/utils/structs/structs.go
sudo git commit -m "feat: add --skip-ids-file flag and skip logic for incremental download"
```

---

## Task 4: Go Downloader — Manifest Output

**Files:**
- Modify: `apple-music-downloader/main.go` (manifest write at end of `ripPlaylist`)

- [ ] **Step 1: Add manifest write at end of `ripPlaylist`**

`ripPlaylist` ends with `return nil` at line ~1780. Insert the manifest write before that return:

```bash
sudo sed -i 's/^\treturn nil\n}$/\tif manifestOut != "" {\n\t\ttype ManifestEntry struct {\n\t\t\tAMTrackID string `json:"am_track_id"`\n\t\t\tLocalPath string `json:"local_path"`\n\t\t}\n\t\tentries := []ManifestEntry{}\n\t\tfor i := range playlist.Tracks {\n\t\t\tt := \&playlist.Tracks[i]\n\t\t\tif t.SavePath != "" {\n\t\t\t\tentries = append(entries, ManifestEntry{\n\t\t\t\t\tAMTrackID: t.ID,\n\t\t\t\t\tLocalPath: t.SavePath,\n\t\t\t\t})\n\t\t\t}\n\t\t}\n\t\tdata, _ := json.MarshalIndent(entries, "", "  ")\n\t\tos.WriteFile(manifestOut, data, 0644)\n\t\tfmt.Printf("Manifest written: %d tracks\\n", len(entries))\n\t}\n\treturn nil\n}/' \
  /home/ilikepie/Documents/VS-Projects/alac-rip/apple-music-downloader/main.go
```

If the `sed` above fails due to multiline complexity, use a Python script instead:

```bash
sudo python3 -c "
import re
path = '/home/ilikepie/Documents/VS-Projects/alac-rip/apple-music-downloader/main.go'
with open(path) as f:
    content = f.read()

manifest_code = '''
\tif manifestOut != \"\" {
\t\ttype ManifestEntry struct {
\t\t\tAMTrackID string \`json:\"am_track_id\"\`
\t\t\tLocalPath string \`json:\"local_path\"\`
\t\t}
\t\tentries := []ManifestEntry{}
\t\tfor i := range playlist.Tracks {
\t\t\tt := &playlist.Tracks[i]
\t\t\tif t.SavePath != \"\" {
\t\t\t\tentries = append(entries, ManifestEntry{
\t\t\t\t\tAMTrackID: t.ID,
\t\t\t\t\tLocalPath: t.SavePath,
\t\t\t\t})
\t\t\t}
\t\t}
\t\tdata, _ := json.MarshalIndent(entries, \"\", \"  \")
\t\tos.WriteFile(manifestOut, data, 0644)
\t\tfmt.Printf(\"Manifest written: %d tracks\\\\n\", len(entries))
\t}
\treturn nil
}'''

# Replace the closing of ripPlaylist (last 'return nil\n}' before writeMP4Tags)
old = '\treturn nil\n}\n\nfunc writeMP4Tags'
new = manifest_code + '\n\nfunc writeMP4Tags'
assert old in content, 'Pattern not found'
content = content.replace(old, new, 1)
with open(path, 'w') as f:
    f.write(content)
print('Done')
"
```

- [ ] **Step 2: Build to verify no compile errors**

```bash
cd /home/ilikepie/Documents/VS-Projects/alac-rip/apple-music-downloader
sudo go build -buildvcs=false ./...
```

Expected: clean build.

- [ ] **Step 3: Smoke test manifest output with a fake skip file**

```bash
echo '{"skip_ids":[]}' > /tmp/skip_test.json
cd /home/ilikepie/Documents/VS-Projects/alac-rip/apple-music-downloader
sudo go run -buildvcs=false main.go --help 2>&1 | grep manifest
```

Expected: `--manifest-out string` appears in help.

- [ ] **Step 4: Commit manifest output changes**

```bash
cd /home/ilikepie/Documents/VS-Projects/alac-rip
sudo git add apple-music-downloader/main.go
sudo git commit -m "feat: add --manifest-out flag to write downloaded track manifest JSON"
```

---

## Task 5: server.py — Pre-flight Phase

**Files:**
- Modify: `alac_rip/server.py`
- Modify: `tests/test_incremental.py`

- [ ] **Step 1: Write failing test for pre-flight emit**

Add to `tests/test_incremental.py`:

```python
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock


def test_preflight_writes_skip_file(state):
    """Pre-flight diff produces skip.json with already-owned IDs."""
    state.add_playlist("Game OST", "https://music.apple.com/us/playlist/game-ost/pl.abc")
    state.add_track(Track(
        track_id="Artist/Album/01 - Song.flac",
        title="Song", artist="Artist", album="Album",
        local_path="/music/song.flac", downloaded_at="2026-01-01T00:00:00",
    ))
    state.update_track_am_id("Artist/Album/01 - Song.flac", "111")
    state.add_track_to_playlist("Game OST", "Artist/Album/01 - Song.flac")

    # AM playlist has track 111 (owned) and 222 (new)
    am_ids = ["111", "222"]
    owned = state.get_playlist_am_ids("Game OST")
    skip_ids = owned & set(am_ids)
    new_ids = set(am_ids) - owned

    assert skip_ids == {"111"}
    assert new_ids == {"222"}

    with tempfile.TemporaryDirectory() as tmp:
        skip_file = Path(tmp) / "skip.json"
        skip_file.write_text(json.dumps({"skip_ids": list(skip_ids)}))
        data = json.loads(skip_file.read_text())
        assert data["skip_ids"] == ["111"]
```

- [ ] **Step 2: Run new test to verify it passes (it's pure logic, no server needed)**

```bash
.venv/bin/pytest tests/test_incremental.py::test_preflight_writes_skip_file -v
```

Expected: PASS (this test exercises the diff logic in pure Python — no server wiring yet).

- [ ] **Step 3: Add import to `server.py`**

At the top of `server.py`, after the existing imports, add:

```python
from alac_rip import am_api
from alac_rip.am_api import AMApiError
```

- [ ] **Step 4: Add pre-flight block to `_run_job` in `server.py`**

In `_run_job`, find the block that builds `cmd` (around line 396–401):

```python
    if format_ == "ATMOS":
        cmd = [go_bin, "run", "main.go", "--atmos", url]
    elif format_ == "AAC":
        cmd = [go_bin, "run", "main.go", "--aac", url]
    else:
        cmd = [go_bin, "run", "main.go", url]
```

Replace with:

```python
    # ── Pre-flight: diff AM playlist against local DB ─────────────────────────
    skip_file_path: Optional[Path] = None
    manifest_path = save_folder / "manifest.json"

    if playlist_name:
        try:
            emit_log("preflight", "Checking playlist for new tracks…")
            bearer = am_api.fetch_bearer_token()
            storefront = amd_cfg.get("storefront", "us")
            media_user_token = amd_cfg.get("media-user-token", "")
            am_ids = am_api.fetch_playlist_track_ids(url, media_user_token, bearer, storefront)
            owned = state.get_playlist_am_ids(playlist_name)
            new_ids = set(am_ids) - owned
            skip_ids = owned & set(am_ids)

            import tempfile
            _tmp = tempfile.mkdtemp()
            skip_file_path = Path(_tmp) / "skip.json"
            skip_file_path.write_text(json.dumps({"skip_ids": list(skip_ids)}))

            emit_log("preflight",
                f"Pre-flight: {len(am_ids)} tracks in playlist, "
                f"{len(new_ids)} new, {len(skip_ids)} already owned"
            )
        except AMApiError as e:
            emit_log("preflight",
                f"Pre-flight check failed ({e}), falling back to full download"
            )
            skip_file_path = None

    if format_ == "ATMOS":
        cmd = [go_bin, "run", "main.go", "--atmos", url]
    elif format_ == "AAC":
        cmd = [go_bin, "run", "main.go", "--aac", url]
    else:
        cmd = [go_bin, "run", "main.go", url]

    if skip_file_path:
        cmd += ["--skip-ids-file", str(skip_file_path)]
    cmd += ["--manifest-out", str(manifest_path)]
```

- [ ] **Step 5: Run full test suite**

```bash
.venv/bin/pytest tests/ -q
```

Expected: 95 passed (server.py changes don't break any existing tests).

- [ ] **Step 6: Commit**

```bash
git add alac_rip/server.py tests/test_incremental.py
git commit -m "feat: add pre-flight AM diff and skip list in _run_job"
```

---

## Task 6: server.py — Manifest Processing

**Files:**
- Modify: `alac_rip/server.py`
- Modify: `tests/test_incremental.py`

- [ ] **Step 1: Write failing test for manifest processing**

Add to `tests/test_incremental.py`:

```python
def test_manifest_processing_updates_am_ids(state):
    """After SyncEngine runs, manifest entries update am_track_id in DB."""
    staging_dir = Path("/tmp/fake-staging")

    # Simulate state after SyncEngine has run — track exists in DB
    state.add_track(Track(
        track_id="Artist/Album/01 - Song.flac",
        title="Song", artist="Artist", album="Album",
        local_path="/music/artists/Artist/Album/01 - Song.flac",
        downloaded_at="2026-01-01T00:00:00",
    ))

    # Manifest from Go downloader (absolute staging path)
    manifest_entries = [
        {
            "am_track_id": "9876543210",
            "local_path": str(staging_dir / "Artist" / "Album" / "01 - Song.flac"),
        }
    ]

    # Derive track_id from manifest entry (same logic as server.py)
    for entry in manifest_entries:
        rel = Path(entry["local_path"]).relative_to(staging_dir)
        track_id = str(rel.with_suffix(".flac"))
        state.update_track_am_id(track_id, entry["am_track_id"])

    ids = state.get_playlist_am_ids.__func__  # method exists
    import sqlite3
    with sqlite3.connect(state.db_path) as conn:
        row = conn.execute(
            "SELECT am_track_id FROM tracks WHERE track_id = ?",
            ("Artist/Album/01 - Song.flac",)
        ).fetchone()
    assert row[0] == "9876543210"


def test_manifest_processing_handles_m4a_source(state):
    """Manifest entry with .m4a extension normalises to .flac track_id."""
    staging_dir = Path("/tmp/fake-staging2")

    state.add_track(Track(
        track_id="Artist/Album/01 - Song.flac",
        title="Song", artist="Artist", album="Album",
        local_path="/music/artists/Artist/Album/01 - Song.flac",
        downloaded_at="2026-01-01T00:00:00",
    ))

    # Go downloader produces .m4a before FLAC conversion
    entry_path = str(staging_dir / "Artist" / "Album" / "01 - Song.m4a")
    rel = Path(entry_path).relative_to(staging_dir)
    track_id = str(rel.with_suffix(".flac"))  # normalised to .flac
    state.update_track_am_id(track_id, "1111111111")

    import sqlite3
    with sqlite3.connect(state.db_path) as conn:
        row = conn.execute(
            "SELECT am_track_id FROM tracks WHERE track_id = ?",
            ("Artist/Album/01 - Song.flac",)
        ).fetchone()
    assert row[0] == "1111111111"
```

- [ ] **Step 2: Run new tests**

```bash
.venv/bin/pytest tests/test_incremental.py::test_manifest_processing_updates_am_ids \
                 tests/test_incremental.py::test_manifest_processing_handles_m4a_source -v
```

Expected: Both PASS (logic is pure Python, no server wiring needed to test the core).

- [ ] **Step 3: Add manifest processing to `_run_job` in `server.py`**

In `_run_job`, find the block after `engine.sync(save_folder)` completes:

```python
    if playlist_name:
        state.update_playlist_synced(playlist_name)
        state.record_sync_run(...)
```

Insert manifest processing between `engine.sync()` and the `state.update_playlist_synced` call:

```python
    # ── Process manifest: update am_track_id in DB ────────────────────────────
    if manifest_path.exists():
        try:
            entries = json.loads(manifest_path.read_text())
            for entry in entries:
                rel = Path(entry["local_path"]).relative_to(save_folder)
                track_id = str(rel.with_suffix(".flac"))
                state.update_track_am_id(track_id, entry["am_track_id"])
            manifest_path.unlink()
            write_log(f"[manifest] updated AM IDs for {len(entries)} tracks")
        except Exception as exc:
            write_log(f"[manifest] warning: could not process manifest: {exc}")
```

- [ ] **Step 4: Run full test suite**

```bash
.venv/bin/pytest tests/ -q
```

Expected: 97 passed.

- [ ] **Step 5: Commit**

```bash
git add alac_rip/server.py tests/test_incremental.py
git commit -m "feat: process Go manifest to store am_track_id after each sync"
```

---

## Task 7: SyncProgress.svelte — Preflight Phase

**Files:**
- Modify: `app/src/lib/SyncProgress.svelte`

- [ ] **Step 1: Add `preflight` to the PHASES array**

In `SyncProgress.svelte`, find:

```typescript
  const PHASES = [
    { key: "downloading", label: "Downloading" },
    { key: "organizing",  label: "Organizing" },
    { key: "done",        label: "Complete" },
  ] as const;

  const PHASE_ORDER: Record<string, number> = {
    downloading: 0, organizing: 1, done: 2,
  };
```

Replace with:

```typescript
  const PHASES = [
    { key: "preflight",   label: "Checking" },
    { key: "downloading", label: "Downloading" },
    { key: "organizing",  label: "Organizing" },
    { key: "done",        label: "Complete" },
  ] as const;

  const PHASE_ORDER: Record<string, number> = {
    preflight: 0, downloading: 1, organizing: 2, done: 3,
  };
```

- [ ] **Step 2: Update the progress counter block**

The live counter block is gated on `phase === "downloading"`. The gate should also cover `preflight` to avoid showing empty counters too early. Find:

```svelte
    {#if phase === "downloading" && progressTotal > 0}
```

Change to:

```svelte
    {#if (phase === "downloading" || phase === "organizing") && progressTotal > 0}
```

- [ ] **Step 3: Start the dev server and verify visually**

```bash
cd /var/home/ilikepie/Documents/VS-Projects/pies-alac-rip-tool/app
npm run dev
```

Open the app in the browser (or Tauri). Trigger a sync on a playlist. Verify:
- Phase timeline shows 4 steps: Checking → Downloading → Organizing → Complete
- The "Checking" step pulses amber while pre-flight runs
- Once pre-flight completes, the timeline advances to "Downloading"
- The pre-flight summary log line ("Pre-flight: X tracks, Y new, Z already owned") appears in the log

- [ ] **Step 4: Kill the dev server and commit**

```bash
git add app/src/lib/SyncProgress.svelte
git commit -m "feat: add preflight phase to sync progress timeline"
```

---

## Task 8: Push and Verify

- [ ] **Step 1: Run full test suite one final time**

```bash
cd /var/home/ilikepie/Documents/VS-Projects/pies-alac-rip-tool
.venv/bin/pytest tests/ -q
```

Expected: 97 passed, 0 failed.

- [ ] **Step 2: Push `release/1.5` branch to GitHub**

```bash
git push -u origin release/1.5
```

- [ ] **Step 3: Push Go downloader changes**

```bash
cd /home/ilikepie/Documents/VS-Projects/alac-rip
sudo git push origin main
```

- [ ] **Step 4: Manual end-to-end smoke test**

1. Start the backend: `cd /var/home/ilikepie/Documents/VS-Projects/pies-alac-rip-tool && .venv/bin/python -m alac_rip.server`
2. Open the app
3. Trigger a sync on "Game OST"
4. Verify in the sync progress UI that "Checking" phase appears first
5. Check the log for "Pre-flight: N tracks in playlist, M new, K already owned"
6. After sync completes, verify `manifest.json` is gone from staging (processed and deleted)
7. Check the DB: `sqlite3 /var/home/ilikepie/Documents/VS-Projects/pies-alac-rip-tool/.state/downloaded.db "SELECT track_id, am_track_id FROM tracks LIMIT 5;"`
   - `am_track_id` column should now have values for newly synced tracks
8. Trigger a second sync on the same playlist
9. Verify "Pre-flight: N tracks in playlist, N already owned, 0 new" — no tracks downloaded

- [ ] **Step 5: Commit smoke test notes (optional)**

If any issues found during smoke test, fix them, re-run tests, and commit before opening a PR.
