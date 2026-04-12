#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="$HOME/.local/share/pies-alac-rip"
CONFIG_DIR="$HOME/.config/pies-alac-rip"
SYSTEMD_DIR="$HOME/.config/systemd/user"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> Uninstalling pies-alac-rip-tool"

# 1. Stop and disable systemd units
systemctl --user stop pies-alac-rip.timer 2>/dev/null || true
systemctl --user disable pies-alac-rip.timer 2>/dev/null || true
rm -f "$SYSTEMD_DIR/pies-alac-rip.service"
rm -f "$SYSTEMD_DIR/pies-alac-rip.timer"
systemctl --user daemon-reload

# 2. Remove binaries
rm -rf "$INSTALL_DIR"

# 3. Remove shim
rm -f "$HOME/.local/bin/music-sync"
rm -f "$HOME/.local/bin/mp4box"

# 4. Remove venv
rm -rf "$SCRIPT_DIR/.venv"

# 5. Remove config (ask first)
if [ -d "$CONFIG_DIR" ]; then
    read -rp "Remove config at $CONFIG_DIR? [y/N] " confirm
    if [[ "$confirm" =~ ^[Yy]$ ]]; then
        rm -rf "$CONFIG_DIR"
        echo "Config removed."
    else
        echo "Config kept at $CONFIG_DIR"
    fi
fi

echo ""
echo "==> Uninstall complete."
echo "  Note: Your music library at ~/Music/Apple Music is untouched."
echo "  Note: The git repo itself is untouched — remove manually if desired."
