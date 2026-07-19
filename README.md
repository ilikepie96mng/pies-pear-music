# Pies Pear Music

Pies Pear Music is a Linux desktop application for maintaining an Apple Music
library through a user-installed downloader and wrapper. Version 0.1 will
support manual playlist syncs from the desktop application only.

## Release status

This repository is being prepared for its first public release. Release
packages are not available yet. Do not use the legacy `install.sh`,
`uninstall.sh`, `music-sync` CLI, or systemd timer as a supported installation
or sync path; they do not represent the desktop product and will not ship in
the public release.

## Planned v0.1 scope

- Linux x86_64 desktop application.
- Manual playlist syncs initiated from the application.
- User-selected local music and state directories.
- User-installed external download and media tools; packages will not silently
  fetch or bundle third-party executables.

Scheduled syncing, a command-line workflow, and Git-backed state replication
are out of scope for v0.1.

## Current desktop functionality

- Launch from the application menu as **Pies Pear Music**, or run the packaged
  `pies-pear-music` executable.
- Add playlists and perform manual syncs; downloaded media remains in the
  music directory selected during setup.
- Export playlists as M3U files, choosing the save location, and open an M3U
  in the system's configured player.
- Use Last.fm recommendations with hidden artists, genre preferences, clear
  explanations, and a local cached/offline fallback.
- Export a privacy-safe listening profile containing aggregate artist, album,
  and track counts only. The **Data & recs** screen manages profile export,
  genres, and hidden artists.
- Choose among curated appearance themes and use the About, Diagnostics, and
  Setup views to understand the local installation.

Pies Pear Music uses user-installed downloader, wrapper, Podman, and media
tools. The Setup and Diagnostics screens identify missing dependencies and
their configured locations without exposing those paths in support output.
See [the complete dependency reference](docs/dependencies.md) before setting
up a source checkout or attempting a sync.

## Data and security

Runtime state, logs, credentials, and downloaded media are user data. They
must never be committed to source control or included in a support bundle.
See [SECURITY.md](SECURITY.md) for vulnerability reporting and
[docs/public-release-plan.md](docs/public-release-plan.md) for the release
readiness criteria. See [RESPONSIBLE_USE.md](RESPONSIBLE_USE.md) for the
project's non-affiliation and responsible-use notice.

The current repository history is private and is not the future public
repository. [The public snapshot manifest](docs/public-snapshot-manifest.md)
defines the required clean-room publication review.

## Development

The supported Python test versions are 3.12 and 3.13. Python dependencies are
defined only in `pyproject.toml`; install the desired `test` or `package`
extra with `python -m pip install -e ".[test]"` or `.[package]`. The frontend
commands are run from `app/`:

```bash
npm ci
npm run check
npm run build
```

The public contribution and AI-use disclosures are in
[CONTRIBUTING.md](CONTRIBUTING.md) and [AI_DISCLOSURE.md](AI_DISCLOSURE.md).
Packaging details and current verification status are in
[docs/packaging.md](docs/packaging.md). Appearance preset behavior is documented
in [docs/appearance.md](docs/appearance.md). Common setup and recovery steps
are in [docs/troubleshooting.md](docs/troubleshooting.md).

Build and verification instructions are in [docs/development.md](docs/development.md).
Component and boundary details are in [docs/architecture.md](docs/architecture.md).
The required pre-change auth regression gate is in [docs/auth-contract.md](docs/auth-contract.md).
Current release blockers and completed preparation are tracked in
[docs/release-status.md](docs/release-status.md).
The required clean-user package checks are listed in
[docs/manual-smoke-test.md](docs/manual-smoke-test.md).
