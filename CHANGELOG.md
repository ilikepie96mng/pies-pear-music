# Changelog

This project uses a Keep a Changelog-style format. Versions are not released
until their public-release acceptance criteria are met.

## Unreleased

### Security

- Keep runtime state out of source control by default.
- Restrict local-file artwork and reveal actions to recorded library tracks
  beneath the configured music directory.
- Validate Apple Music URLs and download formats before jobs are queued.
- Use SQLite write locking for Strawberry playlist exports.

### Changed

- Remove Git-backed state replication and scheduled-sync controls from the
  supported desktop surface.
- Add Python, frontend, and Rust CI quality gates.
