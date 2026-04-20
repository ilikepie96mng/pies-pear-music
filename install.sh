#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="$HOME/.local/share/pies-alac-rip"
CONFIG_DIR="$HOME/.config/pies-alac-rip"
SYSTEMD_DIR="$HOME/.config/systemd/user"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> Installing pies-alac-rip-tool"

# 1. Brew dependencies
echo "==> Installing brew dependencies..."
brew install go gh ffmpeg gpac wget node

# 2. Create directories
mkdir -p "$INSTALL_DIR" "$CONFIG_DIR" "$HOME/.local/bin"

# 3. Clone and build zhaarey apple-music-downloader
if [ ! -d "$INSTALL_DIR/apple-music-downloader" ]; then
    echo "==> Cloning zhaarey/apple-music-downloader..."
    git clone https://github.com/zhaarey/apple-music-downloader "$INSTALL_DIR/apple-music-downloader"
fi
if [ ! -f "$INSTALL_DIR/apple-music-downloader/apple-music-dl" ]; then
    echo "==> Building Go downloader..."
    cd "$INSTALL_DIR/apple-music-downloader"
    go build -o apple-music-dl .
    cd "$SCRIPT_DIR"
fi

# 4. Download wrapper binary
if [ ! -f "$INSTALL_DIR/wrapper" ]; then
    echo "==> Downloading wrapper..."
    WRAPPER_TGZ="/tmp/wrapper.x86_64.tar.gz"
    wget -q -O "$WRAPPER_TGZ" \
        "https://github.com/zhaarey/wrapper/releases/download/linux/wrapper.linux.x86_64.tar.gz"
    mkdir -p "$INSTALL_DIR/wrapper-extract"
    tar -xzf "$WRAPPER_TGZ" -C "$INSTALL_DIR/wrapper-extract"
    WRAPPER_BIN="$(find "$INSTALL_DIR/wrapper-extract" -name wrapper -type f | head -1)"
    cp "$WRAPPER_BIN" "$INSTALL_DIR/wrapper"
    chmod +x "$INSTALL_DIR/wrapper"
    rm -rf "$INSTALL_DIR/wrapper-extract" "$WRAPPER_TGZ"
fi

# 5. Download and set up Bento4
BENTO4_VERSION="1-6-0-641"
BENTO4_DIR="$INSTALL_DIR/bento4"
if [ ! -d "$BENTO4_DIR" ]; then
    echo "==> Downloading Bento4..."
    BENTO4_ZIP="/tmp/bento4.zip"
    wget -q -O "$BENTO4_ZIP" \
        "https://www.bok.net/Bento4/binaries/Bento4-SDK-${BENTO4_VERSION}.x86_64-unknown-linux.zip"
    mkdir -p "$BENTO4_DIR"
    unzip -q "$BENTO4_ZIP" -d "$BENTO4_DIR"
    rm "$BENTO4_ZIP"
fi
# Symlink mp4decrypt from Bento4 (used by the Go downloader for decryption)
MP4DECRYPT_BIN="$(find "$BENTO4_DIR" -name "mp4decrypt" -type f | head -1)"
if [ -n "$MP4DECRYPT_BIN" ]; then
    ln -sf "$MP4DECRYPT_BIN" "$HOME/.local/bin/mp4decrypt"
fi
# mp4box comes from GPAC (installed via brew above) — no symlink needed

# 6. Write zhaarey downloader config (with token placeholder — user fills in)
DOWNLOADER_CONFIG="$INSTALL_DIR/apple-music-downloader/config.yaml"
if [ ! -f "$DOWNLOADER_CONFIG" ]; then
    cat > "$DOWNLOADER_CONFIG" <<'EOF'
media-user-token: "FILL_IN_YOUR_TOKEN"
EOF
fi

# 7. Set up Python venv and install package
echo "==> Setting up Python venv..."
cd "$SCRIPT_DIR"
python3 -m venv .venv
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -e .

# 8. Create wrapper shim in ~/.local/bin
if [ ! -f "$HOME/.local/bin/music-sync" ]; then
    cat > "$HOME/.local/bin/music-sync" <<EOF
#!/usr/bin/env bash
exec "$SCRIPT_DIR/.venv/bin/music-sync" "\$@"
EOF
    chmod +x "$HOME/.local/bin/music-sync"
fi

# 9. Install systemd user units
echo "==> Installing systemd units..."
mkdir -p "$SYSTEMD_DIR"
# Inject the correct path into the service file
sed "s|SCRIPT_DIR|$SCRIPT_DIR|g" "$SCRIPT_DIR/systemd/pies-alac-rip.service" \
    > "$SYSTEMD_DIR/pies-alac-rip.service"
cp "$SCRIPT_DIR/systemd/pies-alac-rip.timer" "$SYSTEMD_DIR/pies-alac-rip.timer"
systemctl --user daemon-reload
systemctl --user enable pies-alac-rip.timer

# 10. Create user config from example, filling in install-time paths
mkdir -p "$SCRIPT_DIR/.state"
if [ ! -f "$CONFIG_DIR/config.yaml" ]; then
    sed \
        -e "s|FILLED_BY_INSTALL_SCRIPT|$SCRIPT_DIR/.state|g" \
        "$SCRIPT_DIR/config.yaml.example" > "$CONFIG_DIR/config.yaml"
    # Also patch downloader_repo and wrapper_bin to real paths
    sed -i \
        -e "s|~/.local/share/pies-alac-rip/apple-music-downloader|$INSTALL_DIR/apple-music-downloader|g" \
        -e "s|~/.local/share/pies-alac-rip/wrapper|$INSTALL_DIR/wrapper|g" \
        "$CONFIG_DIR/config.yaml"
    echo ""
    echo "======================================================"
    echo "  Config created at: $CONFIG_DIR/config.yaml"
    echo "  ACTION REQUIRED: Add your Apple Music media-user-token"
    echo "======================================================"
fi

echo ""
echo "==> Install complete."
echo "  Next steps:"
echo "  1. Edit $CONFIG_DIR/config.yaml — add your media-user-token"
echo "  2. Also update $INSTALL_DIR/apple-music-downloader/config.yaml with the same token"
echo "  3. Run: music-sync auth"
echo "  4. After auth succeeds, run: music-sync add <your-apple-music-playlist-url>"
echo "  5. Run: music-sync sync"
