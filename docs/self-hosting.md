# Pies Pear Music — Complete Setup & Configuration Guide (Desktop vs Server)

Pies Pear Music can run in two modes:
1. **Desktop App Mode**: Native Linux application (Tauri + Svelte) utilizing local directories and local Podman.
2. **Headless Server Mode**: Standalone Docker container with web SPA interface on port `10025` for Unraid, TrueNAS, and Docker / Dockge hosts.

---

## ⚙️ Settings Reference Comparison

| Setting | Desktop App Mode | Docker / Server Mode | Purpose |
| :--- | :--- | :--- | :--- |
| **Music Directory** | Local folder or SMB mount (e.g. `/run/user/1000/kio-fuse.../music`) | `/music` (Mounts your host storage pool) | Root folder where all FLAC tracks, album covers (`cover.jpg`), and `.m3u8` playlists are stored. |
| **State Directory** | `~/.local/share/pies-alac-rip` | `/config/.state` | Location of the SQLite database (`downloaded.db`) tracking all downloaded songs, artwork cache, and sync runs. |
| **ALAC-RIP Directory** | Path to your `alac-rip` source folder (contains `wrapper/` & `apple-music-downloader/`) | `/app` (Pre-embedded inside container) | Location of decryption wrapper and downloader tools. |
| **Apple Music Account** | Log in under Settings -> `Login to Apple Music` | Log in under Settings -> `Login to Apple Music` | Authenticates and persists 2FA session token in `.credentials` for bit-perfect ALAC downloads. |
| **API Token** | Not required on desktop | Optional `PIES_API_TOKEN` environment variable or saved in Settings | Protects API endpoints when exposed across LAN or behind reverse proxy. |
| **Google Gemini API Key** | Optional in Settings | Optional in Settings | Enables Gemini AI intelligent playlist curation and studio version discovery. |
| **Last.fm Credentials** | Optional in Settings | Optional in Settings | Provides artist recommendations, metadata scrobbling, and music intelligence. |
| **Navidrome / Jellyfin** | Optional in Settings | Optional in Settings | Automatically triggers media server library scans when new tracks are downloaded. |
| **Discord / Telegram Webhooks** | Optional in Settings | Optional in Settings | Dispatches push notifications when downloads and scheduled background syncs complete. |

---

## 🐳 Quick Start with Dockge / Docker Compose

### 1. `compose.yaml`:
```yaml
services:
  pies-pear-music:
    build: /home/msadmin/pies-alac-rip-tool
    container_name: pies-pear-music
    restart: unless-stopped
    ports:
      - "10025:10025"
    volumes:
      - "/tank/media/music/Apple Music/.state:/config"
      - "/tank/media/music/Apple Music:/music"
      - /tmp/pies-staging:/staging
    environment:
      - PORT=10025
      - HOST=0.0.0.0
```

### 2. Deploy:
Click **Deploy** in Dockge or run `docker compose up -d`.

### 3. Open Web UI:
Navigate to `http://<server-ip>:10025` in any browser on your home network.

---

## 🔑 Initial Setup Steps in Web UI
1. Go to **Settings**.
2. Click **⚡ Set Container Defaults** to confirm `/music`, `/config/.state`, and `/app` are set.
3. Click **Login to Apple Music** and enter your Apple ID credentials & 2FA code.
4. (Optional) Connect Navidrome / Jellyfin and webhook notifications.
