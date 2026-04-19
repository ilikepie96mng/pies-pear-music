# One-Off Download Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Download page to the sidebar that accepts any Apple Music URL, downloads it via the Go downloader, and organizes it into `Artist/Album/` without creating a playlist.

**Architecture:** Three-task sequence: (1) make SyncEngine's playlist association optional in the backend, (2) add an SSE endpoint that streams download then organize phases, (3) wire up the frontend Download page. Each task is independently committable.

**Tech Stack:** Python/FastAPI (backend), Svelte 5 (frontend), SSE (EventSource), SQLite via StateManager, mutagen (audio tags), ffmpeg (transcoding)

---

## File Map

| File | Change |
|------|--------|
| `alac_rip/sync.py` | Make `playlist_name` optional; skip M3U8 and playlist association when `None` |
| `alac_rip/metadata.py` | Make `playlist_name` param default to `""` |
| `alac_rip/server.py` | Add `GET /download/one-off` SSE endpoint |
| `app/src/api.ts` | Add `download.oneOffUrl(url, format)` |
| `app/src/lib/Download.svelte` | New page component |
| `app/src/lib/Sidebar.svelte` | Add Download nav item + `onopenDownload` prop |
| `app/src/routes/+page.svelte` | Add `"download"` view, import and render Download, wire Sidebar |
| `tests/test_sync.py` | Tests for `playlist_name=None` mode |
| `tests/test_server.py` | Tests for `/download/one-off` |

---

## Task 1: SyncEngine optional playlist mode

**Files:**
- Modify: `alac_rip/metadata.py`
- Modify: `alac_rip/sync.py`
- Test: `tests/test_sync.py`

- [ ] **Step 1: Write the failing tests**

Add to the bottom of `tests/test_sync.py`:

```python
def test_sync_without_playlist_moves_files(music_dir, staging_dir, sync_state):
    make_fake_m4a(
        staging_dir / "Queen" / "A Night at the Opera" / "01 - Bohemian Rhapsody.m4a",
        title="Bohemian Rhapsody", artist="Queen",
        album="A Night at the Opera", track_num=1,
    )
    engine = SyncEngine(state=sync_state, music_dir=music_dir, playlist_name=None)
    result = engine.sync(staging_dir)
    dest = music_dir / "artists" / "Queen" / "A Night at the Opera" / "01 - Bohemian Rhapsody.flac"
    assert dest.exists()
    assert result.new_count == 1


def test_sync_without_playlist_records_in_db(music_dir, staging_dir, sync_state):
    make_fake_m4a(
        staging_dir / "Queen" / "A Night at the Opera" / "01 - Bohemian Rhapsody.m4a",
        title="Bohemian Rhapsody", artist="Queen",
        album="A Night at the Opera", track_num=1,
    )
    engine = SyncEngine(state=sync_state, music_dir=music_dir, playlist_name=None)
    engine.sync(staging_dir)
    assert sync_state.get_downloaded_count() == 1


def test_sync_without_playlist_does_not_write_m3u8(music_dir, staging_dir, sync_state):
    make_fake_m4a(
        staging_dir / "Queen" / "A Night at the Opera" / "01 - Bohemian Rhapsody.m4a",
        title="Bohemian Rhapsody", artist="Queen",
        album="A Night at the Opera", track_num=1,
    )
    engine = SyncEngine(state=sync_state, music_dir=music_dir, playlist_name=None)
    engine.sync(staging_dir)
    playlists_dir = music_dir / "playlists"
    assert not playlists_dir.exists() or not list(playlists_dir.glob("*.m3u8"))
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/ilikepie/Documents/VS-Projects/pies-alac-rip-tool/.worktrees/desktop-app
.venv/bin/pytest tests/test_sync.py::test_sync_without_playlist_moves_files tests/test_sync.py::test_sync_without_playlist_records_in_db tests/test_sync.py::test_sync_without_playlist_does_not_write_m3u8 -v
```

Expected: FAIL — `SyncEngine.__init__` does not accept `playlist_name=None` (TypeError)

- [ ] **Step 3: Make `write_tags` playlist_name optional**

In `alac_rip/metadata.py`, change line 49:

```python
# Before:
    playlist_name: str,

# After:
    playlist_name: str = "",
```

- [ ] **Step 4: Update SyncEngine to accept `playlist_name=None`**

Replace `alac_rip/sync.py` with this full content:

```python
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from mutagen.mp4 import MP4

from alac_rip.metadata import embed_cover_art, read_tags, save_cover_file, write_tags
from alac_rip.organizer import ensure_album_dir, sanitize, track_path
from alac_rip.state import StateManager, Track

LogCallback = Callable[[str, str], None]  # (message, phase)


@dataclass
class SyncResult:
    new_count: int
    skipped_count: int
    error_count: int


class SyncEngine:
    def __init__(
        self,
        state: StateManager,
        music_dir: Path,
        playlist_name: Optional[str] = None,
        on_log: Optional[LogCallback] = None,
    ):
        self.state = state
        self.music_dir = music_dir
        self.playlist_name = playlist_name
        self._on_log: LogCallback = on_log or (lambda msg, phase: None)

    def _log(self, msg: str, phase: str = "processing") -> None:
        self._on_log(msg, phase)

    def _track_id(self, relative_path: str) -> str:
        return relative_path

    def _write_m3u8(self) -> None:
        tracks = self.state.get_playlist_tracks(self.playlist_name)
        if not tracks:
            return

        playlists_dir = self.music_dir / "playlists"
        playlists_dir.mkdir(exist_ok=True)

        m3u8_path = playlists_dir / f"{sanitize(self.playlist_name)}.m3u8"

        lines = ["#EXTM3U", ""]
        for track in tracks:
            lines.append(f"#EXTINF:-1,{track.artist} - {track.title}")
            lines.append(track.local_path)

        m3u8_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _convert_m4a_to_flac(self, src: Path, dest: Path) -> None:
        result = subprocess.run(
            ["ffmpeg", "-i", str(src), "-c:a", "flac", "-map_metadata", "-1", "-y", str(dest)],
            capture_output=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {result.stderr.decode()[:300]}")

    def _handle_cover(self, src_m4a: Path, dest_flac: Path) -> None:
        """Extract embedded cover from M4A, embed in FLAC, and save cover.jpg."""
        try:
            mp4 = MP4(src_m4a)
            if mp4.tags and "covr" in mp4.tags and mp4.tags["covr"]:
                cover_data = bytes(mp4.tags["covr"][0])
                embed_cover_art(dest_flac, cover_data)
                cover_jpg = dest_flac.parent / "cover.jpg"
                if not cover_jpg.exists():
                    save_cover_file(cover_jpg, cover_data)
        except Exception:
            pass  # cover art is best-effort

    def _handle_lrc(self, src_audio: Path, dest_flac: Path) -> None:
        """Move matching .lrc file from staging to album dir."""
        lrc_src = src_audio.with_suffix(".lrc")
        if lrc_src.exists():
            lrc_dest = dest_flac.with_suffix(".lrc")
            shutil.move(str(lrc_src), lrc_dest)

    def sync(self, staging_dir: Path) -> SyncResult:
        """
        Process .m4a/.flac files from staging_dir into music_dir.

        For M4A: reads Apple Music tags with mutagen, transcodes to FLAC via
        ffmpeg (stripping all container metadata), then writes clean Vorbis
        Comments. Also handles embedded cover art and matching .lrc files.

        For FLAC: moves directly, handles .lrc.

        When playlist_name is None, skips playlist association and M3U8 writing.
        """
        audio_files = [f for f in staging_dir.rglob("*") if f.suffix.lower() in (".flac", ".m4a")]
        total = len(audio_files)
        self._log(f"Processing {total} file(s) from staging...", "processing")

        new_count = 0
        skipped_count = 0
        error_count = 0

        for i, src in enumerate(audio_files, 1):
            relative = str(src.relative_to(staging_dir))
            # Track ID uses .flac extension regardless of source format
            track_id = str(Path(relative).with_suffix(".flac"))

            if self.state.is_downloaded(track_id):
                skipped_count += 1
                src.unlink()
                if self.playlist_name:
                    self.state.add_track_to_playlist(self.playlist_name, track_id)
                self._log(f"[{i}/{total}] skipped (already downloaded): {src.name}", "processing")
                continue

            try:
                tags = read_tags(src)
                artist = tags["artist"] or "Unknown Artist"
                album_artist = tags["album_artist"] or artist
                album = tags["album"] or "Unknown Album"
                title = tags["title"] or src.stem
                track_num = tags["track_num"] or 1

                dest = track_path(self.music_dir, album_artist, album, track_num, title, ext=".flac")
                ensure_album_dir(self.music_dir, album_artist, album)

                if src.suffix.lower() == ".m4a":
                    self._convert_m4a_to_flac(src, dest)
                    self._handle_cover(src, dest)
                    src.unlink()
                else:
                    shutil.move(str(src), dest)

                write_tags(dest, title=title, artist=artist, album_artist=album_artist,
                           album=album, track_num=track_num,
                           playlist_name=self.playlist_name or "")

                self._handle_lrc(src, dest)

                self.state.add_track(Track(
                    track_id=track_id,
                    title=title,
                    artist=artist,
                    album=album,
                    local_path=str(dest),
                    downloaded_at=datetime.now().isoformat(),
                ))
                if self.playlist_name:
                    self.state.add_track_to_playlist(self.playlist_name, track_id)
                new_count += 1
                self._log(f"[{i}/{total}] added: {artist} — {title}", "processing")

            except Exception as exc:
                error_count += 1
                self._log(f"[{i}/{total}] error processing {src.name}: {exc}", "processing")

        if self.playlist_name:
            self._write_m3u8()
        self._log(
            f"Sync complete: {new_count} new, {skipped_count} skipped, {error_count} errors",
            "done",
        )

        return SyncResult(new_count=new_count, skipped_count=skipped_count, error_count=error_count)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/test_sync.py -v
```

Expected: all tests pass including the 3 new ones.

- [ ] **Step 6: Commit**

```bash
git add alac_rip/sync.py alac_rip/metadata.py tests/test_sync.py
git commit -m "feat: make SyncEngine playlist_name optional for one-off downloads"
```

---

## Task 2: Add `/download/one-off` SSE endpoint

**Files:**
- Modify: `alac_rip/server.py`
- Test: `tests/test_server.py`

- [ ] **Step 1: Write the failing tests**

Add to the bottom of `tests/test_server.py`:

```python
def test_download_one_off_requires_wrapper(client):
    resp = client.get("/download/one-off?url=https://music.apple.com/album/test&format=ALAC")
    assert resp.status_code == 409
    assert "Wrapper" in resp.json()["detail"]


def test_download_one_off_requires_url(client, monkeypatch):
    import alac_rip.server as server_mod
    monkeypatch.setattr(server_mod, "wrapper_running", True)
    resp = client.get("/download/one-off?url=&format=ALAC")
    assert resp.status_code == 400


def test_download_one_off_rejects_concurrent(client, monkeypatch):
    import alac_rip.server as server_mod
    monkeypatch.setattr(server_mod, "wrapper_running", True)
    monkeypatch.setattr(server_mod, "download_running", True)
    resp = client.get("/download/one-off?url=https://music.apple.com/album/test&format=ALAC")
    assert resp.status_code == 409
    assert "already in progress" in resp.json()["detail"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/test_server.py::test_download_one_off_requires_wrapper tests/test_server.py::test_download_one_off_requires_url tests/test_server.py::test_download_one_off_rejects_concurrent -v
```

Expected: FAIL — endpoint does not exist yet (404)

- [ ] **Step 3: Add the endpoint to `server.py`**

Add the following block immediately after the `get_download_logs` route (after line 744, before the `if __name__ == "__main__":` block):

```python
@app.get("/download/one-off")
async def download_one_off(url: str = "", format: str = "ALAC"):
    if not wrapper_running:
        raise HTTPException(409, "Wrapper not running — log in to Apple Music first")
    if download_running:
        raise HTTPException(409, "Download already in progress")
    if not url:
        raise HTTPException(400, "No URL provided")
    if cfg is None or not cfg.alac_rip_dir or not cfg.alac_rip_dir.exists():
        raise HTTPException(503, "alac_rip_dir not configured")

    amd_dir = cfg.alac_rip_dir / "apple-music-downloader"
    save_folder_key = {"ATMOS": "atmos-save-folder", "AAC": "aac-save-folder"}.get(format, "alac-save-folder")
    try:
        with open(amd_dir / "config.yaml") as f:
            amd_cfg = yaml.safe_load(f) or {}
        save_folder = Path(amd_cfg.get(save_folder_key, "")).expanduser()
    except Exception as exc:
        raise HTTPException(503, f"Cannot read downloader config: {exc}")
    if not save_folder or not save_folder.is_absolute():
        raise HTTPException(503, f"Downloader save folder not configured ({save_folder_key})")

    import os as _os
    linuxbrew_bin = "/var/home/linuxbrew/.linuxbrew/bin"
    env = _os.environ.copy()
    env["PATH"] = f"{linuxbrew_bin}:{env.get('PATH', '')}"
    go_bin = shutil.which("go", path=env["PATH"]) or f"{linuxbrew_bin}/go"

    if format == "ATMOS":
        cmd = [go_bin, "run", "main.go", "--atmos", url]
    elif format == "AAC":
        cmd = [go_bin, "run", "main.go", "--aac", url]
    else:
        cmd = [go_bin, "run", "main.go", url]

    async def event_stream():
        global download_running, download_process

        # ── Phase 1: download ──────────────────────────────────────────────
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                universal_newlines=True,
                cwd=str(amd_dir),
                env=env,
            )
        except Exception as exc:
            yield f"data: {json.dumps({'status': 'error', 'message': str(exc)})}\n\n"
            return

        download_running = True
        download_process = proc
        dl_q: queue.Queue = queue.Queue()

        def _read_dl():
            try:
                for line in iter(proc.stdout.readline, ""):
                    line = line.strip()
                    if line:
                        dl_q.put(line)
            except Exception:
                pass
            finally:
                dl_q.put(None)

        threading.Thread(target=_read_dl, daemon=True).start()

        while True:
            try:
                item = dl_q.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.05)
                continue
            if item is None:
                break
            yield f"data: {json.dumps({'status': 'running', 'phase': 'downloading', 'message': item})}\n\n"

        exit_code = proc.wait()
        download_running = False
        download_process = None

        if exit_code != 0:
            yield f"data: {json.dumps({'status': 'error', 'message': f'Download failed (exit code {exit_code})'})}\n\n"
            return

        # ── Phase 2: organize ──────────────────────────────────────────────
        org_q: queue.Queue = queue.Queue()

        def on_log(msg: str, _phase: str) -> None:
            org_q.put(msg)

        org_result = None
        org_error = None

        def _run_organize():
            nonlocal org_result, org_error
            try:
                engine = SyncEngine(
                    state=state,
                    music_dir=cfg.music_dir,
                    playlist_name=None,
                    on_log=on_log,
                )
                org_result = engine.sync(save_folder)
            except Exception as exc:
                org_error = str(exc)
            finally:
                org_q.put(None)

        threading.Thread(target=_run_organize, daemon=True).start()

        while True:
            try:
                item = org_q.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.05)
                continue
            if item is None:
                break
            yield f"data: {json.dumps({'status': 'running', 'phase': 'organizing', 'message': item})}\n\n"

        if org_error:
            yield f"data: {json.dumps({'status': 'error', 'message': org_error})}\n\n"
        else:
            yield f"data: {json.dumps({'status': 'done', 'new': org_result.new_count, 'skipped': org_result.skipped_count, 'errors': org_result.error_count})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/test_server.py -v
```

Expected: all tests pass including the 3 new ones.

- [ ] **Step 5: Commit**

```bash
git add alac_rip/server.py tests/test_server.py
git commit -m "feat: add /download/one-off SSE endpoint"
```

---

## Task 3: Frontend Download page

**Files:**
- Modify: `app/src/api.ts`
- Create: `app/src/lib/Download.svelte`
- Modify: `app/src/lib/Sidebar.svelte`
- Modify: `app/src/routes/+page.svelte`

- [ ] **Step 1: Add `oneOffUrl` to `api.ts`**

In `app/src/api.ts`, inside the `download:` object (after the `logs` method, before the closing `}`), add:

```typescript
    oneOffUrl(url: string, format: string): string {
      if (_port === null) throw new Error("Port not yet known");
      return `http://127.0.0.1:${_port}/download/one-off?url=${encodeURIComponent(url)}&format=${encodeURIComponent(format)}`;
    },
```

The `download` object in api.ts should then look like:

```typescript
  download: {
    async start(link: string, format: string): Promise<{ status: string; msg: string }> {
      const r = await fetch(`${await base()}/download`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ link, format }),
      });
      if (!r.ok) throw new Error(await r.text());
      return r.json();
    },

    async logs(): Promise<{ running: boolean; logs: string[] }> {
      const r = await fetch(`${await base()}/download/logs`);
      return r.json();
    },

    oneOffUrl(url: string, format: string): string {
      if (_port === null) throw new Error("Port not yet known");
      return `http://127.0.0.1:${_port}/download/one-off?url=${encodeURIComponent(url)}&format=${encodeURIComponent(format)}`;
    },
  },
```

- [ ] **Step 2: Create `Download.svelte`**

Create `app/src/lib/Download.svelte` with this content:

```svelte
<script lang="ts">
  import { onDestroy } from "svelte";
  import { api, type SyncEvent } from "../api";

  type Status = "idle" | "running" | "done" | "error";
  type Phase = "downloading" | "organizing";

  let url = $state("");
  let format = $state("ALAC");
  let status = $state<Status>("idle");
  let phase = $state<Phase>("downloading");
  let logs = $state<{ id: number; text: string; kind: "info" | "add" | "skip" | "err" }[]>([]);
  let result = $state<{ new: number; skipped: number; errors: number } | null>(null);
  let errorMessage = $state<string | null>(null);
  let logEl = $state<HTMLElement | null>(null);
  let source: EventSource | null = null;
  let nextId = 0;

  const PHASES: { key: Phase; label: string }[] = [
    { key: "downloading", label: "Downloading" },
    { key: "organizing", label: "Organizing" },
  ];

  const PHASE_ORDER: Record<Phase, number> = { downloading: 0, organizing: 1 };

  let phaseIndex = $derived(PHASE_ORDER[phase] ?? 0);

  function classifyLine(text: string): "add" | "skip" | "err" | "info" {
    if (text.includes("added:")) return "add";
    if (text.includes("skipped")) return "skip";
    if (text.includes("error")) return "err";
    return "info";
  }

  function startDownload() {
    if (!url.trim() || status === "running") return;
    status = "running";
    phase = "downloading";
    logs = [];
    result = null;
    errorMessage = null;

    source = new EventSource(api.download.oneOffUrl(url.trim(), format));

    source.onmessage = (e) => {
      const data: SyncEvent = JSON.parse(e.data);

      if (data.status === "running") {
        if (data.phase === "organizing") phase = "organizing";
        if (data.message) {
          logs = [...logs, { id: nextId++, text: data.message, kind: classifyLine(data.message) }].slice(-800);
          if (logEl) logEl.scrollTop = logEl.scrollHeight;
        }
      } else if (data.status === "done") {
        status = "done";
        result = { new: data.new ?? 0, skipped: data.skipped ?? 0, errors: data.errors ?? 0 };
        source?.close();
      } else if (data.status === "error") {
        status = "error";
        errorMessage = data.message ?? "Unknown error";
        source?.close();
      }
    };

    source.onerror = () => {
      if (status === "running") {
        status = "error";
        errorMessage = "Lost connection to server.";
      }
      source?.close();
    };
  }

  function reset() {
    status = "idle";
    logs = [];
    result = null;
    errorMessage = null;
  }

  onDestroy(() => source?.close());
</script>

<div class="flex flex-col h-full p-8 max-w-2xl">
  <div class="mb-6">
    <div class="text-amber-500 text-[10px] font-semibold uppercase tracking-widest mb-1">Library</div>
    <h2 class="text-white text-2xl font-bold tracking-tight">Download</h2>
    <p class="text-zinc-600 text-sm mt-1">Paste an Apple Music album or song URL to download and organize it.</p>
  </div>

  <div class="flex gap-2 mb-6">
    <input
      bind:value={url}
      placeholder="https://music.apple.com/…"
      disabled={status === "running"}
      class="flex-1 bg-[#111] border border-[#2a2a2a] rounded-lg px-3 py-2 text-sm text-white placeholder-zinc-700 outline-none focus:border-[#1db954] disabled:opacity-50"
    />
    <select
      bind:value={format}
      disabled={status === "running"}
      class="bg-[#111] border border-[#2a2a2a] rounded-lg px-2 py-2 text-sm text-zinc-300 outline-none disabled:opacity-50"
    >
      <option value="ALAC">ALAC</option>
      <option value="AAC">AAC</option>
      <option value="ATMOS">ATMOS</option>
    </select>
    <button
      onclick={startDownload}
      disabled={status === "running" || !url.trim()}
      class="bg-[#1db954] text-black text-sm font-bold px-4 rounded-lg hover:bg-[#1ed760] transition-colors disabled:opacity-50"
    >
      ↓ Download
    </button>
  </div>

  {#if status === "running"}
    <div class="flex items-center gap-0 mb-6">
      {#each PHASES as step, i}
        {@const done = phaseIndex > i}
        {@const active = phaseIndex === i}
        <div class="flex items-center gap-0">
          <div class="flex flex-col items-center gap-1">
            <div class="w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold transition-colors
              {done   ? 'bg-green-900/60 text-green-400 border border-green-800/50' :
               active  ? 'bg-amber-800/60 text-amber-300 border border-amber-700/50' :
                         'bg-[#1a1a1a] text-zinc-600 border border-[#2a2a2a]'}">
              {#if done}✓{:else if active}
                <span class="w-2.5 h-2.5 rounded-full bg-amber-400 animate-pulse"></span>
              {:else}{i + 1}{/if}
            </div>
            <span class="text-[9px] uppercase tracking-widest font-semibold whitespace-nowrap
              {done ? 'text-green-500' : active ? 'text-amber-400' : 'text-zinc-700'}">
              {step.label}
            </span>
          </div>
          {#if i < PHASES.length - 1}
            <div class="w-12 h-px mb-4 mx-1 transition-colors {done ? 'bg-green-900/50' : 'bg-[#222]'}"></div>
          {/if}
        </div>
      {/each}
    </div>

    <div
      bind:this={logEl}
      class="flex-1 min-h-0 bg-[#080808] border border-[#1a1a1a] rounded-xl p-3 overflow-y-auto font-mono text-xs leading-relaxed"
    >
      {#each logs as line (line.id)}
        <div class="
          {line.kind === 'add'  ? 'text-green-400' :
           line.kind === 'skip' ? 'text-zinc-600' :
           line.kind === 'err'  ? 'text-red-400' :
                                  'text-zinc-500'}">
          {line.text}
        </div>
      {/each}
      {#if logs.length === 0}
        <div class="text-zinc-700">Waiting for output…</div>
      {/if}
    </div>

  {:else if status === "done" && result}
    <div class="bg-[#111] rounded-xl p-6 border border-[#1e1e1e]">
      <div class="text-green-400 font-bold text-sm mb-4 flex items-center gap-2">✓ Download complete</div>
      <div class="flex gap-6">
        <div>
          <div class="text-white text-3xl font-bold tabular-nums">{result.new}</div>
          <div class="text-zinc-500 text-xs mt-1">new tracks</div>
        </div>
        <div>
          <div class="text-zinc-400 text-3xl font-bold tabular-nums">{result.skipped}</div>
          <div class="text-zinc-500 text-xs mt-1">already owned</div>
        </div>
        <div>
          <div class="text-3xl font-bold tabular-nums {result.errors > 0 ? 'text-red-400' : 'text-zinc-700'}">{result.errors}</div>
          <div class="text-zinc-500 text-xs mt-1">errors</div>
        </div>
      </div>
    </div>
    {#if logs.length > 0}
      <details class="mt-4 group">
        <summary class="text-zinc-600 text-xs cursor-pointer hover:text-zinc-400 flex items-center gap-1.5 select-none">
          <span class="group-open:rotate-90 transition-transform inline-block">▶</span>
          Log
        </summary>
        <div class="mt-2 bg-[#080808] border border-[#1a1a1a] rounded-xl p-3 font-mono text-xs text-zinc-600 max-h-48 overflow-y-auto leading-relaxed">
          {#each logs as line (line.id)}
            <div class="{line.kind === 'add' ? 'text-green-500/70' : line.kind === 'err' ? 'text-red-400/70' : ''}">{line.text}</div>
          {/each}
        </div>
      </details>
    {/if}
    <button onclick={reset} class="mt-4 text-zinc-500 hover:text-white text-sm transition-colors">Download another</button>

  {:else if status === "error"}
    <div class="bg-red-950/30 border border-red-900/50 rounded-xl p-5">
      <div class="text-red-400 font-bold mb-1">Download failed</div>
      <div class="text-zinc-400 text-sm leading-relaxed">{errorMessage}</div>
    </div>
    {#if logs.length > 0}
      <div class="mt-4 bg-[#080808] border border-[#1a1a1a] rounded-xl p-3 font-mono text-xs text-zinc-600 max-h-48 overflow-y-auto leading-relaxed">
        {#each logs as line (line.id)}
          <div class="{line.kind === 'err' ? 'text-red-400' : ''}">{line.text}</div>
        {/each}
      </div>
    {/if}
    <button onclick={reset} class="mt-4 text-zinc-500 hover:text-white text-sm transition-colors">Try again</button>
  {/if}
</div>
```

- [ ] **Step 3: Add Download nav item to `Sidebar.svelte`**

In `app/src/lib/Sidebar.svelte`, add `onopenDownload` to the Props interface and destructuring. Then add a nav button.

Replace the Props interface and destructuring (lines 4-22):

```svelte
  interface Props {
    playlists: Playlist[];
    selectedName: string | null;
    syncingPlaylist: string | null;
    onselectPlaylist: (name: string) => void;
    onstartSync: (name: string) => void;
    onopenSettings: () => void;
    onopenSetup: () => void;
    onopenDiagnostics: () => void;
    onopenDashboard: () => void;
    onopenDownload: () => void;
    onplaylistAdded: (pl: Playlist) => void;
  }

  let {
    playlists, selectedName, syncingPlaylist,
    onselectPlaylist, onstartSync,
    onopenSettings, onopenSetup, onopenDiagnostics, onopenDashboard, onopenDownload,
    onplaylistAdded,
  }: Props = $props();
```

Then add the Download button after the Setup button in the `<nav>` block. After the `◆ Setup` button (around line 81), add:

```svelte
    <button
      class="w-full text-left px-3 py-1.5 rounded-md text-sm text-[#888] hover:text-white hover:bg-[#1a1a1a] transition-colors"
      onclick={onopenDownload}
    >
      ↓ Download
    </button>
```

- [ ] **Step 4: Wire up the Download view in `+page.svelte`**

Replace the full content of `app/src/routes/+page.svelte`:

```svelte
<script lang="ts">
  import { onMount } from "svelte";
  import Sidebar from "$lib/Sidebar.svelte";
  import SyncProgress from "$lib/SyncProgress.svelte";
  import Settings from "$lib/Settings.svelte";
  import SetupWizard from "$lib/SetupWizard.svelte";
  import Diagnostics from "$lib/Diagnostics.svelte";
  import Dashboard from "$lib/Dashboard.svelte";
  import PlaylistDetail from "$lib/PlaylistDetail.svelte";
  import Download from "$lib/Download.svelte";
  import { api, type Playlist } from "../api";

  type View = "playlist" | "sync" | "settings" | "setup" | "diagnostics" | "dashboard" | "download";

  let view = $state<View>("dashboard");
  let playlists = $state<Playlist[]>([]);
  let selectedName = $state<string | null>(null);
  let syncingPlaylist = $state<string | null>(null);
  let dashboardKey = $state(0);

  let selectedPlaylist = $derived(playlists.find(p => p.name === selectedName) ?? null);

  onMount(async () => {
    playlists = await api.playlists();
  });

  function selectPlaylist(name: string) {
    selectedName = name;
    view = "playlist";
  }

  function startSync(name: string) {
    if (syncingPlaylist) return;
    syncingPlaylist = name;
    view = "sync";
  }

  async function onSyncDone() {
    syncingPlaylist = null;
    playlists = await api.playlists();
    dashboardKey++;
    view = selectedName ? "playlist" : "dashboard";
  }

  function onPlaylistAdded(pl: Playlist) {
    playlists = [...playlists, pl];
  }

  function onPlaylistDeleted(name: string) {
    playlists = playlists.filter(p => p.name !== name);
    if (selectedName === name) { selectedName = null; view = "dashboard"; }
  }

  function onPlaylistRenamed(oldName: string, newName: string) {
    selectedName = newName;
  }

  function onPlaylistUpdated(updated: Playlist) {
    playlists = playlists.map(p => p.name === updated.name ? updated : p);
  }
</script>

<div class="flex h-screen bg-[#0f0f0f] text-white overflow-hidden select-none">
  <Sidebar
    {playlists}
    selectedName={selectedName}
    {syncingPlaylist}
    onselectPlaylist={selectPlaylist}
    onstartSync={startSync}
    onopenSettings={() => (view = "settings")}
    onopenSetup={() => (view = "setup")}
    onopenDiagnostics={() => (view = "diagnostics")}
    onopenDashboard={() => (view = "dashboard")}
    onopenDownload={() => (view = "download")}
    onplaylistAdded={onPlaylistAdded}
  />
  <main class="flex-1 overflow-hidden">
    {#if view === "setup"}
      <SetupWizard ondone={() => (view = "dashboard")} />
    {:else if view === "diagnostics"}
      <Diagnostics onopenSettings={() => (view = "settings")} />
    {:else if view === "dashboard"}
      {#key dashboardKey}
        <Dashboard
          onstartSync={startSync}
          onselectPlaylist={selectPlaylist}
          onopenDiagnostics={() => (view = "diagnostics")}
        />
      {/key}
    {:else if view === "playlist" && selectedPlaylist}
      {#key selectedName}
        <PlaylistDetail
          playlist={selectedPlaylist}
          syncing={syncingPlaylist === selectedPlaylist.name}
          onstartSync={startSync}
          onrenamed={onPlaylistRenamed}
          ondeleted={onPlaylistDeleted}
          onupdated={onPlaylistUpdated}
        />
      {/key}
    {:else if view === "sync" && syncingPlaylist}
      <SyncProgress playlistName={syncingPlaylist} ondone={onSyncDone} />
    {:else if view === "settings"}
      <Settings />
    {:else if view === "download"}
      <Download />
    {:else}
      <div class="flex items-center justify-center h-full text-zinc-600 text-sm">
        Select a playlist from the sidebar
      </div>
    {/if}
  </main>
</div>
```

- [ ] **Step 5: Verify the app builds**

```bash
cd /home/ilikepie/Documents/VS-Projects/pies-alac-rip-tool/.worktrees/desktop-app/app
npm run check
```

Expected: no TypeScript or Svelte errors.

- [ ] **Step 6: Commit**

```bash
cd /home/ilikepie/Documents/VS-Projects/pies-alac-rip-tool/.worktrees/desktop-app
git add app/src/api.ts app/src/lib/Download.svelte app/src/lib/Sidebar.svelte app/src/routes/+page.svelte
git commit -m "feat: add Download page to sidebar for one-off album/song downloads"
```
