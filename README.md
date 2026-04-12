# pies-alac-rip-tool

Download Apple Music lossless (ALAC) files on Linux, organized for Strawberry.

Built on top of [zhaarey's apple-music-downloader](https://github.com/zhaarey/apple-music-downloader).

## Requirements

- Bazzite / Fedora Linux
- [Homebrew](https://brew.sh) (`brew --version` to check)
- Apple Music subscription
- A browser to grab your `media-user-token`

## Install

```bash
git clone git@github.com:ilikepie96mng/pies-alac-rip-tool.git
cd pies-alac-rip-tool
bash install.sh
```

## First-Time Setup

1. Open Apple Music in your browser
2. Open DevTools (F12) → Application → Storage → Cookies
3. Copy the value of `media-user-token`
4. Edit `~/.config/pies-alac-rip/config.yaml` — paste the token as `media_user_token`
5. Also paste it into `~/.local/share/pies-alac-rip/apple-music-downloader/config.yaml` as `media-user-token`

> **Note:** This token is a session credential — it expires periodically. If downloads stop authenticating, re-fetch it from DevTools and update both config files.

## Usage

```bash
# Add a playlist to track
music-sync add "https://music.apple.com/your/playlist/url" --name "My Mega Playlist"

# Sync all tracked playlists (download new tracks only)
music-sync sync

# Sync a specific playlist
music-sync sync "My Mega Playlist"

# Check status
music-sync status

# Uninstall everything
music-sync clean
```

## Scheduling

A systemd user timer runs `music-sync sync` daily at 03:00 automatically (installed by `install.sh`).

```bash
# Check timer status
systemctl --user status pies-alac-rip.timer

# Run manually right now
systemctl --user start pies-alac-rip.service
```

## Library Structure

Files are organized for Strawberry at `~/Music/Apple Music/`:

```
~/Music/Apple Music/
└── Artist Name/
    └── Album Name/
        ├── 01 - Track Title.m4a
        ├── 02 - Track Title.m4a
        └── cover.jpg
```

Point Strawberry at `~/Music/Apple Music` to scan your library.

## State Backup

After each sync, the playlist state (what's downloaded) is committed and pushed to your private GitHub repo. This means you can reinstall from scratch and resume without re-downloading everything.

## Running Tests

```bash
cd pies-alac-rip-tool
PATH="/home/linuxbrew/.linuxbrew/bin:$PATH" .venv/bin/pytest tests/ -v
```
