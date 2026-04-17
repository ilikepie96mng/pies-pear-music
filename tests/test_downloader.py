from pathlib import Path
from unittest.mock import MagicMock

import pytest

from alac_rip.downloader import DownloadError, Downloader


class FakeProc:
    def __init__(self, stdout_lines=None, poll_result=None):
        self.stdout = iter(stdout_lines or [])
        self._poll_result = poll_result
        self.terminated = False
        self.killed = False

    def poll(self):
        return self._poll_result

    def terminate(self):
        self.terminated = True
        self._poll_result = 0

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.killed = True
        self._poll_result = -9


class FakeDownloaderProc:
    def __init__(self, stdout_lines, returncode=0):
        self.stdout = iter(stdout_lines)
        self.returncode = returncode

    def wait(self):
        return self.returncode


@pytest.fixture
def downloader_repo(tmp_path):
    repo = tmp_path / "apple-music-downloader"
    repo.mkdir()
    return repo


def test_start_wrapper_uses_configured_binary_and_session_dir(tmp_path, downloader_repo, monkeypatch):
    wrapper_root = tmp_path / "install"
    wrapper_root.mkdir()
    wrapper_bin = wrapper_root / "wrapper"
    wrapper_bin.write_text("fake")
    session_dir = wrapper_root / "wrapper-session"
    session_dir.mkdir()
    (session_dir / "cookies.sqlitedb").write_text("db")

    proc = FakeProc(stdout_lines=["ready\n"])
    popen = MagicMock(return_value=proc)
    monkeypatch.setattr("alac_rip.downloader.subprocess.Popen", popen)
    monkeypatch.setattr("alac_rip.downloader.threading.Thread", lambda target, daemon: MagicMock(start=lambda: target()))
    ports = iter([False, True])
    monkeypatch.setattr(Downloader, "_ports_open", lambda self: next(ports, True))

    dl = Downloader(
        downloader_repo=downloader_repo,
        wrapper_bin=wrapper_bin,
        media_user_token="token",
    )
    dl.start_wrapper()

    cmd = popen.call_args.args[0]
    assert cmd[:3] == [str(wrapper_bin), "-B", str(session_dir)]
    assert "-L" not in cmd


def test_start_wrapper_adds_login_when_forced(tmp_path, downloader_repo, monkeypatch):
    wrapper_root = tmp_path / "install"
    wrapper_root.mkdir()
    wrapper_bin = wrapper_root / "wrapper"
    wrapper_bin.write_text("fake")

    proc = FakeProc(stdout_lines=["ready\n"])
    popen = MagicMock(return_value=proc)
    monkeypatch.setattr("alac_rip.downloader.subprocess.Popen", popen)
    monkeypatch.setattr("alac_rip.downloader.threading.Thread", lambda target, daemon: MagicMock(start=lambda: target()))
    ports = iter([False, True])
    monkeypatch.setattr(Downloader, "_ports_open", lambda self: next(ports, True))

    dl = Downloader(
        downloader_repo=downloader_repo,
        wrapper_bin=wrapper_bin,
        media_user_token="token",
        apple_id_email="user@example.com",
        apple_id_password="app-password",
    )
    dl.start_wrapper(force_login=True)

    cmd = popen.call_args.args[0]
    assert "-L" in cmd
    assert "user@example.com:app-password" in cmd


def test_stop_wrapper_terminates_only_owned_process(downloader_repo, tmp_path):
    wrapper_bin = tmp_path / "wrapper"
    wrapper_bin.write_text("fake")
    proc = FakeProc()

    dl = Downloader(
        downloader_repo=downloader_repo,
        wrapper_bin=wrapper_bin,
        media_user_token="token",
    )
    dl._wrapper_proc = proc
    dl._owns_wrapper_process = True

    dl.stop_wrapper()

    assert proc.terminated is True


def test_start_wrapper_raises_when_process_exits_before_ports_open(tmp_path, downloader_repo, monkeypatch):
    wrapper_bin = tmp_path / "wrapper"
    wrapper_bin.write_text("fake")
    proc = FakeProc(stdout_lines=["[!] boom\n"], poll_result=1)

    monkeypatch.setattr("alac_rip.downloader.subprocess.Popen", MagicMock(return_value=proc))
    monkeypatch.setattr("alac_rip.downloader.threading.Thread", lambda target, daemon: MagicMock(start=lambda: target()))
    monkeypatch.setattr(Downloader, "_ports_open", lambda self: False)

    dl = Downloader(
        downloader_repo=downloader_repo,
        wrapper_bin=wrapper_bin,
        media_user_token="token",
    )

    with pytest.raises(DownloadError, match="Wrapper exited before becoming ready"):
        dl.start_wrapper()


def test_start_wrapper_restarts_external_process_when_ports_are_taken(tmp_path, downloader_repo, monkeypatch):
    wrapper_bin = tmp_path / "wrapper"
    wrapper_bin.write_text("fake")
    proc = FakeProc(stdout_lines=["ready\n"])
    popen = MagicMock(return_value=proc)

    ports = iter([True, False, False, True])
    monkeypatch.setattr(Downloader, "_ports_open", lambda self: next(ports, True))
    terminate = MagicMock(return_value=True)
    monkeypatch.setattr(Downloader, "_terminate_external_wrapper", terminate)
    monkeypatch.setattr("alac_rip.downloader.subprocess.Popen", popen)
    monkeypatch.setattr("alac_rip.downloader.threading.Thread", lambda target, daemon: MagicMock(start=lambda: target()))

    dl = Downloader(
        downloader_repo=downloader_repo,
        wrapper_bin=wrapper_bin,
        media_user_token="token",
    )
    dl.start_wrapper()

    terminate.assert_called_once()
    assert popen.called


def test_download_playlist_raises_on_decrypt_failures_even_with_zero_exit(tmp_path, downloader_repo, monkeypatch):
    config = downloader_repo / "config.yaml"
    config.write_text("alac-save-folder: downloads\n")
    downloads = downloader_repo / "downloads"
    downloads.mkdir()
    binary = downloader_repo / "apple-music-dl"
    binary.write_text("fake")

    proc = FakeDownloaderProc([
        "Track 1 of 1: songs\n",
        "Decrypting...   0%  (1.0 kB/68 MB, 341 MB/s) Failed to run v2: decryptFragment: read tcp 127.0.0.1:1->127.0.0.1:10020: read: connection reset by peer\n",
    ])
    monkeypatch.setattr("alac_rip.downloader.subprocess.Popen", MagicMock(return_value=proc))

    dl = Downloader(
        downloader_repo=downloader_repo,
        wrapper_bin=tmp_path / "wrapper",
        media_user_token="token",
    )

    with pytest.raises(DownloadError, match="decryption failures"):
        dl.download_playlist("https://music.apple.com/test")
