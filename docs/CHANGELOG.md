# Changelog

This project uses a Keep a Changelog-style format. Versions are not released
until their public-release acceptance criteria are met.

## Unreleased

### Added

- Portable Digital Audio Player (DAP) export engine and modal UI (`POST /export/dap`, `DapExportModal.svelte`) for transcoding playlists and library audio to Opus/AAC on external storage devices and microSD cards with M3U playlist generation and `.lrc` sidecar syncing.
- Synchronized lyrics engine and modal viewer (`LyricsModal.svelte`, `GET /tracks/{track_id}/lyrics`) with TTML-to-LRC conversion and track badge indicators.
- Digital Preservation "Streaming Graveyard" view (`StreamingGraveyard.svelte`, `GET /streaming-graveyard`) tracking upstream-delisted Apple Music tracks preserved in the local lossless FLAC library with file revealing capabilities (`POST /reveal-track`).
- FLAC stream verification and integrity diagnostics (`flac -t -s`) integrated into sync engine and diagnostics dashboard.
- Workflow and token optimization protocols (`docs/agent-workflow.md`, `docs/plans/`).

### Security

- Enforce strict bitrate format regex (`^[1-9]\d{1,3}k$`) and argument whitelisting for external transcode invocations (`ffmpeg`, `flac`) to prevent argument injection.
- Validate target directory paths and reject filesystem root exports in DAP export workflows.
- Sanitize M3U metadata to strip line breaks and control characters, preventing M3U directive injection.
- Neutralize XML External Entity (XXE) vulnerabilities by parsing Apple Music TTML lyric streams using regex instead of generic XML DOM parsers.
- Reject artist/album/title metadata that sanitizes to a path-traversal segment
  (e.g. `..`, `.`, or empty), preventing malicious/malformed Apple Music
  metadata from writing files outside the configured music directory.
- Add structured per-track download progress (`[N/Y]`) surfaced during the
  downloading phase, reusing the existing organizing-phase progress UI.
- Keep runtime state out of source control by default.
- Restrict local-file artwork and reveal actions to recorded library tracks
  beneath the configured music directory.
- Validate Apple Music URLs and download formats before jobs are queued.
- Use SQLite write locking for Strawberry playlist exports.

### Changed

- Remove Git-backed state replication and scheduled-sync controls from the
  supported desktop surface.
- Add Python, frontend, and Rust CI quality gates.
- Continue organizing successfully downloaded tracks into the library even
  when the external downloader reports per-track errors, instead of
  discarding the entire batch on any non-zero exit code.
- Disable music video downloads by default (`skip-music-videos: true`) after
  identifying catalog music videos whose DRM key acquisition can fail
  unrecoverably and stall the whole sync; see `docs/troubleshooting.md`.

### Fixed

- Log a visible warning when a downloaded file has no source metadata at all,
  instead of silently filing it under "Unknown Artist / Unknown Album" with
  no trace in the logs.
- Surface the real error from music-video decryption-key acquisition
  (e.g. an invalid/expired `media-user-token`) instead of a generic
  `mp4decrypt` argument error.
