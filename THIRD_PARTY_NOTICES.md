# Third-party notices and release status

This file is a release gate, not a claim that all dependencies are cleared for
redistribution. No package may bundle a dependency until its version, license,
source, integrity data, and any modification status are recorded here.

| Component | Intended use | Public-release status |
| --- | --- | --- |
| `lalit22km/alac-rip` | Historical reference for wrapper behavior | **Blocked:** provenance and permission/replacement review required. |
| `zhaarey/apple-music-downloader` | User-installed external downloader | **Blocked:** license and upstream compatibility review required. |
| `zhaarey/wrapper` | User-installed external wrapper | **Blocked:** license, maintenance, and compatibility review required. |
| Bento4 | Optional user-installed media tool | **Blocked:** GPL/commercial distribution review required before any bundling. |
| FastAPI, Uvicorn, Requests, PyYAML, Mutagen | Python dependencies | Track exact locked versions and license notices before packaging. |
| Tauri and frontend dependencies | Desktop application | Track exact locked versions and license notices before packaging. |

Public release remains blocked while any row marked **Blocked** is unresolved.
The release workflow uses the detailed
[upstream compatibility matrix](docs/upstream-compatibility.md) to record
approval evidence.
