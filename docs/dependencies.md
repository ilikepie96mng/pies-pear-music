# Dependencies

This is the canonical dependency reference for Pies Pear Music. Packages ship
the Tauri desktop app and its Python sidecar; they do **not** ship downloader,
wrapper, container, or media executables.

## Running a packaged application

| Dependency | Needed for | Required? | Notes |
| --- | --- | --- | --- |
| Linux x86_64 desktop session | Application | Yes | Version 0.1 target. Ubuntu/Debian/Fedora are package-test targets; use AppImage on Bazzite. |
| `podman` | Apple/wrapper login | Yes for login and sync | Must be usable by the current user. |
| Go (`go`) | Sync | Yes for the unmodified downloader source path | Used to run the configured downloader when no separately patched local executable exists. |
| `ffmpeg` | Media processing | Yes for sync | Must be on `PATH`. |
| GPAC `MP4Box` | Media processing | Yes for sync | The command name is case-sensitive: `MP4Box`. |
| configured `alac-rip` directory | Login and sync | Yes for login and sync | Must contain `apple-music-downloader/` and `wrapper/`. Set it in Setup or Settings. |
| `mp4decrypt` (Bento4) | Protected-media workflow | No | Diagnostics reports it as optional. |
| `secret-tool` (libsecret) | Remembering Apple/wrapper credentials | No | Without Secret Service, credentials are session-only; they are not written to plaintext/base64 files. |
| `xdg-open` | Open an exported M3U in the default player | No | Install it through your desktop environment if absent. |
| `gdbus` | Reveal a local track in a file manager | No | Used when available. |
| Last.fm API key | Online recommendations | No | Genre preferences and artist recommendations require it. A previously successful set can be shown from the local cache while offline. |

The required external downloader/wrapper path is intentionally not an
installer recipe yet. Its provenance, license, immutable revision, and checksum
are release blockers. Do not download a random binary or follow an old
installer script; see [upstream compatibility](upstream-compatibility.md).

## Building from source on Ubuntu 22.04

The supported source/build toolchains are Python 3.12 or 3.13, Node.js 22, and
current stable Rust. Python 3.14 is not a supported test runtime.

```bash
sudo apt update
sudo apt install -y \
  git build-essential pkg-config \
  python3 python3-venv python3-dev \
  libgtk-3-dev libwebkit2gtk-4.1-dev libayatana-appindicator3-dev \
  librsvg2-dev libssl-dev patchelf
```

Install Node.js 22 and Rust using their official distribution methods, then:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[test,package]"

cd app
npm ci
```

The Python packages are declared in `pyproject.toml`; JavaScript packages are
locked in `app/package-lock.json`; Rust packages are locked in
`app/src-tauri/Cargo.lock`. `rustfmt` and Clippy are required for the documented
verification commands.

## Dependency checks

The in-app **Diagnostics** screen is the runtime source of truth. It checks
the command names above, configuration, selected music/state folders, and the
two required source directories. It does not install, download, or modify any
third-party dependency.
