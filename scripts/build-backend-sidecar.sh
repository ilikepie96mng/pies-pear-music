#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
target_dir="$repo_dir/app/src-tauri/binaries"

case "$(uname -m)" in
  x86_64) target_triple="x86_64-unknown-linux-gnu" ;;
  *) echo "Unsupported sidecar architecture: $(uname -m)" >&2; exit 1 ;;
esac

target_bin="$target_dir/pies-backend-${target_triple}"
if [[ "${1:-}" == "--if-stale" ]]; then
  if [[ -x "$target_bin" ]] && ! find "$repo_dir/alac_rip" "$repo_dir/pyproject.toml" "${BASH_SOURCE[0]}" -type f -newer "$target_bin" -print -quit | grep -q .; then
    echo "Backend sidecar is current: $target_bin"
    exit 0
  fi
elif [[ $# -ne 0 ]]; then
  echo "Usage: $0 [--if-stale]" >&2
  exit 2
fi

backend_python="python3"
if [[ -x "$repo_dir/.venv/bin/python" ]]; then
  backend_python="$repo_dir/.venv/bin/python"
fi

work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT

mkdir -p "$target_dir"
cd "$repo_dir"

"$backend_python" -m PyInstaller \
  --noconfirm \
  --clean \
  --onefile \
  --name "pies-backend-${target_triple}" \
  --distpath "$target_dir" \
  --workpath "$work_dir/work" \
  --specpath "$work_dir/spec" \
  --paths "$repo_dir" \
  alac_rip/server.py

echo "Built $target_bin"
