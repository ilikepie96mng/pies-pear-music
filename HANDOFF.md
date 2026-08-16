# Handoff — pies-alac-rip-tool

**Last Updated:** 2026-08-16  
**Status:** Phase 5 Completed & Released (Production Packaging, Notifications & Verification Harness)  
**Next Up:** Project Roadmap Complete / Ongoing Maintenance & Future Enhancements

---

## 1. Project Overview & Architecture
* **Frontend**: SvelteKit / Vite desktop interface (`app/src/lib/`).
* **Shell**: Tauri desktop wrapper (`app/src-tauri/`).
* **Backend**: FastAPI sidecar (`alac_rip/server.py`). Communicates with Tauri via ephemeral stdin capability token (`X-Pies-Api-Token`).
* **Downloader**: External Go binary (`apple-music-downloader`), deployed at `~/.local/share/pies-alac-rip/amd-main`.
* **State**: SQLite database (`state_dir / "downloaded.db"`), tracked via `alac_rip/state.py`.
* **Target Platforms**: Linux (Ubuntu 22.04+, Fedora Workstation mandatory, Arch/Bazzite via AppImage) + Windows 10/11 native support.

---

## 2. Completed Milestones & Phase Progress
* [x] **Phase 1**: Core architecture, sidecar lifecycle, FastAPI bridge & initial Svelte interface.
* [x] **Phase 2**: Dual-pane Library UI, interactive track selection, status polling & progress tracking.
* [x] **Phase 3**: Enhanced metadata enrichment, cover art pipeline, album/playlist view optimizations.
* [x] **Phase 4**: Library stewardship, file deduplication, custom directory structures & DAP export.
* [x] **Phase 5**: Packaging pipeline (Linux RPM/DEB/AppImage + Windows), cross-platform native desktop notifications, capability security boundaries, and automated packaging smoke verification harness.

---

## 3. Phase 5 Release Highlights
* **Security & Capability Boundaries**:
  - **Notification Permissions**: Scoped strictly via `notification:default` in `app/src-tauri/capabilities/default.json`. Dispatcher in `app/src/lib/notifications.ts` gracefully degrades in unsupported or non-Tauri environments without throwing exceptions.
  - **Sidecar Isolation & Handshake**: Spawning restricted strictly to `binaries/pies-backend` with stdin token exchange over loopback (`127.0.0.1`).
  - **Packaging Bundle Integrity**: Desktop category set to `Music`, identifier `com.pies.pear-music`, and all asset icons verified on disk.
* **Packaging & Distribution Pipeline**:
  - `scripts/build-packages.sh`: Automates PyInstaller sidecar freezing, Svelte frontend build, and Tauri bundle generation (`.deb`, `.rpm`, `.AppImage`).
  - `scripts/verify-packaging.sh`: Automated smoke harness validates frozen sidecar handshake execution, capability configurations, and package contents.
  - `tests/test_packaging.py`: Unit test coverage ensuring package metadata, permissions, and build script validity.

---

## 4. Verification & Test Suite Passing State
* **Python Test Suite**: `249 passed` (`.venv/bin/pytest`)
* **Packaging Unit Tests**: `6 passed` (`.venv/bin/pytest tests/test_packaging.py`)
* **Svelte Diagnostics**: `0 errors, 0 warnings` (`cd app && npm run check`)
* **Packaging Verification Harness**: `Verified 2 package archive(s)` (`bash scripts/verify-packaging.sh`)

---

## 5. Starter Prompt for Next Session

```markdown
You are the AI Assistant maintaining pies-alac-rip-tool according to docs/agent-workflow.md.

Phase 5 has been fully released. All 5 core phases of the roadmap are complete:
- Review HANDOFF.md and current codebase status.
- Let me know if you would like to begin planning a new feature / phase or perform specific maintenance/verification tasks.
```
