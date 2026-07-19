# Manual Desktop Smoke Test

Run this on a clean user account before release, first on Ubuntu 22.04 and
then on the current Fedora and Bazzite targets. Do not use production Apple
credentials or a large playlist.

1. Install the package and confirm **Pies Pear Music** appears in the desktop
   application launcher under Audio/Video or Music.
2. Launch it from the application menu, not a terminal. Confirm Diagnostics
   reports actionable results for missing external tools.
3. Complete the setup wizard with a new music directory and state directory;
   restart the application and confirm the choices remain available.
4. Log in with an authorized non-production account, complete 2FA if prompted,
   then restart and verify the intended Secret Service/session-only behavior.
5. Add a small authorized playlist, run one manual sync, and check the music
   and state remain after an application restart.
6. Export an M3U to a chosen location, then use **Player** and confirm the
   desktop default application receives that playlist.
7. Export a listening profile and confirm it contains aggregate artists/albums
   but no paths, URLs, tokens, credentials, or downloaded media.
8. Hide and restore a recommendation; confirm the change survives restart.
9. Uninstall the package without deleting user data, reinstall it, and confirm
   the configuration, state, and downloaded music are retained.

Record the distribution, package type, version, and every failure with a
redacted summary. Never attach credentials, media-user tokens, full playlist
URLs, absolute paths, or runtime databases to a report.
