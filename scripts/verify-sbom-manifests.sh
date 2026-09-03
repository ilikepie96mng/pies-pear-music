#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <artifact-directory>" >&2
  exit 2
fi

artifact_dir="$1"
for manifest in SBOM-python.json SBOM-node.json SBOM-rust.json; do
  path="$artifact_dir/$manifest"
  if [[ ! -s "$path" ]]; then
    echo "Missing or empty SBOM manifest: $path" >&2
    exit 1
  fi
  python3 -m json.tool "$path" >/dev/null
done

if [[ ! -s "$artifact_dir/SBOM-rust-Cargo.lock" ]]; then
  echo "Missing Rust dependency lock inventory" >&2
  exit 1
fi

echo "SBOM manifests are present and valid JSON"
