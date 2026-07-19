#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <artifact-directory>" >&2
  exit 2
fi

artifact_dir="$1"
repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ ! -d "$artifact_dir" || ! -s "$artifact_dir/SHA256SUMS" || ! -s "$artifact_dir/BUILD-INFO.txt" ]]; then
  echo "Artifact directory is missing checksums or build information: $artifact_dir" >&2
  exit 1
fi

(
  cd "$artifact_dir"
  sha256sum --check SHA256SUMS
)
"$repo_dir/scripts/verify-sbom-manifests.sh" "$artifact_dir"

while IFS= read -r -d '' package; do
  "$repo_dir/scripts/verify-package-contents.sh" "$package"
done < <(find "$artifact_dir" -type f \( -name '*.deb' -o -name '*.rpm' \) -print0)

echo "Release artifacts verified"
