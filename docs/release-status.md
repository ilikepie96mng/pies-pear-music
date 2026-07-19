# Release Status

This is a working readiness record for the first public `0.1.0` release. It is
not a publication approval.

## Completed preparation

- Desktop package launches a PyInstaller backend sidecar instead of requiring a
  source checkout.
- Local Debian and RPM packages build and contain `usr/bin/pies-backend`.
- CI defines an Ubuntu 22.04 Debian/AppImage build with sidecar, checksum,
  build-input, and SBOM validation. A green artifact run is still pending.
- URL/format/name/path input validation, bounded SQLite waits, Strawberry busy
  handling, generic error-path redaction, constrained CORS, and a restrictive
  Tauri CSP are in place.
- Diagnostics validates the required user-installed toolchain and source
  directories without exposing local paths.
- Public governance, packaging, architecture, appearance, development,
  troubleshooting, snapshot, and auth-contract documentation exists.
- The public snapshot verifier rejects private state, legacy installers,
  private planning material, and machine-specific paths.
- The frozen wrapper-command/2FA contract suite covers Secret Service
  save/load/clear and a no-keyring session-only fallback. The application no
  longer reads or writes a plaintext/base64 credential file.
- Each packaged sidecar launch receives a fresh Tauri-generated loopback port
  and API capability over a stdin handshake. Header-based requests,
  authenticated fetch streams, and authenticated artwork blobs are verified
  with fixture-only tests.

## Verified locally

- Compatible local Python suite: 154 passing on the available Python 3.14 environment.
- Svelte check/build: zero diagnostics.
- Rust format/Clippy/tests: passing, including sidecar port parsing tests.
- Debian/RPM artifact verifier: checksums, SBOM manifests, build info, and
  sidecar placement pass.

## Publication blockers

- Build and smoke-test AppImage on the Ubuntu 22.04 CI baseline. Fedora 44
  local AppImage bundling is blocked by linuxdeploy's older `strip` tool not
  understanding newer ELF `RELR` sections; it is not release evidence.
- Validate the complete package smoke matrix on Ubuntu 22.04, Debian 12,
  current Fedora, and current Bazzite.
- Resolve third-party provenance and licensing for every borrowed or external
  dependency path. No package may distribute an unlicensed patch or binary.
- Create the sanitized public repository from a reviewed new history and pass
  secret/PII/history review. Never publish this private history.
- Run the Python API suite on the supported 3.12 and 3.13 CI environments.
  Local Python 3.14 hangs during FastAPI TestClient lifespan startup.
- Perform the authorized manual release check: login/2FA, manual playlist sync,
  restart, desktop Secret Service behavior, authenticated sidecar launch,
  dependency failures, and state retention. No live credentials or downloads
  run in public CI.
- Run the clean-user package smoke checklist on Ubuntu 22.04, Debian 12, and
  current Fedora; it includes launcher, setup, player, reinstall, and
  data-retention checks. On Bazzite, validate the AppImage only; RPM layering
  is intentionally not a release acceptance path.
