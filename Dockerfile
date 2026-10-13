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
FROM docker.io/library/ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    ffmpeg \
    flac \
    gpac \
    ca-certificates \
    curl \
    gosu \
    procps \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install python dependencies
COPY pyproject.toml .
RUN pip3 install --no-cache-dir --break-system-packages .

# Copy application source
COPY alac_rip/ ./alac_rip/
COPY vendor/apple-music-downloader/ ./apple-music-downloader/

# Copy built frontend SPA from Stage 1
COPY --from=frontend-builder /app/build ./web

# Copy compiled Go downloader binary from Stage 2
COPY --from=go-builder /bin/amd-main /usr/local/bin/amd-main
RUN chmod +x /usr/local/bin/amd-main

# Setup native decryption wrapper and rootfs (uses local files if present, or downloads upstream release)
COPY vendor/wrapper/ /tmp/wrapper-src/
RUN if [ -f /tmp/wrapper-src/wrapper ] && [ -d /tmp/wrapper-src/rootfs/system ]; then \
        echo "Using local decryption wrapper assets..." && \
        mv /tmp/wrapper-src/wrapper /app/wrapper && \
        mv /tmp/wrapper-src/rootfs /app/rootfs; \
    else \
        echo "Downloading decryption wrapper from upstream release..." && \
        mkdir -p /tmp/wrap-extract /app && \
        curl -sSL -o /tmp/wrapper.tar.gz "https://github.com/zhaarey/wrapper/releases/download/linux/wrapper.linux.x86_64.tar.gz" && \
        tar -xzf /tmp/wrapper.tar.gz -C /tmp/wrap-extract && \
        mv /tmp/wrap-extract/wrapper /app/wrapper && \
        mv /tmp/wrap-extract/rootfs /app/rootfs && \
        rm -rf /tmp/wrap-extract /tmp/wrapper.tar.gz; \
    fi && \
    chmod +x /app/wrapper && \
    mkdir -p /app/rootfs/dev && \
    rm -rf /tmp/wrapper-src

COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Configuration defaults for Docker container
ENV PIES_CONFIG_PATH=/config/config.yaml \
    PIES_STATE_DIR=/config \
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
CMD ["python3", "-m", "alac_rip.server"]
