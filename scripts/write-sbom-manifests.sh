#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <artifact-directory>" >&2
  exit 2
fi

artifact_dir="$1"
if [[ ! -d "$artifact_dir" ]]; then
  echo "Artifact directory does not exist: $artifact_dir" >&2
  exit 2
fi

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
artifact_dir="$(cd "$artifact_dir" && pwd)"

python3 -m pip list --format=json > "$artifact_dir/SBOM-python.json"
npm --prefix "$repo_dir/app" ls --package-lock-only --all --json > "$artifact_dir/SBOM-node.json"
cargo metadata --locked --no-deps --format-version 1 --manifest-path "$repo_dir/app/src-tauri/Cargo.toml" > "$artifact_dir/SBOM-rust.json"
cp "$repo_dir/app/src-tauri/Cargo.lock" "$artifact_dir/SBOM-rust-Cargo.lock"

echo "Wrote Python, Node, and Rust component manifests to $artifact_dir"
