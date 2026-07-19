# Upstream compatibility matrix

This matrix controls what Pies Pear Music may tell users to install or may
bundle. A blank or blocked field is not approval.

| Component | Role | Architecture | Tested revision | Integrity | License/provenance | Package policy | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `zhaarey/apple-music-downloader` | External downloader | Linux x86_64 | None approved | None recorded | Fork lineage and license review pending | Never bundle or silently download | Blocked |
| `zhaarey/wrapper` | External authentication/decryption wrapper | Linux x86_64 | None approved | None recorded | Archived upstream; license and replacement review pending | Never bundle or silently download | Blocked |
| `lalit22km/alac-rip` | Historical behavior reference | N/A | N/A | N/A | Permission or independent replacement required for borrowed code | Never bundle | Blocked |
| Bento4 / `mp4decrypt` | Optional media tool | Linux x86_64 | None approved | None recorded | Distribution obligations pending review | Never bundle until cleared | Blocked |
| FFmpeg | User-installed media tool | Linux x86_64 | None approved | None recorded | Package/distribution obligations pending review | User-installed only | Pending |
| GPAC / MP4Box | User-installed media tool | Linux x86_64 | None approved | None recorded | Package/distribution obligations pending review | User-installed only | Pending |

## Promotion rule

A row can move to **Approved** only when its exact repository URL, immutable
commit or release, SHA-256, architecture, patch status, tested environment,
and license review are recorded. For wrapper-dependent flows, the exact
end-to-end manual test must also be recorded without storing credentials or
personal media data.

The application must present a clear setup link and compatibility result for
user-installed tools. It must not fetch executables itself.
