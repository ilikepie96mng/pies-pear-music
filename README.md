# Pies Pear Music 🍐🎵

> **The Self-Hosted & Local-First Audiophile Music Archival Hub**  
> Bit-perfect Apple Lossless (ALAC/FLAC) syncing, universal cross-service playlist matching, high-performance virtual library (12k+ tracks @ 60fps), automated Jellyfin & Navidrome streaming server webhooks, duplicate sweep engine, and Gemini AI music curation.

[![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20Docker%20%7C%20Windows-blue.svg)](#platform-support)
[![Frontend](https://img.shields.io/badge/Frontend-Svelte%205%20%2B%20TailwindCSS-orange.svg)](app/)
[![Backend](https://img.shields.io/badge/Backend-FastAPI%20%7C%20Python%203.12-green.svg)](alac_rip/)
[![Audio](https://img.shields.io/badge/Audio-ALAC%20%7C%20FLAC%20Lossless-purple.svg)](#key-features)
[![Tests](https://img.shields.io/badge/Tests-334%20Passing-brightgreen.svg)](tests/)
[![License](https://img.shields.io/badge/License-GPL--3.0-lightgrey.svg)](LICENSE)

---

## ✨ Key Features

* 💎 **Bit-Perfect Lossless ALAC/FLAC**: Archive albums and playlists in pristine uncompressed high-resolution audio (up to 24-bit / 192kHz).
* ⚡ **High-Performance Virtual Library**: Seamlessly browse and search 12,000+ track libraries at 60fps with lightweight virtual DOM windowing and low memory consumption.
* 🔍 **Intelligent Duplicate Scanner & Storage Sweep**: Automated library audit that detects cross-release duplicates (Single vs Album), collision files (`_coll_*.flac`), safely removes duplicates from disk, and auto-remaps playlist references without broken links.
* 🎧 **Embedded Mini-Player & Waveforms**: Persistent auditioning player with real-time waveform peak scrubbing, volume memory, and OS Media Session keyboard controls.
* 🎤 **Synchronized Karaoke Lyrics**: Timed `.lrc` lyrics with automatic fallback to [LRCLIB](https://lrclib.net) saved alongside your tracks.
* 🔄 **Universal Playlist Importer (Match-and-Rip)**: Ingest playlist URLs from **Spotify, Tidal, Qobuz, Apple Music, CSV, and M3U8** — resolves tracks via ISRC and fetches lossless audio.
* 🤖 **Gemini AI Music Intelligence**: Plug in a Gemini API key for library taste profiling, natural-language smart playlist generation (*e.g. "Create a 25-track late-night synthwave mix"*), and 1-click lossless ripping.
* 📡 **Media Server Webhooks**: Automatic background notifications to **Jellyfin** (`/Library/Refresh`) and **Navidrome / Subsonic** (`/rest/startScan.view`) whenever new music arrives.
* 🔐 **Web Password Authentication**: Optional password protection for public LANs or reverse-proxy deployments.
* 📱 **DAP & Strawberry Export**: Direct database sync to Strawberry Music Player or transcode to Opus/MP3 for portable microSD DAPs.

---

## 🐳 Quickstart with Docker Compose

The easiest way to run Pies Pear Music is via Docker Compose / Dockge:

```yaml
services:
  pies-pear-music:
    image: ghcr.io/ilikepie96mng/pies-pear-music:latest
    container_name: pies-pear-music
    restart: unless-stopped
    ports:
      - "10025:10025"
    volumes:
      # 1. State & Database: where SQLite database (downloaded.db) and config.yaml live
      - ./config:/config
      # 2. Music Library: where ALAC/FLAC files and playlists/ folder are stored
      - /path/to/your/music:/music
      # 3. Fast Staging Buffer: temporary directory for downloading and tag processing
      - /tmp/pies-staging:/staging
    cap_add:
      - SYS_ADMIN
      - SYS_CHROOT
    security_opt:
      - seccomp:unconfined
    environment:
      - PIES_CONFIG_PATH=/config/config.yaml
      - PIES_STATE_DIR=/config
      - PIES_MUSIC_DIR=/music
      - PIES_STAGING_DIR=/staging
      - PORT=10025
      - HOST=0.0.0.0
      # Optional: set a password to protect the web dashboard
      # - PIES_AUTH_PASSWORD=your_secure_password_here
```

Start the container:
```bash
docker compose up -d
```
Open **`http://localhost:10025`** (or your server's IP) in your browser.

---

## 📁 Directory Mounts Explained

| Volume | Container Path | Purpose |
| :--- | :--- | :--- |
| **Config** | `/config` | Stores `config.yaml`, SQLite library state (`downloaded.db`), and persistent secrets. |
| **Music** | `/music` | Destination directory where FLAC/ALAC songs, cover art, and `playlists/*.m3u8` files are organized. |
| **Staging** | `/staging` | Fast temporary buffer used during download, format conversion, and tag embedding before atomic commit. |

---

## 🔐 Apple Music DRM & FairPlay Key Expiration

* **Why Login is Needed**: Apple Music streams are FairPlay DRM encrypted. The pre-bundled decryption daemon authenticates with Apple to acquire temporary Content Key Contexts (CKCs) for bit-perfect audio extraction.
* **FairPlay Key Expiration (`-42786`)**: Apple enforces a 24–72h session key expiration. When session keys expire, simply click the **`🔄 Reconnect`** button on the Dashboard to renew DRM keys with 1 click using saved credentials.

---

## 🖥️ Optional: Linux Desktop App (Tauri)

If you prefer running a native desktop window on your Linux workstation instead of Docker:

```bash
# Clone the repository
git clone https://github.com/ilikepie96mng/pies-pear-music.git
cd pies-pear-music

# Install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[test,package]"

cd app
npm install
npm run tauri dev
```

---

## 💻 Running from Source (Development)

```bash
# 1. Run the backend server in headless mode
python3 -m alac_rip.server --headless

# 2. Run the frontend Vite dev server (in app/)
cd app
npm run dev
```

---

---

## 💖 Credits & Upstream Projects

Pies Pear Music stands on the shoulders of incredible open-source tools and community research:

* **[`lalit22km/alac-rip`](https://github.com/lalit22km/alac-rip)** — Initial ALAC streaming protocol research, daemon concepts, and containerization architecture.
* **[`zhaarey/apple-music-downloader`](https://github.com/zhaarey/apple-music-downloader)** — Downloader utilities, API structures, and Android translation runtime research.
* **[Strawberry Music Player](https://www.strawberrymusicplayer.org/)** — High-fidelity audio player inspiration.
* **[Mutagen](https://github.com/quodlibet/mutagen)** — Audio tag manipulation and FLAC/ID3/MP4 metadata embedding.
* **[FFmpeg](https://ffmpeg.org/)** — Universal audio transcoding and waveform downsampling engine.
* **[FastAPI](https://fastapi.tiangolo.com/)** & **[SvelteKit](https://kit.svelte.dev/)** — Modern asynchronous API backend and reactive web interface.

---

## ⚖️ Legal Disclaimer

Pies Pear Music is intended solely for personal backup and archival of music you are legally authorized to access. This software does not bypass DRM for commercial distribution. Please respect artist rights and copyright laws.
