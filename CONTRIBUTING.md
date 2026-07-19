# Contributing

Thank you for helping improve Pies Pear Music.

## Before opening a change

- Do not commit runtime state, downloaded music, credentials, logs, or
  machine-specific paths.
- Do not add third-party code or binaries without recording its source,
  version, checksum, and license status in `THIRD_PARTY_NOTICES.md`.
- Keep authentication and wrapper-protocol changes isolated. They require
  fixture-driven regression coverage before review.

## Local checks

Use Python 3.12 or 3.13 for the backend test suite. From `app/`, run
`npm run check` and `npm run build`. From `app/src-tauri/`, run
`cargo fmt --check`, `cargo clippy --locked -- -D warnings`, and
`cargo test --locked`.

## Pull requests

Describe user-visible behavior, tests run, external dependencies affected, and
any security or data-migration impact. Keep changes small and avoid unrelated
formatting or refactors.
