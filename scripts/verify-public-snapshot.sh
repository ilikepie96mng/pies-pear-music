#!/usr/bin/env bash
set -euo pipefail

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Run this from the candidate public Git repository." >&2
  exit 2
fi

failed=0
while IFS= read -r path; do
  case "$path" in
    .state/*|*.db|*.log|*.pem|*.key|config.yaml|PENDING_CHANGES.md|.codex/*|.agents/*|docs/superpowers/*|docs/frontend-product-roadmap.md|install.sh|uninstall.sh|systemd/*|alac_rip/cli.py|alac_rip/github_sync.py)
      printf 'Forbidden public-snapshot path: %s\n' "$path" >&2
      failed=1
      ;;
  esac
done < <(git ls-files)

if git grep -nI -E '/(home|var/home)/' -- .; then
  echo "Candidate contains an absolute home path." >&2
  failed=1
fi

if [[ $failed -ne 0 ]]; then
  echo "Public snapshot verification failed." >&2
  exit 1
fi

echo "Public snapshot path checks passed. Run a dedicated secret scanner and PII review before publication."
