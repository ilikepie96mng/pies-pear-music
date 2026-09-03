#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir"

echo "==> 1. Preparing backend sidecar..."
bash "$repo_dir/scripts/build-backend-sidecar.sh" --if-stale

echo "==> 2. Building frontend web assets..."
(
  cd "$repo_dir/app"
  npm run build
)

echo "==> 3. Building Tauri release bundles..."
(
  cd "$repo_dir/app"
  if [[ $# -gt 0 ]]; then
    npm run tauri build -- "$@"
  else
    npm run tauri build
  fi
)

echo "==> 4. Verifying package artifacts..."
bundle_dir="$repo_dir/app/src-tauri/target/release/bundle"
if [[ -d "$bundle_dir" ]]; then
  echo "Built packages in $bundle_dir:"
  find "$bundle_dir" -type f \( -name '*.deb' -o -name '*.rpm' -o -name '*.AppImage' \) -exec ls -lh {} +
fi

echo "Packaging build completed successfully."
