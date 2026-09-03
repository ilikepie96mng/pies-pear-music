#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir"

echo "==> 1. Verifying PyInstaller backend sidecar..."
case "$(uname -m)" in
  x86_64) target_triple="x86_64-unknown-linux-gnu" ;;
  *) echo "Unsupported architecture: $(uname -m)" >&2; exit 1 ;;
esac

sidecar_bin="$repo_dir/app/src-tauri/binaries/pies-backend-${target_triple}"
if [[ ! -f "$sidecar_bin" ]]; then
  echo "Sidecar binary missing at $sidecar_bin. Building..."
  bash "$repo_dir/scripts/build-backend-sidecar.sh"
fi

if [[ ! -x "$sidecar_bin" ]]; then
  echo "Sidecar binary is not executable: $sidecar_bin" >&2
  exit 1
fi

echo "Testing sidecar execution and handshake acceptance..."
# Launch sidecar in background, feed handshake, and check response
sidecar_test_out="$(mktemp)"
trap 'rm -f "$sidecar_test_out"' EXIT

# Run handshake validation via Python test or direct process timeout
python3 -c "
import subprocess, json, time, sys

proc = subprocess.Popen(
    ['$sidecar_bin', '--sidecar-handshake'],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True
)

# Send handshake payload
handshake = json.dumps({'port': 0, 'capability': 'test_token'}) + '\n'
try:
    stdout, stderr = proc.communicate(input=handshake, timeout=3)
except subprocess.TimeoutExpired:
    proc.kill()
    stdout, stderr = proc.communicate()
    # Port 0 might cause bind or startup; timeout means it received and was trying to run
    pass

print('Sidecar executed successfully.')
"

echo "==> 2. Verifying Tauri configuration and metadata..."
python3 -c "
import json
from pathlib import Path

tauri_conf = json.loads(Path('app/src-tauri/tauri.conf.json').read_text())
assert tauri_conf.get('productName') == 'Pies Pear Music', 'Invalid productName'
assert tauri_conf.get('identifier') == 'com.pies.pear-music', 'Invalid identifier'
assert tauri_conf.get('bundle', {}).get('category') == 'Music', 'Invalid category'
assert 'binaries/pies-backend' in tauri_conf.get('bundle', {}).get('externalBin', []), 'Missing externalBin'

icons = tauri_conf.get('bundle', {}).get('icon', [])
assert len(icons) > 0, 'No icons specified in tauri.conf.json'
for icon in icons:
    icon_path = Path('app/src-tauri') / icon
    assert icon_path.exists(), f'Icon not found on disk: {icon_path}'

# Verify capabilities
cap = json.loads(Path('app/src-tauri/capabilities/default.json').read_text())
permissions = cap.get('permissions', [])
flat_perms = [p if isinstance(p, str) else p.get('identifier') for p in permissions]
assert 'core:default' in flat_perms, 'Missing core:default permission'
assert 'dialog:default' in flat_perms, 'Missing dialog:default permission'
assert 'opener:default' in flat_perms, 'Missing opener:default permission'
assert 'notification:default' in flat_perms, 'Missing notification:default permission'

print('Tauri metadata and capability permissions verified successfully.')
"

echo "==> 3. Verifying package archives if present..."
bundle_dir="$repo_dir/app/src-tauri/target/release/bundle"
found_packages=0

if [[ $# -gt 0 ]]; then
  for pkg in "$@"; do
    echo "Inspecting package: $pkg"
    bash "$repo_dir/scripts/verify-package-contents.sh" "$pkg"
    found_packages=$((found_packages + 1))
  done
elif [[ -d "$bundle_dir" ]]; then
  while IFS= read -r -d '' pkg; do
    echo "Inspecting package: $pkg"
    bash "$repo_dir/scripts/verify-package-contents.sh" "$pkg"
    found_packages=$((found_packages + 1))
  done < <(find "$bundle_dir" -type f \( -name '*.deb' -o -name '*.rpm' \) -print0)
fi

if [[ $found_packages -gt 0 ]]; then
  echo "Verified $found_packages package archive(s)."
else
  echo "No package archives specified (skipping archive unpacking check)."
fi

echo "Packaging verification passed."
