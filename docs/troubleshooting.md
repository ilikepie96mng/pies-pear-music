# Troubleshooting

Pies Pear Music is not publicly released yet. These notes describe the
supported desktop/manual-sync direction for version 0.1; they do not make the
legacy installer, timer, or command-line workflow supported.

## Start with Diagnostics

Open **Diagnostics** in the application. It checks Podman, Go, FFmpeg, MP4Box,
the optional `mp4decrypt` tool, configured data directories, and the expected
downloader and wrapper source directories. Details intentionally report status
rather than absolute local paths.

## Missing tools or a GUI PATH problem

Install Podman, Go, FFmpeg, and MP4Box using your distribution's package
manager, then fully restart the desktop application. A GUI launched from an
application menu may have a different `PATH` than a terminal. Check the exact
GUI-visible status in Diagnostics instead of assuming terminal results apply.

`mp4decrypt` is optional and is reported as a warning when absent. Do not use
the application to download third-party executables; install only a reviewed,
compatible external tool yourself.

## Wrapper, login, or 2FA problems

Confirm that Diagnostics reports both the downloader and wrapper source
directories. If the wrapper stops, use its displayed error and restart the app
before retrying. Apple account changes, expired sessions, or a 2FA request can
require a new interactive login. Do not paste credentials, session values,
playlist URLs, or raw wrapper output into a bug report.

## Missing media tools or downloader failures

Verify the selected external checkout contains both `apple-music-downloader/`
and `wrapper/`. Ensure the downloader's own configuration has writable output
locations and that its supported external media tools are installed. Preserve
the local session log for your own review, but redact paths, URLs, tokens, and
account identifiers before sharing any excerpt.

## Stuck or failed syncs

Only one sync should actively run at a time. Wait for the current job to finish
or restart the app if the backend connection is lost. A failed job records a
short error in sync history; it does not make the legacy scheduler supported.
If a retry fails consistently, collect the diagnostic statuses and a redacted
error summary.

## Strawberry database locks

Close Strawberry before exporting a playlist. Pies Pear Music checks for a
running Strawberry process, obtains a bounded SQLite lock, and creates a
timestamped database backup only after it acquires the write reservation. If
the database remains busy, close other Strawberry instances and retry. Do not
delete the backup until you have confirmed the export result.

## Other music players and reinstalling

Use **M3U** on a playlist to save a portable playlist file, or **Player** to
save it and open it with the system default application for M3U files. This
does not modify another player's database. Package removal leaves downloaded
music, configuration, state, logs, and credentials intact, so reinstalling is
safe by default.

## AppImage issues

Some Linux systems require FUSE support to launch AppImages. If an AppImage is
mounted with `noexec`, move it to an executable user-owned directory and mark
it executable. The release AppImage must be built on the Ubuntu 22.04 baseline;
locally built Fedora AppImages are not release evidence.

## Safe local-state reset

State, logs, and downloaded media are user data. Back up the configured state
directory before changing anything. To reset only application history, quit the
application, make a dated copy of the configured state directory, then remove
or rename the copied database only after confirming the backup contains the
expected playlists and history. Do not commit state files, logs, or diagnostic
archives to source control.

## Reporting a problem

Report the application version, distribution, package type, the Diagnostics
pass/fail labels, and a redacted error summary. Never include credentials,
tokens, full playlist URLs, account identifiers, absolute local paths, or raw
databases.
