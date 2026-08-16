# Phase 5 Technical Specification: Packaging, Distribution Pipeline & Desktop Notifications

## Goal
Implement Phase 5 of the Pies Pear Music roadmap (Release 2 Serious Desktop Product & Release Readiness):
1. **Linux Packaging & Distribution Pipeline**: Automated packaging tooling and validation scripts for Linux x86_64 target bundles (`.AppImage`, `.deb`, `.rpm`) using Tauri 2.0 bundle targets and frozen PyInstaller backend sidecar (`pies-backend`).
2. **Native Desktop Notifications & Sync Event Dispatch**: Cross-platform system notifications on sync milestone triggers (Sync Started, Sync Completed with track counts, Sync Failed with actionable error context) and long-running job completion (Audio Integrity Scan, DAP Export).
3. **Packaging Smoke Test & Sidecar Validation Harness**: Automated smoke test harness (`scripts/verify-packaging.sh`) ensuring PyInstaller sidecar binary portability, dynamic library resolution (glibc compatibility / bundled dependencies), and Tauri packaging readiness.
4. **Desktop Integration & System Tray / App Lifecycle Health**: Verify window behavior, graceful background shutdown, and packaging metadata alignment across `tauri.conf.json`, `Cargo.toml`, and desktop environment `.desktop` / icon definitions.

---

## Architectural Details & Components

### 1. PyInstaller Sidecar & Packaging Automation (`scripts/build-backend-sidecar.sh`, `scripts/build-packages.sh`, `scripts/verify-packaging.sh`)
* **PyInstaller Sidecar Freezing (`scripts/build-backend-sidecar.sh`)**:
  - Validates Python virtualenv dependencies.
  - Bundles `alac_rip` package, FastAPI, Uvicorn, Mutagen, PyYAML, Requests into a standalone self-contained executable `app/src-tauri/binaries/pies-backend-x86_64-unknown-linux-gnu`.
  - Ensures `--hidden-import` rules cover dynamic Uvicorn and FastAPI dependencies.
* **Packaging Pipeline Script (`scripts/build-packages.sh`) [NEW]**:
  - Orchestrates clean frontend build (`npm run build`), sidecar verification, and `npm run tauri build -- --bundles appimage,deb,rpm`.
  - Validates output artifacts in `app/src-tauri/target/release/bundle/`.
* **Packaging Verification & Smoke Harness (`scripts/verify-packaging.sh` & `tests/test_packaging.py` [NEW])**:
  - Checks binary permissions and execution of frozen sidecar with `--sidecar-handshake`.
  - Validates `tauri.conf.json` bundle metadata (icons, identifier `com.pies.pear-music`, product name `Pies Pear Music`, category `Music`, license `GPL-3.0-or-later`).
  - Verifies presence of system dependencies checks in Diagnostics.

---

### 2. Native Desktop Notifications (`app/src-tauri/Cargo.toml`, `app/src-tauri/src/lib.rs`, `app/src/lib/notifications.ts` [NEW], `app/src/lib/SyncProgress.svelte`)
* **Tauri Notification Plugin Integration**:
  - Add `tauri-plugin-notification = "2"` to `app/src-tauri/Cargo.toml` and initialize `tauri_plugin_notification::init()` in `app/src-tauri/src/lib.rs`.
  - Add permission capabilities in Tauri configuration.
* **Frontend Notification Dispatcher (`app/src/lib/notifications.ts` [NEW])**:
  - Helper functions:
    - `notifySyncStarted(playlistName: string)`: Sends system notification when a playlist sync begins.
    - `notifySyncCompleted(playlistName: string, newCount: number, skippedCount: number)`: Sends completion notification with added/skipped counts.
    - `notifySyncFailed(playlistName: string, errorMessage: string)`: Sends failure notification with actionable summary.
    - `notifyIntegrityCompleted(corruptedCount: number)`: Notifies when audio verification finishes.
    - `notifyDapExportCompleted(playlistName: string, exportedCount: number)`: Notifies when DAP device export finishes.
  - Graceful fallback: checks `isPermissionGranted()` and requests permission if needed, falls back silently if desktop notifications are disabled or unsupported.
* **Integration Points**:
  - `SyncProgress.svelte`: Triggers `notifySyncStarted`, `notifySyncCompleted`, `notifySyncFailed`.
  - `Library.svelte` (Health Tab): Triggers `notifyIntegrityCompleted`.
  - `DapExportModal.svelte`: Triggers `notifyDapExportCompleted`.

---

### 3. Desktop Application Metadata & Production Hardening
* **Tauri Configuration & Permissions (`app/src-tauri/tauri.conf.json`, `app/src-tauri/capabilities/default.json`)**:
  - Ensure notification capability permissions are declared under `capabilities/default.json`.
  - Ensure CSP allows secure local loopback IPC and sidecar token auth.
* **Backend Sidecar Shutdown & Signal Handling (`alac_rip/server.py`, `app/src-tauri/src/lib.rs`)**:
  - Ensure `CloseRequested` window event and SIGTERM / SIGINT terminate any running child processes (downloader, wrapper, ffmpeg) cleanly to prevent zombie processes.

---

## Edge Cases, Invariants & Security Guardrails

1. **Sidecar Isolation & Token Security**:
   - The frozen `pies-backend` binary only listens on `127.0.0.1:<allocated_port>` and strictly requires `X-Pies-Api-Token` capability handshake over stdin pipe.
2. **Notification Flood Protection**:
   - Notifications must only be sent on state transitions (start, complete, fail), never on per-track log progress lines.
3. **Non-GUI / Headless Fallback**:
   - If notification daemon is not available on Linux (e.g. minimal WM or permission denied), the app continues functioning normally without errors.

---

## Verification Plan

### Automated Checks
1. **Python Test Suite**:
   ```bash
   .venv/bin/pytest
   ```
2. **Frontend Typechecks & Diagnostics**:
   ```bash
   cd app && npm run check
   ```
3. **Packaging & Sidecar Smoke Checks**:
   ```bash
   bash scripts/build-backend-sidecar.sh --if-stale
   bash scripts/verify-packaging.sh
   ```

### Manual Verification Flow
1. Run `cd app && npm run tauri dev`.
2. Trigger a sync on any playlist; verify desktop system notification appears on start and completion.
3. Trigger DAP export and audio integrity verification; verify completion notification fires.
4. Verify graceful app exit without lingering background processes (`pgrep -f pies-backend`).
