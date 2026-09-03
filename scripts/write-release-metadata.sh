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

mapfile -d '' packages < <(
  find "$artifact_dir" -type f \( -name '*.AppImage' -o -name '*.deb' -o -name '*.rpm' \) -print0 | sort -z
)
if [[ ${#packages[@]} -eq 0 ]]; then
  echo "No AppImage, Debian, or RPM artifacts found in $artifact_dir" >&2
  exit 1
fi

checksum_file="$artifact_dir/SHA256SUMS"
build_info_file="$artifact_dir/BUILD-INFO.txt"
: > "$checksum_file"
for package in "${packages[@]}"; do
  checksum="$(sha256sum "$package" | cut -d ' ' -f 1)"
  relative_path="${package#"$artifact_dir"/}"
  printf '%s  %s\n' "$checksum" "$relative_path" >> "$checksum_file"
done

{
  printf 'project=Pies Pear Music\n'
  printf 'commit=%s\n' "$(git -C "$repo_dir" rev-parse HEAD)"
  printf 'python=%s\n' "$(python3 --version)"
  printf 'node=%s\n' "$(node --version)"
  printf 'rustc=%s\n' "$(rustc --version)"
  printf 'built_at_utc=%s\n' "$(date --utc +%Y-%m-%dT%H:%M:%SZ)"
} > "$build_info_file"

echo "Wrote $checksum_file and $build_info_file"
