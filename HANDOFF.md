# Handoff — pies-alac-rip-tool

**Last Updated:** 2026-08-16  
**Status:** Phase 4 Review & Security Audit Complete (Release 1.5 Ready)  
**Next Up:** Session 4: Git Commit & Release Tagging for Phase 4 (Library Stewardship & Health Maintenance Workstation)

---

## 1. Project Overview & Architecture
* **Frontend**: SvelteKit / Vite desktop interface (`app/src/lib/`).
* **Shell**: Tauri desktop wrapper (`app/src-tauri/`).
* **Backend**: FastAPI sidecar (`alac_rip/server.py`). Communicates with Tauri via ephemeral stdin capability token (`X-Pies-Api-Token`).
* **Downloader**: External Go binary (`apple-music-downloader`), deployed at `~/.local/share/pies-alac-rip/amd-main`.
* **State**: SQLite database (`state_dir / "downloaded.db"`), tracked via `alac_rip/state.py`.
* **Target Platforms**: Linux (Ubuntu 22.04+, Fedora Workstation mandatory, Arch/Bazzite via AppImage) + Windows 10/11 native support.

---

## 2. Phase 4 Review & Security Audit Results (Session 3: Audit)

### 1. Security & Edge Cases Verified
* **Path Scoping & Traversal Controls**:
  - `alac_rip/audit.py` enforces `_is_safe_subpath()` verifying all adopted or scanned paths reside strictly within the resolved `music_dir`.
  - `alac_rip/server.py` guards library routes with `_resolve_library_file()` and checks `state.has_track_path()`.
  - Capability token authentication (`x-pies-api-token` via `secrets.compare_digest`) protects sidecar endpoints against unauthorized local processes.
* **Non-Destructive Repair Guarantees**:
  - Database track pruning (`prune_missing_tracks`) only deletes SQLite metadata for verified missing files; no filesystem audio files are deleted.
  - Orphan adoption reads existing metadata tags non-destructively and indexes them into SQLite state.
  - Playlist repair generates clean `#EXTM3U` files safely scoped to `music_dir / "playlists"`.
* **SQLite Query Safety & Scalability**:
  - `prune_missing_tracks` chunks deletions in batches of 500 to adhere to SQLite parameter limits.
  - All database queries use parameterized SQL inputs.

### 2. Code & Architecture Review
* **`alac_rip/audit.py`**: Clean, modular audit engine with stream frame verification (`flac -t -s`), orphan scanner, and tag fallback.
* **`alac_rip/state.py`**: Added provenance tracking, library statistics aggregation, and track pruning.
* **`alac_rip/server.py`**: Added `/library/tracks`, `/library/stats`, `/library/audit`, `/library/verify-integrity`, and `/library/repair`.
* **`app/src/api.ts` & `app/src/lib/Library.svelte`**: Complete TypeScript typing and multi-tab interface (Tracks, Albums, Artists, Health & Diagnostics) with real-time filtering, sorting, lyrics viewer, DAP export, and 1-click diagnostic repair tools.

---

## 3. Verification & Test Suite Passing State
* **Python Test Suite**: `243 passed in 6.51s` (`.venv/bin/pytest`)
* **Svelte Diagnostics**: `0 errors, 0 warnings` (`cd app && npm run check`)

---

## 4. Instructions for Next Agent Session (Session 4: Release & Commit)
1. **Target Action**: Commit Phase 4 changes to Git repository.
2. **Commit Message Format**:
   - `feat(library): phase 4 library stewardship, health audit & maintenance workstation`
3. **Files to Stage**:
   - `alac_rip/audit.py`
   - `alac_rip/server.py`
   - `alac_rip/state.py`
   - `app/src/api.ts`
   - `app/src/lib/Library.svelte`
   - `app/src/lib/Sidebar.svelte`
   - `app/src/routes/+page.svelte`
   - `docs/plans/phase-4-spec.md`
   - `tests/test_audit.py`
   - `tests/test_library_api.py`
   - `HANDOFF.md`

---

## 5. Starter Prompt for Next Session (Session 4: Release / Commit)

```markdown
You are the Release Agent executing Session 4 of the Archival Music Workstation roadmap according to docs/agent-workflow.md.

Please review HANDOFF.md and stage/commit the Phase 4 implementation:
1. Verify git status.
2. Stage and commit Phase 4 changes with message:
   `feat(library): phase 4 library stewardship, health audit & maintenance workstation`
3. Run final sanity test checks (`.venv/bin/pytest` and `cd app && npm run check`).
```
