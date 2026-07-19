# Pies Pear Music desktop frontend

This directory contains the Svelte 5 interface and Tauri 2 desktop shell for
Pies Pear Music. It is not an independent web application: at runtime the
Tauri shell starts the bundled Python sidecar and gives the frontend an
authenticated loopback connection.

Run frontend checks from this directory:

```bash
npm ci
npm run check
npm run build
npm run tauri dev
```

See the root [README](../README.md), [dependency reference](../docs/dependencies.md),
and [development guide](../docs/development.md) for the complete toolchain and
Linux system packages.
