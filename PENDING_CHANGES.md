# Pending Changes

## release/2 — Feature work in progress

### Home page improvements
- [x] Scrollable home page (overflow on content area)
- [x] Recommended artist → opens Apple Music search page on click
- [ ] Recommended songs section (Last.fm artist.getTopTracks for each rec artist)
- [ ] Recommended albums section (Last.fm artist.getTopAlbums for each rec artist)

### Future
- [ ] Strawberry M3U8 auto-update already done (🍓 Strawberry button)
- [ ] Packaging (Tauri bundle + Python sidecar)

---

## release/public — Code review fixes (from codex + Claude agent audit)

All fixes applied to release/public ONLY. release/2 stays as-is.

- [ ] **server.py:76** — Atomic chmod: write credentials to temp file → chmod 600 → rename (eliminates world-readable window)
- [ ] **server.py:169** — Strip Apple ID email from wrapper_logs (currently logs `email` in plain text, exposed via /wrapper/status API)
- [ ] **server.py:191** — Password passed via `podman -e args=-L email:password` (visible in ps/podman inspect). Pass via stdin or temp file instead.
- [ ] **server.py:817** — `/reveal-track` accepts arbitrary filesystem paths. Validate path is under cfg.music_dir.
- [ ] **strawberry_sync.py:71** — TOCTOU race: pgrep check then SQLite write. Strawberry could start between check and write. Use SQLite timeout + lock detection.
- [ ] **install.sh:33,51** — Predictable /tmp filenames (wrapper.tar.gz, bento4.zip). Replace with mktemp.
- [ ] **server.py:191** (hard) — Password in podman env var. Requires wrapper binary to accept via stdin.
