#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <package.deb|package.rpm>" >&2
  exit 2
fi

package="$1"
if [[ ! -f "$package" ]]; then
  echo "Package does not exist: $package" >&2
  exit 2
fi

case "$package" in
  *.deb)
    data_member="$(ar t "$package" | awk '/^data\.tar/ { print; exit }')"
    if [[ -z "$data_member" ]]; then
      echo "Debian package has no data archive: $package" >&2
      exit 1
    fi
    case "$data_member" in
      *.gz) tar_list_args=(-tz); tar_extract_args=(-xzO) ;;
      *.xz) tar_list_args=(-tJ); tar_extract_args=(-xJO) ;;
      *.zst) tar_list_args=(--zstd -t); tar_extract_args=(--zstd -xO) ;;
      *) tar_list_args=(-t); tar_extract_args=(-xO) ;;
    esac
    package_files="$(ar p "$package" "$data_member" | tar "${tar_list_args[@]}")"
    if ! grep -E '(^|/)usr/bin/pies-backend$' <<<"$package_files" >/dev/null; then
      echo "Debian package is missing usr/bin/pies-backend: $package" >&2
      exit 1
    fi
    desktop_path="$(grep -E '(^|/)usr/share/applications/[^/]+\.desktop$' <<<"$package_files" | head -n 1)"
    if [[ -z "$desktop_path" ]]; then
      echo "Debian package is missing a desktop launcher: $package" >&2
      exit 1
    fi
    desktop_entry="$(ar p "$package" "$data_member" | tar "${tar_extract_args[@]}" "$desktop_path")"
    ;;
  *.rpm)
    if ! rpm -qlp "$package" | grep -Fxq '/usr/bin/pies-backend'; then
      echo "RPM package is missing /usr/bin/pies-backend: $package" >&2
      exit 1
    fi
    desktop_path="$(rpm -qlp "$package" | grep -E '^/usr/share/applications/[^/]+\.desktop$' | head -n 1)"
    if [[ -z "$desktop_path" ]]; then
      echo "RPM package is missing a desktop launcher: $package" >&2
      exit 1
    fi
    desktop_entry="$(rpm2cpio "$package" | cpio --quiet -i --to-stdout ".${desktop_path}")"
    ;;
  *)
    echo "Unsupported package type: $package" >&2
    exit 2
    ;;
esac

if ! grep -Fxq 'Exec=pies-pear-music' <<<"$desktop_entry"; then
  echo "Desktop launcher has an unexpected executable: $package" >&2
  exit 1
fi
if ! grep -E '^Categories=.*Music;' <<<"$desktop_entry" >/dev/null; then
  echo "Desktop launcher is missing the Music category: $package" >&2
  exit 1
fi

echo "Verified backend sidecar and desktop launcher in $package"
