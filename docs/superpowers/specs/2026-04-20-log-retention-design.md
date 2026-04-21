# Log Retention — Design Spec

**Date:** 2026-04-20

---

## Goal

Automatically delete sync log files older than a configurable number of days so the `.state/logs/` directory does not grow unbounded.

---

## Design

Log cleanup runs at the start of each `_run_job` call in `server.py`, immediately after `logs_dir.mkdir(parents=True, exist_ok=True)`. It deletes any `*.log` files whose `mtime` is older than `log_retention_days * 86400` seconds. Failures are silently ignored — a log that cannot be deleted is not worth failing a sync over.

---

## Config Field

Added to `alac_rip/config.py`:

```python
log_retention_days: int = 2
```

Read in `load_config()`:

```python
log_retention_days=int(data.get("log_retention_days", 2)),
```

Documented in `config.yaml.example`:

```yaml
# Number of days to keep sync logs. Logs older than this are deleted at the
# start of each sync. Set to 0 to disable cleanup.
log_retention_days: 2
```

---

## Cleanup Logic (`server.py` — `_run_job`)

Inserted immediately after `logs_dir.mkdir(parents=True, exist_ok=True)`:

```python
if cfg.log_retention_days > 0:
    cutoff = datetime.now().timestamp() - cfg.log_retention_days * 86400
    for _log in logs_dir.glob("*.log"):
        try:
            if _log.stat().st_mtime < cutoff:
                _log.unlink()
        except OSError:
            pass
```

`datetime` is already imported in `server.py`. No new imports required.

---

## API Patch Support

`ConfigUpdate` (the Pydantic model for `PATCH /config`) gains:

```python
log_retention_days: int | None = None
```

This allows the value to be updated at runtime via the existing config endpoint without restarting the server.

---

## Backward Compatibility

- Existing `config.yaml` files without the field default to `2` days — same behaviour as the manual cleanup already performed.
- Setting `log_retention_days: 0` disables cleanup entirely.

---

## Files Modified

| File | Change |
|------|--------|
| `alac_rip/config.py` | Add `log_retention_days: int = 2` field and loader |
| `alac_rip/server.py` | Add cleanup block after `logs_dir.mkdir()`; add `log_retention_days` to `ConfigUpdate` |
| `config.yaml.example` | Document the new field |
| `tests/test_log_retention.py` | Create — unit tests for cleanup logic |
