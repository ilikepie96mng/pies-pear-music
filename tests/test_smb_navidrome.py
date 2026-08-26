import hashlib
import os
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient

import alac_rip.server as server_mod
from alac_rip.server import app
import alac_rip.smb_helper as smb_helper
from alac_rip.state import StateManager, Track
from alac_rip.sync import SyncEngine


@pytest.fixture
def client(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        f"music_dir: {tmp_path}/Music\n"
        f"state_dir: {tmp_path}/state\n"
    )
    monkeypatch.setattr(server_mod, "DEFAULT_CONFIG_PATH", cfg_file)
    with TestClient(app) as c:
        yield c


def test_subsonic_token_generator():
    res = smb_helper.generate_subsonic_token("supersecretpassword")
    assert "token" in res
    assert "salt" in res
    assert len(res["salt"]) == 12
    # Verify MD5 calculation
    expected_md5 = hashlib.md5(("supersecretpassword" + res["salt"]).encode("utf-8")).hexdigest()
    assert res["token"] == expected_md5


def test_parse_smb_uri():
    uri = "smb://msadmin@192.168.0.250/tank/media/music/"
    parsed = smb_helper.parse_smb_uri(uri)
    assert parsed["host"] == "192.168.0.250"
    assert parsed["user"] == "msadmin"
    assert parsed["share"] == "tank"
    assert parsed["subpath"] == "media/music"


def test_resolve_smb_mount_gvfs(tmp_path, monkeypatch):
    fake_user = tmp_path / "user"
    fake_user.mkdir()
    fake_gvfs = fake_user / "gvfs"
    mount_folder = fake_gvfs / "smb-share:server=192.168.0.250,share=tank,user=msadmin"
    mount_folder.mkdir(parents=True)
    media_music = mount_folder / "media" / "music"
    media_music.mkdir(parents=True)

    monkeypatch.setattr(os, "getuid", lambda: 1000)
    # Simulate DBus not returning and no kio-fuse in fake_user
    with patch("subprocess.run", side_effect=Exception("DBus not available")):
        with patch("alac_rip.smb_helper.Path") as mock_path:
            def _custom_path(p):
                if str(p) == "/run/user/1000":
                    return fake_user
                if str(p) == "/run/user/1000/gvfs":
                    return fake_gvfs
                return Path(p)
            mock_path.side_effect = _custom_path

            resolved = smb_helper.resolve_smb_mount("smb://msadmin@192.168.0.250/tank/media/music")
            assert resolved == media_music


def test_resolve_smb_mount_kio_dbus(tmp_path):
    kio_mount = tmp_path / "kio_mount"
    kio_mount.mkdir()
    fake_process = MagicMock(return_value=MagicMock(returncode=0, stdout=f"('{kio_mount}',)"))
    with patch("subprocess.run", fake_process):
        resolved = smb_helper.resolve_smb_mount("smb://msadmin@192.168.0.250/tank/media/music")
        assert resolved == kio_mount.resolve()


def test_test_storage_path(tmp_path):
    res = smb_helper.test_storage_path(tmp_path)
    assert res["exists"] is True
    assert res["is_dir"] is True
    assert res["writable"] is True
    assert res["latency_ms"] >= 0.0
    assert "Ready" in res["message"]


def test_sync_engine_relative_m3u8_generation(tmp_path):
    music_dir = tmp_path / "music"
    music_dir.mkdir(parents=True)
    artists_dir = music_dir / "artists" / "Daft Punk" / "Discovery"
    artists_dir.mkdir(parents=True)
    track_file = artists_dir / "01 - One More Time.flac"
    track_file.write_text("dummy-audio-content")

    db_file = tmp_path / "downloaded.db"
    state = StateManager(db_file)
    state.add_track(Track(
        track_id="01 - One More Time.flac",
        title="One More Time",
        artist="Daft Punk",
        album="Discovery",
        local_path=str(track_file),
        downloaded_at="2026-08-22T00:00:00",
    ))
    state.add_track_to_playlist("Electronic Hits", "01 - One More Time.flac")

    engine = SyncEngine(
        state=state,
        music_dir=music_dir,
        playlist_name="Electronic Hits",
    )
    engine._write_m3u8()

    m3u8_file = music_dir / "playlists" / "Electronic Hits.m3u8"
    assert m3u8_file.exists()
    content = m3u8_file.read_text(encoding="utf-8")
    assert "#EXTM3U" in content
    assert "#EXTINF:-1,Daft Punk - One More Time" in content
    # Crucial for Navidrome: path must be relative to playlists/ folder
    assert "../artists/Daft Punk/Discovery/01 - One More Time.flac" in content


def test_sync_engine_safe_commit_fallback(tmp_path, monkeypatch):
    music_dir = tmp_path / "music"
    music_dir.mkdir()
    db_file = tmp_path / "downloaded.db"
    state = StateManager(db_file)
    engine = SyncEngine(state=state, music_dir=music_dir)

    src = tmp_path / "source.flac"
    src.write_text("test-flac-data")
    dest = music_dir / "dest.flac"

    # Simulate cross-filesystem error on os.replace
    orig_replace = os.replace
    call_count = [0]
    def _mock_replace(s, d):
        call_count[0] += 1
        if call_count[0] == 1:
            raise OSError(18, "Invalid cross-device link")
        return orig_replace(s, d)

    monkeypatch.setattr(os, "replace", _mock_replace)

    engine._safe_commit(src, dest)
    assert dest.exists()
    assert dest.read_text() == "test-flac-data"
    assert not src.exists()


def test_storage_endpoints(client, tmp_path):
    # 1. Test Storage
    resp = client.post("/api/v1/storage/test", json={"path": str(tmp_path)})
    assert resp.status_code == 200
    data = resp.json()
    assert data["writable"] is True
    assert data["exists"] is True

    # 2. Resolve SMB
    resp = client.post("/api/v1/storage/resolve-smb", json={"uri": "smb://invalid-host/share"})
    assert resp.status_code == 200
    assert resp.json()["found"] is False

    # 3. Generate Navidrome Token
    resp = client.post("/api/v1/integrations/navidrome/generate-token", json={"password": "mypassword123"})
    assert resp.status_code == 200
    data = resp.json()
    assert "token" in data
    assert "salt" in data
    assert len(data["salt"]) == 12
