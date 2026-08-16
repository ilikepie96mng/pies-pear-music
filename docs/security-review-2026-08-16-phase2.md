# Security & Quality Review — Phase 2 (Pies Pear Music)

**Review date:** 2026-08-16  
**Repository:** `pies-alac-rip-tool`  
**Reviewed branch:** `release/2`, including Phase 2 implementations  
**Review type:** Adversarial source-level security audit, input validation review, and test coverage assessment

---

## Executive Summary

Phase 2 introduces automated FLAC stream validation (`flac -t`), synchronized lyrics (.lrc / TTML) extraction and tag embedding, and multi-format DAP transcode exports (Opus / AAC). 

The review confirms that the security posture established in Phase 1 (100% remediations resolved) is fully preserved:
- No shell injection vectors were introduced; all subprocess executions (`ffmpeg`, `flac`) use explicit argument arrays without `shell=True`.
- Temporary-file atomicity is maintained during ingestion: FLAC stream integrity is validated on `.tmp` files *before* atomic `os.replace` commits files to the user's music library.
- Regex-based TTML parsing eliminates vulnerability to XML external entity (XXE) and XML entity expansion (Billion Laughs) DoS attacks.
- Export routines generate relative M3U playlists with newline and control character sanitization.

One low-severity hardening recommendation was identified (SR-12: Bitrate parameter format validation in DAP export).

---

## Scope & Target Components

### 1. FLAC Stream Integrity Verification (`alac_rip/sync.py`)
- **Audit Points**: Subprocess execution safety, binary discovery via `shutil.which`, error handling on corrupted FLAC files, cleanup of temporary files upon decode failure.
- **Findings**:
  - `_verify_flac_integrity` executes `[flac_bin, "-t", "-s", str(file_path)]` with `capture_output=True`.
  - Corrupt files raise `IntegrityError`, preventing commitment into SQLite state or filesystem destinations.
  - Temporary files are cleanly unlinked in `except` blocks.
  - Graceful fallback when the `flac` command-line utility is absent.

### 2. Time-Synced Lyrics & TTML Engine (`alac_rip/am_api.py`, `alac_rip/metadata.py`, `alac_rip/sync.py`)
- **Audit Points**: Handling of untrusted Apple Music catalog lyrics responses, XML parser safety, sidecar `.lrc` file paths.
- **Findings**:
  - `ttml_to_lrc` uses pure regular expressions rather than standard DOM/XML parsers, completely avoiding XXE/Billion-Laughs vulnerabilities.
  - `_parse_ttml_time` validates timestamp formats and rejects malformed inputs safely.
  - Sidecar `.lrc` files are written directly adjacent to the sanitized track name (`{idx:02d} - {title}.lrc`) inside the validated album directory.

### 3. DAP / Portable Transcode Profiles (`alac_rip/dap_export.py`, `alac_rip/server.py`)
- **Audit Points**: Target directory traversal, bitrate/format parameter injection, relative M3U generation.
- **Findings**:
  - `validate_dap_target_dir` checks for absolute paths and rejects filesystem root (`/`).
  - Output directories and file paths are sanitized via `sanitize()`.
  - Playlist lines flatten control characters and newlines (`\r`, `\n`, `\t`) to prevent M3U directive injection.

---

## Audit Findings & Hardening Recommendations

### SR-12 — Validate DAP Bitrate Argument Format (Low Severity)
- **Category**: Input Validation / Defense-in-Depth
- **Affected File**: `alac_rip/dap_export.py:73` and `alac_rip/server.py:1259`
- **Description**: While `subprocess.run` uses an argument list preventing shell injection, the `bitrate` parameter accepted arbitrary strings. If a string starting with `-` were provided, `ffmpeg` could misinterpret it as a command option flag.
- **Remediation**: Enforce a strict regex validator on the bitrate string (e.g. `^(\d{2,4}k|[1-9]\d{0,2}M)$` or whitelist standard rates such as `96k`, `128k`, `160k`, `192k`, `256k`, `320k`).

---

## Test & Build Verification

- **Backend Pytest Suite**: `230 passed in 4.84s` (`.venv/bin/pytest`)
- **Frontend SvelteKit**: `0 errors, 0 warnings` (`cd app && npm run check`)
- **Git Status**: Clean working tree changes; all state databases untracked.

---

## Release Decision

**APPROVED**: Phase 2 implementation meets all security, fidelity, and reliability criteria.
