# Security policy

## Reporting a vulnerability

Until a public issue tracker and security contact are published, do not report
credentials, private library paths, state databases, or proof-of-concept
details in public issues. Contact the maintainer through the private channel
provided with the release instead.

Please include the affected version or commit, a minimal reproduction, impact,
and any safe mitigation. Reports affecting credentials, local files, the
desktop/backend boundary, or packaged artifacts are treated as high priority.

## Supported versions

No public version is supported before the 0.1.0 release. Security fixes will
be released for the latest public version after publication.

## Sensitive data

Never attach `config.yaml`, `.credentials`, runtime databases, wrapper logs,
or unredacted diagnostics to a report. Redact account identifiers, tokens,
playlist URLs, and local paths first.
