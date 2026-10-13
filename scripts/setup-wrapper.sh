#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WRAPPER_DIR="$REPO_DIR/vendor/wrapper"
WRAPPER_BIN="$WRAPPER_DIR/wrapper"
ROOTFS_DIR="$WRAPPER_DIR/rootfs"

UPSTREAM_URL="https://github.com/zhaarey/wrapper/releases/download/linux/wrapper.linux.x86_64.tar.gz"

echo "==> Checking Apple FairPlay decryption wrapper..."

if [[ -f "$WRAPPER_BIN" && -d "$ROOTFS_DIR/system/lib64" ]]; then
    echo "✓ Wrapper and rootfs are already present in $WRAPPER_DIR"
    exit 0
fi

echo "==> Wrapper or rootfs missing. Downloading upstream release..."
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

ARCHIVE="$TMP_DIR/wrapper.linux.x86_64.tar.gz"
curl -sSL --retry 3 -o "$ARCHIVE" "$UPSTREAM_URL"

echo "==> Extracting wrapper assets..."
mkdir -p "$TMP_DIR/extracted"
tar -xzf "$ARCHIVE" -C "$TMP_DIR/extracted"

mkdir -p "$WRAPPER_DIR"
if [[ -f "$TMP_DIR/extracted/wrapper" ]]; then
    cp "$TMP_DIR/extracted/wrapper" "$WRAPPER_BIN"
    chmod +x "$WRAPPER_BIN"
fi

if [[ -d "$TMP_DIR/extracted/rootfs" ]]; then
    mkdir -p "$ROOTFS_DIR"
    cp -r "$TMP_DIR/extracted/rootfs/"* "$ROOTFS_DIR/"
fi

mkdir -p "$ROOTFS_DIR/dev" "$ROOTFS_DIR/data/data/com.apple.android.music"

echo "✓ Wrapper setup complete in $WRAPPER_DIR"
