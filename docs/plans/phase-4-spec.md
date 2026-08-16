# Phase 4 Technical Specification: Library Stewardship, Health Audit & Maintenance Workstation

## Goal
Implement Phase 4 of the Archival Music Workstation roadmap (Release 1.5 Library Stewardship & Integrity Maintenance):
1. **Searchable Global Library Browser**: Comprehensive workstation view to browse, filter, and sort all local library tracks, albums, and artists with track provenance (source playlist, download date, artwork, lyrics, audio resolution).
2. **Library Health & Diagnostics Audit**: Automated scanner comparing filesystem state against the SQLite database to detect orphaned disk files, missing local audio files, missing artwork, and missing lyrics sidecars.
3. **Batch FLAC Stream Integrity Scanner & Repair Engine**: Library-wide `flac -t` audio integrity verification tool with repair actions (regenerate `.m3u8` playlists, prune dead DB references, adopt untracked files).
4. **Desktop Navigation & UI Integration**: Integrate the Library Stewardship Hub into `Sidebar.svelte`, `Library.svelte`, `DataControls.svelte`, and `api.ts`.

---

## Architectural Details & Components

### 1. Backend Library & Health Audit Engine (`alac_rip/state.py`, `alac_rip/audit.py`, `alac_rip/server.py`)
* **State Manager Extensions (`alac_rip/state.py`)**:
  - `get_all_tracks_with_provenance() -> list[dict]`:
    - Returns all unique tracks along with a list of playlist names they belong to, download timestamps, and local paths.
  - `get_library_stats() -> dict`:
    - Total tracks, total albums, total artists, total storage size (calculated from files on disk), delisted count.
  - `prune_missing_tracks(missing_track_ids: list[str]) -> int`:
    - Safely removes track records and playlist associations for files that no longer exist on disk after user confirmation.
* **Health Audit & Verification Service (`alac_rip/audit.py` [NEW])**:
  - `audit_library(music_dir: Path, state: StateManager) -> dict`:
    - **Missing Files**: Tracks in SQLite DB whose `local_path` does not exist on disk.
    - **Orphaned Files**: `.flac` / `.m4a` files inside `music_dir` that are not tracked in SQLite.
    - **Missing Artwork / Lyrics**: Tracks lacking embedded Vorbis artwork / `.lrc` sidecars.
    - **Summary Counts**: `{missing_files: [...], orphaned_files: [...], missing_lyrics: [...], missing_art: [...]}`.
  - `verify_library_flac_integrity(music_dir: Path, state: StateManager, limit: Optional[int] = None) -> dict`:
    - Runs `flac -t -s` concurrently or sequentially across library tracks.
    - Reports corrupted/truncated audio files with error messages.
  - `repair_playlists(music_dir: Path, state: StateManager) -> dict`:
    - Re-generates all `.m3u8` playlist files from SQLite database mappings to fix corrupted/missing playlist files.
* **FastAPI Server Endpoints (`alac_rip/server.py`)**:
  - `GET /library/tracks`: Returns list of all tracks across the entire library with provenance playlists, artwork URL, and lyrics flag.
  - `GET /library/audit`: Runs fast health audit (missing files, orphaned files, missing metadata) and returns report.
  - `POST /library/verify-integrity`: Triggers audio frame / MD5 stream validation for FLAC files in the library.
  - `POST /library/repair`: Accepts action `{"action": "regenerate_m3u8" | "prune_missing" | "adopt_orphans"}` and executes safe repair.

---

### 2. Frontend Workstation & Stewardship Views (`app/src/lib/` & `app/src/api.ts`)

* **API Client Updates (`app/src/api.ts`)**:
  - `api.allLibraryTracks()`: Calls `GET /library/tracks`.
  - `api.auditLibrary()`: Calls `GET /library/audit`.
  - `api.verifyIntegrity()`: Calls `POST /library/verify-integrity`.
  - `api.repairLibrary(action: string, payload?: any)`: Calls `POST /library/repair`.

* **Global Library Browser (`app/src/lib/Library.svelte`)**:
  - Sub-views: **Tracks**, **Albums**, **Artists**, **Health & Cleanup**.
  - Search bar with instant real-time filtering across track title, artist, album, and playlist name.
  - Sort by: Date Downloaded (newest first), Artist, Album, Title, File Size.
  - Track Row details:
    - Cover thumbnail.
    - Title, Artist, Album.
    - Provenance tags: Badges showing which playlists contain this track.
    - Lyrics badge (`.lrc`), Hi-Res/Lossless indicator, Integrity check status.
    - Actions: "Reveal File", "View Lyrics", "Export DAP".

* **Health & Repair Modal / Tab (`app/src/lib/LibraryHealth.svelte` [NEW] or embedded in `Library.svelte`)**:
  - Diagnostic cards:
    - Missing files count with "Prune from database" action.
    - Orphaned audio files on disk with "Import to library" or "Review" action.
    - Integrity audit status with "Run Audio Integrity Scan" button.
    - M3U8 Playlist sync health with "Regenerate All M3U8s" button.

* **Sidebar & App Navigation (`app/src/lib/Sidebar.svelte` & `app/src/routes/+page.svelte`)**:
  - Add `♫ Library` navigation entry to `Sidebar.svelte` between `Home` and `Dashboard`.
  - Wire `onopenLibrary` in `+page.svelte` to switch to `view = "library"`.

---

## Edge Cases, Invariants & Security Guardrails

1. **Path Traversal & Safe Path Scoping**:
   - All audit scanning is strictly scoped to `resolved` `music_dir` subdirectories.
   - Any repair actions that delete/prune or read files must validate paths using `_resolve_library_file` ensuring no symlink or escaping path traversal vulnerabilities.
2. **Non-Destructive Repair Defaults**:
   - No files are deleted automatically. Pruning missing DB entries only affects database metadata where the file is verified to be non-existent on disk.
3. **Responsive Background Execution**:
   - FLAC stream verification and full audit operations handle large libraries (10k+ tracks) efficiently without blocking SQLite or timing out.

---

## Verification Plan

### Automated Checks
* **Backend Unit & Integration Tests**:
  - `tests/test_audit.py`: Test missing file detection, orphaned file detection, and playlist regeneration.
  - `tests/test_library_api.py`: Test `GET /library/tracks`, `GET /library/audit`, `POST /library/repair`.
  - Run tests:
    ```bash
    .venv/bin/pytest
    ```
* **Frontend Diagnostics**:
  - Run SvelteKit typechecking and diagnostics:
    ```bash
    cd app && npm run check
    ```

### Manual Verification Flow
1. Open the app -> Click **♫ Library** in the sidebar.
2. Search for artists and tracks across multiple playlists; verify provenance badges display correctly.
3. Switch to Album / Artist grouped views.
4. Run "Library Health Audit" -> Verify missing files, orphaned files, and M3U8 repair actions work cleanly.
