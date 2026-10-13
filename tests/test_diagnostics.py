from pathlib import Path

import alac_rip.server as server
from alac_rip.config import Config


def test_diagnostics_do_not_expose_local_paths(tmp_path, monkeypatch):
    config_path = tmp_path / "private" / "config.yaml"
    config_path.parent.mkdir()
    config_path.write_text("music_dir: /unused\n")
    music_dir = tmp_path / "private" / "Music"
    state_dir = tmp_path / "private" / "state"
    tool_dir = tmp_path / "private" / "tools"
    music_dir.mkdir()
    state_dir.mkdir()
    tool_dir.mkdir()

    monkeypatch.setattr(server, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(
        server,
        "cfg",
        Config(music_dir=music_dir, state_dir=state_dir, alac_rip_dir=tool_dir),
    )

    checks = server.get_diagnostics()

    assert all(str(tmp_path) not in check["detail"] for check in checks)
    assert {check["label"] for check in checks} >= {
        "Podman", "Go", "FFmpeg", "MP4Box", "mp4decrypt", "Config file",
        "Music directory", "State directory", "alac-rip directory", "Downloader source", "Wrapper source",
    }


def test_runtime_error_redaction_hides_absolute_paths():
    message = "could not open /var/music/private/Music/song.m4a: permission denied"
    assert server._redact_runtime_paths(message) == "could not open <local path>: permission denied"
