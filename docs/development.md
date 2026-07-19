# Development and Build

## Supported toolchains

- Python 3.12 or 3.13 for tests and the release sidecar.
- Node.js 22 for the Svelte/Tauri frontend.
- Current stable Rust toolchain for the Tauri shell.
- Linux x86_64 for version 0.1 packages.

Python 3.14 is not a supported test runtime yet: the local FastAPI TestClient
lifespan suite hangs before its first assertion. CI deliberately gates Python
3.12 and 3.13 while that compatibility issue remains open.

## Install development dependencies

```bash
python -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[test,package]"

cd app
npm ci
```

Python dependencies are declared in `pyproject.toml`; there is no separate
`requirements.txt` source of truth.

## Verification commands

From the repository root:

```bash
.venv/bin/pytest tests -q --timeout=120
```

From `app/`:

```bash
npm run check
npm run build
```

From `app/src-tauri/`:

```bash
cargo fmt --check
cargo clippy --locked -- -D warnings
cargo test --locked
```

## Run the desktop app in development

From `app/`:

```bash
npm run tauri dev
```

The dev command rebuilds the PyInstaller sidecar only when `alac_rip/`,
`pyproject.toml`, or the sidecar build script is newer than the existing
sidecar binary. Run `npm run prepare-sidecar` directly if you need to refresh
it before starting Tauri.

## Build the desktop packages

Build the Python backend sidecar first:

```bash
scripts/build-backend-sidecar.sh
```

Then build the desired packages from `app/`:

```bash
npm run tauri build -- --bundles deb,appimage
npm run tauri build -- --bundles rpm
```

The release baseline is Ubuntu 22.04. It is required for the AppImage and
Debian build because newer systems can raise the glibc baseline or break older
linuxdeploy tooling. RPM may be validated separately on a supported Fedora
environment. After packaging, run:

```bash
scripts/verify-package-contents.sh app/src-tauri/target/release/bundle/deb/*.deb
scripts/write-release-metadata.sh app/src-tauri/target/release/bundle
```

Do not treat a locally successful package as publishable until the provenance,
public-snapshot, CI, and manual release checks in the release plan are complete.
