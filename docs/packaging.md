# Packaging Pies Pear Music

## Supported release targets

Version 0.1 targets Linux x86_64 with AppImage, Debian, and RPM artifacts.
Ubuntu 22.04 is the build baseline. Ubuntu and Debian use `.deb` or AppImage;
Fedora Workstation uses RPM or AppImage; Bazzite and Arch-family systems use
AppImage only. Arch-family support is best-effort until its clean-machine smoke
test exists. No distro is labeled release-supported before its manual package
check passes.

## Launching

Each package installs the `pies-pear-music` executable and a **Pies Pear
Music** application-menu entry in the Music category. The launcher has no
shell-wrapper dependency: it starts the bundled Tauri application and its
bundled Python sidecar directly. Its pear icon is installed with the desktop
application.

On immutable Fedora-family systems such as Bazzite, prefer the AppImage for
evaluation rather than layering the RPM. RPM remains a Fedora package format;
Bazzite RPM layering is not a release acceptance path.
Packages contain the Tauri application and the Python backend sidecar. They do
not bundle the downloader, wrapper, Bento4, FFmpeg, GPAC, or other external
media tools.

## Uninstall and data retention

Removing a package removes the application and its desktop launcher. It does
not remove downloaded music, the XDG state directory, logs, configuration, or
Secret Service credentials. This makes reinstalling safe by default. Removing
user data is a separate, deliberate action documented in troubleshooting.

The desktop webview uses a restrictive Tauri Content Security Policy. It only
permits app assets, HTTPS artwork, and the loopback backend connection required
by the installed sidecar.

## Build the backend sidecar

Use Python 3.12 on the release baseline:

```bash
python -m pip install -e ".[package]"
scripts/build-backend-sidecar.sh
```

The script writes a target-triple-named executable below
`app/src-tauri/binaries/`. Tauri embeds that executable through
`bundle.externalBin`; it is a build output and is intentionally untracked.

## Build packages

From `app/`:

```bash
npm ci
npm run tauri build -- --bundles deb,appimage
```

Build release artifacts on Ubuntu 22.04. Building on newer Linux systems can
raise the glibc requirement and make packages unusable on supported systems.
The CI `package-linux` job is the baseline package build and retains its
artifacts for inspection; it does not publish a release.

After a successful package build, run:

```bash
scripts/write-release-metadata.sh app/src-tauri/target/release/bundle
```

This creates `SHA256SUMS` for the AppImage, Debian, and RPM artifacts that are
present, plus `BUILD-INFO.txt` with the source commit and tool versions. CI
stores those files with its private package artifact.

`scripts/write-sbom-manifests.sh` writes separate JSON component manifests for
the Python and Node inputs, plus the Rust package metadata and its locked
transitive dependency graph. These are inventory artifacts, not a license or
vulnerability assessment; the release review must still validate licenses,
provenance, and dependency advisories.

`scripts/verify-package-contents.sh` smoke-checks a Debian or RPM artifact for
the embedded `usr/bin/pies-backend` sidecar. CI runs this after its Debian
package build.

After generating all metadata, run
`scripts/verify-release-artifacts.sh app/src-tauri/target/release/bundle` to
validate checksums, SBOM inventory files, and every Debian/RPM sidecar in the
artifact directory.

## Verification record

- Debian and RPM sidecar embedding: verified locally; each package contains
  `usr/bin/pies-backend`.
- AppImage: not accepted until the Ubuntu 22.04 CI job completes. Local Fedora
  bundling reaches `linuxdeploy` but its bundled `strip` cannot read Fedora
  44's newer ELF `RELR` sections. This is a host-toolchain incompatibility,
  not an application packaging acceptance result, and it reinforces the
  Ubuntu 22.04 baseline requirement.

## Release requirements

Before publishing, retain the package checksums, SBOM, provenance information,
release notes, package smoke-test results, and the exact sidecar build inputs.
Do not publish a package while the third-party compatibility matrix has a
blocked row.
