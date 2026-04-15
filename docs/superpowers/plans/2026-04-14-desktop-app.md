# Desktop App Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Tauri 2.x desktop app around the existing Apple Music sync pipeline — a FastAPI sidecar serves the existing Python modules, a Svelte 5 + Tailwind frontend delivers a dark music-app UI.

**Architecture:** Python FastAPI server (`alac_rip/server.py`) wraps existing modules with no changes to them. Rust (`app/src-tauri`) spawns Python on startup, reads the auto-assigned port, and kills it on close. Svelte UI communicates with Python via plain HTTP/SSE, receiving the port from Rust via one Tauri command.

**Tech Stack:** Python 3.12+, FastAPI ≥0.111, uvicorn ≥0.29, Tauri 2.x, Rust stable, Svelte 5, Tailwind CSS 3, Node 20+

---

## File Map

| File | Status | Responsibility |
|------|--------|----------------|
| `alac_rip/server.py` | **NEW** | FastAPI app — all endpoints, SSE sync stream, port selection |
| `requirements.txt` | **MODIFY** | Add fastapi, uvicorn, httpx |
| `tests/test_server.py` | **NEW** | FastAPI endpoint tests via TestClient |
| `app/` | **NEW** | Tauri project root (created by scaffold command) |
| `app/src-tauri/src/lib.rs` | **MODIFY** | Spawn Python sidecar, expose `get_api_port` Tauri command |
| `app/src-tauri/Cargo.toml` | **MODIFY** | Add `ureq = "2"` dependency |
| `app/src-tauri/tauri.conf.json` | **MODIFY** | App name, window size |
| `app/src/api.ts` | **NEW** | All HTTP calls — single module, typed |
| `app/src/App.svelte` | **MODIFY** | Root layout: sidebar + view router |
| `app/src/lib/Sidebar.svelte` | **NEW** | Playlist list, add/remove, Sync All button |
| `app/src/lib/Library.svelte` | **NEW** | Cover art grid for a playlist |
| `app/src/lib/SyncProgress.svelte` | **NEW** | SSE-driven live sync display |
| `app/src/lib/Settings.svelte` | **NEW** | Config editor |

---

## Task 1: FastAPI skeleton — port selection and health endpoint

**Files:**
- Create: `alac_rip/server.py`
- Create: `tests/test_server.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_server.py
from fastapi.testclient import TestClient
from alac_rip.server import app

client = TestClient(app)


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
```

- [ ] **Step 2: Run to confirm it fails**

```bash
cd /home/ilikepie/Documents/VS-Projects/pies-alac-rip-tool
source .venv/bin/activate
pytest tests/test_server.py::test_health -v
```

Expected: `ModuleNotFoundError: No module named 'alac_rip.server'`

- [ ] **Step 3: Install new dependencies**

```bash
pip install "fastapi>=0.111" "uvicorn>=0.29" "httpx>=0.27"
pip freeze | grep -E "fastapi|uvicorn|httpx|anyio|starlette" >> requirements.txt
```

- [ ] **Step 4: Create `alac_rip/server.py`**

```python
import json
import socket
import sqlite3
import threading
from pathlib import Path
from typing import Optional

import uvicorn
import yaml
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from mutagen.mp4 import MP4, MP4Cover
from pydantic import BaseModel

from alac_rip.config import DEFAULT_CONFIG_PATH, load_config
from alac_rip.downloader import Downloader
from alac_rip.state import StateManager
from alac_rip.sync import SyncEngine

app = FastAPI(title="pies-alac-rip")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

cfg = load_config(DEFAULT_CONFIG_PATH)
cfg.state_dir.mkdir(parents=True, exist_ok=True)
state = StateManager(cfg.state_dir / "downloaded.db")


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    Path("/tmp/pies-alac-rip.port").write_text(str(port))
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
```

- [ ] **Step 5: Run test — expect pass**

```bash
pytest tests/test_server.py::test_health -v
```

Expected: `PASSED`

- [ ] **Step 6: Commit**

```bash
git add alac_rip/server.py tests/test_server.py requirements.txt
git commit -m "feat: FastAPI server skeleton with health endpoint"
```

---

## Task 2: Playlists CRUD endpoints

**Files:**
- Modify: `alac_rip/server.py`
- Modify: `tests/test_server.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_server.py`:

```python
def test_get_playlists_returns_list():
    resp = client.get("/playlists")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_add_and_delete_playlist():
    resp = client.post("/playlists", json={"name": "Test PL", "url": "https://music.apple.com/test"})
    assert resp.status_code == 201
    assert resp.json()["name"] == "Test PL"

    resp = client.delete("/playlists/Test PL")
    assert resp.status_code == 204

    names = [p["name"] for p in client.get("/playlists").json()]
    assert "Test PL" not in names
```

- [ ] **Step 2: Run to confirm they fail**

```bash
pytest tests/test_server.py -v
```

Expected: `FAILED` — `404 Not Found` for `/playlists`

- [ ] **Step 3: Add playlist endpoints to `alac_rip/server.py`**

Add after the `health()` function:

```python
class PlaylistIn(BaseModel):
    name: str
    url: str


@app.get("/playlists")
def get_playlists():
    return [
        {"name": p.name, "url": p.url, "last_synced": p.last_synced}
        for p in state.get_playlists()
    ]


@app.post("/playlists", status_code=201)
def add_playlist(body: PlaylistIn):
    state.add_playlist(body.name, body.url)
    return {"name": body.name, "url": body.url, "last_synced": None}


@app.delete("/playlists/{name}", status_code=204)
def delete_playlist(name: str):
    with sqlite3.connect(cfg.state_dir / "downloaded.db") as conn:
        conn.execute("DELETE FROM playlists WHERE name = ?", (name,))
        conn.execute("DELETE FROM playlist_tracks WHERE playlist_name = ?", (name,))
    return None
```

- [ ] **Step 4: Run tests — expect pass**

```bash
pytest tests/test_server.py -v
```

Expected: all `PASSED`

- [ ] **Step 5: Commit**

```bash
git add alac_rip/server.py tests/test_server.py
git commit -m "feat: playlists GET/POST/DELETE endpoints"
```

---

## Task 3: Sync SSE endpoint

**Files:**
- Modify: `alac_rip/server.py`
- Modify: `tests/test_server.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_server.py`:

```python
def test_sync_unknown_playlist_returns_404():
    resp = client.get("/sync/Nonexistent Playlist")
    assert resp.status_code == 404


def test_sync_streams_done_event(monkeypatch):
    from alac_rip import sync as sync_mod
    from alac_rip.sync import SyncResult

    # Add a real playlist first
    client.post("/playlists", json={"name": "SSE Test", "url": "https://music.apple.com/fake"})

    # Patch SyncEngine.sync to return immediately without touching the downloader
    monkeypatch.setattr(
        sync_mod.SyncEngine,
        "sync",
        lambda self, url: SyncResult(new_count=3, skipped_count=1, error_count=0),
    )

    events = []
    with client.stream("GET", "/sync/SSE Test") as r:
        assert r.status_code == 200
        for line in r.iter_lines():
            if line.startswith("data:"):
                events.append(json.loads(line[5:].strip()))
                if events[-1]["status"] != "running":
                    break

    done = next(e for e in events if e["status"] == "done")
    assert done["new"] == 3
    assert done["skipped"] == 1

    # Cleanup
    client.delete("/playlists/SSE Test")
```

Also add at the top of `tests/test_server.py`:

```python
import json
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_server.py::test_sync_unknown_playlist_returns_404 tests/test_server.py::test_sync_streams_done_event -v
```

Expected: `FAILED` — 404 on both (endpoint doesn't exist yet)

- [ ] **Step 3: Add sync endpoint to `alac_rip/server.py`**

Add after `delete_playlist`:

```python
@app.get("/sync/{name}")
def sync_playlist(name: str):
    playlists = {p.name: p for p in state.get_playlists()}
    if name not in playlists:
        raise HTTPException(404, f"Playlist '{name}' not found")

    playlist = playlists[name]
    pre_count = state.get_downloaded_count()
    result_holder: dict = {}
    error_holder: dict = {}

    def run_sync():
        try:
            downloader = Downloader(
                downloader_repo=cfg.downloader_repo,
                wrapper_bin=cfg.wrapper_bin,
                media_user_token=cfg.media_user_token,
                apple_id_email=cfg.apple_id_email,
                apple_id_password=cfg.apple_id_password,
            )
            engine = SyncEngine(
                downloader=downloader,
                state=state,
                music_dir=cfg.music_dir,
                playlist_name=name,
            )
            result_holder["result"] = engine.sync(playlist.url)
            state.update_playlist_synced(name)
        except Exception as exc:
            error_holder["error"] = str(exc)

    thread = threading.Thread(target=run_sync, daemon=True)
    thread.start()

    def event_stream():
        import time
        while thread.is_alive():
            current = max(state.get_downloaded_count() - pre_count, 0)
            yield f"data: {json.dumps({'status': 'running', 'new_so_far': current})}\n\n"
            time.sleep(1)

        if "error" in error_holder:
            yield f"data: {json.dumps({'status': 'error', 'message': error_holder['error']})}\n\n"
        else:
            r = result_holder.get("result")
            yield f"data: {json.dumps({'status': 'done', 'new': r.new_count, 'skipped': r.skipped_count, 'errors': r.error_count})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

- [ ] **Step 4: Run tests — expect pass**

```bash
pytest tests/test_server.py -v
```

Expected: all `PASSED`

- [ ] **Step 5: Commit**

```bash
git add alac_rip/server.py tests/test_server.py
git commit -m "feat: sync SSE endpoint — streams progress without touching sync.py"
```

---

## Task 4: Library and track art endpoints

**Files:**
- Modify: `alac_rip/server.py`
- Modify: `tests/test_server.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_server.py`:

```python
def test_library_returns_dict():
    resp = client.get("/library")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)
    # Each value is a list of tracks
    for tracks in data.values():
        assert isinstance(tracks, list)


def test_track_art_missing_path_returns_404():
    resp = client.get("/track-art", params={"path": "/tmp/nonexistent.m4a"})
    assert resp.status_code == 404
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_server.py::test_library_returns_dict tests/test_server.py::test_track_art_missing_path_returns_404 -v
```

Expected: `FAILED`

- [ ] **Step 3: Add library + track art endpoints to `alac_rip/server.py`**

Add after `sync_playlist`:

```python
@app.get("/library")
def get_library():
    result: dict = {}
    for pl in state.get_playlists():
        tracks = state.get_playlist_tracks(pl.name)
        result[pl.name] = [
            {
                "track_id": t.track_id,
                "title": t.title,
                "artist": t.artist,
                "album": t.album,
                "local_path": t.local_path,
                "downloaded_at": t.downloaded_at,
            }
            for t in tracks
        ]
    return result


@app.get("/track-art")
def get_track_art(path: str):
    track_path = Path(path)
    if not track_path.exists():
        raise HTTPException(404, "File not found")
    try:
        tags = MP4(track_path)
        covers = tags.get("covr", [])
        if not covers:
            raise HTTPException(404, "No cover art embedded")
        cover = covers[0]
        fmt = "image/jpeg" if cover.imageformat == MP4Cover.FORMAT_JPEG else "image/png"
        return Response(content=bytes(cover), media_type=fmt)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
```

- [ ] **Step 4: Run tests — expect pass**

```bash
pytest tests/test_server.py -v
```

Expected: all `PASSED`

- [ ] **Step 5: Commit**

```bash
git add alac_rip/server.py tests/test_server.py
git commit -m "feat: library and track-art endpoints"
```

---

## Task 5: Config endpoints

**Files:**
- Modify: `alac_rip/server.py`
- Modify: `tests/test_server.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_server.py`:

```python
def test_get_config_omits_password():
    resp = client.get("/config")
    assert resp.status_code == 200
    data = resp.json()
    assert "music_dir" in data
    assert "apple_id_password" not in data


def test_put_config_roundtrip(tmp_path, monkeypatch):
    import alac_rip.server as server_mod

    fake_cfg_path = tmp_path / "config.yaml"
    fake_cfg_path.write_text(
        "music_dir: ~/Music\nmedia_user_token: tok\napple_id_email: a@b.com\n"
        "apple_id_password: secret\nstaging_dir: /tmp/s\n"
        "downloader_repo: /tmp/d\nwrapper_bin: /tmp/w\nstate_dir: /tmp/st\n"
        "github_remote: ''\napple_id_password: secret\n"
    )
    monkeypatch.setattr(server_mod, "DEFAULT_CONFIG_PATH", fake_cfg_path)

    resp = client.put("/config", json={"apple_id_email": "new@email.com"})
    assert resp.status_code == 200
    data = fake_cfg_path.read_text()
    assert "new@email.com" in data
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_server.py::test_get_config_omits_password tests/test_server.py::test_put_config_roundtrip -v
```

Expected: `FAILED`

- [ ] **Step 3: Add config endpoints to `alac_rip/server.py`**

Add after `get_track_art`:

```python
class ConfigUpdate(BaseModel):
    music_dir: Optional[str] = None
    staging_dir: Optional[str] = None
    media_user_token: Optional[str] = None
    apple_id_email: Optional[str] = None
    apple_id_password: Optional[str] = None
    github_remote: Optional[str] = None


@app.get("/config")
def get_config():
    with open(DEFAULT_CONFIG_PATH) as f:
        data = yaml.safe_load(f) or {}
    data.pop("apple_id_password", None)
    return data


@app.put("/config")
def update_config(body: ConfigUpdate):
    with open(DEFAULT_CONFIG_PATH) as f:
        data = yaml.safe_load(f) or {}
    updates = body.model_dump(exclude_none=True)
    data.update(updates)
    with open(DEFAULT_CONFIG_PATH, "w") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True)
    global cfg
    cfg = load_config(DEFAULT_CONFIG_PATH)
    return {"status": "ok"}
```

- [ ] **Step 4: Run full test suite — expect all pass**

```bash
pytest tests/test_server.py -v
```

Expected: all `PASSED`

- [ ] **Step 5: Commit**

```bash
git add alac_rip/server.py tests/test_server.py
git commit -m "feat: config GET/PUT endpoints"
```

---

## Task 6: Scaffold Tauri app

**Files:**
- Create: `app/` (via CLI)

- [ ] **Step 1: Verify prerequisites**

```bash
node --version   # must be 20+
rustc --version  # must be installed; if not: curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
cargo --version
```

- [ ] **Step 2: Scaffold the Tauri + Svelte project**

```bash
cd /home/ilikepie/Documents/VS-Projects/pies-alac-rip-tool
npm create tauri-app@latest app -- --template svelte-ts --manager npm
cd app
npm install
```

- [ ] **Step 3: Install Tailwind CSS**

```bash
cd /home/ilikepie/Documents/VS-Projects/pies-alac-rip-tool/app
npm install -D tailwindcss postcss autoprefixer
npx tailwindcss init -p
```

- [ ] **Step 4: Configure Tailwind — replace `tailwind.config.js`**

```js
// app/tailwind.config.js
export default {
  content: ['./src/**/*.{html,svelte,ts,js}'],
  theme: { extend: {} },
  plugins: [],
}
```

- [ ] **Step 5: Wire Tailwind into `app/src/app.css`**

Replace entire file content:

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

* { box-sizing: border-box; }
body { margin: 0; font-family: system-ui, -apple-system, sans-serif; }
```

- [ ] **Step 6: Update `app/src-tauri/tauri.conf.json`** — set app name and window size

Change `"productName"` to `"pies"`, and inside `"app" > "windows"[0]` set:

```json
"title": "pies",
"width": 1100,
"height": 700,
"minWidth": 800,
"minHeight": 500
```

- [ ] **Step 7: Verify dev build works (Svelte only, ignore Python for now)**

```bash
cd /home/ilikepie/Documents/VS-Projects/pies-alac-rip-tool/app
npm run tauri dev
```

Expected: Tauri window opens with the default Svelte scaffold. Close it.

- [ ] **Step 8: Add `app/` to `.gitignore` exclusions but commit everything except build artifacts**

```bash
cd /home/ilikepie/Documents/VS-Projects/pies-alac-rip-tool
echo "app/node_modules/\napp/dist/\napp/src-tauri/target/" >> .gitignore
git add app/ .gitignore
git commit -m "feat: scaffold Tauri app with Svelte + Tailwind"
```

---

## Task 7: Rust sidecar — spawn Python, expose port

**Files:**
- Modify: `app/src-tauri/src/lib.rs`
- Modify: `app/src-tauri/Cargo.toml`

- [ ] **Step 1: Add `ureq` to `app/src-tauri/Cargo.toml`**

Open `app/src-tauri/Cargo.toml` and add to `[dependencies]`:

```toml
ureq = "2"
```

- [ ] **Step 2: Replace `app/src-tauri/src/lib.rs` entirely**

```rust
use std::fs;
use std::path::PathBuf;
use std::process::{Child, Command};
use std::sync::Mutex;
use std::time::{Duration, Instant};
use tauri::Manager;

struct PythonProcess(Mutex<Option<Child>>);

#[tauri::command]
fn get_api_port() -> Result<u16, String> {
    let port_file = std::env::temp_dir().join("pies-alac-rip.port");
    fs::read_to_string(&port_file)
        .map_err(|e| e.to_string())?
        .trim()
        .parse::<u16>()
        .map_err(|e| e.to_string())
}

fn find_python() -> PathBuf {
    // CARGO_MANIFEST_DIR = app/src-tauri; project root is two levels up
    let project_root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .parent()
        .unwrap()
        .to_path_buf();
    let venv = project_root.join(".venv/bin/python3");
    if venv.exists() { venv } else { PathBuf::from("python3") }
}

fn project_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .parent()
        .unwrap()
        .to_path_buf()
}

fn wait_for_python(timeout: Duration) -> bool {
    let port_file = std::env::temp_dir().join("pies-alac-rip.port");
    let deadline = Instant::now() + timeout;
    while Instant::now() < deadline {
        if let Ok(content) = fs::read_to_string(&port_file) {
            if let Ok(port) = content.trim().parse::<u16>() {
                let url = format!("http://127.0.0.1:{}/health", port);
                if ureq::get(&url).call().map(|r| r.status() == 200).unwrap_or(false) {
                    return true;
                }
            }
        }
        std::thread::sleep(Duration::from_millis(500));
    }
    false
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    // Remove stale port file from a previous run
    let port_file = std::env::temp_dir().join("pies-alac-rip.port");
    let _ = fs::remove_file(&port_file);

    let python = find_python();
    let root = project_root();

    let child = Command::new(&python)
        .args(["-m", "alac_rip.server"])
        .current_dir(&root)
        .spawn()
        .expect("Failed to spawn Python server — is the venv set up?");

    tauri::Builder::default()
        .setup(move |app| {
            app.manage(PythonProcess(Mutex::new(Some(child))));

            if !wait_for_python(Duration::from_secs(15)) {
                eprintln!("WARNING: Python server did not respond within 15 seconds");
            }

            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { .. } = event {
                if let Ok(mut guard) = window.state::<PythonProcess>().0.lock() {
                    if let Some(mut child) = guard.take() {
                        let _ = child.kill();
                    }
                }
            }
        })
        .invoke_handler(tauri::generate_handler![get_api_port])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
```

- [ ] **Step 3: Verify Rust compiles**

```bash
cd /home/ilikepie/Documents/VS-Projects/pies-alac-rip-tool/app
cargo build --manifest-path src-tauri/Cargo.toml 2>&1 | tail -5
```

Expected: `Compiling pies-alac-rip ...` then `Finished`

- [ ] **Step 4: Smoke test — open app and verify Python starts**

```bash
# Terminal 1: watch Python's port file appear
watch -n1 cat /tmp/pies-alac-rip.port

# Terminal 2:
cd /home/ilikepie/Documents/VS-Projects/pies-alac-rip-tool/app
npm run tauri dev
```

Expected: port file appears within 5 seconds, window opens.

- [ ] **Step 5: Commit**

```bash
cd /home/ilikepie/Documents/VS-Projects/pies-alac-rip-tool
git add app/src-tauri/src/lib.rs app/src-tauri/Cargo.toml app/src-tauri/Cargo.lock
git commit -m "feat: Rust sidecar — spawn Python on open, kill on close"
```

---

## Task 8: `api.ts` — centralised HTTP client

**Files:**
- Create: `app/src/api.ts`

- [ ] **Step 1: Create `app/src/api.ts`**

```typescript
import { invoke } from "@tauri-apps/api/core";

let _port: number | null = null;

async function getPort(): Promise<number> {
  if (_port !== null) return _port;
  _port = await invoke<number>("get_api_port");
  return _port;
}

async function base(): Promise<string> {
  return `http://127.0.0.1:${await getPort()}`;
}

export interface Playlist {
  name: string;
  url: string;
  last_synced: string | null;
}

export interface Track {
  track_id: string;
  title: string;
  artist: string;
  album: string;
  local_path: string;
  downloaded_at: string;
}

export interface SyncEvent {
  status: "running" | "done" | "error";
  new_so_far?: number;
  new?: number;
  skipped?: number;
  errors?: number;
  message?: string;
}

export const api = {
  async playlists(): Promise<Playlist[]> {
    const r = await fetch(`${await base()}/playlists`);
    return r.json();
  },

  async addPlaylist(name: string, url: string): Promise<Playlist> {
    const r = await fetch(`${await base()}/playlists`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, url }),
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async deletePlaylist(name: string): Promise<void> {
    await fetch(`${await base()}/playlists/${encodeURIComponent(name)}`, {
      method: "DELETE",
    });
  },

  async library(): Promise<Record<string, Track[]>> {
    const r = await fetch(`${await base()}/library`);
    return r.json();
  },

  async trackArtUrl(localPath: string): Promise<string> {
    return `${await base()}/track-art?path=${encodeURIComponent(localPath)}`;
  },

  async syncUrl(name: string): Promise<string> {
    return `${await base()}/sync/${encodeURIComponent(name)}`;
  },

  async config(): Promise<Record<string, string>> {
    const r = await fetch(`${await base()}/config`);
    return r.json();
  },

  async updateConfig(updates: Partial<Record<string, string>>): Promise<void> {
    const r = await fetch(`${await base()}/config`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(updates),
    });
    if (!r.ok) throw new Error(await r.text());
  },
};
```

- [ ] **Step 2: Commit**

```bash
cd /home/ilikepie/Documents/VS-Projects/pies-alac-rip-tool
git add app/src/api.ts
git commit -m "feat: api.ts — typed HTTP client for all FastAPI endpoints"
```

---

## Task 9: `App.svelte` root layout + `Sidebar.svelte`

**Files:**
- Modify: `app/src/App.svelte`
- Create: `app/src/lib/Sidebar.svelte`

- [ ] **Step 1: Replace `app/src/App.svelte`**

```svelte
<script lang="ts">
  import "./app.css";
  import Sidebar from "./lib/Sidebar.svelte";
  import Library from "./lib/Library.svelte";
  import SyncProgress from "./lib/SyncProgress.svelte";
  import Settings from "./lib/Settings.svelte";

  type View = "library" | "sync" | "settings";

  let view = $state<View>("library");
  let selectedPlaylist = $state<string | null>(null);
  let syncingPlaylist = $state<string | null>(null);

  function selectPlaylist(name: string) {
    selectedPlaylist = name;
    view = "library";
  }

  function startSync(name: string) {
    syncingPlaylist = name;
    view = "sync";
  }

  function onSyncDone() {
    syncingPlaylist = null;
    view = "library";
  }
</script>

<div class="flex h-screen bg-[#0f0f0f] text-white overflow-hidden select-none">
  <Sidebar
    {selectedPlaylist}
    {syncingPlaylist}
    onselectPlaylist={selectPlaylist}
    onstartSync={startSync}
    onopenSettings={() => (view = "settings")}
  />
  <main class="flex-1 overflow-auto">
    {#if view === "library" && selectedPlaylist}
      <Library playlistName={selectedPlaylist} />
    {:else if view === "sync" && syncingPlaylist}
      <SyncProgress playlistName={syncingPlaylist} ondone={onSyncDone} />
    {:else if view === "settings"}
      <Settings />
    {:else}
      <div class="flex items-center justify-center h-full text-zinc-600 text-sm">
        Select a playlist from the sidebar
      </div>
    {/if}
  </main>
</div>
```

- [ ] **Step 2: Create `app/src/lib/Sidebar.svelte`**

```svelte
<script lang="ts">
  import { onMount } from "svelte";
  import { api, type Playlist } from "../api";

  interface Props {
    selectedPlaylist: string | null;
    syncingPlaylist: string | null;
    onselectPlaylist: (name: string) => void;
    onstartSync: (name: string) => void;
    onopenSettings: () => void;
  }

  let { selectedPlaylist, syncingPlaylist, onselectPlaylist, onstartSync, onopenSettings }: Props = $props();

  let playlists = $state<Playlist[]>([]);
  let showAddForm = $state(false);
  let newName = $state("");
  let newUrl = $state("");
  let adding = $state(false);

  onMount(async () => {
    playlists = await api.playlists();
    if (playlists.length > 0 && !selectedPlaylist) {
      onselectPlaylist(playlists[0].name);
    }
  });

  async function addPlaylist() {
    if (!newName.trim() || !newUrl.trim()) return;
    adding = true;
    try {
      const pl = await api.addPlaylist(newName.trim(), newUrl.trim());
      playlists = [...playlists, pl];
      newName = "";
      newUrl = "";
      showAddForm = false;
    } finally {
      adding = false;
    }
  }

  async function removePlaylist(name: string, e: MouseEvent) {
    e.stopPropagation();
    await api.deletePlaylist(name);
    playlists = playlists.filter((p) => p.name !== name);
  }
</script>

<aside class="w-[180px] min-w-[180px] bg-[#111] flex flex-col border-r border-[#1e1e1e]">
  <div class="p-4 border-b border-[#1e1e1e]">
    <div class="text-white font-bold text-[15px] tracking-tight">pies</div>
    <div class="text-[#555] text-[10px] mt-0.5">Apple Music ↓</div>
  </div>

  <nav class="p-2 border-b border-[#1e1e1e]">
    <button
      class="w-full text-left px-3 py-1.5 rounded-md text-sm text-[#888] hover:text-white hover:bg-[#1a1a1a] transition-colors"
      onclick={onopenSettings}
    >
      ⚙ Settings
    </button>
  </nav>

  <div class="px-3 pt-3 pb-1 text-[10px] text-[#555] uppercase tracking-widest">Playlists</div>

  <div class="flex-1 overflow-y-auto px-2 flex flex-col gap-0.5">
    {#each playlists as pl}
      <button
        class="group w-full text-left px-3 py-2 rounded-md text-sm flex items-center justify-between transition-colors
          {selectedPlaylist === pl.name ? 'bg-[#1a1a1a] text-white' : 'text-[#888] hover:text-white hover:bg-[#1a1a1a]'}"
        onclick={() => onselectPlaylist(pl.name)}
      >
        <span class="truncate">{pl.name}</span>
        <span
          class="hidden group-hover:inline text-[#555] hover:text-red-400 text-xs ml-1 cursor-pointer"
          onclick={(e) => removePlaylist(pl.name, e)}
          role="button"
          tabindex="-1"
        >✕</span>
      </button>
    {/each}

    {#if showAddForm}
      <div class="px-1 py-2 flex flex-col gap-1">
        <input bind:value={newName} placeholder="Name"
          class="bg-[#1a1a1a] border border-[#333] rounded px-2 py-1 text-xs text-white w-full outline-none focus:border-[#1db954]" />
        <input bind:value={newUrl} placeholder="Apple Music URL"
          class="bg-[#1a1a1a] border border-[#333] rounded px-2 py-1 text-xs text-white w-full outline-none focus:border-[#1db954]" />
        <div class="flex gap-1">
          <button onclick={addPlaylist} disabled={adding}
            class="flex-1 bg-[#1db954] text-black text-xs rounded py-1 font-semibold disabled:opacity-50">
            {adding ? "…" : "Add"}
          </button>
          <button onclick={() => (showAddForm = false)}
            class="flex-1 text-[#888] text-xs rounded py-1 bg-[#1a1a1a]">Cancel</button>
        </div>
      </div>
    {:else}
      <button onclick={() => (showAddForm = true)}
        class="w-full text-left px-3 py-2 text-[#555] hover:text-white text-sm transition-colors">
        + Add playlist
      </button>
    {/if}
  </div>

  {#if syncingPlaylist}
    <div class="mx-2 mb-2 bg-[#1a1a1a] rounded-lg p-3 border border-[#222]">
      <div class="text-[10px] text-[#555] uppercase tracking-widest mb-1">Syncing</div>
      <div class="text-white text-xs font-medium truncate">{syncingPlaylist}</div>
      <div class="h-1 bg-[#333] rounded-full mt-2">
        <div class="h-full bg-[#1db954] rounded-full w-full animate-pulse"></div>
      </div>
    </div>
  {/if}

  <div class="p-2 border-t border-[#1e1e1e]">
    <button
      onclick={() => { for (const pl of playlists) onstartSync(pl.name); }}
      disabled={!!syncingPlaylist}
      class="w-full bg-[#1db954] text-black text-sm font-bold rounded-lg py-2 hover:bg-[#1ed760] transition-colors disabled:opacity-50"
    >
      ↻ Sync All
    </button>
  </div>
</aside>
```

- [ ] **Step 3: Verify app renders with sidebar**

```bash
cd /home/ilikepie/Documents/VS-Projects/pies-alac-rip-tool/app
npm run tauri dev
```

Expected: Dark window with sidebar showing "pies" header, Settings button, playlist list from your DB, Sync All button.

- [ ] **Step 4: Commit**

```bash
cd /home/ilikepie/Documents/VS-Projects/pies-alac-rip-tool
git add app/src/App.svelte app/src/lib/Sidebar.svelte
git commit -m "feat: App layout and Sidebar — playlist list, add/remove, sync trigger"
```

---

## Task 10: `Library.svelte` — cover art grid

**Files:**
- Create: `app/src/lib/Library.svelte`

- [ ] **Step 1: Create `app/src/lib/Library.svelte`**

```svelte
<script lang="ts">
  import { api, type Track } from "../api";

  interface Props { playlistName: string }
  let { playlistName }: Props = $props();

  let tracks = $state<Track[]>([]);
  let artUrls = $state<Record<string, string>>({});
  let loading = $state(true);

  async function load(name: string) {
    loading = true;
    tracks = [];
    artUrls = {};
    const lib = await api.library();
    tracks = lib[name] ?? [];
    loading = false;
    // Preload art for first 60 tracks
    for (const t of tracks.slice(0, 60)) {
      artUrls[t.track_id] = await api.trackArtUrl(t.local_path);
    }
  }

  // $effect runs on mount and whenever playlistName changes — no onMount needed
  $effect(() => { load(playlistName); });
</script>

<div class="p-6">
  <div class="flex items-baseline gap-3 mb-6">
    <h1 class="text-white text-2xl font-bold">{playlistName}</h1>
    <span class="text-zinc-500 text-sm">{tracks.length} tracks</span>
  </div>

  {#if loading}
    <div class="text-zinc-600 text-sm">Loading…</div>
  {:else if tracks.length === 0}
    <div class="text-zinc-600 text-sm">No tracks yet. Sync this playlist to download them.</div>
  {:else}
    <div class="grid gap-4" style="grid-template-columns: repeat(auto-fill, minmax(140px, 1fr))">
      {#each tracks as track (track.track_id)}
        <div class="bg-[#1a1a1a] rounded-xl overflow-hidden hover:bg-[#222] transition-colors cursor-default">
          <div class="aspect-square bg-[#111] flex items-center justify-center overflow-hidden">
            {#if artUrls[track.track_id]}
              <img src={artUrls[track.track_id]} alt={track.album} class="w-full h-full object-cover" />
            {:else}
              <span class="text-3xl opacity-10">♪</span>
            {/if}
          </div>
          <div class="p-3">
            <div class="text-white text-xs font-semibold truncate">{track.title}</div>
            <div class="text-zinc-500 text-xs truncate mt-0.5">{track.artist}</div>
          </div>
        </div>
      {/each}
    </div>
  {/if}
</div>
```

- [ ] **Step 2: Verify in app**

```bash
cd /home/ilikepie/Documents/VS-Projects/pies-alac-rip-tool/app && npm run tauri dev
```

Expected: Clicking "Game OST" shows a cover art grid of 520 tracks.

- [ ] **Step 3: Commit**

```bash
cd /home/ilikepie/Documents/VS-Projects/pies-alac-rip-tool
git add app/src/lib/Library.svelte
git commit -m "feat: Library cover art grid"
```

---

## Task 11: `SyncProgress.svelte` — live SSE progress

**Files:**
- Create: `app/src/lib/SyncProgress.svelte`

- [ ] **Step 1: Create `app/src/lib/SyncProgress.svelte`**

```svelte
<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { api, type SyncEvent } from "../api";

  interface Props {
    playlistName: string;
    ondone: () => void;
  }
  let { playlistName, ondone }: Props = $props();

  let status = $state<"running" | "done" | "error">("running");
  let newSoFar = $state(0);
  let result = $state<{ new: number; skipped: number; errors: number } | null>(null);
  let errorMessage = $state<string | null>(null);
  let source: EventSource | null = null;

  onMount(async () => {
    const url = await api.syncUrl(playlistName);
    source = new EventSource(url);

    source.onmessage = (e) => {
      const data: SyncEvent = JSON.parse(e.data);
      status = data.status;
      if (data.status === "running") {
        newSoFar = data.new_so_far ?? 0;
      } else if (data.status === "done") {
        result = { new: data.new ?? 0, skipped: data.skipped ?? 0, errors: data.errors ?? 0 };
        source?.close();
      } else if (data.status === "error") {
        errorMessage = data.message ?? "Unknown error";
        source?.close();
      }
    };

    source.onerror = () => {
      if (status === "running") {
        status = "error";
        errorMessage = "Lost connection to sync server.";
      }
      source?.close();
    };
  });

  onDestroy(() => source?.close());
</script>

<div class="p-8 flex flex-col items-center justify-center min-h-full">
  <div class="w-full max-w-md">
    <h2 class="text-white text-xl font-bold mb-2">{playlistName}</h2>

    {#if status === "running"}
      <p class="text-zinc-400 text-sm mb-4">
        Downloading and syncing… <span class="text-white font-bold">{newSoFar}</span> new tracks so far
      </p>
      <div class="h-1.5 bg-[#1a1a1a] rounded-full overflow-hidden">
        <div class="h-full bg-[#1db954] rounded-full w-full animate-pulse"></div>
      </div>

    {:else if status === "done" && result}
      <div class="bg-[#1a1a1a] rounded-xl p-6 border border-[#222] mt-4">
        <div class="text-[#1db954] font-bold text-base mb-4">✓ Sync complete</div>
        <div class="flex gap-8 text-sm">
          <div><div class="text-white font-bold text-2xl">{result.new}</div><div class="text-zinc-500 mt-0.5">new</div></div>
          <div><div class="text-white font-bold text-2xl">{result.skipped}</div><div class="text-zinc-500 mt-0.5">skipped</div></div>
          <div>
            <div class="font-bold text-2xl {result.errors > 0 ? 'text-red-400' : 'text-white'}">{result.errors}</div>
            <div class="text-zinc-500 mt-0.5">errors</div>
          </div>
        </div>
      </div>
      <button onclick={ondone}
        class="mt-4 w-full bg-[#1db954] text-black font-bold py-2 rounded-lg hover:bg-[#1ed760] transition-colors">
        Back to library
      </button>

    {:else if status === "error"}
      <div class="bg-red-950 border border-red-800 rounded-xl p-4 mt-4">
        <div class="text-red-400 font-bold mb-2">Sync failed</div>
        <pre class="text-red-300 text-xs overflow-auto max-h-48 whitespace-pre-wrap">{errorMessage}</pre>
      </div>
      <button onclick={ondone} class="mt-4 text-zinc-500 hover:text-white text-sm transition-colors">← Back</button>
    {/if}
  </div>
</div>
```

- [ ] **Step 2: Verify in app — trigger a sync**

```bash
cd /home/ilikepie/Documents/VS-Projects/pies-alac-rip-tool/app && npm run tauri dev
```

Click Sync All. Expected: SyncProgress view appears, counter increments, "done" summary appears when finished.

- [ ] **Step 3: Commit**

```bash
cd /home/ilikepie/Documents/VS-Projects/pies-alac-rip-tool
git add app/src/lib/SyncProgress.svelte
git commit -m "feat: SyncProgress — live SSE-driven sync display"
```

---

## Task 12: `Settings.svelte` — config editor

**Files:**
- Create: `app/src/lib/Settings.svelte`

- [ ] **Step 1: Create `app/src/lib/Settings.svelte`**

```svelte
<script lang="ts">
  import { onMount } from "svelte";
  import { api } from "../api";

  let cfg = $state<Record<string, string>>({});
  let newPassword = $state("");
  let saving = $state(false);
  let saved = $state(false);
  let error = $state<string | null>(null);

  onMount(async () => { cfg = await api.config(); });

  const fields: { key: string; label: string }[] = [
    { key: "music_dir",        label: "Music directory" },
    { key: "staging_dir",      label: "Staging directory" },
    { key: "media_user_token", label: "Media user token" },
    { key: "apple_id_email",   label: "Apple ID email" },
    { key: "github_remote",    label: "GitHub remote (optional)" },
  ];

  async function save() {
    saving = true;
    error = null;
    try {
      const updates: Record<string, string> = Object.fromEntries(
        fields.map(f => [f.key, cfg[f.key] ?? ""])
      );
      if (newPassword.trim()) updates.apple_id_password = newPassword.trim();
      await api.updateConfig(updates);
      saved = true;
      newPassword = "";
      setTimeout(() => (saved = false), 2500);
    } catch (e) {
      error = String(e);
    } finally {
      saving = false;
    }
  }
</script>

<div class="p-8 max-w-lg">
  <h1 class="text-white text-2xl font-bold mb-6">Settings</h1>

  <div class="flex flex-col gap-4">
    {#each fields as f}
      <label class="flex flex-col gap-1">
        <span class="text-zinc-400 text-xs uppercase tracking-widest">{f.label}</span>
        <input bind:value={cfg[f.key]}
          class="bg-[#1a1a1a] border border-[#333] rounded-lg px-3 py-2 text-white text-sm outline-none focus:border-[#1db954] transition-colors" />
      </label>
    {/each}

    <label class="flex flex-col gap-1">
      <span class="text-zinc-400 text-xs uppercase tracking-widest">
        Apple ID password (leave blank to keep current)
      </span>
      <input type="password" bind:value={newPassword} placeholder="••••••••"
        class="bg-[#1a1a1a] border border-[#333] rounded-lg px-3 py-2 text-white text-sm outline-none focus:border-[#1db954] transition-colors" />
    </label>

    {#if error}
      <div class="text-red-400 text-sm bg-red-950 border border-red-800 rounded-lg px-3 py-2">{error}</div>
    {/if}

    <button onclick={save} disabled={saving}
      class="bg-[#1db954] text-black font-bold py-2 rounded-lg hover:bg-[#1ed760] transition-colors disabled:opacity-50 mt-2">
      {saving ? "Saving…" : saved ? "✓ Saved" : "Save changes"}
    </button>
  </div>
</div>
```

- [ ] **Step 2: Verify in app**

```bash
cd /home/ilikepie/Documents/VS-Projects/pies-alac-rip-tool/app && npm run tauri dev
```

Click Settings. Expected: fields populated from `config.yaml`, save button updates the file.

- [ ] **Step 3: Final full test run**

```bash
cd /home/ilikepie/Documents/VS-Projects/pies-alac-rip-tool
source .venv/bin/activate
pytest tests/ -v
```

Expected: all tests `PASSED`

- [ ] **Step 4: Commit**

```bash
cd /home/ilikepie/Documents/VS-Projects/pies-alac-rip-tool
git add app/src/lib/Settings.svelte
git commit -m "feat: Settings — config editor with password masking"
```
