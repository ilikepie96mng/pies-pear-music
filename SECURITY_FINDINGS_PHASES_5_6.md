# Security Findings — Phases 5 & 6

**Project:** `pies-alac-rip-tool` / Pies Pear Music  
**Review date:** 2026-08-16  
**Audited revision:** `566a41d`  
**Release verdict:** **ACTION REQUIRED**

## Executive summary

The packaged sidecar uses a strong 256-bit random capability, constant-time comparison, loopback binding, and app-wide authentication middleware. Static path traversal and ordinary symlink attacks against the audio stream are also blocked. Svelte renders reviewed metadata and lyrics using escaped interpolation, with no `{@html}` or equivalent raw-HTML sink found.

Release is nevertheless blocked by four high-severity findings:

1. Jellyfin/Navidrome endpoints permit SSRF, and credentials can leak through redirects, logs, and API error responses.
2. LRCLIB lyric persistence follows a malicious `.lrc` symlink and can overwrite an arbitrary user-writable file.
3. Gemini API keys appear in request URLs and are returned in transport-error responses.
4. The frontend build currently contains known high-severity dependency advisories.

Additional medium and low findings affect sidecar startup isolation, unbounded input/model output, secret exposure, wallpaper handling, Range parsing, Tauri least privilege, and tracked runtime databases.

## Verification performed

- `.venv/bin/pytest -q`: **268 passed** in 6.70 seconds.
- `cd app && npm run check`: **0 errors and 0 warnings**.
- `cd app/src-tauri && cargo test --locked`: **2 passed**.
- App-wide authentication PoC exercised **52 API routes** without a token; all returned `401` while `_api_capability` was configured.
- Linux config write PoC confirmed mode `0600`.
- `npm audit --json`: **7 vulnerable packages** — 4 high, 2 moderate, 1 low.

The source changed during the audit and revision `566a41d` was committed. The backend and frontend checks above were rerun successfully against that revision.

## Findings

### HIGH-01 — SSRF and media-server credential disclosure

**Affected code**

- `alac_rip/server.py:1845-1866`
- `alac_rip/integrations.py:9-53`
- `alac_rip/integrations.py:56-114`

The authenticated API accepts an arbitrary `server_url` for Jellyfin and Navidrome. It does not validate the scheme, credentials, hostname, resolved IP address, or redirect destinations. `requests` follows redirects by default.

This permits requests to loopback services, link-local/cloud metadata services such as `169.254.169.254`, and other destinations reachable from the workstation. Media-server URLs are expected to support private LAN hosts, but link-local, metadata, unspecified, multicast, and unexpected loopback destinations still require explicit policy.

Jellyfin's custom `X-Emby-Token` header is retained across a cross-origin redirect. A local PoC used one loopback server to redirect to a second server. The second server observed:

```text
first_token = SECRET-JELLYFIN-TOKEN
redirected_sink_token = SECRET-JELLYFIN-TOKEN
```

Navidrome credentials are placed in the query string. A connection failure produced and returned this form of error:

```text
/rest/ping.view?u=SECRET-USER&t=SECRET-TOKEN&s=SECRET-SALT&...
```

The refresh path also logs the same exception at `alac_rip/integrations.py:113-114`.

**Required remediation**

- Accept only `http` and `https`; reject userinfo, fragments, malformed ports, and ambiguous host syntax.
- Resolve the hostname and validate every resulting address. Block link-local, metadata, unspecified, multicast, and broadcast ranges. Make loopback an explicit local-server opt-in.
- Disable redirects for authenticated integration requests. If redirects are required, validate every hop and never forward credentials across origins.
- Return generic errors and log only a sanitized origin/status. Never return or log prepared URLs containing query credentials.
- Prefer HTTPS. Warn clearly before allowing HTTP on a private LAN.
- Add tests for IPv4, IPv6, DNS rebinding, redirects, encoded host forms, and credential redaction.

### HIGH-02 — Arbitrary file overwrite through `.lrc` symlink

**Affected code**

- `alac_rip/server.py:1524-1553`
- `alac_rip/lyrics.py:62-69`

The read path refuses an existing symlink at `server.py:1528`, but the LRCLIB fallback later calls `save_lrc_file()` on the same path. `Path.write_text()` follows the symlink.

Safe PoC:

1. Create a recorded track inside the music directory.
2. Create `track.lrc` as a symlink to a temporary file outside the music directory.
3. Make the LRCLIB response return controlled lyrics.
4. Request `/tracks/t/lyrics`.

Observed result:

```text
status 200 source lrclib
outside_file_after ATTACKER-CONTROLLED-LYRICS
```

An attacker able to place a symlink in the library can therefore overwrite any file writable by the application user.

**Required remediation**

- Refuse symlinks and other non-regular files using a race-resistant open operation.
- On POSIX, create with `O_NOFOLLOW`, restrictive permissions, and a same-directory temporary file followed by an atomic replace.
- On Windows, reject reparse points and use handle-based validation suitable for NTFS.
- Revalidate the canonical parent and target immediately before commit.
- Add regression tests for existing symlinks, parent-directory symlinks, replacement races, and hard links where supported.

### HIGH-03 — Gemini API key disclosure in error responses

**Affected code**

- `alac_rip/gemini_ai.py:83-108`
- `alac_rip/server.py:2023-2058`

The Gemini key is placed in `?key=...` at `gemini_ai.py:85`. Transport exceptions include the prepared URL. The multi-model fallback stores `str(e)` and returns it to the API caller at line 108; the server then includes it in an HTTP error response at `server.py:2057-2058`.

Observed safe PoC against a closed loopback port:

```text
Max retries exceeded with url: /generate?key=SECRET-GEMINI-KEY
```

The key was present in the function result and therefore reaches the frontend error response.

**Required remediation**

- Send the key in the `x-goog-api-key` header, not the URL.
- Never return raw `requests` exceptions or upstream response bodies.
- Log a sanitized error category, model name, API version, and status only.
- Add a redaction assertion using a sentinel key across every failure path.

### HIGH-04 — Known vulnerable frontend build dependencies

`npm audit --json` reported 4 high, 2 moderate, and 1 low vulnerable package entries. Installed versions include:

- Vite `6.4.2` — Windows filesystem-deny bypass and UNC/NTLM disclosure advisories.
- PostCSS `8.5.9` — source-map path traversal/arbitrary `.map` disclosure advisories.
- devalue `5.7.1` — sparse-array deserialization denial of service.
- nanoid `3.3.11` — infinite-loop advisories.
- Svelte `5.55.4`, SvelteKit `2.57.1`, and cookie `0.6.0` — XSS, ReDoS, prototype-pollution, payload-crash, and validation advisories.

Most affected packages are build/development dependencies and some SSR-specific advisories do not apply directly to the static Tauri runtime. Vite's Windows development-server issue and PostCSS build-time file disclosure are relevant to this project's supported Windows environment and release pipeline.

**Required remediation**

- Update the lockfile until `npm audit` is clean or each remaining advisory has a documented non-applicability decision.
- Re-run `npm run check`, production build, Tauri tests, and packaging on Linux and Windows.
- Add dependency auditing to CI for npm, Python, and Rust.

### MEDIUM-01 — Sidecar authentication fails open outside handshake mode

**Affected code**

- `alac_rip/server.py:400-407`
- `tests/test_api_capability.py:49-54`

Authentication is enforced only when `_api_capability` is truthy. Starting the backend directly leaves every endpoint unauthenticated on loopback; the test suite explicitly treats that as supported development behavior.

The packaged path is stronger: a 64-character capability is read from stdin, compared with `secrets.compare_digest`, and all 52 tested resource routes returned `401` without it. There is no HTTP handshake endpoint; the initial handshake is stdin JSON.

**Required remediation**

- Fail closed by default.
- Require an explicit, loudly warned `--insecure-dev` switch for unauthenticated mode, or generate and display a development token.
- Add an integration test that boots the actual sidecar and probes every route without, with an incorrect, and with a correct token.

### MEDIUM-02 — Backend port reservation race can disclose the capability

**Affected code**

- `app/src-tauri/src/lib.rs:26-37`
- `app/src-tauri/src/lib.rs:48-62`
- `app/src-tauri/src/lib.rs:87-117`

Rust allocates a free port and immediately drops the listener before spawning Python. Another local process can bind that port during the gap. `wait_for_python()` then sends the secret capability to whatever process owns the port.

**Required remediation**

- Have the child bind port `0` and report its selected port through its existing private pipe, or pass an already-bound listener/handle to the child.
- Do not send the capability to a listener whose ownership has not been established.
- Add a hostile-port-occupier startup test.

### MEDIUM-03 — Windows capability generation uses `/dev/urandom`

**Affected code**

- `app/src-tauri/src/lib.rs:18-23`

The native Windows target has no `/dev/urandom`, so the packaged application cannot generate its capability using this implementation. This is primarily an availability/release-portability defect, but replacing it incorrectly could weaken the authentication boundary.

**Required remediation**

- Use Rust's OS-backed `getrandom`/`rand_core::OsRng` abstraction.
- Test capability generation in Windows CI and retain the 256-bit/64-hex-character assertions.

### MEDIUM-04 — Playlist and AI inputs are unbounded

**Affected code**

- `alac_rip/server.py:1940-2015`
- `alac_rip/playlist_import.py:31-94`
- `app/src/lib/PlaylistImportModal.svelte:21-42`
- `alac_rip/gemini_ai.py:20-108`
- `alac_rip/lyrics.py:39-53`

CSV/M3U content, prompt length, model track count, Spotify HTML, LRCLIB JSON/lyrics, Gemini JSON, arrays, and string fields have no meaningful size or count limits. The frontend calls `file.text()` before checking size, and the backend receives the entire JSON request body before parsing. Large content can exhaust memory or trigger large numbers of Apple Music searches.

The reviewed URL regexes are simple and no catastrophic ReDoS pattern was identified. The dominant risk is unbounded memory and work amplification.

**Required remediation**

- Enforce request-body limits before JSON parsing.
- Cap import files, rows, line length, field length, prompt length, response bytes, lyrics length, and track count.
- Stream external responses with byte limits and use connect/read timeouts.
- Reject excess data instead of truncating silently.

### MEDIUM-05 — Gemini output has no schema validation or prompt-data boundary

**Affected code**

- `alac_rip/gemini_ai.py:40-66`
- `alac_rip/gemini_ai.py:94-131`
- `app/src/lib/GeminiCurator.svelte:94-138`

Library artist metadata and the user's prompt are concatenated directly with instructions. Model output is only passed through `json.loads`; it is not validated as an object with bounded strings, arrays, and track objects. Malformed elements can cause crashes, while an oversized track array can amplify Apple Music requests.

No automatic persistent state mutation was found in the current Gemini flow, which limits impact.

**Required remediation**

- Put trusted instructions in a system instruction field and delimit untrusted metadata as data.
- Validate output with strict Pydantic models: forbid extra fields, cap every string/list, and enforce the requested track range.
- Treat all model text as untrusted and reject malformed results before enrichment or UI return.

### MEDIUM-06 — Integration secrets are returned by `/config`

**Affected code**

- `alac_rip/server.py:1644-1654`
- `app/src/lib/Settings.svelte:29-43`

Top-level Gemini and Last.fm keys are omitted, but `_CONFIG_OMIT` does not recursively redact `integrations`. Jellyfin API keys and Navidrome tokens/salts are therefore returned to the frontend in the `integrations` object.

The endpoint is capability-protected in packaged mode, but write-only secrets would reduce the impact of a future frontend compromise.

**Required remediation**

- Return only `configured: true/false` or a masked placeholder for integration secrets.
- Preserve stored secrets when the UI omits them on update.
- Prefer an OS credential store rather than YAML for service credentials.

### MEDIUM-07 — Wallpaper import accepts arbitrary persisted URLs and unbounded data

**Affected code**

- `app/src/lib/Settings.svelte:61-71`
- `app/src/lib/Settings.svelte:94-105`
- `app/src/lib/themes.ts:72-89`
- `app/src/lib/themes.ts:113-136`

The uploader trusts the browser-provided MIME type and reads the entire file into a data URL. Appearance JSON accepts any `wallpaper` string, including remote HTTPS URLs and extremely large data URLs, then persists it in local storage and inserts it into a CSS `url(...)` value.

No reliable JavaScript execution was demonstrated: CSP and image-context handling materially reduce `javascript:`/SVG script risk. However, an imported preset can cause persistent outbound tracking requests and storage/UI denial of service.

**Required remediation**

- Accept only bounded JPEG, PNG, or WebP data verified by decoded magic bytes.
- Reject SVG, `javascript:`, arbitrary remote URLs, malformed data URLs, and oversized images.
- Validate imported `dim` and `blur` as finite bounded numbers.

### MEDIUM-08 — Tauri capability set is broader than current use

**Affected code**

- `app/src-tauri/capabilities/default.json:6-20`

`opener:default`, `dialog:default`, and `notification:default` expose broad command sets to the webview. The notification default includes channel/listener/batch management beyond ordinary notifications. The shell capability permits sidecar spawning and should not be exposed to webview code if it is needed only by native Rust startup.

**Required remediation**

- Replace defaults with the exact opener, dialog, and notification commands used.
- Scope opener URLs to expected HTTPS domains where feasible.
- Remove webview shell spawning if native Rust can start the sidecar without it; otherwise pin the exact sidecar and fixed `--sidecar-handshake` argument.
- Add a capability regression test or reviewed generated manifest snapshot.

### LOW-01 — HTTP Range grammar is not parsed strictly

**Affected code**

- `alac_rip/server.py:1811-1842`

The regex uses `re.match` rather than a full match. The server accepted malformed values:

```text
Range: bytes=0-1,5-6   -> 206 with bytes 0-1
Range: bytes=0-1garbage -> 206 with bytes 0-1
```

Suffix ranges such as `bytes=-3` are rejected. Streaming itself is chunked in 64 KiB blocks, so no whole-file memory read was found.

**Required remediation**

- Use a strict full match.
- Explicitly support or reject suffix and multi-range requests.
- Return RFC-compliant `416` responses with `Content-Range: bytes */size`.
- Add concurrency limits and tests for huge integers, empty files, disconnects, and file changes during streaming.

### LOW-02 — Residual stream filesystem race

**Affected code**

- `alac_rip/server.py:98-112`
- `alac_rip/server.py:1775-1842`
- `alac_rip/state.py:244-255`

Static traversal, tampered out-of-library database paths, unrecorded files, and static symlinks are rejected through canonical resolution plus database membership. However, validation, `stat()`, and `open()` are separate operations. A writable parent directory could be replaced with a symlink between validation and open.

**Required remediation**

- Open through directory/file descriptors with no-follow semantics and stream from the validated handle.
- Verify the opened file identity and regular-file type before reading.

### LOW-03 — CSV formula prefixes are preserved

**Affected code**

- `alac_rip/playlist_import.py:31-49`

Values beginning with `=`, `+`, `-`, or `@` are preserved. PoC values such as `=1+1` and `@HYPERLINK` survived parsing unchanged.

The current import UI renders them as escaped text and does not export them to a spreadsheet, so no formula execution exists in the reviewed flow. This becomes exploitable if imported values are later emitted to CSV or another spreadsheet-compatible format.

**Required remediation**

- Keep canonical internal metadata intact if required, but neutralize formula prefixes on every spreadsheet export.
- Add explicit tests so a future export cannot introduce formula injection.

### LOW-04 — Runtime databases are tracked in Git

**Affected files**

- `.state/downloaded.db`
- `.state/state.db`

Both runtime databases are tracked. Such files can contain playlist history, local paths, and library metadata. Ignoring the directory does not remove already tracked files or history.

**Required remediation**

- Remove runtime databases from the Git index.
- Add a CI rule rejecting `.state/` artifacts and common database files.
- If the repository has been published, assess history cleanup and rotate any secrets found during a controlled review.

## Controls that passed review

- The packaged backend binds only to `127.0.0.1` (`server.py:2084-2087`).
- The sidecar handshake validates a 256-bit lowercase-hex capability (`server.py:2063-2074`).
- Authentication uses `secrets.compare_digest` (`server.py:400-407`).
- CORS is limited to the Tauri and local Vite origins (`server.py:410-418`).
- All 52 tested resource routes returned `401` without the configured capability.
- Track IDs are passed to parameterized SQLite queries (`state.py:195-200`).
- Stream paths are canonicalized, required to remain under `music_dir`, and required to match a recorded path (`server.py:98-112`).
- Static out-of-tree paths and ordinary symlinks do not bypass the stream boundary.
- Stream reads are chunked at 64 KiB (`server.py:1800-1803`, `1824-1834`).
- LRCLIB uses HTTPS, a User-Agent, and request timeouts (`lyrics.py:9`, `35-49`).
- Config writes are atomic and mode `0600` on Linux (`config.py:41-60`); the live config was also mode `0600`.
- No `{@html}`, `innerHTML`, `eval`, `new Function`, or equivalent raw execution sink was found in `app/src`.
- Reviewed Svelte components use escaped interpolation for track, artist, album, lyric, error, and model strings.
- CSP blocks objects, forms, and arbitrary connect targets outside the app and loopback (`tauri.conf.json:23-33`).
- Shell spawning is scoped to the packaged sidecar name (`capabilities/default.json:11-18`).

## Release gates

Release remains **ACTION REQUIRED** until at least the following are complete:

1. Fix HIGH-01 through HIGH-04.
2. Add regression tests for SSRF/redirect credential stripping, secret redaction, and `.lrc` symlink writes.
3. Make production authentication fail closed and remove the sidecar port/token race.
4. Enforce request, response, row, field, prompt, track, and wallpaper size limits.
5. Validate Gemini output with a strict bounded schema.
6. Re-run backend, Svelte, Rust, dependency, Linux package, and Windows package checks from a clean worktree.
