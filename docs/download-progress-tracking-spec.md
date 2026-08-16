# Spec: Track-count progress during the downloading phase

## Problem

During the **organizing** phase, the UI (`app/src/lib/SyncProgress.svelte`) already shows a
"X / Y new" counter and progress bar, because `alac_rip/sync.py`'s `SyncEngine.sync()` emits
log lines prefixed `[i/total]` (e.g. `[938/938] added: ...`), and the frontend already parses
that exact prefix:

```ts
// SyncProgress.svelte:71-77
function parseProgress(text: string) {
  const m = text.match(/^\[(\d+)\/(\d+)\]/);
  if (m) {
    progressCurrent = parseInt(m[1]);
    progressTotal = parseInt(m[2]);
  }
}
```

and renders it whenever `phase === "downloading" || phase === "organizing"`
(`SyncProgress.svelte:257`) — the downloading-phase branch is already wired up in the UI,
it's just never fed, because during the **downloading** phase the raw lines streamed from
the Go binary (`apple-music-downloader`) never match that `[i/total]` shape. Its lines look
like:

```
Track 334 of 943: music-videos
Queue 1 of 1: Playlist
=======  [✔ ] Completed: 942/943  |  [⚠ ] Warnings: 0  |  [✖ ] Errors: 1  =======
```

So today, during downloading, the user only sees per-file byte progress
(`Downloading... 56% (80/142 MB, 109 MB/s)`), never "X of Y songs" — which is what prompted
this request.

## Fix

No frontend changes are required — the parsing and rendering already exist. The only change
needed is in `alac_rip/server.py`, in the stdout-reading loop for the downloading phase
(`server.py:706-709`):

```python
for line in iter(proc.stdout.readline, ""):
    line = line.strip()
    if line:
        emit_log("downloading", line)
```

Add a regex match for the Go binary's `Track N of Y:` line and reformat it (or emit an
additional companion line) into the `[N/Y]` shape the frontend already parses, e.g.:

```python
import re

_TRACK_PROGRESS_RE = re.compile(r"^Track\s+(\d+)\s+of\s+(\d+):\s*(.*)$")

for line in iter(proc.stdout.readline, ""):
    line = line.strip()
    if line:
        m = _TRACK_PROGRESS_RE.match(line)
        if m:
            current, total, rest = m.groups()
            emit_log("downloading", f"[{current}/{total}] {rest}".rstrip())
        else:
            emit_log("downloading", line)
```

This preserves the existing per-line log display (still one line per event, no duplication)
while making the downloading phase's progress bar/counter populate exactly like the
organizing phase's already does.

## Edge cases / things to verify

- **Regex specificity**: only match the Go binary's *per-track* progress line
  (`Track N of Y:`), not the separate outer `Queue N of Y: Playlist` line (used when multiple
  album/playlist URLs are passed to the binary at once) — these have different denominators
  and would corrupt the counter if conflated. The regex above already anchors on the literal
  word `Track`, which is distinct from `Queue`.
- **No reset between phases**: `progressCurrent`/`progressTotal` in `SyncProgress.svelte` are
  never explicitly reset between downloading → organizing. This is fine — the next matching
  `[i/total]` line from either phase simply overwrites the previous values, so the counter
  will naturally jump from e.g. "5/943" (downloading) to "938/938" (organizing) without any
  extra code.
- **Skipped tracks still counted**: the Go binary's `Track N of Y` counter includes tracks
  it skips (e.g. "already owned" via `--skip-ids-file`), so `N` still climbs steadily even
  when nothing is actually being downloaded for that track. This matches the existing
  organizing-phase behavior (which also counts skips in its `[i/total]`), so it's consistent,
  not a regression.
- **MV/album/station variants**: `ripAlbum`, `ripPlaylist`, and `ripStation` in the Go binary
  all use the same `Track %d of %d:` format (confirmed via `grep -n "Track.*of.*:"` pattern
  usage across `main.go`) — verify this holds for all three job types before shipping, since
  this repo can invoke any of them depending on the input URL type.

## Testing

1. Kick off a real download job with several tracks (or use the currently in-progress job
   once it's done).
2. Confirm the SSE stream (`GET` job event endpoint) emits `[N/Y]` messages during the
   downloading phase.
3. Confirm `SyncProgress.svelte`'s progress bar and "X / Y new" label populate during
   downloading, not just organizing.
4. Confirm the raw log panel still shows one readable line per track (no duplicate/garbled
   lines from the reformat).
