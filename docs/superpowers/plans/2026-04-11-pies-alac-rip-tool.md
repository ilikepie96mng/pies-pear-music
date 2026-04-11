# pies-alac-rip-tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python CLI tool that syncs Apple Music playlists as ALAC lossless files on Bazzite Linux, organized for Strawberry, with daily auto-sync via systemd and GitHub state backup.

**Architecture:** Python orchestration layer wrapping zhaarey's Go-based `apple-music-downloader` + `wrapper` binary. Playlist state in SQLite. Files tagged with mutagen and organized into `Artist/Album/Track.m4a`. CLI via Typer, scheduling via systemd user timer, state backed up to a private GitHub repo after each sync.

**Tech Stack:** Python 3.12+, Typer, Rich, mutagen, SQLite3, Go (zhaarey downloader), systemd, gh CLI, Bento4/MP4Box, Homebrew

---

## File Map

| File | Responsibility |
|------|----------------|
| `alac_rip/__init__.py` | Package marker, version string |
| `alac_rip/config.py` | Load `~/.config/pies-alac-rip/config.yaml` into a dataclass |
| `alac_rip/state.py` | SQLite: read/write downloaded tracks + tracked playlists |
| `alac_rip/organizer.py` | Canonical file path construction + album dir creation |
| `alac_rip/metadata.py` | mutagen: read tags, write tags, embed cover art, save cover.jpg |
| `alac_rip/downloader.py` | subprocess: start wrapper binary, run Go downloader against a URL |
| `alac_rip/sync.py` | Orchestrate: invoke downloader → scan staging → diff vs DB → move new files → tag |
| `alac_rip/github_sync.py` | git add/commit/push the `.state/` dir after each sync |
| `alac_rip/cli.py` | Typer entrypoint: `music-sync`, `music-add`, `music-status`, `music-clean` |
| `tests/conftest.py` | Shared pytest fixtures (tmp dirs, sample m4a, mock downloader) |
| `tests/test_config.py` | Config loading from YAML |
| `tests/test_state.py` | SQLite state CRUD |
| `tests/test_organizer.py` | Path construction + sanitization |
| `tests/test_metadata.py` | Tag read/write on a real fixture m4a |
| `tests/test_sync.py` | Sync logic with mocked downloader |
| `install.sh` | Full install: brew deps, Go binary, wrapper, Bento4, venv, systemd, gh auth |
| `uninstall.sh` | Full removal: binaries, venv, systemd units, state dir |
| `systemd/pies-alac-rip.service` | systemd user service |
| `systemd/pies-alac-rip.timer` | systemd user timer (daily at 03:00) |
| `config.yaml.example` | Template — never committed with real token |
| `.gitignore` | Excludes music files, config.yaml, venv, staging |
| `requirements.txt` | Python deps with pinned versions |
| `pyproject.toml` | Package + CLI entrypoint definition |
| `README.md` | Install, first-run, commands |

---

## Task 1: Create GitHub Repo + Project Scaffold

**Files:**
- Create: `pies-alac-rip-tool/` (repo root, wherever user clones)
- Create: `alac_rip/__init__.py`
- Create: `pyproject.toml`
- Create: `requirements.txt`
- Create: `.gitignore`
- Create: `config.yaml.example`

- [ ] **Step 1: Authenticate GitHub CLI and create private repo**

```bash
gh auth login
# follow the browser-based OAuth flow
gh repo create pies-alac-rip-tool --private --clone
cd pies-alac-rip-tool
```

Expected: repo cloned to `./pies-alac-rip-tool/`, remote `origin` points to `git@github.com:<your-username>/pies-alac-rip-tool.git`

- [ ] **Step 2: Create package init**

Create `alac_rip/__init__.py`:
```python
__version__ = "0.1.0"
```

- [ ] **Step 3: Create pyproject.toml**

Create `pyproject.toml`:
```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.backends.legacy:build"

[project]
name = "pies-alac-rip-tool"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "typer>=0.12",
    "rich>=13",
    "mutagen>=1.47",
    "requests>=2.31",
    "textual>=0.60",
    "pyyaml>=6.0",
]

[project.scripts]
music-sync = "alac_rip.cli:app"
music-add = "alac_rip.cli:app"
music-status = "alac_rip.cli:app"
music-clean = "alac_rip.cli:app"

[tool.setuptools.packages.find]
where = ["."]
include = ["alac_rip*"]
```

- [ ] **Step 4: Create requirements.txt**

```
typer==0.12.3
rich==13.7.1
mutagen==1.47.0
requests==2.31.0
textual==0.60.1
pyyaml==6.0.1
pytest==8.2.0
pytest-mock==3.14.0
```

- [ ] **Step 5: Create .gitignore**

Create `.gitignore`:
```
# Python
.venv/
__pycache__/
*.pyc
*.egg-info/
dist/
build/

# App secrets — NEVER commit
config.yaml

# Music files — too large for git
*.m4a
*.flac
*.mp3
*.mp4
*.aac

# Binaries installed by install.sh
.local/

# .state/ is intentionally NOT gitignored — it's committed after each sync
# to back up playlist state to GitHub
```

- [ ] **Step 6: Create config.yaml.example**

Create `config.yaml.example`:
```yaml
# Copy this to ~/.config/pies-alac-rip/config.yaml and fill in values.
# This file is safe to commit. config.yaml (without .example) is gitignored.

# Your Apple Music media-user-token.
# Get it: open Apple Music in browser → DevTools → Application → Cookies → media-user-token
media_user_token: "YOUR_TOKEN_HERE"

# Where to store downloaded music (must exist or be creatable)
music_dir: "~/Music/Apple Music"

# Staging area for in-progress downloads (auto-created)
staging_dir: "~/Music/.staging"

# Path to cloned zhaarey downloader repo
downloader_repo: "~/.local/share/pies-alac-rip/apple-music-downloader"

# Path to wrapper binary
wrapper_bin: "~/.local/share/pies-alac-rip/wrapper"

# Path to state directory — MUST be inside the repo root so git add works.
# install.sh sets this to the absolute path of <repo>/.state automatically.
state_dir: "FILLED_BY_INSTALL_SCRIPT"

# GitHub remote for state sync (set automatically by install.sh)
github_remote: ""
```

- [ ] **Step 7: Create directory structure and initial commit**

```bash
mkdir -p alac_rip tests systemd docs/superpowers/{specs,plans}
touch tests/__init__.py
git add .
git commit -m "chore: initial project scaffold"
git push -u origin main
```

Expected: push succeeds, repo visible at `https://github.com/<username>/pies-alac-rip-tool`

---

## Task 2: Install Script — Dependencies + Download Core

**Files:**
- Create: `install.sh`

**Context:** This script is run once on a fresh system. It installs all system deps via brew, downloads the zhaarey Go downloader and builds it, fetches the wrapper binary, downloads Bento4, sets up the Python venv, installs the CLI, installs systemd units, and prompts for token setup.

- [ ] **Step 1: Create install.sh**

Create `install.sh`:
```bash
#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="$HOME/.local/share/pies-alac-rip"
CONFIG_DIR="$HOME/.config/pies-alac-rip"
SYSTEMD_DIR="$HOME/.config/systemd/user"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> Installing pies-alac-rip-tool"

# 1. Brew dependencies
echo "==> Installing brew dependencies..."
brew install go gh ffmpeg gpac wget

# 2. Create directories
mkdir -p "$INSTALL_DIR" "$CONFIG_DIR" "$HOME/.local/bin"

# 3. Clone and build zhaarey apple-music-downloader
if [ ! -d "$INSTALL_DIR/apple-music-downloader" ]; then
    echo "==> Cloning zhaarey/apple-music-downloader..."
    git clone https://github.com/zhaarey/apple-music-downloader "$INSTALL_DIR/apple-music-downloader"
fi
echo "==> Building Go downloader..."
cd "$INSTALL_DIR/apple-music-downloader"
go build -o apple-music-dl .
cd "$SCRIPT_DIR"

# 4. Download wrapper binary
# The wrapper binary is the decryption service used by the downloader.
# Source: https://github.com/zhaarey/wrapper (check releases page for latest URL)
WRAPPER_URL="https://github.com/zhaarey/wrapper/releases/latest/download/wrapper-linux-amd64"
if [ ! -f "$INSTALL_DIR/wrapper" ]; then
    echo "==> Downloading wrapper binary..."
    wget -q -O "$INSTALL_DIR/wrapper" "$WRAPPER_URL"
    chmod +x "$INSTALL_DIR/wrapper"
fi

# 5. Download and set up Bento4
BENTO4_VERSION="1-6-0-641"
BENTO4_DIR="$INSTALL_DIR/bento4"
if [ ! -d "$BENTO4_DIR" ]; then
    echo "==> Downloading Bento4..."
    BENTO4_ZIP="/tmp/bento4.zip"
    wget -q -O "$BENTO4_ZIP" \
        "https://www.bok.net/Bento4/binaries/Bento4-SDK-${BENTO4_VERSION}.x86_64-unknown-linux.zip"
    mkdir -p "$BENTO4_DIR"
    unzip -q "$BENTO4_ZIP" -d "$BENTO4_DIR"
    rm "$BENTO4_ZIP"
    # Symlink MP4Box to ~/.local/bin
    find "$BENTO4_DIR" -name "mp4box" -exec ln -sf {} "$HOME/.local/bin/mp4box" \;
fi

# 6. Write zhaarey downloader config (with token placeholder — user fills in)
DOWNLOADER_CONFIG="$INSTALL_DIR/apple-music-downloader/config.yaml"
if [ ! -f "$DOWNLOADER_CONFIG" ]; then
    cat > "$DOWNLOADER_CONFIG" <<'EOF'
media-user-token: "FILL_IN_YOUR_TOKEN"
EOF
fi

# 7. Set up Python venv and install package
echo "==> Setting up Python venv..."
cd "$SCRIPT_DIR"
python3 -m venv .venv
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -e .

# 8. Create wrapper shims in ~/.local/bin
cat > "$HOME/.local/bin/music-sync" <<EOF
#!/usr/bin/env bash
exec "$SCRIPT_DIR/.venv/bin/music-sync" "\$@"
EOF
chmod +x "$HOME/.local/bin/music-sync"

# 9. Install systemd user units
echo "==> Installing systemd units..."
mkdir -p "$SYSTEMD_DIR"
# Inject the correct path into the service file
sed "s|SCRIPT_DIR|$SCRIPT_DIR|g" "$SCRIPT_DIR/systemd/pies-alac-rip.service" \
    > "$SYSTEMD_DIR/pies-alac-rip.service"
cp "$SCRIPT_DIR/systemd/pies-alac-rip.timer" "$SYSTEMD_DIR/pies-alac-rip.timer"
systemctl --user daemon-reload
systemctl --user enable pies-alac-rip.timer

# 10. Create user config from example, filling in install-time paths
mkdir -p "$SCRIPT_DIR/.state"
if [ ! -f "$CONFIG_DIR/config.yaml" ]; then
    sed \
        -e "s|FILLED_BY_INSTALL_SCRIPT|$SCRIPT_DIR/.state|g" \
        "$SCRIPT_DIR/config.yaml.example" > "$CONFIG_DIR/config.yaml"
    # Also patch downloader_repo and wrapper_bin to real paths
    sed -i \
        -e "s|~/.local/share/pies-alac-rip/apple-music-downloader|$INSTALL_DIR/apple-music-downloader|g" \
        -e "s|~/.local/share/pies-alac-rip/wrapper|$INSTALL_DIR/wrapper|g" \
        "$CONFIG_DIR/config.yaml"
    echo ""
    echo "======================================================"
    echo "  Config created at: $CONFIG_DIR/config.yaml"
    echo "  ACTION REQUIRED: Add your Apple Music media-user-token"
    echo "======================================================"
fi

echo ""
echo "==> Install complete."
echo "  Next steps:"
echo "  1. Edit $CONFIG_DIR/config.yaml — add your media-user-token"
echo "  2. Also update $INSTALL_DIR/apple-music-downloader/config.yaml with the same token"
echo "  3. Run: music-add <your-apple-music-playlist-url>"
echo "  4. Run: music-sync"
```

- [ ] **Step 2: Make install.sh executable and commit**

```bash
chmod +x install.sh
git add install.sh config.yaml.example
git commit -m "feat: add install script with brew deps, Go downloader, wrapper, Bento4"
git push
```

**Discovery note:** During first real run, verify:
- The wrapper binary URL is correct (check `https://github.com/zhaarey/wrapper/releases`)
- The Bento4 version string matches the download URL format
- The Go downloader builds successfully (`go build` vs `go run`)
- Update install.sh with the correct URLs before marking this task done.

---

## Task 3: Config Module + Tests

**Files:**
- Create: `alac_rip/config.py`
- Create: `tests/test_config.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Write failing tests**

Create `tests/conftest.py`:
```python
import pytest
from pathlib import Path


@pytest.fixture
def tmp_config(tmp_path):
    """Write a minimal config.yaml to a temp dir and return its path."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        "media_user_token: 'test-token-abc'\n"
        "music_dir: '~/Music/Apple Music'\n"
        "staging_dir: '~/Music/.staging'\n"
        "downloader_repo: '~/.local/share/pies-alac-rip/apple-music-downloader'\n"
        "wrapper_bin: '~/.local/share/pies-alac-rip/wrapper'\n"
        "state_dir: '~/Music/Apple Music/.state'\n"
        "github_remote: 'git@github.com:user/pies-alac-rip-tool.git'\n"
    )
    return config_file
```

Create `tests/test_config.py`:
```python
from pathlib import Path
from alac_rip.config import load_config, Config


def test_load_config_returns_config_dataclass(tmp_config):
    cfg = load_config(tmp_config)
    assert isinstance(cfg, Config)


def test_load_config_reads_token(tmp_config):
    cfg = load_config(tmp_config)
    assert cfg.media_user_token == "test-token-abc"


def test_load_config_expands_home_in_music_dir(tmp_config):
    cfg = load_config(tmp_config)
    assert not str(cfg.music_dir).startswith("~")
    assert cfg.music_dir.is_absolute()


def test_load_config_expands_home_in_staging_dir(tmp_config):
    cfg = load_config(tmp_config)
    assert cfg.staging_dir.is_absolute()


def test_load_config_expands_home_in_downloader_repo(tmp_config):
    cfg = load_config(tmp_config)
    assert cfg.downloader_repo.is_absolute()


def test_load_config_expands_home_in_wrapper_bin(tmp_config):
    cfg = load_config(tmp_config)
    assert cfg.wrapper_bin.is_absolute()


def test_load_config_reads_github_remote(tmp_config):
    cfg = load_config(tmp_config)
    assert cfg.github_remote == "git@github.com:user/pies-alac-rip-tool.git"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
.venv/bin/pytest tests/test_config.py -v
```

Expected: `ModuleNotFoundError: No module named 'alac_rip.config'`

- [ ] **Step 3: Implement config.py**

Create `alac_rip/config.py`:
```python
from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "pies-alac-rip" / "config.yaml"


@dataclass
class Config:
    media_user_token: str
    music_dir: Path
    staging_dir: Path
    downloader_repo: Path
    wrapper_bin: Path
    state_dir: Path
    github_remote: str


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> Config:
    with open(path) as f:
        data = yaml.safe_load(f)

    def p(key: str) -> Path:
        return Path(data[key]).expanduser().resolve()

    return Config(
        media_user_token=data["media_user_token"],
        music_dir=p("music_dir"),
        staging_dir=p("staging_dir"),
        downloader_repo=p("downloader_repo"),
        wrapper_bin=p("wrapper_bin"),
        state_dir=p("state_dir"),
        github_remote=data.get("github_remote", ""),
    )
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
.venv/bin/pytest tests/test_config.py -v
```

Expected: 7 tests PASSED

- [ ] **Step 5: Commit**

```bash
git add alac_rip/config.py tests/conftest.py tests/test_config.py
git commit -m "feat: config module with YAML loading and path expansion"
git push
```

---

## Task 4: State Module + Tests

**Files:**
- Create: `alac_rip/state.py`
- Create: `tests/test_state.py`

- [ ] **Step 1: Add fixture to conftest.py**

Add to `tests/conftest.py`:
```python
from alac_rip.state import StateManager

@pytest.fixture
def state(tmp_path):
    """Return a StateManager backed by a temp SQLite DB."""
    db_path = tmp_path / "downloaded.db"
    return StateManager(db_path)
```

- [ ] **Step 2: Write failing tests**

Create `tests/test_state.py`:
```python
from datetime import datetime
from alac_rip.state import StateManager, Track, Playlist


def test_new_track_is_not_downloaded(state):
    assert state.is_downloaded("track-abc-123") is False


def test_add_track_marks_it_downloaded(state):
    track = Track(
        track_id="track-abc-123",
        title="Bohemian Rhapsody",
        artist="Queen",
        album="A Night at the Opera",
        local_path="/Music/Queen/A Night at the Opera/01 - Bohemian Rhapsody.m4a",
        downloaded_at=datetime.now().isoformat(),
    )
    state.add_track(track)
    assert state.is_downloaded("track-abc-123") is True


def test_add_track_idempotent(state):
    track = Track(
        track_id="track-abc-123",
        title="Bohemian Rhapsody",
        artist="Queen",
        album="A Night at the Opera",
        local_path="/Music/Queen/A Night at the Opera/01 - Bohemian Rhapsody.m4a",
        downloaded_at=datetime.now().isoformat(),
    )
    state.add_track(track)
    state.add_track(track)  # second add should not raise
    assert state.is_downloaded("track-abc-123") is True


def test_add_playlist(state):
    state.add_playlist("My Mega Playlist", "https://music.apple.com/playlist/xyz")
    playlists = state.get_playlists()
    assert len(playlists) == 1
    assert playlists[0].name == "My Mega Playlist"
    assert playlists[0].url == "https://music.apple.com/playlist/xyz"
    assert playlists[0].last_synced is None


def test_add_playlist_idempotent(state):
    state.add_playlist("My Mega Playlist", "https://music.apple.com/playlist/xyz")
    state.add_playlist("My Mega Playlist", "https://music.apple.com/playlist/xyz")
    assert len(state.get_playlists()) == 1


def test_update_playlist_synced(state):
    state.add_playlist("My Mega Playlist", "https://music.apple.com/playlist/xyz")
    state.update_playlist_synced("My Mega Playlist")
    playlists = state.get_playlists()
    assert playlists[0].last_synced is not None


def test_downloaded_count(state):
    assert state.get_downloaded_count() == 0
    for i in range(3):
        state.add_track(Track(
            track_id=f"track-{i}",
            title=f"Track {i}",
            artist="Artist",
            album="Album",
            local_path=f"/Music/track-{i}.m4a",
            downloaded_at=datetime.now().isoformat(),
        ))
    assert state.get_downloaded_count() == 3
```

- [ ] **Step 3: Run tests to confirm they fail**

```bash
.venv/bin/pytest tests/test_state.py -v
```

Expected: `ModuleNotFoundError: No module named 'alac_rip.state'`

- [ ] **Step 4: Implement state.py**

Create `alac_rip/state.py`:
```python
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass
class Track:
    track_id: str
    title: str
    artist: str
    album: str
    local_path: str
    downloaded_at: str


@dataclass
class Playlist:
    name: str
    url: str
    last_synced: Optional[str]


class StateManager:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tracks (
                    track_id    TEXT PRIMARY KEY,
                    title       TEXT NOT NULL,
                    artist      TEXT NOT NULL,
                    album       TEXT NOT NULL,
                    local_path  TEXT NOT NULL,
                    downloaded_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS playlists (
                    name        TEXT PRIMARY KEY,
                    url         TEXT NOT NULL,
                    last_synced TEXT
                )
            """)

    def is_downloaded(self, track_id: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM tracks WHERE track_id = ?", (track_id,)
            ).fetchone()
            return row is not None

    def add_track(self, track: Track) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO tracks VALUES (?, ?, ?, ?, ?, ?)",
                (track.track_id, track.title, track.artist,
                 track.album, track.local_path, track.downloaded_at),
            )

    def add_playlist(self, name: str, url: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO playlists VALUES (?, ?, NULL)",
                (name, url),
            )

    def get_playlists(self) -> list[Playlist]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT name, url, last_synced FROM playlists"
            ).fetchall()
            return [Playlist(name=r[0], url=r[1], last_synced=r[2]) for r in rows]

    def update_playlist_synced(self, name: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE playlists SET last_synced = ? WHERE name = ?",
                (datetime.now().isoformat(), name),
            )

    def get_downloaded_count(self) -> int:
        with self._conn() as conn:
            return conn.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]
```

- [ ] **Step 5: Run tests to confirm they pass**

```bash
.venv/bin/pytest tests/test_state.py -v
```

Expected: 8 tests PASSED

- [ ] **Step 6: Commit**

```bash
git add alac_rip/state.py tests/test_state.py tests/conftest.py
git commit -m "feat: SQLite state manager for tracks and playlists"
git push
```

---

## Task 5: Organizer Module + Tests

**Files:**
- Create: `alac_rip/organizer.py`
- Create: `tests/test_organizer.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_organizer.py`:
```python
from pathlib import Path
from alac_rip.organizer import sanitize, track_path, cover_path, ensure_album_dir


def test_sanitize_removes_forbidden_chars():
    assert sanitize('AC/DC') == 'AC_DC'
    assert sanitize('Guns N\' Roses') == "Guns N' Roses"  # apostrophe is allowed
    assert sanitize('Artist: Name') == 'Artist_ Name'


def test_sanitize_strips_whitespace():
    assert sanitize('  Artist  ') == 'Artist'


def test_track_path_structure(tmp_path):
    path = track_path(tmp_path, "Queen", "A Night at the Opera", 1, "Bohemian Rhapsody")
    assert path == tmp_path / "Queen" / "A Night at the Opera" / "01 - Bohemian Rhapsody.m4a"


def test_track_path_pads_track_number(tmp_path):
    path = track_path(tmp_path, "Artist", "Album", 9, "Track")
    assert path.name == "09 - Track.m4a"
    path2 = track_path(tmp_path, "Artist", "Album", 10, "Track")
    assert path2.name == "10 - Track.m4a"


def test_track_path_sanitizes_artist(tmp_path):
    path = track_path(tmp_path, "AC/DC", "Highway to Hell", 1, "Highway to Hell")
    assert "AC_DC" in str(path)


def test_cover_path_structure(tmp_path):
    path = cover_path(tmp_path, "Queen", "A Night at the Opera")
    assert path == tmp_path / "Queen" / "A Night at the Opera" / "cover.jpg"


def test_ensure_album_dir_creates_directories(tmp_path):
    album_dir = ensure_album_dir(tmp_path, "Queen", "A Night at the Opera")
    assert album_dir.exists()
    assert album_dir.is_dir()
    assert album_dir == tmp_path / "Queen" / "A Night at the Opera"


def test_ensure_album_dir_idempotent(tmp_path):
    ensure_album_dir(tmp_path, "Queen", "A Night at the Opera")
    ensure_album_dir(tmp_path, "Queen", "A Night at the Opera")  # should not raise
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
.venv/bin/pytest tests/test_organizer.py -v
```

Expected: `ModuleNotFoundError: No module named 'alac_rip.organizer'`

- [ ] **Step 3: Implement organizer.py**

Create `alac_rip/organizer.py`:
```python
import re
from pathlib import Path

# Characters forbidden in filenames on Linux and Windows (for portability)
_FORBIDDEN = re.compile(r'[<>:"/\\|?*]')


def sanitize(name: str) -> str:
    """Replace filesystem-unsafe characters with underscores and strip whitespace."""
    return _FORBIDDEN.sub("_", name).strip()


def track_path(music_dir: Path, artist: str, album: str, track_num: int, title: str) -> Path:
    """Return the canonical absolute path for a downloaded track file."""
    return (
        music_dir
        / sanitize(artist)
        / sanitize(album)
        / f"{track_num:02d} - {sanitize(title)}.m4a"
    )


def cover_path(music_dir: Path, artist: str, album: str) -> Path:
    """Return the canonical path for cover.jpg in an album directory."""
    return music_dir / sanitize(artist) / sanitize(album) / "cover.jpg"


def ensure_album_dir(music_dir: Path, artist: str, album: str) -> Path:
    """Create Artist/Album directory tree if it doesn't exist. Returns the album dir path."""
    album_dir = music_dir / sanitize(artist) / sanitize(album)
    album_dir.mkdir(parents=True, exist_ok=True)
    return album_dir
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
.venv/bin/pytest tests/test_organizer.py -v
```

Expected: 8 tests PASSED

- [ ] **Step 5: Commit**

```bash
git add alac_rip/organizer.py tests/test_organizer.py
git commit -m "feat: file organizer — path construction and sanitization"
git push
```

---

## Task 6: Metadata Module + Tests

**Files:**
- Create: `alac_rip/metadata.py`
- Create: `tests/test_metadata.py`
- Create: `tests/fixtures/` (directory for a minimal valid .m4a fixture)

**Note:** This task requires a minimal valid `.m4a` file as a test fixture. The simplest approach: generate one using `ffmpeg` during test setup. This avoids committing binary files to git.

- [ ] **Step 1: Add m4a fixture to conftest.py**

Add to `tests/conftest.py`:
```python
import subprocess

@pytest.fixture
def sample_m4a(tmp_path):
    """Generate a minimal valid M4A file using ffmpeg for testing metadata operations."""
    m4a_path = tmp_path / "test_track.m4a"
    subprocess.run(
        [
            "ffmpeg", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-c:a", "alac", "-y", str(m4a_path),
        ],
        check=True,
        capture_output=True,
    )
    return m4a_path
```

- [ ] **Step 2: Write failing tests**

Create `tests/test_metadata.py`:
```python
from alac_rip.metadata import read_tags, write_tags, embed_cover_art, save_cover_file


def test_write_and_read_tags(sample_m4a):
    write_tags(sample_m4a, title="Bohemian Rhapsody", artist="Queen",
               album="A Night at the Opera", track_num=1, playlist_name="Mega Playlist")
    tags = read_tags(sample_m4a)
    assert tags["title"] == "Bohemian Rhapsody"
    assert tags["artist"] == "Queen"
    assert tags["album"] == "A Night at the Opera"
    assert tags["track_num"] == 1


def test_embed_cover_art_does_not_raise(sample_m4a):
    # 1x1 white JPEG in bytes
    jpeg_bytes = (
        b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00'
        b'\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t'
        b'\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a'
        b'\x1f\x1e\x1d\x1a\x1c\x1c $.\' ",#\x1c\x1c(7),01444\x1f\'9=82<.342\x1e!'
        b'11=36=\x1bF\x1b2;\x1b F7\x1c!!!\x1c\x1f\x1f\x1e\x1f""\x1d\xff\xc0'
        b'\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x1f\x00'
        b'\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00'
        b'\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xff\xc4\x00\xb5\x10'
        b'\x00\x02\x01\x03\x03\x02\x04\x03\x05\x05\x04\x04\x00\x00\x01}'
        b'\x01\x02\x03\x00\x04\x11\x05\x12!1A\x06\x13Qa\x07"q\x142\x81\x91'
        b'\xa1\x08#B\xb1\xc1\x15R\xd1\xf0$3br\x82\t\n\x16\x17\x18\x19\x1a'
        b'%&\'()*456789:CDEFGHIJSTUVWXYZcdefghijstuvwxyz\x83\x84\x85\x86\x87'
        b'\x88\x89\x8a\x92\x93\x94\x95\x96\x97\x98\x99\x9a\xa2\xa3\xa4\xa5'
        b'\xa6\xa7\xa8\xa9\xaa\xb2\xb3\xb4\xb5\xb6\xb7\xb8\xb9\xba\xc2\xc3'
        b'\xc4\xc5\xc6\xc7\xc8\xc9\xca\xd2\xd3\xd4\xd5\xd6\xd7\xd8\xd9\xda'
        b'\xe1\xe2\xe3\xe4\xe5\xe6\xe7\xe8\xe9\xea\xf1\xf2\xf3\xf4\xf5\xf6'
        b'\xf7\xf8\xf9\xfa\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xfb\xd4P\x00'
        b'\x00\x00\x1f\xff\xd9'
    )
    embed_cover_art(sample_m4a, jpeg_bytes)  # should not raise


def test_save_cover_file(tmp_path):
    cover_bytes = b"fake-jpeg-data"
    out = tmp_path / "cover.jpg"
    save_cover_file(out, cover_bytes)
    assert out.exists()
    assert out.read_bytes() == cover_bytes
```

- [ ] **Step 3: Run tests to confirm they fail**

```bash
.venv/bin/pytest tests/test_metadata.py -v
```

Expected: `ModuleNotFoundError: No module named 'alac_rip.metadata'`

- [ ] **Step 4: Implement metadata.py**

Create `alac_rip/metadata.py`:
```python
from pathlib import Path

from mutagen.mp4 import MP4, MP4Cover


def read_tags(file_path: Path) -> dict:
    """Read metadata tags from an M4A file.

    Returns dict with keys: title, artist, album, track_num (int).
    Missing tags return empty string or 0.
    """
    audio = MP4(file_path)
    tags = audio.tags or {}
    track_info = tags.get("trkn", [(0, 0)])[0]
    return {
        "title": str(tags.get("©nam", [""])[0]),
        "artist": str(tags.get("©ART", [""])[0]),
        "album": str(tags.get("©alb", [""])[0]),
        "track_num": int(track_info[0]) if track_info else 0,
    }


def write_tags(
    file_path: Path,
    title: str,
    artist: str,
    album: str,
    track_num: int,
    playlist_name: str,
) -> None:
    """Write metadata tags to an M4A file. Overwrites existing tags."""
    audio = MP4(file_path)
    if audio.tags is None:
        audio.add_tags()
    audio.tags["©nam"] = [title]
    audio.tags["©ART"] = [artist]
    audio.tags["©alb"] = [album]
    audio.tags["trkn"] = [(track_num, 0)]
    audio.tags["©gen"] = [playlist_name]
    audio.save()


def embed_cover_art(file_path: Path, cover_data: bytes) -> None:
    """Embed cover art JPEG into an M4A file, replacing any existing cover."""
    audio = MP4(file_path)
    if audio.tags is None:
        audio.add_tags()
    audio.tags["covr"] = [MP4Cover(cover_data, imageformat=MP4Cover.FORMAT_JPEG)]
    audio.save()


def save_cover_file(cover_path: Path, cover_data: bytes) -> None:
    """Write cover art bytes to a cover.jpg file on disk."""
    cover_path.write_bytes(cover_data)
```

- [ ] **Step 5: Run tests to confirm they pass**

```bash
.venv/bin/pytest tests/test_metadata.py -v
```

Expected: 3 tests PASSED

- [ ] **Step 6: Commit**

```bash
git add alac_rip/metadata.py tests/test_metadata.py tests/conftest.py
git commit -m "feat: metadata module — mutagen tag read/write and cover art embedding"
git push
```

---

## Task 7: Downloader Module

**Files:**
- Create: `alac_rip/downloader.py`

**Note:** The downloader shells out to real binaries — no unit tests here. Correctness is validated in Task 14 (first real sync). This task focuses on a clean subprocess interface.

- [ ] **Step 1: Create downloader.py**

Create `alac_rip/downloader.py`:
```python
import os
import subprocess
import time
from pathlib import Path
from typing import Optional


class DownloadError(Exception):
    pass


class Downloader:
    """Wraps zhaarey's apple-music-downloader Go binary and the wrapper decryption service."""

    def __init__(
        self,
        downloader_repo: Path,
        wrapper_bin: Path,
        media_user_token: str,
    ):
        self.downloader_repo = downloader_repo
        self.wrapper_bin = wrapper_bin
        self.media_user_token = media_user_token
        self._wrapper_proc: Optional[subprocess.Popen] = None

    def _write_downloader_config(self) -> None:
        """Write the zhaarey downloader's config.yaml with the current media-user-token."""
        config_path = self.downloader_repo / "config.yaml"
        config_path.write_text(f"media-user-token: {self.media_user_token!r}\n")

    def start_wrapper(self) -> None:
        """Start the wrapper decryption service in the background."""
        if self._wrapper_proc and self._wrapper_proc.poll() is None:
            return  # already running
        self._wrapper_proc = subprocess.Popen(
            [str(self.wrapper_bin)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(1)  # give wrapper a moment to bind its port

    def stop_wrapper(self) -> None:
        """Stop the wrapper decryption service."""
        if self._wrapper_proc and self._wrapper_proc.poll() is None:
            self._wrapper_proc.terminate()
            self._wrapper_proc.wait(timeout=5)
        self._wrapper_proc = None

    def download_playlist(self, playlist_url: str) -> Path:
        """
        Download all tracks from an Apple Music playlist URL.

        The zhaarey downloader writes output to ./downloads/ relative to its repo dir.
        Returns the path to that downloads directory.

        Raises DownloadError if the downloader exits with a non-zero status.
        """
        self._write_downloader_config()

        result = subprocess.run(
            ["go", "run", "main.go", playlist_url],
            cwd=str(self.downloader_repo),
            capture_output=True,
            text=True,
            env={**os.environ, "HOME": str(Path.home())},
        )

        if result.returncode != 0:
            raise DownloadError(
                f"Downloader exited with code {result.returncode}.\n"
                f"stderr: {result.stderr}\n"
                f"stdout: {result.stdout}"
            )

        downloads_dir = self.downloader_repo / "downloads"
        if not downloads_dir.exists():
            raise DownloadError(
                f"Downloader succeeded but ./downloads/ dir not found at {downloads_dir}. "
                "Check the downloader's actual output directory."
            )

        return downloads_dir
```

- [ ] **Step 2: Commit**

```bash
git add alac_rip/downloader.py
git commit -m "feat: downloader module — subprocess wrapper for Go binary and wrapper service"
git push
```

---

## Task 8: Sync Engine + Tests

**Files:**
- Create: `alac_rip/sync.py`
- Create: `tests/test_sync.py`

**Context:** The sync engine is the heart of the app. It calls the downloader, scans the output, compares against the DB, and moves+tags new files. Tests mock the downloader to avoid needing real Apple Music credentials.

- [ ] **Step 1: Write failing tests**

Create `tests/test_sync.py`:
```python
import shutil
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from alac_rip.organizer import track_path
from alac_rip.state import StateManager, Track
from alac_rip.sync import SyncEngine


@pytest.fixture
def music_dir(tmp_path):
    d = tmp_path / "Music" / "Apple Music"
    d.mkdir(parents=True)
    return d


@pytest.fixture
def downloads_dir(tmp_path):
    """Simulate a downloads dir the Go downloader would produce."""
    d = tmp_path / "downloads"
    d.mkdir()
    return d


@pytest.fixture
def state(tmp_path):
    return StateManager(tmp_path / "downloaded.db")


@pytest.fixture
def mock_downloader(downloads_dir):
    dl = MagicMock()
    dl.download_playlist.return_value = downloads_dir
    dl.start_wrapper = MagicMock()
    dl.stop_wrapper = MagicMock()
    return dl


def make_fake_m4a(path: Path, title: str, artist: str, album: str, track_num: int) -> Path:
    """Write a tiny but valid M4A via ffmpeg."""
    import subprocess
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.1",
         "-c:a", "alac", "-y", str(path)],
        check=True, capture_output=True,
    )
    # Write minimal tags so read_tags works
    from alac_rip.metadata import write_tags
    write_tags(path, title=title, artist=artist, album=album,
               track_num=track_num, playlist_name="Test Playlist")
    return path


def test_sync_moves_new_tracks_to_music_dir(music_dir, downloads_dir, state, mock_downloader):
    # Arrange: one track in downloads, none in DB
    fake = make_fake_m4a(
        downloads_dir / "Queen" / "A Night at the Opera" / "01 - Bohemian Rhapsody.m4a",
        title="Bohemian Rhapsody", artist="Queen",
        album="A Night at the Opera", track_num=1,
    )

    engine = SyncEngine(
        downloader=mock_downloader,
        state=state,
        music_dir=music_dir,
        playlist_name="Test Playlist",
    )
    engine.sync("https://music.apple.com/playlist/xyz")

    dest = music_dir / "Queen" / "A Night at the Opera" / "01 - Bohemian Rhapsody.m4a"
    assert dest.exists()


def test_sync_records_track_in_db(music_dir, downloads_dir, state, mock_downloader):
    make_fake_m4a(
        downloads_dir / "Queen" / "A Night at the Opera" / "01 - Bohemian Rhapsody.m4a",
        title="Bohemian Rhapsody", artist="Queen",
        album="A Night at the Opera", track_num=1,
    )

    engine = SyncEngine(
        downloader=mock_downloader,
        state=state,
        music_dir=music_dir,
        playlist_name="Test Playlist",
    )
    engine.sync("https://music.apple.com/playlist/xyz")

    assert state.get_downloaded_count() == 1


def test_sync_skips_already_downloaded_tracks(music_dir, downloads_dir, state, mock_downloader):
    # Arrange: put track in DB first
    state.add_track(Track(
        track_id="Queen/A Night at the Opera/01 - Bohemian Rhapsody.m4a",
        title="Bohemian Rhapsody", artist="Queen",
        album="A Night at the Opera",
        local_path=str(music_dir / "Queen" / "A Night at the Opera" / "01 - Bohemian Rhapsody.m4a"),
        downloaded_at=datetime.now().isoformat(),
    ))

    make_fake_m4a(
        downloads_dir / "Queen" / "A Night at the Opera" / "01 - Bohemian Rhapsody.m4a",
        title="Bohemian Rhapsody", artist="Queen",
        album="A Night at the Opera", track_num=1,
    )

    engine = SyncEngine(
        downloader=mock_downloader,
        state=state,
        music_dir=music_dir,
        playlist_name="Test Playlist",
    )
    result = engine.sync("https://music.apple.com/playlist/xyz")

    assert result.new_count == 0
    assert result.skipped_count == 1


def test_sync_returns_summary(music_dir, downloads_dir, state, mock_downloader):
    make_fake_m4a(
        downloads_dir / "Queen" / "A Night at the Opera" / "01 - Bohemian Rhapsody.m4a",
        title="Bohemian Rhapsody", artist="Queen",
        album="A Night at the Opera", track_num=1,
    )
    engine = SyncEngine(
        downloader=mock_downloader,
        state=state,
        music_dir=music_dir,
        playlist_name="Test Playlist",
    )
    result = engine.sync("https://music.apple.com/playlist/xyz")
    assert result.new_count == 1
    assert result.skipped_count == 0
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
.venv/bin/pytest tests/test_sync.py -v
```

Expected: `ModuleNotFoundError: No module named 'alac_rip.sync'`

- [ ] **Step 3: Implement sync.py**

Create `alac_rip/sync.py`:
```python
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from alac_rip.downloader import Downloader
from alac_rip.metadata import read_tags, write_tags
from alac_rip.organizer import ensure_album_dir, track_path
from alac_rip.state import StateManager, Track


@dataclass
class SyncResult:
    new_count: int
    skipped_count: int
    error_count: int


class SyncEngine:
    def __init__(
        self,
        downloader: Downloader,
        state: StateManager,
        music_dir: Path,
        playlist_name: str,
    ):
        self.downloader = downloader
        self.state = state
        self.music_dir = music_dir
        self.playlist_name = playlist_name

    def _track_id(self, relative_path: str) -> str:
        """Derive a stable track ID from its relative path in the downloads dir."""
        return relative_path

    def sync(self, playlist_url: str) -> SyncResult:
        """
        Run a full sync for one playlist URL.

        1. Invoke downloader → get downloads_dir
        2. Walk downloads_dir for .m4a files
        3. For each file: if not in DB, move to music_dir + tag + record
        4. Returns SyncResult
        """
        self.downloader.start_wrapper()
        try:
            downloads_dir = self.downloader.download_playlist(playlist_url)
        finally:
            self.downloader.stop_wrapper()

        new_count = 0
        skipped_count = 0
        error_count = 0

        for src in downloads_dir.rglob("*.m4a"):
            relative = str(src.relative_to(downloads_dir))
            track_id = self._track_id(relative)

            if self.state.is_downloaded(track_id):
                skipped_count += 1
                src.unlink()  # discard staging copy
                continue

            try:
                tags = read_tags(src)
                artist = tags["artist"] or "Unknown Artist"
                album = tags["album"] or "Unknown Album"
                title = tags["title"] or src.stem
                track_num = tags["track_num"] or 1

                dest = track_path(self.music_dir, artist, album, track_num, title)
                ensure_album_dir(self.music_dir, artist, album)
                shutil.move(str(src), dest)

                write_tags(dest, title=title, artist=artist, album=album,
                           track_num=track_num, playlist_name=self.playlist_name)

                self.state.add_track(Track(
                    track_id=track_id,
                    title=title,
                    artist=artist,
                    album=album,
                    local_path=str(dest),
                    downloaded_at=datetime.now().isoformat(),
                ))
                new_count += 1

            except Exception:
                error_count += 1

        return SyncResult(new_count=new_count, skipped_count=skipped_count, error_count=error_count)
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
.venv/bin/pytest tests/test_sync.py -v
```

Expected: 4 tests PASSED

- [ ] **Step 5: Commit**

```bash
git add alac_rip/sync.py tests/test_sync.py
git commit -m "feat: sync engine — staging diff, move new tracks, tag metadata"
git push
```

---

## Task 9: GitHub Sync Module

**Files:**
- Create: `alac_rip/github_sync.py`

- [ ] **Step 1: Create github_sync.py**

Create `alac_rip/github_sync.py`:
```python
import subprocess
from datetime import datetime
from pathlib import Path


class GitSyncError(Exception):
    pass


def push_state(repo_root: Path, state_dir: Path, new_count: int) -> None:
    """
    Commit and push the .state/ directory to the GitHub remote.

    repo_root: the root of the pies-alac-rip-tool git repo
    state_dir: path to <repo_root>/.state/ — MUST be inside repo_root
    new_count: number of new tracks downloaded (used in commit message)
    """
    if not state_dir.exists():
        return

    # Verify state_dir is inside repo_root to ensure git add works
    try:
        state_dir.relative_to(repo_root)
    except ValueError:
        raise GitSyncError(
            f"state_dir {state_dir} is not inside repo_root {repo_root}. "
            "Check your config.yaml — state_dir must be set to <repo>/.state by install.sh."
        )

    date_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    message = f"sync: {date_str} — {new_count} new track(s)"

    def run(cmd: list[str]) -> None:
        result = subprocess.run(cmd, cwd=str(repo_root), capture_output=True, text=True)
        if result.returncode != 0:
            raise GitSyncError(
                f"Git command failed: {' '.join(cmd)}\n{result.stderr}"
            )

    # Use repo-relative path so git add always works
    relative = state_dir.relative_to(repo_root)
    run(["git", "add", str(relative)])
    run(["git", "commit", "-m", message])
    run(["git", "push"])
```

- [ ] **Step 2: Commit**

```bash
git add alac_rip/github_sync.py
git commit -m "feat: github sync — commit and push state dir after each sync"
git push
```

---

## Task 10: CLI — music-add + music-status

**Files:**
- Create: `alac_rip/cli.py`

- [ ] **Step 1: Create cli.py with music-add and music-status**

Create `alac_rip/cli.py`:
```python
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from alac_rip.config import load_config, DEFAULT_CONFIG_PATH
from alac_rip.state import StateManager

app = typer.Typer(help="pies-alac-rip-tool — Apple Music lossless sync for Linux")
console = Console()


def _get_state(cfg) -> StateManager:
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    return StateManager(cfg.state_dir / "downloaded.db")


@app.command("add")
def music_add(
    url: str = typer.Argument(..., help="Apple Music playlist URL"),
    name: str = typer.Option(..., "--name", "-n", prompt="Playlist name"),
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c"),
):
    """Start tracking a new playlist."""
    cfg = load_config(config)
    state = _get_state(cfg)
    state.add_playlist(name, url)
    console.print(f"[green]Added playlist:[/green] {name}")
    console.print(f"  URL: {url}")
    console.print(f"  Run [bold]music-sync[/bold] to download it.")


@app.command("status")
def music_status(
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c"),
):
    """Show tracked playlists and library stats."""
    cfg = load_config(config)
    state = _get_state(cfg)

    playlists = state.get_playlists()
    total = state.get_downloaded_count()

    table = Table(title="Tracked Playlists")
    table.add_column("Name", style="cyan")
    table.add_column("Last Synced", style="green")
    table.add_column("URL")

    for pl in playlists:
        table.add_row(
            pl.name,
            pl.last_synced or "[dim]never[/dim]",
            pl.url[:60] + "..." if len(pl.url) > 60 else pl.url,
        )

    console.print(table)
    console.print(f"\n[bold]Total downloaded tracks:[/bold] {total}")
    console.print(f"[bold]Music directory:[/bold] {cfg.music_dir}")


@app.command("clean")
def music_clean(
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """Uninstall: run uninstall.sh from the project root."""
    import subprocess
    from pathlib import Path as P

    if not yes:
        typer.confirm("This will remove all installed binaries and systemd units. Continue?", abort=True)

    uninstall_script = P(__file__).parent.parent / "uninstall.sh"
    if not uninstall_script.exists():
        console.print(f"[red]uninstall.sh not found at {uninstall_script}[/red]")
        raise typer.Exit(1)

    subprocess.run(["bash", str(uninstall_script)], check=True)
```

- [ ] **Step 2: Commit**

```bash
git add alac_rip/cli.py
git commit -m "feat: CLI — music-add, music-status, music-clean commands"
git push
```

---

## Task 11: CLI — music-sync (Wire Everything Together)

**Files:**
- Modify: `alac_rip/cli.py`

- [ ] **Step 1: Add music-sync command to cli.py**

Add this function to `alac_rip/cli.py` (import additions at top of file):

Add to imports at top:
```python
from rich.progress import Progress, SpinnerColumn, TextColumn
from alac_rip.downloader import Downloader
from alac_rip.github_sync import push_state, GitSyncError
from alac_rip.sync import SyncEngine
```

Add the `sync` command after the `add` command:
```python
@app.command("sync")
def music_sync(
    playlist_name: Optional[str] = typer.Argument(None, help="Sync a specific playlist by name (syncs all if omitted)"),
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c"),
):
    """Sync tracked playlists — download new tracks only."""
    cfg = load_config(config)
    state = _get_state(cfg)

    playlists = state.get_playlists()
    if not playlists:
        console.print("[yellow]No playlists tracked yet. Run:[/yellow] music-add <url>")
        raise typer.Exit()

    if playlist_name:
        playlists = [p for p in playlists if p.name == playlist_name]
        if not playlists:
            console.print(f"[red]No playlist named '{playlist_name}'. Run music-status to list tracked playlists.[/red]")
            raise typer.Exit(1)

    downloader = Downloader(
        downloader_repo=cfg.downloader_repo,
        wrapper_bin=cfg.wrapper_bin,
        media_user_token=cfg.media_user_token,
    )

    total_new = 0

    for playlist in playlists:
        console.rule(f"[bold]{playlist.name}[/bold]")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task(f"Downloading {playlist.name}...", total=None)

            engine = SyncEngine(
                downloader=downloader,
                state=state,
                music_dir=cfg.music_dir,
                playlist_name=playlist.name,
            )

            try:
                result = engine.sync(playlist.url)
                state.update_playlist_synced(playlist.name)
                total_new += result.new_count
                progress.update(task, description=f"Done — {result.new_count} new, {result.skipped_count} skipped")
            except Exception as e:
                progress.update(task, description=f"[red]Error: {e}[/red]")
                console.print_exception()

    # Push state to GitHub
    if cfg.github_remote:
        try:
            repo_root = Path(__file__).parent.parent
            push_state(repo_root, cfg.state_dir, total_new)
            console.print("[dim]State pushed to GitHub.[/dim]")
        except GitSyncError as e:
            console.print(f"[yellow]GitHub push failed (non-fatal): {e}[/yellow]")

    console.print(f"\n[bold green]Sync complete.[/bold green] {total_new} new track(s) downloaded.")
```

- [ ] **Step 2: Commit**

```bash
git add alac_rip/cli.py
git commit -m "feat: music-sync command — orchestrates full playlist sync with progress display"
git push
```

---

## Task 12: Systemd Units

**Files:**
- Create: `systemd/pies-alac-rip.service`
- Create: `systemd/pies-alac-rip.timer`

- [ ] **Step 1: Create service unit**

Create `systemd/pies-alac-rip.service`:
```ini
[Unit]
Description=pies-alac-rip-tool — daily Apple Music sync
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
# SCRIPT_DIR is replaced by install.sh with the actual repo path
ExecStart=SCRIPT_DIR/.venv/bin/music-sync
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
```

- [ ] **Step 2: Create timer unit**

Create `systemd/pies-alac-rip.timer`:
```ini
[Unit]
Description=Run pies-alac-rip-tool daily at 03:00

[Timer]
OnCalendar=*-*-* 03:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

- [ ] **Step 3: Verify timer installs correctly (manual)**

After running `install.sh`, check:
```bash
systemctl --user list-timers pies-alac-rip.timer
```

Expected output includes `pies-alac-rip.timer` with a `NEXT` time showing the next 03:00.

- [ ] **Step 4: Commit**

```bash
git add systemd/
git commit -m "feat: systemd user service and timer for daily auto-sync at 03:00"
git push
```

---

## Task 13: Uninstall Script

**Files:**
- Create: `uninstall.sh`

- [ ] **Step 1: Create uninstall.sh**

Create `uninstall.sh`:
```bash
#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="$HOME/.local/share/pies-alac-rip"
CONFIG_DIR="$HOME/.config/pies-alac-rip"
SYSTEMD_DIR="$HOME/.config/systemd/user"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> Uninstalling pies-alac-rip-tool"

# 1. Stop and disable systemd units
systemctl --user stop pies-alac-rip.timer 2>/dev/null || true
systemctl --user disable pies-alac-rip.timer 2>/dev/null || true
rm -f "$SYSTEMD_DIR/pies-alac-rip.service"
rm -f "$SYSTEMD_DIR/pies-alac-rip.timer"
systemctl --user daemon-reload

# 2. Remove binaries
rm -rf "$INSTALL_DIR"

# 3. Remove shim
rm -f "$HOME/.local/bin/music-sync"
rm -f "$HOME/.local/bin/mp4box"

# 4. Remove venv
rm -rf "$SCRIPT_DIR/.venv"

# 5. Remove config (ask first)
if [ -d "$CONFIG_DIR" ]; then
    read -rp "Remove config at $CONFIG_DIR? [y/N] " confirm
    if [[ "$confirm" =~ ^[Yy]$ ]]; then
        rm -rf "$CONFIG_DIR"
        echo "Config removed."
    else
        echo "Config kept at $CONFIG_DIR"
    fi
fi

echo ""
echo "==> Uninstall complete."
echo "  Note: Your music library at ~/Music/Apple Music is untouched."
echo "  Note: The git repo itself is untouched — remove manually if desired."
```

- [ ] **Step 2: Make executable and commit**

```bash
chmod +x uninstall.sh
git add uninstall.sh
git commit -m "feat: uninstall script — removes binaries, venv, systemd units"
git push
```

---

## Task 14: README + First Real Sync Validation

**Files:**
- Create: `README.md`

- [ ] **Step 1: Create README.md**

Create `README.md`:
```markdown
# pies-alac-rip-tool

Download Apple Music lossless (ALAC) files on Linux, organized for Strawberry.

## Requirements

- Bazzite / Fedora Linux
- Homebrew
- Apple Music subscription
- A browser to grab your `media-user-token`

## Install

```bash
git clone git@github.com:<your-username>/pies-alac-rip-tool.git
cd pies-alac-rip-tool
bash install.sh
```

## First-Time Setup

1. Open Apple Music in your browser
2. Open DevTools (F12) → Application → Storage → Cookies
3. Copy the value of `media-user-token`
4. Edit `~/.config/pies-alac-rip/config.yaml` — paste the token
5. Also paste it into `~/.local/share/pies-alac-rip/apple-music-downloader/config.yaml`

## Usage

```bash
# Add a playlist
music-add "https://music.apple.com/your/playlist/url" --name "My Mega Playlist"

# Sync (download new tracks only)
music-sync

# Sync a specific playlist
music-sync "My Mega Playlist"

# Check status
music-status

# Uninstall
music-clean
```

## Scheduling

A systemd user timer runs `music-sync` daily at 03:00 automatically.
Check it with: `systemctl --user status pies-alac-rip.timer`

## Library Location

```
~/Music/Apple Music/
└── Artist/
    └── Album/
        ├── 01 - Track Title.m4a
        └── cover.jpg
```

Point Strawberry at `~/Music/Apple Music` to scan your library.
```

- [ ] **Step 2: Run full test suite**

```bash
.venv/bin/pytest tests/ -v
```

Expected: All tests pass. Note any failures and fix before proceeding.

- [ ] **Step 3: Run install.sh on real system**

```bash
bash install.sh
```

Verify each step completes without error. Fix any URL or path issues in `install.sh` discovered here (wrapper binary URL, Bento4 version, etc.) and commit the fixes.

- [ ] **Step 4: First real sync**

```bash
music-add "https://music.apple.com/your-actual-playlist-url" --name "My Mega Playlist"
music-sync
```

Verify:
- Wrapper binary starts without error
- Downloader authenticates and begins fetching
- Files appear in `~/Music/Apple Music/`
- Files are named `Artist/Album/NN - Title.m4a`
- `music-status` shows the playlist with a last-synced timestamp
- State directory committed and pushed to GitHub

- [ ] **Step 5: Final commit**

```bash
git add README.md
git commit -m "docs: README with install and usage instructions"
git push
```

---

## Post-Implementation Notes

- **Track ID strategy:** The current implementation uses the relative file path as track ID. If the downloader changes its directory structure between runs, tracks may re-download. If this happens, switch to reading the Apple Music track ID from the embedded metadata (tag key `apID` or similar) and update `sync.py:_track_id()` accordingly.
- **Rate limiting:** For a 2000+ track playlist, the downloader may be slow or get throttled. On first sync, expect this to take a long time. Subsequent syncs (new tracks only) will be fast.
- **Cover art:** The zhaarey downloader may already embed cover art in the downloaded files. If `read_tags()` shows `covr` is populated, skip the `embed_cover_art()` call in sync.py to avoid re-encoding.
