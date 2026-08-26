#!/bin/sh
set -e

if [ -d /app/rootfs/dev ]; then
    rm -f /app/rootfs/dev/urandom
    touch /app/rootfs/dev/urandom
    mount --bind /dev/urandom /app/rootfs/dev/urandom 2>/dev/null || true
fi

exec "$@"
