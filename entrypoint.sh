#!/bin/sh
set -e

if [ -d /app/rootfs/dev ]; then
    rm -f /app/rootfs/dev/urandom
    mknod /app/rootfs/dev/urandom c 1 9 2>/dev/null || mount --bind /dev/urandom /app/rootfs/dev/urandom 2>/dev/null || true
    chmod 666 /app/rootfs/dev/urandom 2>/dev/null || true
fi

exec "$@"
