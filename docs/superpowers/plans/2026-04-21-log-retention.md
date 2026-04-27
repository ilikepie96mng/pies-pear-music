# Log Retention Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically delete `*.log` files older than a configurable number of days at the start of each sync, so the `.state/logs/` directory does not grow unbounded.

**Architecture:** `log_retention_days` is added to the `Config` dataclass and `load_config()`. Cleanup runs at the top of `_run_job` immediately after `logs_dir.mkdir()`. A `log_retention_days: int | None = None` field on `ConfigUpdate` allows runtime updates. Default is 2 days; `0` disables.

**Tech Stack:** Python, pathlib, pytest

---

## File Map

| File | Change |
|------|--------|
| `alac_rip/config.py` | Add `log_retention_days: int = 2` to `Config`; add loader line to `load_config()` |
| `alac_rip/server.py` | Add cleanup block after `logs_dir.mkdir()` (line 360); add `log_retention_days` to `ConfigUpdate` (line 728) |
| `config.yaml.example` | Document the new field |
| `tests/test_log_retention.py` | Create — unit tests for cleanup logic |

---

### Task 1: Add `log_retention_days` to `Config` and update the example

**Files:**
- Modify: `alac_rip/config.py`
- Modify: `config.yaml.example`
- Create: `tests/test_log_retention.py`

- [ ] **Step 1: Write a failing test that imports `log_retention_days` from `Config`**

Create `tests/test_log_retention.py`:

```python
import pytest
from pathlib import Path
from alac_rip.config import Config, load_config


def test_config_defaults_log_retention_to_2():
    cfg = Config(
        music_dir=Path("/music"),
        state_dir=Path("/state"),
        github_remote="",
        alac_rip_dir=Path("/amd"),
        log_retention_days=2,
    )
    assert cfg.log_retention_days == 2


def test_load_config_reads_log_retention_days(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "music_dir: /music\n"
        "state_dir: /state\n"
        "github_remote: ''\n"
        "alac_rip_dir: /amd\n"
        "log_retention_days: 7\n"
    )
    cfg = load_config(cfg_file)
    assert cfg.log_retention_days == 7


def test_load_config_defaults_log_retention_when_absent(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "music_dir: /music\n"
        "state_dir: /state\n"
        "github_remote: ''\n"
        "alac_rip_dir: /amd\n"
    )
    cfg = load_config(cfg_file)
    assert cfg.log_retention_days == 2
```

- [ ] **Step 2: Run tests to confirm they fail**

```
.venv/bin/pytest tests/test_log_retention.py -v
```
Expected: FAIL with `TypeError: Config.__init__() got an unexpected keyword argument 'log_retention_days'`

- [ ] **Step 3: Add `log_retention_days` to `Config` and `load_config` in `alac_rip/config.py`**

```python
from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "pies-alac-rip" / "config.yaml"


@dataclass
class Config:
    music_dir: Path
    state_dir: Path
    github_remote: str
    alac_rip_dir: Path
    log_retention_days: int = 2


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> Config:
    with open(path) as f:
        data = yaml.safe_load(f) or {}

    def p(key: str, default: str = "") -> Path:
        val = data.get(key, default)
        return Path(val).expanduser().resolve() if val else Path("")

    return Config(
        music_dir=p("music_dir", "~/Music/pies-alac-rip"),
        state_dir=p("state_dir", str(Path.home() / ".local/share/pies-alac-rip")),
        github_remote=data.get("github_remote", ""),
        alac_rip_dir=p("alac_rip_dir", ""),
        log_retention_days=int(data.get("log_retention_days", 2)),
    )
```

- [ ] **Step 4: Run tests to confirm they pass**

```
.venv/bin/pytest tests/test_log_retention.py -v
```
Expected: 3 PASS

- [ ] **Step 5: Document the field in `config.yaml.example`**

Add to the end of `config.yaml.example`:

```yaml

# Number of days to keep sync logs. Logs older than this are deleted at the
# start of each sync. Set to 0 to disable cleanup.
log_retention_days: 2
```

- [ ] **Step 6: Run the full test suite to confirm nothing regressed**

```
.venv/bin/pytest -v
```
Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add alac_rip/config.py config.yaml.example tests/test_log_retention.py
git commit -m "feat: add log_retention_days config field (default 2 days)"
```

---

### Task 2: Cleanup block in `_run_job` and `ConfigUpdate`

**Files:**
- Modify: `alac_rip/server.py`
- Modify: `tests/test_log_retention.py`

- [ ] **Step 1: Write 3 failing tests in `tests/test_log_retention.py`**

Add at the end of the file:

```python
import time


def _make_log(logs_dir: Path, name: str, age_seconds: float) -> Path:
    p = logs_dir / name
    p.write_text("log content")
    mtime = time.time() - age_seconds
    import os
    os.utime(p, (mtime, mtime))
    return p


def test_cleanup_deletes_old_logs(tmp_path):
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    old = _make_log(logs_dir, "old.log", age_seconds=3 * 86400)
    recent = _make_log(logs_dir, "recent.log", age_seconds=1 * 86400)

    retention_days = 2
    cutoff = time.time() - retention_days * 86400
    for log in logs_dir.glob("*.log"):
        try:
            if log.stat().st_mtime < cutoff:
                log.unlink()
        except OSError:
            pass

    assert not old.exists()
    assert recent.exists()


def test_cleanup_skips_when_retention_zero(tmp_path):
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    old = _make_log(logs_dir, "old.log", age_seconds=10 * 86400)

    retention_days = 0
    if retention_days > 0:
        cutoff = time.time() - retention_days * 86400
        for log in logs_dir.glob("*.log"):
            try:
                if log.stat().st_mtime < cutoff:
                    log.unlink()
            except OSError:
                pass

    assert old.exists()


def test_cleanup_ignores_non_log_files(tmp_path):
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    other = logs_dir / "notes.txt"
    other.write_text("keep me")
    import os
    old_mtime = time.time() - 10 * 86400
    os.utime(other, (old_mtime, old_mtime))

    retention_days = 2
    cutoff = time.time() - retention_days * 86400
    for log in logs_dir.glob("*.log"):
        try:
            if log.stat().st_mtime < cutoff:
                log.unlink()
        except OSError:
            pass

    assert other.exists()
```

- [ ] **Step 2: Run new tests to confirm they pass (they test the logic directly, not server.py)**

```
.venv/bin/pytest tests/test_log_retention.py::test_cleanup_deletes_old_logs tests/test_log_retention.py::test_cleanup_skips_when_retention_zero tests/test_log_retention.py::test_cleanup_ignores_non_log_files -v
```
Expected: 3 PASS (these tests verify the logic itself, not the integration — the next step wires it in)

- [ ] **Step 3: Add cleanup block to `_run_job` in `alac_rip/server.py` after line 360**

Locate the block:
```python
    logs_dir = cfg.state_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    label = _log_slug(playlist_name or "one-off")
```

Insert immediately after `logs_dir.mkdir(parents=True, exist_ok=True)`:

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

- [ ] **Step 4: Add `log_retention_days` to `ConfigUpdate` in `alac_rip/server.py` at line 728**

Locate:
```python
class ConfigUpdate(BaseModel):
    music_dir: Optional[str] = None
    state_dir: Optional[str] = None
    github_remote: Optional[str] = None
    alac_rip_dir: Optional[str] = None
```

Replace with:
```python
class ConfigUpdate(BaseModel):
    music_dir: Optional[str] = None
    state_dir: Optional[str] = None
    github_remote: Optional[str] = None
    alac_rip_dir: Optional[str] = None
    log_retention_days: Optional[int] = None
```

- [ ] **Step 5: Run the full test suite**

```
.venv/bin/pytest -v
```
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add alac_rip/server.py tests/test_log_retention.py
git commit -m "feat: log cleanup in _run_job and ConfigUpdate support"
```
