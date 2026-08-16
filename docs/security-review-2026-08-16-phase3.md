# Security & Quality Review — Phase 3 (UI Workstation Features)

**Review date:** 2026-08-16  
**Repository:** `pies-alac-rip-tool`  
**Reviewed branch:** `release/2`, including Phase 3 implementations  
**Review type:** Adversarial source-level security audit, input validation review, XSS audit, and test coverage assessment

---

## Executive Summary

Phase 3 introduces user-facing workstation interface extensions:
1. **DAP / Portable Player Transcode Export Modal & API** (`DapExportModal.svelte`, `alac_rip/dap_export.py`, `POST /export/dap`)
2. **Synchronized Lyrics Reader & Endpoints** (`LyricsModal.svelte`, `GET /tracks/{track_id}/lyrics`, `.lrc` sidecar integration)
3. **Digital Preservation Graveyard View** (`StreamingGraveyard.svelte`, `GET /streaming-graveyard`, `POST /reveal-track`)
4. **FLAC Stream Integrity Diagnostics** (Subprocess validation and integrity reporting)

The adversarial security and quality review confirms that the repository maintains high security standards:
- **No Command / Subprocess Injection**: Subprocess invocations (`ffmpeg`, `flac`, `gdbus`, `xdg-open`) use explicit argument arrays without `shell=True`. Bitrate and format parameters are strictly validated against whitelists and regex constraints (`^[1-9]\d{1,3}k$`).
- **No Path Traversal or Arbitrary File Overwrites**: Target export paths are resolved and validated with root (`/`) directory protection; library file resolution is constrained to safe paths; symlinks are rejected when resolving `.lrc` sidecars.
- **No XSS / Unsafe DOM Insertion**: All Svelte components (`DapExportModal.svelte`, `LyricsModal.svelte`, `StreamingGraveyard.svelte`, `PlaylistDetail.svelte`) render user/track data via standard Svelte text interpolation, avoiding `{@html}` tags.
- **No XML External Entity (XXE) Vulnerabilities**: TTML lyric streams are parsed with pure regular expressions rather than standard DOM/XML parsers.
- **Preserved Atomic Transactions**: FLAC integrity checks and staging workflows validate temporary files prior to final filesystem commitments.

---

## Component Audit Details

### 1. DAP Transcode & Export Engine (`alac_rip/dap_export.py`, `alac_rip/server.py`, `app/src/lib/DapExportModal.svelte`)
- **Path Validation**: `validate_dap_target_dir` calls `.expanduser().resolve()` and explicitly rejects the filesystem root (`/`). The API requires an absolute path.
- **Parameter Validation**: Bitrate inputs are strictly constrained by regex `^[1-9]\d{1,3}k$`, preventing flag-injection (e.g. `-option`) into `ffmpeg`. Format is constrained to `opus`, `aac`, or `m4a`.
- **M3U Playlist Safety**: Metadata entries (artist, title) stripped of newlines (`\r`, `\n`) and control characters (`\x00-\x1f\x7f-\x9f`) to prevent M3U directive injection.
- **Sidecar Safety**: Sidecar `.lrc` copying requires `.is_file() and not .is_symlink()`.

### 2. Synced Lyrics & TTML Engine (`alac_rip/am_api.py`, `alac_rip/server.py`, `app/src/lib/LyricsModal.svelte`)
- **Parsing Safety**: TTML-to-LRC conversion in `ttml_to_lrc` uses regex extraction without constructing an XML DOM, completely neutralizing XXE and XML entity expansion attacks.
- **Endpoint Protection**: `GET /tracks/{track_id}/lyrics` verifies track existence in SQLite state, resolves file paths via `_resolve_library_file`, and safely falls back when tags or `.lrc` files are missing.
- **UI Rendering**: `LyricsModal.svelte` displays timed lines and text content safely without `{@html}` interpolation. Includes search query sanitization and escape-key handling.

### 3. Streaming Graveyard & Digital Preservation (`alac_rip/state.py`, `alac_rip/server.py`, `app/src/lib/StreamingGraveyard.svelte`)
- **Query Safety**: SQLite state queries in `StateManager.get_delisted_tracks` use parameterized queries.
- **Reveal File Action**: `POST /reveal-track` verifies file existence within the user's library directory, URI-encodes the path safely (`file://` + `quote()`), and handles D-Bus / `xdg-open` subprocesses safely.

### 4. FLAC Stream Integrity (`alac_rip/sync.py`, `alac_rip/server.py`, `app/src/lib/Diagnostics.svelte`)
- **Subprocess Execution**: `_verify_flac_integrity` executes `[flac_bin, "-t", "-s", str(file_path)]` with `capture_output=True`.
- **Atomic Rollback**: Files failing stream validation raise `IntegrityError` and are unlinked before any database commit or destination copy occurs.

---

## Test & Build Verification

- **Backend Pytest Suite**: `234 passed in 6.12s` (`.venv/bin/pytest`)
- **Frontend Svelte Diagnostics**: `0 errors, 0 warnings` (`cd app && npm run check`)
- **Build / Typecheck**: Clean compilation across all modules.

---

## Release Decision

**APPROVED**: Phase 3 implementation passes adversarial review with zero critical or high vulnerabilities. The codebase is verified and ready for Session 4 git commit and release.
