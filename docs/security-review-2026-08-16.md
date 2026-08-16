# Security Review — Pies Pear Music

**Review date:** 2026-08-16  
**Repository:** `pies-alac-rip-tool`  
**Reviewed branch:** `release/2` at `f096d13`, including the uncommitted changes present on the review date  
**Review type:** Read-only source, configuration, dependency, and regression-coverage review

## Executive summary

No critical remote-code-execution vulnerability was identified in the reviewed
Python, Svelte, or Tauri code. The packaged desktop/backend boundary is generally
well designed: the backend listens only on loopback, packaged launches require a
random per-process capability token, CORS and CSP are restricted, SQL statements
are parameterized, YAML is loaded with `safe_load`, and subprocesses use argument
arrays rather than a shell.

The review found four high-priority issues:

1. Organization is not scoped to files produced by the current download job.
2. Metadata-derived destination collisions can silently overwrite library files.
3. Runtime SQLite databases containing private library data remain tracked in Git.
4. Apple account credentials are included in the Podman process command line.

Five medium-priority hardening areas were also identified: plaintext Last.fm
transport, control-character injection into filenames/playlists/logs, unbounded
job resources, non-atomic and insufficiently permission-hardened configuration
writes, and vulnerable development/build dependencies.

The current dot-segment sanitization patch fixes the reported literal `.`/`..`
path traversal case. It should be retained, but it is not a complete filesystem
security boundary by itself. The new continue-after-downloader-error behavior
addresses a serious recovery problem, but it should not be committed as the final
design until current-job provenance and overwrite protection are added.

## Scope and limitations

### Reviewed

- FastAPI backend routes, authentication middleware, job queue, wrapper process
  lifecycle, configuration handling, local-file endpoints, and integrations.
- Sync, metadata, organizer, state, and Strawberry export behavior.
- Svelte API client and security-relevant frontend behavior.
- Tauri lifecycle, CSP, capabilities, sidecar handshake, and permissions.
- Python, npm, and Cargo dependency declarations and lockfiles.
- Existing tests and the uncommitted changes described in `HANDOFF.md`.
- Git tracking and ignore behavior for runtime state.

### Not reviewed

- The separate `alac-rip/apple-music-downloader` Go source tree and wrapper source
  were outside the permitted workspace boundary and were not independently
  audited.
- The deployed `~/.local/share/pies-alac-rip/amd-main` binary was not inspected or
  compared to a reproducible source build.
- No live Apple credentials, Apple authentication, DRM operation, or real media
  download was used during this review.
- Python and Rust advisory scanners were not installed in the review environment.
  Their dependency trees still require dedicated automated audits before release.
- This is a source-level review, not a formal penetration test or sandbox escape
  assessment of WebKitGTK, Podman, FFmpeg, or the host desktop.

## Security model

Pies Pear Music is a local Linux desktop application. Its primary trusted
components are the Tauri shell and packaged Python sidecar. The sidecar performs
high-impact operations under the desktop user's account: it launches external
programs, writes configuration and state, moves and transcodes media, updates a
Strawberry SQLite database, and opens local files or URLs.

The review treats the following as untrusted or partially trusted inputs:

- Apple Music URLs and catalog metadata.
- Media files and tags created by the external downloader.
- Downloader stdout and manifest content.
- Last.fm API responses and external URLs.
- User-selected configuration paths.
- Mutable external downloader and wrapper source trees or binaries.
- Requests reaching the loopback API without the packaged sidecar handshake.

The main assets are Apple credentials, capability tokens, Last.fm API keys,
playlist URLs, local library paths, media integrity, the state database, and the
availability of the desktop/backend processes.

## Severity definitions

- **Critical:** Direct compromise of the host or secrets through a remotely
  reachable path with little or no user interaction.
- **High:** Credible credential disclosure, destructive file impact, private-data
  publication, or a release-blocking trust failure.
- **Medium:** Material confidentiality, integrity, or availability weakness that
  needs local access, user interaction, unusual input, or a development context.
- **Low:** Defense-in-depth, observability, or robustness weakness with limited
  direct impact.

## Findings

### SR-01 — Organization is not scoped to the current download job

**Severity:** High  
**Category:** Data integrity, unsafe path configuration, provenance  
**Affected code:** `alac_rip/server.py:580-598`, `alac_rip/server.py:724-756`,
`alac_rip/sync.py:115-124`

The backend reads an absolute save directory from the external downloader's YAML
configuration. It checks only that the value is absolute. `SyncEngine.sync()`
then recursively selects every `.flac` and `.m4a` below that directory. The
manifest is read only after organization, so it does not constrain which files
are processed.

This means a job can organize stale media left by previous jobs and associate it
with the current playlist. More seriously, an unsafe configuration such as the
music library, the user's home directory, or `/` can cause a broad scan followed
by file moves, transcodes, tag rewrites, or deletion of files considered already
downloaded. Continuing organization after a downloader error increases exposure
to stale partial output.

#### Recommendation

1. Resolve the staging directory before starting a job.
2. Reject `/`, the user's home directory, and any staging directory equal to,
   containing, or contained by `music_dir`, `state_dir`, or the configured tool
   source directory.
3. Treat a per-job downloader manifest as the authoritative list of source files.
4. Change `SyncEngine` to receive an explicit collection of approved source paths
   rather than recursively discovering the entire staging tree.
5. Require each source to be a regular, non-symlink file whose resolved path is
   beneath the validated staging root.
6. Have the Go downloader append successful entries to an atomically maintained
   manifest so a non-zero exit still exposes recoverable files.
7. If the manifest is missing, corrupt, or inconsistent, preserve staging and
   return a recoverable error instead of organizing unknown files.

#### Acceptance criteria

- A stale audio file absent from the current manifest is never moved or linked to
  the current playlist.
- `/`, the home directory, the library, and overlapping staging/library paths are
  rejected before the downloader starts.
- Manifest paths containing `..`, paths outside staging, directories, FIFOs, and
  symlinks are rejected.
- A non-zero downloader exit still organizes every valid manifest-listed success
  and no other file.

### SR-02 — Metadata collisions can silently overwrite library tracks

**Severity:** High  
**Category:** Data loss, unsafe file replacement  
**Affected code:** `alac_rip/sync.py:60-67`, `alac_rip/sync.py:148-162`

Destination names are derived from sanitized album artist, album, track number,
and title. Multiple distinct source tracks can map to the same destination. For
example, sanitization makes `AC/DC` and `AC_DC` equivalent. Incorrect or duplicate
metadata can also produce identical destinations.

M4A conversion uses FFmpeg with `-y`, which overwrites an existing destination.
The FLAC path uses `shutil.move`, which can replace an existing file on Unix. The
database identity remains based on the source's staging-relative path, so multiple
records can end up referring to the same final path after earlier audio has been
destroyed.

Failures after conversion or movement can also leave a destination file on disk
without a corresponding committed database record.

#### Recommendation

1. Never overwrite an existing destination implicitly.
2. Transcode and tag into a unique temporary file in the destination directory.
3. Commit the file only after conversion, artwork, and tag operations succeed.
4. Use the Apple Music ID as the stable logical identity when available.
5. If an existing destination belongs to the same Apple Music ID, treat the job
   as an idempotent retry. If it belongs to a different track, retain the staged
   file and report a collision.
6. If automatic disambiguation is desired, use a deterministic suffix derived
   from the Apple Music ID rather than a timing-dependent counter.
7. Remove FFmpeg's unconditional `-y` behavior.

#### Acceptance criteria

- Two distinct tracks with colliding sanitized metadata cannot replace each
  other's audio.
- An existing untracked file at the destination is preserved.
- A conversion or tagging failure leaves neither a partial final file nor an
  incorrect database row.
- Retrying the same Apple Music track remains idempotent.

### SR-03 — Private runtime databases remain tracked in Git

**Severity:** High for publication; Medium in the current private repository  
**Category:** Privacy, source-control hygiene  
**Affected assets:** `.state/downloaded.db`, `.state/state.db`

`.gitignore` now excludes `.state/`, but both SQLite databases are already tracked
and have appeared repeatedly in repository history. Ignore rules do not affect
tracked files. The databases contain playlist metadata, timestamps, and absolute
local library paths. This conflicts with the README and security policy, which
classify runtime state as private user data.

#### Recommendation

1. Remove both databases from the Git index while preserving the user's working
   copies.
2. Add a CI check that fails if `.state/`, `*.db`, logs, configuration, keys, or
   credentials become tracked.
3. Do not publish this private repository history. Use the documented clean
   public-snapshot process, or sanitize history before any publication.
4. Treat playlist URLs and local paths already present in shared history as
   disclosed and review access accordingly.

#### Acceptance criteria

- `git ls-files .state` returns no paths.
- A clean checkout does not contain runtime databases.
- Public-snapshot validation fails if a database or `.state` entry is introduced.

### SR-04 — Apple credentials are exposed in Podman process arguments

**Severity:** High  
**Category:** Credential exposure  
**Affected code:** `alac_rip/server.py:330-348`, `tests/test_auth_contract.py:116-147`

Wrapper login constructs a Podman command containing
`-e args=-L <email>:<password>`. The complete credential string is therefore
present in the Podman process's argv and may be visible through process inspection
depending on host `/proc` policy. Secret Service protects credentials at rest but
does not mitigate this runtime command-line exposure.

The current authentication contract deliberately freezes this command shape.
Remediation must update the contract and repeat the documented authentication
verification rather than silently changing wrapper behavior.

#### Recommendation

1. Prefer changing the wrapper to accept credentials through stdin or separate
   structured inputs that are not command-line arguments.
2. As an interim measure, put the `args` value into the child environment and
   invoke Podman with `--env args` without including its value in argv.
3. Confirm how the wrapper parses spaces, colons, quotes, and option-shaped
   password content. Avoid concatenated command strings if the wrapper can accept
   distinct email and password inputs.
4. Continue redacting submitted values from all wrapper logs and errors.
5. Update the auth contract tests and manually verify login, both 2FA modes,
   restart, failure, and shutdown using synthetic fixtures and an authorized test
   account.

#### Acceptance criteria

- Neither email nor password appears in the Podman process command line.
- Wrapper logs, API errors, and diagnostic output never contain submitted values.
- Passwords containing spaces, colons, or leading dashes are handled as data.
- Existing authentication state transitions continue to pass contract tests.

### SR-05 — Last.fm API key and responses use plaintext HTTP

**Severity:** Medium  
**Category:** Transport security, response integrity  
**Affected code:** `alac_rip/lastfm_api.py:3-21`

Every Last.fm request uses `http://ws.audioscrobbler.com/2.0/` and includes the
configured API key as a query parameter. A network observer can capture the key
or modify recommendation data and external URLs. The endpoint responds over
HTTPS and should be used even though portions of Last.fm's documentation still
display the HTTP root.

#### Recommendation

- Change the API root to HTTPS.
- Set an identifiable application `User-Agent`, as requested by Last.fm.
- Reject transport downgrade redirects.
- Validate response-provided links before handing them to the Tauri opener;
  recommendation links should be HTTPS and limited to expected Last.fm hosts.

#### Acceptance criteria

- Tests assert that all Last.fm requests use HTTPS.
- Redirects to HTTP fail closed.
- Non-HTTPS or unexpected-host recommendation URLs are not opened.

References:

- <https://www.last.fm/api/intro>
- <https://www.last.fm/api/rest>

### SR-06 — Control characters can inject playlist and log lines

**Severity:** Medium  
**Category:** Injection, unsafe metadata handling  
**Affected code:** `alac_rip/organizer.py:8-18`, `alac_rip/sync.py:48-58`,
`alac_rip/server.py:570-576`

The new sanitizer correctly replaces path separators and collapses empty or
dot-only components. Embedded control characters remain valid, including newline
characters. Catalog or malformed media metadata can therefore create filenames
containing line breaks, forge additional log lines, or inject extra M3U entries
and directives. The public M3U helper flattens title and artist line breaks, but
the internally generated M3U and path lines do not receive equivalent handling.

#### Recommendation

- Replace C0/C1 controls and Unicode line separators in filesystem components.
- Normalize metadata to a documented Unicode form and impose a safe byte-length
  limit for each path component.
- Flatten CR/LF in every M3U metadata and path line.
- Convert untrusted downloader output and metadata to one-line form before
  structured log emission.
- Preserve original display metadata in the database only if output contexts
  apply their own escaping consistently.

#### Acceptance criteria

- Artist, album, title, playlist, and source names containing controls cannot
  create additional M3U or log records.
- Resulting destination components cannot be empty, `.`/`..`, or exceed the
  supported filesystem component length.

### SR-07 — Job output and child lifetime are unbounded

**Severity:** Medium  
**Category:** Availability, resource exhaustion  
**Affected code:** `alac_rip/server.py:112-128`, `alac_rip/server.py:707-722`,
`alac_rip/server.py:778-819`, `alac_rip/server.py:1428-1438`

The per-job event queue is unbounded. If the UI disconnects while a downloader
continues emitting output, memory use can grow until the job completes. Wrapper
logs are also stored in an unbounded list even though the API returns only the
last 200 entries. Downloader jobs have no inactivity watchdog, cancellation
endpoint, or guaranteed process-tree termination.

#### Recommendation

- Use a bounded event buffer; retain the on-disk log as the complete source of
  truth and collapse or drop older UI events when necessary.
- Store wrapper logs in `collections.deque(maxlen=200)`.
- Add explicit queued-job and active-job cancellation.
- Start each downloader in its own process group and terminate the complete group
  on cancellation, backend shutdown, or configurable inactivity timeout.
- Never delete staged media as part of timeout or cancellation cleanup.

#### Acceptance criteria

- Disconnecting the SSE consumer cannot cause unbounded memory growth.
- An indefinitely silent or repeating downloader can be cancelled from the UI.
- Cancellation terminates child processes but preserves recoverable media.

### SR-08 — Configuration writes are non-atomic and not permission-hardened

**Severity:** Medium  
**Category:** Local confidentiality, configuration integrity  
**Affected code:** `alac_rip/server.py:1320-1373`, `alac_rip/config.py:7-35`

Configuration is rewritten directly to its final path. A crash or write failure
can truncate the file. A newly created file receives permissions derived from the
process umask rather than an explicit private mode. Legacy secret fields omitted
from the API response can remain in the YAML and be rewritten unchanged.

#### Recommendation

- Complete migration of all credentials and tokens out of YAML.
- Write configuration through a mode-`0600` temporary file in the same directory,
  flush and `fsync` it, then atomically replace the target.
- Restrict the state/config directories to `0700` and sensitive files to `0600`.
- Maintain a last-known-good backup and validate the complete new configuration
  before replacement.

#### Acceptance criteria

- New config files are mode `0600` regardless of ordinary umask.
- Interrupted writes preserve either the old or complete new configuration.
- No Apple password, media token, or equivalent secret remains in YAML.

### SR-09 — Development and build dependencies contain known advisories

**Severity:** Medium  
**Category:** Supply chain, developer environment  
**Affected assets:** `app/package-lock.json`, CI dependency policy

`npm audit --omit=dev` reported no production-runtime advisories. A full audit of
the lockfile reported seven affected packages: four high, two moderate, and one
low. Direct or build-relevant affected packages include Vite 6.4.2, PostCSS
8.5.9, Svelte 5.55.4, and SvelteKit 2.57.1; transitive findings include
`devalue`, `nanoid`, and `cookie`.

Many reported paths have reduced reachability because this project produces a
static Linux desktop application rather than an exposed SSR service. They still
represent developer-workstation and build-pipeline risk and should block a public
release until the complete audit is clean.

#### Recommendation

1. Refresh the npm lockfile to patched compatible versions.
2. Require a clean full `npm audit`, not only a production-only audit.
3. Add Python and Rust advisory scanners and secret scanning to CI.
4. Run dependency audits on a schedule because new advisories do not require a
   repository change to become applicable.
5. Re-run Svelte checks, the production build, Rust checks, package builds, and
   smoke tests after dependency updates.

Relevant advisories include:

- Vite filesystem deny bypass: <https://github.com/advisories/GHSA-fx2h-pf6j-xcff>
- PostCSS source-map file disclosure: <https://github.com/advisories/GHSA-6g55-p6wh-862q>
- PostCSS path traversal: <https://github.com/advisories/GHSA-r28c-9q8g-f849>

### SR-10 — Partial failures are recorded as indistinguishable success

**Severity:** Low  
**Category:** Auditability, integrity signaling  
**Affected code:** `alac_rip/server.py:717-775`, `app/src/api.ts:81-90`,
`app/src/api.ts:117-128`

After the current change, a non-zero downloader exit is logged but the job emits
`done`, the playlist is marked synced, and history records `success`. The behavior
preserves the frontend's existing status-string contract, but consumers cannot
distinguish a clean run from a degraded run without opening its log.

#### Recommendation

Preserve the existing public status strings for compatibility, but add optional
structured fields such as `degraded`, `downloader_exit_code`, and
`warning_count`. Store the degraded state in sync history and render it visibly
in the UI. Do not advance a freshness indicator without showing that some
downloaded items may be missing.

#### Acceptance criteria

- A downloader error with successfully organized tracks remains recoverable and
  produces `done`, but is visibly marked degraded.
- History retains the downloader exit code and warning summary.
- A clean run remains unchanged.

### SR-11 — Path containment needs defense at the write boundary

**Severity:** Low after the current dot-segment fix  
**Category:** Defense in depth  
**Affected code:** `alac_rip/organizer.py:8-40`, `tests/test_organizer.py:18-29`

The current patch blocks names that sanitize to empty or entirely dots and fixes
the demonstrated traversal. Its regression test checks lexical containment only.
It does not verify resolved containment, symlinked ancestors, titles, control
characters, or all write targets.

#### Recommendation

- Keep the sanitizer fix.
- Add a centralized destination builder that resolves the intended path and
  verifies containment beneath the resolved `music_dir/artists` root.
- Reject existing symlink ancestors and non-regular staging sources.
- Apply the same invariant to covers, lyrics, and generated playlists.

## Review of current uncommitted changes

### Dot-segment sanitization

The change is correct for literal `.`, `..`, longer all-dot strings, and empty
values. It closes the concrete metadata traversal described in the handoff. The
test suite should be extended as described in SR-06 and SR-11 before treating
sanitization as the complete filesystem boundary.

### Continue organizing after downloader failure

The prior all-or-nothing behavior could strand hundreds of valid downloads. The
new behavior is valuable and should remain as a product requirement. Its present
implementation processes the shared staging tree without proving which files
belong to the failed job. SR-01 and SR-02 should therefore be addressed before
the change is considered release-ready.

### Download progress parsing

The parser is anchored and only reformats output for logging/UI display. It does
not create a direct execution path. Add direct tests for valid progress, unrelated
lines, malformed numbers, zero totals, and `current > total`. The UI should clamp
or ignore invalid ratios rather than trusting arbitrary downloader output.

### Missing metadata warning

The warning improves visibility but does not prevent untagged or corrupted files
from being committed to the library. Consider treating complete metadata absence
as a quarantined error instead of automatically filing it under `Unknown Artist /
Unknown Album`, especially after a downloader-reported failure.

## Existing safeguards confirmed

- The backend binds to `127.0.0.1`.
- Packaged launches use a random 256-bit capability token passed through stdin.
- Every packaged API request requires the capability header.
- CORS is limited to the Tauri webview and local Vite development origin.
- CSP restricts script/resource behavior and loopback connectivity.
- Library artwork and reveal endpoints require resolved containment and a known
  database track path.
- SQL statements use parameters for user-controlled values.
- YAML loading uses `yaml.safe_load`.
- Subprocess calls use argument arrays and do not use `shell=True`.
- Credentials persist through Secret Service or session memory; there is no
  plaintext fallback credential file.
- Tauri shell spawn permission is scoped to the packaged backend sidecar.
- Strawberry export uses parameterized SQL, a write transaction, busy handling,
  and a pre-write backup.

## Remediation roadmap

### Phase 1 — Prevent destructive or cross-job media handling

1. Implement staging-root validation and manifest-scoped inputs.
2. Reject symlinks and non-regular source files.
3. Add transactional destination writes and collision handling.
4. Add partial-failure, stale-file, unsafe-root, collision, and rollback tests.

### Phase 2 — Protect secrets and private data

1. Remove runtime databases from Git tracking and public history.
2. Remove Apple credentials from Podman argv and update the auth contract.
3. Move remaining secrets out of YAML and harden atomic permissions.
4. Switch Last.fm to HTTPS and validate opened URLs.

### Phase 3 — Improve resilience and observability

1. Bound event and wrapper-log memory.
2. Add cancellation, inactivity timeout, and process-group shutdown.
3. Add structured degraded-run history without breaking status-string
   compatibility.
4. Normalize metadata for filesystem, playlist, and log contexts.

### Phase 4 — Close supply-chain release blockers

1. Update npm dependencies until the full audit is clean.
2. Add scheduled npm, Python, Rust, and secret audits to CI.
3. Record immutable revisions, hashes, licenses, architectures, and patch status
   for the downloader, wrapper, and media tools.
4. Reproducibly build and verify the deployed Go binary before approval.

## Required regression scenarios

- Non-zero downloader exit with two manifest-listed successes and one failure.
- Non-zero exit with no manifest and preserved staging.
- Stale staging media absent from the current manifest.
- Manifest paths outside staging, containing `..`, or resolving through symlinks.
- Staging configured as `/`, home, library, state, or a parent/child overlap.
- Two distinct tracks whose metadata maps to the same destination.
- Existing untracked destination and same-ID idempotent retry.
- Conversion, artwork, tag, and database failures with rollback assertions.
- Metadata containing CR, LF, C0/C1 controls, Unicode line separators, all dots,
  forbidden separators, and overlong components.
- Disconnected event consumer during sustained downloader output.
- Job cancellation and inactivity timeout with descendant processes.
- Credentials containing spaces, colons, quotes, and leading dashes without argv
  disclosure.
- Atomic config interruption and file-mode checks under a permissive umask.
- Last.fm HTTPS enforcement and rejection of downgrade/unexpected-host URLs.
- Progress parsing for valid, malformed, zero-total, and out-of-range lines.

## Verification performed

- `.venv/bin/pytest -q`: **195 passed**.
- `npm run check`: **0 errors and 0 warnings**.
- `git diff --check`: passed.
- `npm audit --omit=dev --json`: no production-runtime advisories.
- Full `npm audit --json`: seven affected dependency entries—four high, two
  moderate, one low.
- Ruff was not installed in the active virtual environment and was not run.
- No repository files were changed during the audit itself.

## Release decision

The reviewed repository should not be treated as security-release-ready until
SR-01 through SR-04 are resolved and the runtime databases are absent from any
published source history. The existing capability-token boundary and path
sanitization improvements provide a strong base, but current-job provenance,
non-overwriting media installation, credential process handling, and external
dependency provenance remain mandatory release gates.
