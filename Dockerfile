# ── Stage 1: Build Frontend SPA ──────────────────────────────────────────────
FROM docker.io/library/node:22-alpine AS frontend-builder
WORKDIR /app

COPY app/package.json app/package-lock.json ./
RUN npm ci

COPY app/ ./
RUN npm run build

# ── Stage 2: Build Apple Music Downloader (Go) ────────────────────────────────
FROM docker.io/library/golang:1.24-alpine AS go-builder
WORKDIR /src

COPY vendor/apple-music-downloader/ ./
RUN go build -ldflags="-s -w" -o /bin/amd-main main.go

# ── Stage 3: Backend Runtime ──────────────────────────────────────────────────
FROM docker.io/library/python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    flac \
    ca-certificates \
    curl \
    gosu \
    procps \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install python dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Copy application source
COPY alac_rip/ ./alac_rip/

# Copy built frontend SPA from Stage 1
COPY --from=frontend-builder /app/build ./web

# Copy compiled Go downloader binary from Stage 2
COPY --from=go-builder /bin/amd-main /usr/local/bin/amd-main
RUN chmod +x /usr/local/bin/amd-main

# Copy native decryption wrapper and rootfs
COPY vendor/wrapper/wrapper /app/wrapper
COPY vendor/wrapper/rootfs /app/rootfs
RUN chmod +x /app/wrapper && \
    mkdir -p /app/rootfs/dev

COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Configuration defaults for Docker container
ENV PIES_CONFIG_PATH=/config/config.yaml \
    PIES_STATE_DIR=/config/.state \
    PIES_MUSIC_DIR=/music \
    PIES_WEB_DIR=/app/web \
    PIES_HEADLESS=1 \
    PIES_NATIVE_WRAPPER=1 \
    HOST=0.0.0.0 \
    PORT=10025 \
    PYTHONUNBUFFERED=1

EXPOSE 10025

VOLUME ["/config", "/music", "/staging"]

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python", "-m", "alac_rip.server"]
