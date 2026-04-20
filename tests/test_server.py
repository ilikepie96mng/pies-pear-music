from fastapi.testclient import TestClient

import alac_rip.server as server_mod


def make_client():
    return TestClient(server_mod.app)


def test_health():
    with make_client() as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


def test_get_config_omits_password(tmp_path, monkeypatch):
    fake_cfg_path = tmp_path / "config.yaml"
    fake_cfg_path.write_text(
        "music_dir: ~/Music\n"
        "media_user_token: tok\n"
        "apple_id_email: a@b.com\n"
        "apple_id_password: secret\n"
        "staging_dir: /tmp/s\n"
        "downloader_repo: /tmp/d\n"
        "wrapper_bin: /tmp/w\n"
        "state_dir: /tmp/st\n"
        "github_remote: ''\n"
    )
    monkeypatch.setattr(server_mod, "DEFAULT_CONFIG_PATH", fake_cfg_path)

    with make_client() as client:
        resp = client.get("/config")
        assert resp.status_code == 200
        data = resp.json()
        assert data["music_dir"] == "~/Music"
        assert "apple_id_password" not in data


def test_put_config_roundtrip(tmp_path, monkeypatch):
    fake_cfg_path = tmp_path / "config.yaml"
    fake_cfg_path.write_text(
        "music_dir: ~/Music\n"
        "media_user_token: tok\n"
        "apple_id_email: a@b.com\n"
        "apple_id_password: secret\n"
        "staging_dir: /tmp/s\n"
        "downloader_repo: /tmp/d\n"
        "wrapper_bin: /tmp/w\n"
        "state_dir: /tmp/st\n"
        "github_remote: ''\n"
    )
    monkeypatch.setattr(server_mod, "DEFAULT_CONFIG_PATH", fake_cfg_path)

    with make_client() as client:
        resp = client.put(
            "/config",
            json={
                "apple_id_email": "new@email.com",
                "media_user_token": "updated-token",
            },
        )
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    data = fake_cfg_path.read_text()
    assert "new@email.com" in data
    assert "updated-token" in data
    assert "apple_id_password: secret" in data
