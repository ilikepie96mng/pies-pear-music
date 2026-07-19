# Pies Pear Music Public Release Plan

## Goal

Prepare a sanitized `0.1.0` public release of Pies Pear Music for Linux
x86_64. Ship AppImage, Debian, and RPM packages containing the Tauri UI and
Python backend. Downloader and wrapper tools remain user-installed external
dependencies. Manual sync is the only supported v1 workflow; scheduling is
deferred.

## Confirmed Decisions

- Canonical product name: Pies Pear Music.
- First platform: Linux x86_64 broadly.
- Release artifacts: AppImage, `.deb`, and `.rpm`.
- Public history: start a new sanitized history instead of publishing or
  rewriting the current private history.
- License direction: GPL-3.0-or-later for independently owned code after the
  provenance review is complete.
- Upstream distribution: do not bundle the downloader, wrapper, `alac-rip`,
  Bento4, or patched third-party binaries.
- AI disclosure: state that the project was substantially AI-generated, then
  human-reviewed and tested.
- Authentication: preserve the fragile wrapper protocol, build regression
  coverage first, and change credential persistence last.
- Final credential target: Linux Secret Service with session-only fallback and
  no plaintext/base64 fallback.
- Themes: curated presets plus semantic color overrides, live preview,
  contrast warnings, reset, and versioned import/export.
- Scheduled syncing: deferred until after v1.

## Audit Baseline

### Publication blockers

- `.state/downloaded.db` is tracked and has appeared repeatedly in Git history.
  The current database contains 5,146 tracks, four playlists, 5,146 playlist
  memberships, and 40 sync records. Its schema stores playlist URLs, music
  metadata, absolute local paths, log paths, and errors.
- Every advertised `music-sync` command currently raises `NotImplementedError`.
  The README, installer shim, and systemd timer therefore describe or install a
  nonfunctional workflow.
- The Tauri backend launcher resolves the source repository at compile time and
  searches for `<repo>/.venv/bin/python3`. Current bundles cannot run without a
  source checkout.
- The backend writes a predictable `/tmp/pies-alac-rip.port` file and exposes an
  unauthenticated loopback HTTP API with unrestricted CORS. Tauri CSP is
  disabled.
- Credentials are base64-encoded on disk, written without an atomic restrictive
  creation step, passed through Podman environment data, and partially exposed
  in wrapper logs.
- `/reveal-track` and `/track-art` accept arbitrary existing filesystem paths.
- The installer downloads mutable upstream content without commit pins or
  integrity verification and uses predictable `/tmp` filenames.
- No root license, security policy, contribution guide, release workflow,
  changelog, complete third-party notice, or AI-use disclosure exists.

### Quality baseline

- Python collected 139 tests under Python 3.14 but hung at
  `tests/test_home_endpoint.py::test_home_empty_library`.
- `npm run check` passed with four Svelte warnings involving modal
  accessibility, hover-only behavior, and stale initial component state.
- `npm run build` passed with the same warnings.
- `cargo check --locked` and `cargo test --locked` passed, but Rust has zero
  tests.
- Shell syntax checks passed for `install.sh` and `uninstall.sh`.
- `requirements.txt` contains duplicate, conflicting FastAPI/Uvicorn/HTTPX
  versions and differs from `pyproject.toml`.
- The example config, backend `Config`, update API, Settings UI, installer, and
  documentation disagree about accepted fields and active features.
- Git-backed state backup settings and code are present but are not called by
  the desktop pipeline.

### Provenance concerns

- Auth behavior was pulled from `lalit22km/alac-rip`, which does not visibly
  provide a license file.
- `zhaarey/apple-music-downloader` also does not visibly provide a license and
  is itself a fork with earlier-author attribution.
- `zhaarey/wrapper` is archived, recommends another wrapper, and does not
  visibly provide a license file.
- GPL licensing of Pies Pear Music cannot grant rights to copied third-party
  code. Permission or an independently implemented replacement is a release
  gate.
- Bento4 uses a GPL/commercial dual-license model. It must not be bundled until
  its distribution obligations have been reviewed and satisfied.

## Implementation Plan

### 1. Sanitize and establish governance

- Create the public repository from a reviewed source snapshot with new Git
  history. Exclude `.state/`, databases, logs, credentials, private plans,
  generated files, and machine-specific paths.
- Run full-history secret and PII scans before the first public push.
- Store runtime state under XDG data directories and make databases untrackable
  by default.
- Audit every section influenced by `lalit22km/alac-rip`. Obtain permission or
  independently replace borrowed code before applying GPL-3.0-or-later.
- Add `LICENSE`, `THIRD_PARTY_NOTICES`, `SECURITY.md`, contribution guidance,
  changelog, AI-use disclosure, and non-affiliation/responsible-use notices.
- Maintain an upstream compatibility matrix with repository URL, tested
  commit/release, architecture, checksum, patch status, and license status.
- Do not publish if a working setup requires distributing an unlicensed patch
  or binary.

### 2. Restore a truthful supported product surface

- Make the desktop application and manual sync the sole v1 interface.
- Remove the broken CLI entry point, installer shim, systemd units, timer UI,
  scheduling claims, and Git-backed database synchronization from the supported
  surface.
- Consolidate configuration into one validated model for music/state paths,
  external tool locations, log retention, Last.fm, and app preferences.
- Move secrets out of YAML. Use atomic writes, mode-restricted files, backups,
  and an explicit migration path for the existing private installation.
- Split the large server into configuration, auth, jobs, library, integration,
  and API ownership boundaries while preserving behavior.
- Add structured errors, graceful process shutdown, single-instance handling,
  queue cancellation behavior, and SQLite locking/timeouts.

### 3. Secure the desktop/backend boundary

- Replace the predictable port file with a Rust-managed sidecar handshake.
- Generate a per-process capability token and pass connection data through
  process pipes rather than command arguments or shared files.
- Require authentication on every API route, restrict allowed origins, and
  replace unauthenticated `EventSource` use with authenticated fetch streaming.
- Enable a least-privilege Tauri CSP and narrow opener permissions.
- Validate Apple Music URLs, formats, playlist names, query limits, and all
  requested filesystem paths.
- Allow artwork and reveal operations only for known library records beneath
  the configured music directory.
- Redact emails, passwords, tokens, sensitive URLs, and local paths from logs,
  diagnostics, errors, API responses, and support bundles.
- Add safe Strawberry database backups, busy handling, transactions, and
  concurrent-process checks.

### 4. Package a real desktop application

- Freeze the Python 3.12 backend as a PyInstaller sidecar and launch it from
  Tauri resources instead of a repository-relative virtual environment.
- Build AppImage, Debian, and RPM artifacts on an Ubuntu 22.04 baseline to
  reduce glibc compatibility problems.
- Normalize product name, reverse-domain identifier, version, maintainer,
  description, license, icons, and desktop metadata.
- Include only owned code and redistributable dependencies in packages.
- Make onboarding locate and validate user-installed Podman, FFmpeg, MP4Box,
  optional `mp4decrypt`, downloader, and wrapper installations.
- Never silently download third-party executables. Show compatible tested
  versions and actionable setup links instead.
- Publish SHA-256 checksums, an SBOM, build provenance, release notes, and clear
  uninstall/data-retention behavior.

### 5. Add the appearance system

- Replace hardcoded component colors with semantic tokens for canvas, surfaces,
  elevated surfaces, text levels, borders, accent/foreground, focus, success,
  warning, and error.
- Ship at least six visually distinct presets covering dark, light, multihue,
  OLED, and high-contrast use cases.
- Add system/light/dark behavior plus an advanced editor for semantic color
  overrides, live preview, contrast warnings, reset, and versioned JSON
  import/export. Arbitrary CSS is not supported.
- Store appearance separately from operational configuration. Validate imports
  and atomically fall back to the default theme on invalid data.
- Fix keyboard navigation, modal focus trapping, visible focus states,
  reduced-motion support, icon labels, responsive overflow, loading failures,
  and current Svelte warnings.
- Add an About view with version, license, AI disclosure, upstream credits,
  data locations, diagnostics, and documentation links.

### 6. Change auth last

- First add fixture-driven contract tests for login, auto-login, SMS 2FA,
  trusted-device 2FA, success, failure, restart, and shutdown without using live
  credentials.
- Preserve wrapper invocation and parsing until those tests reliably reproduce
  current behavior.
- Then replace only credential persistence with a narrow Secret Service adapter.
  If a keyring is unavailable, use session-only credentials.
- Remove base64/plaintext credential storage and redact auth logs.
- Document any residual same-user Podman inspection exposure. Do not claim that
  keyring storage eliminates runtime exposure inside the wrapper process.

### 7. Documentation and automated QA

- Produce publication-readiness, secure runtime/packaging, auth compatibility,
  and theme schema specifications before their implementations.
- Replace the README with accurate screenshots, supported platforms,
  limitations, package installation, external dependency policy, first-run
  setup, and links to detailed guides.
- Add feature, configuration/theming, troubleshooting, development/build,
  architecture, security, contribution, third-party, AI-use, and release docs.
- Troubleshooting must cover auth/2FA, expired tokens, Podman and wrapper
  failures, upstream incompatibility, missing media tools, AppImage/FUSE and
  `noexec`, GUI `PATH`, permissions, stuck jobs, Strawberry locks, safe state
  reset, and redacted diagnostic collection.
- Consolidate Python dependencies in `pyproject.toml` with a reproducible locked
  build set. Internally support Python 3.12-3.13 until the 3.14 hang is fixed.
- Add Ruff, public-boundary type checks, ShellCheck, frontend lint/format,
  Rustfmt/Clippy, dependency audits, secret scanning, and SBOM validation.
- CI gates include timed Python unit/API tests and coverage, auth contract tests,
  zero-warning Svelte checks, frontend unit/component tests, Rust lifecycle
  tests, production builds, package builds, and clean-worktree verification.
- Package smoke tests cover Ubuntu 22.04 AppImage/deb, Debian 12 AppImage/deb,
  current Fedora AppImage/rpm, and current Bazzite AppImage.
- Real Apple authentication and a small authorized-playlist download remain a
  manual release check. Live credentials and media downloads never run in
  public CI.

## Release Acceptance

- A new user can install a published package, launch Pies Pear Music from the
  application menu, configure user-installed dependencies, authenticate, add a
  playlist, run a manual sync, inspect results, restart, and retain state
  without a source checkout.
- Missing dependencies and auth failures produce actionable UI errors instead
  of hangs or raw tracebacks.
- No personal data, credentials, private paths, unlicensed third-party binaries,
  or recoverable state databases exist in the public repository or artifacts.
- All CI gates and the package smoke matrix pass from the sanitized public
  commit.
- Publication remains blocked until provenance is cleared, auth-at-rest is
  migrated after its regression harness passes, and an unmodified supported
  upstream dependency path completes an end-to-end sync.

## Handoff Starting Point

Begin by rereading this document, `PENDING_CHANGES.md`, the current README,
`alac_rip/server.py`, and the Tauri launcher. Before editing, preserve the
user-owned changes currently visible in `.state/downloaded.db` and the untracked
`.codex` entry. Never commit, delete, rewrite, or expose the private state
database while preparing the public repository.
