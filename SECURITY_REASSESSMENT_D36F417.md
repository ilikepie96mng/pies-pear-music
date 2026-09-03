# Security Remediation Re-Assessment — Pies Pear Music v1.0.0

**Public commit:** `dcc9650331e6efdb431485531d2e38553c21ff81`  
**Release commit:** `d36f41717ada8cd6cf18edf4180da0afe4ba6f66`  
**Re-assessment date:** 2026-09-02  
**Verdict:** **ACTION REQUIRED — release gate not cleared**

The application source and tests under `alac_rip/`, `app/src/`, and `tests/` are identical between the two commits. The public commit differs only by omission of the two internal security review documents.

## Verification results

| Item | Result | Assessment |
|---|---|---|
| HIGH-01 — fail-closed auth | **Verified with test gap** | Headless requests fail closed in source; configured token/password coverage is uniform. The named regression test does not actually exercise headless mode without configured secrets. |
| HIGH-02 — config redaction | **Verified** | Previously verified and unchanged. |
| HIGH-03 — wrapper process secrets | **Not fixed** | Native password remains in `argv`; container password remains in container environment state. |
| MEDIUM-01 — sessions | **Verified** | Logout, TTL, cap, cookie-only browser flow, and rate limiting are implemented. Minor operational hardening remains. |
| MEDIUM-02 — cover containment | **Verified** | Previously verified and unchanged. |
| MEDIUM-03 — LRC writes | **Verified** | Canonical parent containment, exclusive/no-follow temp creation, file fsync, atomic replace, and directory fsync are present. |
| MEDIUM-04 — FLAC audit containment | **Verified** | Previously verified and unchanged. |
| MEDIUM-05 — waveform bounds | **Accepted with residual risk** | Four-job semaphore and 30-minute cap establish bounds, though output remains fully buffered. |
| LOW-01 — atomic config | **Verified** | Parent/file modes, exclusive temporary creation, file fsync, replacement, and directory fsync are present. |
| LOW-02 — extension allowlist | **Verified** | Invalid extensions raise and the resolved target is checked against the resolved music root. |
| Frontend type check | **Verified** | `svelte-check` passes with zero errors and zero warnings. |

## Remaining release blocker

### HIGH-03 — credentials remain exposed in process metadata

The remediation changes how the container runtime receives the secret, but it does not remove the secret from process/container metadata.

#### Native execution remains unchanged

At `alac_rip/server.py:446-447`:

```python
cmd = [str(native_bin), "-L", f"{email}:{password}"]
```

The password is visible in the native wrapper's command line through process inspection such as `/proc/<pid>/cmdline` to principals permitted by the host's process-isolation policy.

#### Container execution still stores the secret in its environment

At `alac_rip/server.py:468-490`, a private temporary file contains:

```text
args=-L email:password
```

Podman consumes this as a container environment variable. Removing the host-side file after `Popen` hides the temporary file but does not remove `args` from the created container's configuration or environment. It may remain available through container inspection and `/proc/<pid>/environ` according to runtime privileges. The environment-file path also has a startup race: the parent unlinks it immediately after `Popen` returns, before there is an explicit acknowledgement that Podman has opened and consumed it.

The regression test at `tests/test_auth_contract.py:158` asserts only that `--env-file` appears in the command. It does not assert that credentials are absent from the resulting process/container environment.

#### Required remediation

Change the wrapper interface so credentials are read from a one-shot stdin protocol or inherited anonymous pipe and are not copied into the wrapper's long-lived environment or command line. If the opaque wrapper cannot support this, HIGH-03 cannot be considered fixed; document it as an accepted risk with strict host/container isolation, or replace/patch the wrapper.

## Other observations

### HIGH-01 test coverage does not match its name

`tests/test_security_remediation.py:18-42` configures both `auth_password` and `api_token`. Therefore `test_fail_closed_unauthenticated_requests` at lines `45-69` exercises the `auth_configured` branch, not `_is_headless=True` with no configured secrets.

The source at `alac_rip/server.py:697-715` does enforce `401` when `_is_headless` is true, so the control is present. Add a separate test that sets headless mode with both secrets empty. Also consider refusing startup or reporting an explicit locked/misconfigured state: `/auth/status` and `/auth/login` currently report that authentication is unnecessary when no password exists, even though headless middleware rejects protected requests and no usable session can be created.

### Session and rate-limit residuals

The browser no longer stores or transmits `pies_session_token`; login returns no bearer token, cookie expiry matches the seven-day server TTL, logout removes the active session, and pruning maintains at most 500 entries.

For production reverse-proxy deployments, define the trusted-proxy policy used to derive the client IP. The current process-local, per-IP limiter can cause all users behind one proxy/NAT to share a bucket and is reset on restart. Cap/prune `_login_failed_attempts` globally to avoid unbounded distinct-IP keys.

### Waveform residual memory usage

At 8 kHz, signed 16-bit mono, a 30-minute decode produces about 28.8 MB of PCM. Four concurrent jobs can therefore retain roughly 115.2 MB of raw output, before Python copies/arrays and captured stderr. This is now bounded and is not assessed as a release blocker, but incremental peak calculation would be more robust.

## Executed checks

```text
.venv/bin/pytest -q
340 passed in 29.62s

.venv/bin/pytest -q tests/test_security_remediation.py
6 passed in 0.27s

cd app && npm run check
svelte-check found 0 errors and 0 warnings
```

## Gate decision

All previously blocking findings except HIGH-03 are sufficiently remediated. The release gate remains closed because Apple credentials are still placed in native command-line metadata and container environment metadata. Once the wrapper credential transport is changed to a pipe/stdin mechanism—or the risk is explicitly accepted under a documented threat model—the gate can be reassessed.
