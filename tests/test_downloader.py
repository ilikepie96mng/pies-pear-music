from pathlib import Path
from unittest.mock import MagicMock

import pytest

from alac_rip.downloader import DownloadError, Downloader


def make_downloader(tmp_path: Path) -> Downloader:
    repo = tmp_path / "amd"
    repo.mkdir()
    staging = tmp_path / "staging"
    wrapper_dir = tmp_path / "wrapper-dir"
    wrapper_dir.mkdir()
    wrapper_bin = wrapper_dir / "wrapper"
    wrapper_bin.write_text("")
    return Downloader(
        downloader_repo=repo,
        wrapper_bin=wrapper_bin,
        media_user_token="tok",
        staging_dir=staging,
        apple_id_email="user@example.com",
        apple_id_password="secret",
    )


def test_authenticate_interactive_uses_wrapper_binary(monkeypatch, tmp_path):
    dl = make_downloader(tmp_path)
    run = MagicMock(return_value=MagicMock(returncode=0))
    monkeypatch.setattr("alac_rip.downloader.subprocess.run", run)
    monkeypatch.setattr("alac_rip.downloader.os.geteuid", lambda: 0)

    dl.authenticate_interactive()

    run.assert_called_once_with(
        [str(dl.wrapper_bin), "-L", "user@example.com:secret"],
        cwd=str(dl.wrapper_bin.parent),
    )


def test_authenticate_interactive_requires_credentials(tmp_path):
    repo = tmp_path / "amd"
    repo.mkdir()
    wrapper_dir = tmp_path / "wrapper-dir"
    wrapper_dir.mkdir()
    wrapper_bin = wrapper_dir / "wrapper"
    wrapper_bin.write_text("")
    dl = Downloader(
        downloader_repo=repo,
        wrapper_bin=wrapper_bin,
        media_user_token="tok",
        staging_dir=tmp_path / "staging",
    )

    with pytest.raises(DownloadError):
        dl.authenticate_interactive()


def test_authenticate_interactive_uses_sudo_when_not_root(monkeypatch, tmp_path):
    dl = make_downloader(tmp_path)
    run = MagicMock(return_value=MagicMock(returncode=130))
    monkeypatch.setattr("alac_rip.downloader.subprocess.run", run)
    monkeypatch.setattr("alac_rip.downloader.os.geteuid", lambda: 1000)

    dl.authenticate_interactive()

    run.assert_called_once_with(
        ["sudo", str(dl.wrapper_bin), "-L", "user@example.com:secret"],
        cwd=str(dl.wrapper_bin.parent),
    )


def test_start_wrapper_uses_wrapper_binary_without_login(monkeypatch, tmp_path):
    dl = make_downloader(tmp_path)
    proc = MagicMock()
    proc.poll.return_value = None
    monkeypatch.setattr(dl, "_wrapper_is_running", MagicMock(side_effect=[False, True]))
    popen = MagicMock(return_value=proc)
    monkeypatch.setattr("alac_rip.downloader.subprocess.Popen", popen)

    dl.start_wrapper()

    popen.assert_called_once()
    args, kwargs = popen.call_args
    assert args[0] == [str(dl.wrapper_bin)]
    assert kwargs["cwd"] == str(dl.wrapper_bin.parent)


def test_stop_wrapper_terminates_started_process(tmp_path):
    dl = make_downloader(tmp_path)
    proc = MagicMock()
    proc.poll.return_value = None
    dl._wrapper_proc = proc

    dl.stop_wrapper()

    proc.terminate.assert_called_once()


def test_download_playlist_streams_output(monkeypatch, tmp_path):
    dl = make_downloader(tmp_path)
    binary = dl.downloader_repo / "apple-music-dl"
    binary.write_text("")
    downloads_dir = dl.staging_dir
    downloads_dir.mkdir()

    proc = MagicMock()
    proc.stdout = iter(["line one\n", "line two\n"])
    proc.wait.return_value = 0
    monkeypatch.setattr("alac_rip.downloader.subprocess.Popen", MagicMock(return_value=proc))

    lines: list[str] = []
    out = dl.download_playlist("https://example.com/playlist", log=lines.append)

    assert out == downloads_dir
    assert lines == ["line one", "line two"]


def test_write_downloader_config_uses_staging_dir(tmp_path):
    dl = make_downloader(tmp_path)

    dl._write_downloader_config()

    config = (dl.downloader_repo / "config.yaml").read_text()
    assert f"alac-save-folder: {dl.staging_dir}" in config
