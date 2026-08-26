# Self-Hosting Pies Pear Music with Docker

Pies Pear Music provides an all-in-one headless Docker container that runs the web interface, the Apple Music metadata/lossless ripping engine, ALAC decryption daemon, and automated media server syncs (Navidrome & Jellyfin).

---

## 🚀 Quick Start with Docker Compose

### 1. Create a `docker-compose.yml` file:

```yaml
services:
  pies-pear-music:
    image: ghcr.io/ilikepie96mng/pies-pear-music:latest
    container_name: pies-pear-music
    restart: unless-stopped
    ports:
      - "10025:10025"
    volumes:
      - ./config:/config
      - /path/to/your/music/library:/music
      - /tmp/pies-staging:/staging
    environment:
      - PORT=10025
      - HOST=0.0.0.0
```

### 2. Start the container:
```bash
docker compose up -d
```

### 3. Open the Web UI:
Navigate to `http://<your-server-ip>:10025` in any web browser on your local network.

---

## 📁 Volume Mounts Explained

| Container Path | Host Path Example | Description |
| :--- | :--- | :--- |
| `/config` | `./config` or `/mnt/user/appdata/pies-pear-music` | Stores `config.yaml`, `.state/downloaded.db`, credentials, and session logs. |
| `/music` | `/mnt/tank/music/Apple Music` | The root destination where all organized FLAC audio files, album covers (`cover.jpg`), and `.m3u8` playlists are saved. |
| `/staging` | `/tmp/pies-staging` | High-speed temporary scratch space for downloading streams before tagging and organizing. |

---

## 🔒 Optional API Token Authentication

If exposing Pies Pear Music across a reverse proxy (Caddy, Nginx Proxy Manager, Traefik) or LAN, you can enable API token protection:

```yaml
    environment:
      - PIES_API_TOKEN=your-super-secret-token-here
```
When enabled, requests require the `X-Pies-Api-Token` header, `Authorization: Bearer <token>`, or you can save the token directly in the Web UI Settings tab.

---

## 🔄 Media Server Integrations

In the Web UI under **Settings**:
* **Navidrome / Subsonic**: Configure URL (`http://192.168.0.250:4533`), username, and token for automatic library scans on download completion.
* **Jellyfin**: Configure server URL (`http://192.168.0.250:8096`) and API key.
* **Discord / Telegram / Gotify**: Add webhook URLs to receive instant notifications when batch downloads and scheduled syncs finish.
