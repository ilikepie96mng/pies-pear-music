# Authentication Contract and Migration Gate

This document defines the regression harness and scope for Apple/wrapper
credential persistence. The wrapper invocation, response parsing, 2FA behavior,
and Podman runtime exposure remain frozen while this work is verified.

## Scope boundary

The implemented change is limited to credential persistence at rest:

- Store the JSON credential record with the desktop Secret Service through
  `secret-tool`; the legacy on-disk credential file is never read.
- If no keyring is available, retain credentials only for the current backend
  session. No plaintext fallback file is created.
- Remove a legacy credential file only after a successful Secret Service save.
- Do not alter wrapper command construction, wrapper image build behavior,
  stdout parsing, 2FA prompts, container networking, or login state rules in
  the same change.
- Do not claim that keyring storage removes same-user runtime exposure in the
  wrapper/Podman process.

## Fixture rules

- No fixture may contain a real account, email address, password, token,
  playlist URL, cookie, device identifier, or copied production log.
- Use synthetic wrapper lines with the exact structural markers consumed by the
  backend, plus redacted surrounding text.
- Mock Podman/subprocess process creation and use an in-memory pipe for stdout
  and stdin. Contract tests must never start a container or contact Apple.
- Use a temporary state directory and a fake keyring adapter. Tests must assert
  that persistent fallback files are not created when keyring storage is
  unavailable.

## Required contract cases

| Case | Fixture behavior | Required assertion |
| --- | --- | --- |
| Manual login starts | synthetic process starts | wrapper launch state and user-visible start message are retained |
| SMS 2FA | `credentialHandler` + `2FA: true` marker | SMS 2FA state is set and a code can be written to mocked stdin |
| Trusted-device 2FA | response-type-4 marker | device 2FA state is set with the distinct user message |
| Login success | response-type-6 marker | wrapper becomes ready; 2FA state clears |
| Login failure | process exits before success | wrapper is not marked ready and the failure is reported without secrets |
| Auto-login success | stored synthetic credentials + success marker | current-session login succeeds without changing wrapper arguments/parsing |
| Auto-login failure | stored synthetic credentials + failed exit | stored credential reference is removed; no plaintext fallback is created |
| Restart | successful login followed by backend restart | only the approved persistence adapter is consulted; session-only credentials do not survive |
| Shutdown | active mocked wrapper process | child termination is requested exactly once and login state clears |
| Log redaction | wrapper line contains synthetic secret-shaped values | user-visible logs and errors do not contain the values |

## Migration and verification sequence

1. Record the exact wrapper command shape and parsed state transitions in the
   tests. Review the fixtures without real data.
2. Test Secret Service save/load/clear behavior and the session-only fallback
   with mocked subprocess calls; no test may touch the user keyring.
3. Remove the old base64 file writer/reader only after migration and restart
   coverage pass.
4. Run the full Python suite on 3.12 and 3.13, then perform a manual authorized
   login/2FA/restart/shutdown check using a non-production test account.
5. Review logs, diagnostics, and generated support material for secrets before
   publication.

Any failure in wrapper invocation, parsing, 2FA state, restart, or shutdown is
a stop condition. The migration must be split into smaller changes rather than
patched around with live credentials.
