# Security Remediation Verification — Pies Pear Music v1.0.0

**Verified commit:** `9c14fc69a9de52fd502de0da83e363976d70b4a9`  
**Date:** 2026-09-02  
**Release verdict:** **ACTION REQUIRED — gate not cleared**

## Summary

| Audit item | Result | Notes |
|---|---|---|
| HIGH-01 — fail-closed authentication | **Partial** | Token coverage is uniform when configured, but no-auth operation still fails open. |
| HIGH-02 — config secret redaction | **Verified** | `auth_password` and `api_token` are omitted and replaced by boolean flags. |
| HIGH-03 — process credential exposure | **Not fixed** | Password remains in native `argv` and container environment. |
| MEDIUM-01 — session lifecycle | **Partial / regression** | TTL exists, but logout crashes, token remains in `localStorage`, and the cap is off by one. |
| MEDIUM-02 — cover symlink boundary | **Verified** | Direct symlinks and canonical escapes are rejected. |
| MEDIUM-03 — safe LRC writes | **Partial** | Random temporary replacement exists, but no containment or no-follow open is enforced. |
| MEDIUM-04 — FLAC audit containment | **Verified** | Canonical library containment is enforced before `flac`. |
| MEDIUM-05 — waveform resource bound | **Partial** | Duration is capped, but up to roughly 115 MB PCM per request is still buffered. |
| LOW-01 — atomic secret writes | **Partial** | Config temp creation is improved; credential fallback and directory hardening remain. |
| LOW-02 — extension allowlist | **Partial** | Traversal through `ext` is prevented, but invalid values are silently coerced and final containment is not asserted. |

## Remaining release blockers

### 1. HIGH-01 remains fail-open when authentication is absent

At `alac_rip/server.py:646-659`, authorization is enforced only when `auth_configured` is true. If `_api_capability` is absent and neither `auth_password` nor `api_token` is configured, every non-public endpoint proceeds to `call_next()` at line 666.

The refactor successfully fixes the old `/api/*` inconsistency: when either configured secret exists, all non-public routes use the same check. It does not implement fail-closed behavior.

**Required change:** refuse non-loopback startup without a configured secret, or require a generated secret for all non-public routes even in passwordless mode. Add tests for:

- no secrets + state-changing route => `401` (or startup refusal on non-loopback);
- API token only + every state-changing route => `401` without token;
- password only + every state-changing route => `401` without session;
- public allowlist accepts only the exact intended method/path pairs.

### 2. HIGH-03 remains unchanged

At `alac_rip/server.py:435-436`, native wrapper credentials remain in the process command line:

```python
cmd = [str(native_bin), "-L", f"{email}:{password}"]
```

At `alac_rip/server.py:468-469`, container credentials remain in the child environment:

```python
child_env["args"] = f"-L {email}:{password}"
```

Log-string replacement at `server.py:330-351` does not protect `/proc/<pid>/cmdline`, `/proc/<pid>/environ`, process inspection, container inspection, crash collection, or privileged local readers. The remediation commit contains no relevant change to this launch path.

**Required change:** modify the wrapper interface to receive credentials over stdin or an inherited private descriptor. Do not put the password in `argv` or environment variables.

### 3. MEDIUM-01 introduced broken logout and did not remove browser token storage

The session store was renamed to `_sessions` at `alac_rip/server.py:577`, but logout still accesses `_valid_sessions` at lines `714-715`. An authenticated logout raises `NameError` and returns HTTP 500. This was reproduced directly during verification.

Fix it as follows:

```python
if token:
    _sessions.pop(token, None)
```

The server still returns the token in JSON at `server.py:708`, and `app/src/api.ts:39-42` and `620-633` still read/write it through `localStorage`. The claimed standardization on HttpOnly cookies therefore did not occur.

Additional lifecycle issues:

- `_prune_expired_sessions()` runs during token creation, not automatically on every request.
- Pruning occurs before insertion. At exactly 500 sessions no entry is evicted, after which insertion produces 501 sessions.
- Cookie `max_age` is 30 days (`server.py:706`) while server TTL is 7 days.
- No login rate limiting or backoff is present.

**Required change:** use the cookie exclusively, remove the token from the JSON response and `localStorage`, fix logout, align cookie/server expiry, prune before verification and after insertion, and add authentication lifecycle tests.

## Partially remediated items

### Safe LRC writes

`alac_rip/sync.py:242-250` now removes an existing target symlink and atomically replaces from a random temporary name. It still:

- does not prove `target` or its parent is beneath `music_dir`;
- uses `Path.write_text()` rather than `O_EXCL|O_NOFOLLOW`;
- has a check/write race in a directory writable by an attacker;
- does not `fsync` the file or directory;
- silently suppresses all failures.

Use a shared bounded-write helper that receives the trusted root, resolves and verifies the parent, opens with exclusive/no-follow flags, fsyncs, replaces, and fsyncs the parent directory.

### Waveform memory usage

`alac_rip/waveform.py:45` adds `-t 7200`, but lines `56-72` still use `subprocess.run(..., stdout=PIPE)` and retain the complete decoded stream. Two hours of 8 kHz, 16-bit mono PCM is approximately 115.2 MB per request, excluding Python copies and concurrent requests.

Reduce the duration bound to the product requirement and incrementally aggregate peaks from a streaming `Popen` pipe. Add a small concurrency semaphore.

### Atomic secret files

`alac_rip/config.py:124-146` now uses `mkstemp` and `fchmod(0600)`, fixing predictable temporary-file creation. Remaining hardening includes enforcing `0700` on the parent, treating final permission failures as errors, and fsyncing the directory. The headless credential fallback at `alac_rip/server.py:272-280` still uses `write_text()` followed by `chmod`, so the original transient-permission/symlink concern remains there.

### Extension handling

`alac_rip/organizer.py:58-68` prevents separators in the resulting extension, but it silently converts invalid input to `.flac` when the string merely contains `flac`, otherwise `.m4a`. Reject invalid values explicitly and perform the documented final containment assertion before returning the path.

## Verified fixes

### HIGH-02 — config redaction

Verified at `alac_rip/server.py:2564-2613`. Both authentication secrets are omitted and only `*_configured` booleans are returned. Mask preservation exists at lines `2626-2644`.

### MEDIUM-02 — cover-art boundary

Verified at `alac_rip/server.py:2506-2518`. A direct symlink is rejected and the strict resolved path must be relative to resolved `music_dir` before reading.

### MEDIUM-04 — FLAC audit containment

Verified at `alac_rip/audit.py:150-164`. Database paths pass through normalization and a canonical `_is_safe_subpath` check before subprocess use.

## Test verification

- Backend: **334 passed in 30.89 seconds** using `.venv/bin/pytest -q`.
- Direct logout regression check: **failed** with `NameError: name '_valid_sessions' is not defined` at `alac_rip/server.py:714`.
- Frontend: **failed** using `cd app && npm run check` with one TypeScript error at `app/src/lib/SetupWizard.svelte:75`: `needs_2fa` is absent from the declared wrapper-login response type.
- The remediation commit did not add or modify tests. The 334-test pass therefore does not exercise the new auth/session regressions.

## Gate decision

The release gate is **not cleared**. Fix the process-metadata credential exposure, fail-open no-auth behavior for network deployments, broken logout, and browser bearer-token storage. Then add remediation-specific tests and require both backend tests and `npm run check` to pass before reassessment.
