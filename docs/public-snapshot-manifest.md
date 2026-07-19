# Public Snapshot Manifest

This repository's current Git history is private. Do **not** publish it,
rewrite it in place, or use it as the initial history for Pies Pear Music.
Create a new repository from a reviewed working-tree snapshot only after every
release blocker in `public-release-plan.md` is resolved.

## Include only after review

- `alac_rip/` source, excluding obsolete modules that are not part of the
  desktop v1 product.
- `app/` source and owned application assets.
- `tests/` that do not contain personal paths, credentials, or copied private
  fixtures.
- `.github/`, `scripts/build-backend-sidecar.sh`, `pyproject.toml`, and the
  dependency lockfiles needed by CI and packaging.
- Public documentation: README, SECURITY, CONTRIBUTING, CHANGELOG,
  RESPONSIBLE_USE, AI disclosure, third-party notices, packaging,
  compatibility matrix, and this release plan.

Every included file must be independently owned or have a documented,
redistributable license status. The auth/wrapper path is specifically blocked
by the provenance review.

## Must exclude

- `.state/`, all `*.db` runtime copies, logs, downloaded media, credentials,
  caches, virtual environments, build outputs, and sidecar binaries.
- `config.yaml` and any real configuration or diagnostic bundle.
- `PENDING_CHANGES.md`, `.codex/`, `.agents/`, `docs/superpowers/`,
  `docs/frontend-product-roadmap.md`, and any private task/session/design notes.
- `install.sh`, `uninstall.sh`, `systemd/`, `alac_rip/cli.py`, and
  `alac_rip/github_sync.py`; these are obsolete unsupported paths and must not
  enter the public snapshot.
- Third-party wrapper/downloader/Bento4 sources, patches, executables, and
  copied code without documented permission or a compatible license.

## Required review commands

Run these against the candidate public repository, not this private history:

```bash
scripts/verify-public-snapshot.sh
git log --all --format=%H | while read -r commit; do git grep -nE '/(home|var/home)/|music\.apple\.com/.+\?' "$commit" -- . || exit 0; done
git fsck --no-reflogs --unreachable
```

Each command must produce no sensitive content. Review the complete candidate
file list, then run a secret scanner and PII review before the first push.
The new public repository must start with a fresh initial commit; it must not
retain unreachable objects, refs, remotes, or reflogs from this repository.
