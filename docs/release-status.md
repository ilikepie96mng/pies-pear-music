# Release Status

This is a working readiness record for the first public `0.1.0` release. It is
not a publication approval.

## Completed preparation

- Desktop package launches a PyInstaller backend sidecar instead of requiring a
  source checkout.
- Local Debian and RPM packages build and contain `usr/bin/pies-backend`.
- CI successfully builds Ubuntu 22.04 Debian and AppImage packages with the
  real backend sidecar, then verifies package contents, checksums, build-input
  metadata, and SBOM manifests before uploading the artifacts. The first fully
  green artifact run was
  [CI run 29705112778](https://github.com/ilikepie96mng/pies-alac-rip-tool/actions/runs/29705112778).
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
- CI Python suites pass on Python 3.12 and 3.13; frontend and Rust checks pass.
- CI builds and verifies Ubuntu 22.04 Debian and AppImage artifacts. This is
  build evidence, not a substitute for the clean-machine smoke tests below.

## Publication blockers

- Validate the complete package smoke matrix on Ubuntu 22.04, Debian 12,
  current Fedora, and current Bazzite.
- Resolve third-party provenance and licensing for every borrowed or external
  dependency path. No package may distribute an unlicensed patch or binary.
- Create the sanitized public repository from a reviewed new history and pass
  secret/PII/history review. Never publish this private history.
- Perform the authorized manual release check: login/2FA, manual playlist sync,
  restart, desktop Secret Service behavior, authenticated sidecar launch,
  dependency failures, and state retention. No live credentials or downloads
  run in public CI.
- Run the clean-user package smoke checklist on Ubuntu 22.04, Debian 12, and
  current Fedora; it includes launcher, setup, player, reinstall, and
  data-retention checks. On Bazzite, validate the AppImage only; RPM layering
  is intentionally not a release acceptance path.
