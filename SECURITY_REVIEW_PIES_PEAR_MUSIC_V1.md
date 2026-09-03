# Defensive Security Review — Pies Pear Music v1.0.0

**Review target:** `ilikepie96mng/pies-pear-music`, branch `main`  
**Reviewed commit:** `938634651fb593d224e2ea4faf89a475881a17a6`  
**Review date:** 2026-09-02  
**Verdict:** **ACTION REQUIRED**

## Executive summary

The project has several good foundations: cryptographically strong session tokens, constant-time secret comparisons, centralized authentication middleware, canonical path checks for audio streams, strict single-range parsing, filename sanitization, structured subprocess argument arrays, parameterized SQLite values, and atomic `0600` configuration writes.

Release should nevertheless be blocked until the High findings are corrected. The most important issue is fail-open authentication: with no password or Tauri capability, most routes are public, and an `api_token` by itself protects only `/api/*`, leaving destructive and configuration routes exposed. In addition, `/config` does not redact `auth_password` or `api_token`, and Apple credentials are exposed in child-process command-line/environment metadata.

| Severity | Count |
|---|---:|
| Critical | 0 |
| High | 3 |
| Medium | 5 |
| Low | 2 |

## Findings and recommendations

### HIGH-01 — Authentication fails open and API-token coverage is path-dependent

**References:** `alac_rip/server.py:603-644`, notably `620-644`; state-changing examples at `2312-2324`, `2576-2618`, and `2635-2660`.

When `auth_password` is configured, the centralized middleware correctly requires a valid session or API token for all non-public state-changing routes reviewed. However:

- If `_api_capability`, `auth_password`, and `api_token` are absent, the middleware falls through and permits every request.
- If only `api_token` is configured, it protects only paths beginning with `/api/`. Routes such as `PUT /config`, `POST /library/deduplicate`, `POST /database/import`, sync routes, and wrapper-login routes remain unauthenticated.
- Authorization policy is coupled to URL spelling rather than endpoint sensitivity.

**Safe proof of concept:** start the sidecar with no password/capability, then request `GET /config`; middleware reaches `call_next()` at line 644. With only `api_token` set, `POST /library/deduplicate` also bypasses the `path.startswith("/api/")` branch.

**Recommended patch:** make authentication fail closed whenever the server is reachable beyond the Tauri bootstrap, and apply one policy to every non-public route.

```python
PUBLIC = {("GET", "/health"), ("GET", "/auth/status"), ("POST", "/auth/login")}

if request.method != "OPTIONS" and (request.method, request.url.path) not in PUBLIC:
    supplied = request.headers.get(_API_CAPABILITY_HEADER)
    valid_capability = bool(
        supplied and _api_capability and secrets.compare_digest(supplied, _api_capability)
    )
    valid_api_token = bool(
        supplied and cfg and cfg.api_token and secrets.compare_digest(supplied, cfg.api_token)
    )
    valid_session = _verify_session_token(_extract_session_token(request))
    if not (valid_capability or valid_api_token or valid_session):
        return JSONResponse({"detail": "Authentication required"}, status_code=401)
```

For intentional passwordless desktop operation, require the random Tauri capability and bind only to loopback. Refuse startup when binding a non-loopback address without an authentication secret. Add a route-table regression test that enumerates every `POST`, `PUT`, `PATCH`, and `DELETE` route and asserts `401` without credentials.

### HIGH-02 — `/config` returns the authentication password and API token

**References:** `alac_rip/server.py:2535-2559`, `2562-2573`.

`_CONFIG_OMIT` excludes several secrets, but it does not include `auth_password` or `api_token`. Consequently, `GET /config` can return those values when they are stored in YAML. In the fail-open deployment described in HIGH-01, this can be an unauthenticated credential disclosure; even with authentication, it unnecessarily exposes reusable secrets to frontend JavaScript and any authenticated low-trust user.

**Recommended patch:** add both keys to the never-return set and expose only boolean configured flags.

```python
_CONFIG_OMIT = {
    "apple_id_password", "media_user_token", "lastfm_api_key",
    "lastfm_shared_secret", "gemini_api_key", "github_remote",
    "auth_password", "api_token",
}

sanitized["auth_password_configured"] = bool(data.get("auth_password"))
sanitized["api_token_configured"] = bool(data.get("api_token"))
```

Also ensure `ConfigUpdate` treats mask placeholders as “preserve existing” for these two top-level secrets.

### HIGH-03 — Apple credentials are exposed through process metadata

**References:** `alac_rip/server.py:435-436`, `457-469`, `474-482`.

Native mode passes `email:password` in the wrapper command line. Container mode places it in the `args` environment variable. Command lines are commonly readable via process inspection, and environment values can be exposed through `/proc`, crash reports, container inspection, or diagnostics. Structured argument lists prevent shell injection, but do not provide credential confidentiality.

**Recommended patch:** change the wrapper boundary to accept credentials over an inherited pipe or stdin, then immediately overwrite/drop the in-memory buffer where practical. If the wrapper cannot support this, use a root/user-private `0600` temporary file opened with `O_CREAT|O_EXCL|O_NOFOLLOW`, pass only its descriptor, and unlink it immediately. Never place passwords in `argv`, environment variables, logs, or exceptions.

### MEDIUM-01 — Browser session handling weakens the HttpOnly-cookie protection

**References:** `alac_rip/server.py:575-588`, `672-695`; `app/src/api.ts:620-641`; `app/src/lib/LoginModal.svelte:14-31`.

Token generation has adequate entropy (`secrets.token_urlsafe(32)`), comparison of the password is constant-time, and logout removes the submitted token. However, the login response also returns the bearer token and the frontend saves it in `localStorage`, making it available to any successful XSS. Server-side sessions have no creation time, idle timeout, absolute expiry, or bounded count. Cookie `max_age` does not expire the corresponding server-side set entry, and the cookie lacks `Secure`.

**Recommended patch:** use the HttpOnly cookie only; remove `token` from the response and remove `localStorage` session handling. Store `{token_hash: expires_at}` server-side, enforce absolute/idle expiry, prune expired sessions, cap concurrent sessions, rotate on login/password change, and use `secure=True` whenever TLS terminates at the app. Add login throttling by source plus exponential backoff.

### MEDIUM-02 — Cover-art fallback follows symlinks outside `music_dir`

**References:** `alac_rip/server.py:2484-2490`; protected track resolution at `111-143`.

The audio track is canonically constrained to `music_dir`, but the fallback cover candidate is checked only with `is_file()` and then read. A library-controlled symlink named `cover.jpg` can point outside the library. The response labels arbitrary bytes as an image, but it still constitutes an out-of-bound file read and the route is deliberately public via `server.py:613`.

**Recommended patch:** resolve the cover and require it to remain beneath the resolved music root; reject symlinks or open with no-follow semantics.

```python
resolved = cand.resolve(strict=True)
resolved.relative_to(cfg.music_dir.expanduser().resolve())
if cand.is_symlink() or not resolved.is_file():
    continue
```

Also remove `/track-art` from public routes or use short-lived, scoped media URLs.

### MEDIUM-03 — Lyrics synchronization can overwrite an out-of-library symlink target

**References:** `alac_rip/sync.py:231-260`, especially `246` and `253`.

The source `.lrc` rejects symlinks, but the destination is written with `Path.write_text()` without checking whether the existing destination is a symlink. A malicious or shared library tree can redirect the write outside `music_dir`.

**Recommended patch:** centralize safe sidecar writes: resolve and verify the parent beneath `music_dir`, reject an existing symlink, create a same-directory temporary file with `O_EXCL|O_NOFOLLOW`, `fsync`, and `os.replace`. Reuse the hardened helper for every cover, playlist, and lyric write.

### MEDIUM-04 — FLAC integrity audit does not enforce the library boundary

**References:** `alac_rip/audit.py:150-209`.

`verify_library_flac_integrity()` directly resolves database `local_path` values and invokes `flac`/`read_tags` without checking containment. This differs from the deduplication path, which performs `_is_safe_subpath()` before deletion at `audit.py:525-545`. A tampered/imported database can cause processing of files outside the library and disclose paths/tool errors in the response.

**Recommended patch:** use a single strict resolver for every database-backed file operation. Do not let `_normalize_track_file_path()` return an absolute file before proving containment (`audit.py:31-32`). Return a generic per-track failure rather than raw subprocess errors and local paths.

### MEDIUM-05 — Waveform extraction buffers all decoded PCM in memory

**References:** `alac_rip/waveform.py:41-79`.

The invocation is safe from shell injection and includes a 45-second timeout and one-thread limit, but `stdout=PIPE` buffers the entire decoded 8 kHz PCM stream before processing. Multiple long or adversarial audio files can cause substantial memory pressure.

**Recommended patch:** impose an ffmpeg duration cap (`-t`), stream fixed-size blocks with `Popen`, compute peaks incrementally, cap concurrent waveform jobs, and kill the entire process group on timeout. Bound stderr capture as well.

### LOW-01 — Atomic secret writes need symlink and directory hardening

**References:** `alac_rip/config.py:124-145`; fallback credential write at `alac_rip/server.py:272-280`.

Configuration writes create a predictable `.tmp` path with `O_TRUNC`, without `O_EXCL`/`O_NOFOLLOW`; the credential fallback uses `write_text()` and applies `0600` only afterward. In a directory writable by another local user, this creates symlink and transient-permission risks. Errors from final `chmod` are silently ignored.

**Recommended patch:** require the config directory to be owned by the service user and mode `0700`; use `tempfile.mkstemp(dir=path.parent)`, `fchmod(0600)`, flush/fsync, verify a regular file, `os.replace`, and fsync the directory. For credentials, use the same helper and fail closed if private permissions cannot be established.

### LOW-02 — Filename extension and final containment should be allowlisted

**References:** `alac_rip/organizer.py:6-55`, `58-84`.

`sanitize()` correctly normalizes Unicode, replaces separators and control characters, handles dot-only and Windows-reserved names, and caps component length. However, `track_path()` accepts `ext` without sanitization and its docstring claims canonical containment without actually resolving/checking the final path.

**Recommended patch:** map a trusted format enum to an extension (for example `{ALAC: ".m4a", FLAC: ".flac"}`), reject every other value, then resolve the parent and require `target.resolve(strict=False).relative_to(music_dir.resolve())` to succeed. Consider byte-length, not just character-length, limits for UTF-8 filesystems and deterministic collision handling after truncation.

## Confirmed defensive controls

- **Authentication when a password is configured:** the middleware at `server.py:620-632` covers reviewed non-public state-changing routes. The password comparison at `676` uses `secrets.compare_digest`, tokens have approximately 256 bits of randomness, and logout revokes the supplied token.
- **Audio streaming boundary:** `_resolve_library_file()` canonicalizes and checks containment plus database membership (`server.py:111-143`). Streaming uses 64 KiB chunks and strict `Range` full-match/bounds checks (`2840-2915`). A residual file-open TOCTOU remains; descriptor-based `openat`/no-follow handling would fully harden it.
- **Deduplication:** deletion is guarded by canonical `_is_safe_subpath()` checks (`audit.py:525-556`). Apply the same guard separately to `.lrc` and cover cleanup targets before unlinking.
- **Subprocess command injection:** reviewed calls in `sync.py` and `waveform.py` use argument lists and no `shell=True`. User-controlled filenames remain single arguments. The credential-metadata issue in HIGH-03 is separate from shell injection.
- **SQLite injection:** reviewed values are parameter-bound. Dynamic SQL at `state.py:983-985` and `1023-1026` interpolates only programmatically generated `?` placeholders; the update clause at `1273` is assembled exclusively from fixed column names. `with self._conn()` provides commit-on-success/rollback-on-exception transactions, and a five-second busy timeout is set at `state.py:48-54`.
- **Configuration output:** integration, Gemini, Last.fm, media-user, and Apple password fields are otherwise omitted or masked at `server.py:2535-2559`. Wrapper output has explicit redaction. HIGH-02 must extend this to the two missing authentication secrets.

## Verification notes

- The exact reviewed upstream revision is identified above, so line references are reproducible.
- Static review covered the requested backend, frontend login flow, relevant route middleware, all subprocess call sites in the named modules, dynamic SQL construction, and secret serialization/redaction.
- The full pytest invocation did **not** complete within 180 seconds in this review environment. A focused `tests/test_virtual_stream.py` run also stalled on its first test, so no passing-test claim is made. This is itself a CI robustness issue: run the suite with per-test timeouts and publish JUnit timing data before release.

## Release gate

Do not approve v1.0.0 for network-accessible or multi-user deployment until HIGH-01 through HIGH-03 are fixed and regression-tested. MEDIUM-02 through MEDIUM-04 should also block use with writable network shares or other untrusted library storage. After patching, require tests proving fail-closed auth across the route table, config-secret redaction, symlink rejection for every read/write/delete path, session expiry, and bounded waveform resource use.
