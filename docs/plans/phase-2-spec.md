# Phase 2 Technical Specification: Audio Fidelity, Lyrics & DAP Profiles

## Goal
Implement Phase 2 of the Archival Music Workstation roadmap:
1. **Automated FLAC Stream Verification (`flac -t`)**: Verify MD5 checksums and audio frame decode validity on every newly ingested FLAC before committing to library state.
2. **Time-Synced Lyrics (.lrc / TTML)**: Fetch and save synchronized syllable/line lyrics sidecars (`.lrc`) alongside `.flac` files and embed lyric tags for Strawberry and DAP players.
3. **Multi-Format DAP / Portable Transcode Profile**: Add a worker utility to export/transcode selected playlists to an external microSD / folder in high-quality Opus (160kbps) or AAC-VBR.

---

## Architectural Details & Components

### 1. FLAC Stream Integrity Verification (`alac_rip/sync.py` & `alac_rip/organizer.py`)
* **Mechanism**:
  - In `SyncEngine._verify_flac_integrity(file_path: Path) -> tuple[bool, str]`:
    - Run `subprocess.run(["flac", "-t", "-s", str(file_path)], capture_output=True)`.
    - If `flac` binary is missing, log warning and gracefully continue.
    - If `returncode != 0`, raise `IntegrityError` or quarantine the corrupt file to prevent committing bad audio.
* **Security & Invariants**:
  - Temporary file `.tmp_PID_i_name.flac` is tested with `flac -t` **before** the atomic `os.replace` to the final destination.

### 2. Time-Synced Lyrics (.lrc / TTML) (`alac_rip/am_api.py` & `alac_rip/sync.py`)
* **Mechanism**:
  - In `am_api.py`, add `fetch_lyrics(track_id: str, bearer_token: str, storefront: str = "us") -> Optional[str]`:
    - Queries Apple Music AMP API `https://amp-api.music.apple.com/v1/catalog/{storefront}/songs/{track_id}/lyrics` or parses TTML/LRC format.
  - When saving track in `SyncEngine`:
    - If `.lrc` exists in staging or lyrics are fetched, write sidecar `01 - Title.lrc` in the album directory.
    - Embed `UNSYNCEDLYRICS` / `LYRICS` tags in Vorbis comments in `alac_rip/metadata.py`.

### 3. DAP / Portable Export Profile (`alac_rip/dap_export.py` & `alac_rip/server.py`)
* **Mechanism**:
  - Provide `export_dap_playlist(music_dir: Path, playlist_name: str, target_dir: Path, format: str = "opus", bitrate: str = "160k") -> dict`:
    - Reads playlist tracks from `state.db`.
    - For each track, transcodes `.flac` to `.opus` or `.m4a` (AAC) into `target_dir / playlist_name / NN - Title.opus` using ffmpeg.
    - Generates a relative `.m3u` playlist in `target_dir` with relative paths (`01 - Title.opus`).
  - Endpoint: `POST /export/dap` taking `{"playlist_name": str, "target_dir": str, "format": "opus"|"aac"}`.

---

## Test Plan & Verification
* **Unit Tests**:
  - `tests/test_flac_integrity.py`: Test `flac -t` verification with valid vs truncated/corrupt fake FLAC files.
  - `tests/test_lyrics.py`: Test `.lrc` sidecar writing and Vorbis comment lyric embedding.
  - `tests/test_dap_export.py`: Test DAP transcode export with relative M3U generation.
* **Commands to Run**:
  - `.venv/bin/pytest`
  - `npm run check`
