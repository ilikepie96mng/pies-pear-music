import os
import queue
import re
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, Optional

import yaml


class DownloadError(Exception):
    pass


LogCallback = Callable[[str, str], None]  # (message, phase)


class Downloader:
    """Wraps zhaarey's apple-music-downloader Go binary and the wrapper decryption service."""

    def __init__(
        self,
        downloader_repo: Path,
        wrapper_bin: Path,
        media_user_token: str,
        apple_id_email: str = "",
        apple_id_password: str = "",
        on_log: Optional[LogCallback] = None,
    ):
        self.downloader_repo = downloader_repo
        self.wrapper_bin = wrapper_bin
        self.media_user_token = media_user_token
        self.apple_id_email = apple_id_email
        self.apple_id_password = apple_id_password
        self._on_log: LogCallback = on_log or (lambda msg, phase: None)
        self._wrapper_proc: Optional[subprocess.Popen] = None
        self._owns_wrapper_process = False

    def _log(self, msg: str, phase: str = "running") -> None:
        self._on_log(msg, phase)

    def _write_downloader_config(self) -> None:
        """Update media-user-token in the downloader's config.yaml, preserving all other settings."""
        config_path = self.downloader_repo / "config.yaml"
        if config_path.exists():
            content = config_path.read_text()
            content = re.sub(
                r'^(media-user-token:\s*).*$',
                f'media-user-token: {self.media_user_token}',
                content,
                flags=re.MULTILINE,
            )
            config_path.write_text(content)
        else:
            config_path.write_text(
                f"media-user-token: {self.media_user_token}\n"
                "alac-save-folder: downloads\n"
            )

    def _get_downloads_dir(self) -> Path:
        """Return the directory where the downloader saves ALAC files, per its config."""
        config_path = self.downloader_repo / "config.yaml"
        if config_path.exists():
            data = yaml.safe_load(config_path.read_text()) or {}
            folder = data.get("alac-save-folder", "downloads")
        else:
            folder = "downloads"
        return self.downloader_repo / folder

    _CONTAINER_NAME = "alac-rip-wrapper"
    _WRAPPER_IMAGE = "localhost/alac-rip-wrapper:latest"

    def _wrapper_base_dir(self) -> Path:
        """Return the persisted wrapper session directory expected by the local wrapper binary."""
        candidates = [
            self.wrapper_bin.parent / "wrapper-session",
            Path.home() / ".local/share/pies-alac-rip/wrapper-session",
            self.wrapper_bin.parent / "rootfs/data/data/com.apple.android.music/files",
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return candidates[0]

    def _has_saved_session(self, base_dir: Path) -> bool:
        session_markers = [
            "adi.pb",
            "accounts.sqlitedb",
            "cookies.sqlitedb",
            "mpl_db/accounts.sqlitedb",
            "mpl_db/cookies.sqlitedb",
        ]
        return any((base_dir / marker).exists() for marker in session_markers)

    def _ports_open(self) -> bool:
        """Return True if all three wrapper ports are accepting connections."""
        for port in [10020, 20020, 30020]:
            s = socket.socket()
            s.settimeout(0.5)
            result = s.connect_ex(("localhost", port))
            s.close()
            if result != 0:
                return False
        return True

    def _terminate_external_wrapper(self) -> bool:
        """Terminate any existing wrapper process for the configured binary path."""
        try:
            result = subprocess.run(
                ["pgrep", "-f", str(self.wrapper_bin)],
                capture_output=True,
                text=True,
            )
        except OSError:
            return False

        if result.returncode != 0:
            return False

        terminated = False
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                pid = int(line)
            except ValueError:
                continue
            if pid == os.getpid():
                continue
            try:
                os.kill(pid, 15)
                terminated = True
            except ProcessLookupError:
                continue
            except PermissionError:
                continue

        if terminated:
            for _ in range(20):
                if not self._ports_open():
                    break
                time.sleep(0.25)
        return terminated

    def start_wrapper(self, force_login: bool = False) -> None:
        """Start the configured FairPlay wrapper binary and wait until it is ready."""
        if self._wrapper_proc and self._wrapper_proc.poll() is None and self._ports_open() and not force_login:
            self._log("Wrapper already running and ready", "wrapper_starting")
            return

        if self._ports_open() and not force_login:
            self._log("Existing wrapper detected on decrypt ports; restarting configured wrapper...", "wrapper_starting")
            self._terminate_external_wrapper()
            if self._ports_open():
                raise DownloadError(
                    "A wrapper process is already bound to the decrypt ports and could not be restarted. "
                    "Stop the existing wrapper and try again."
                )

        if self._wrapper_proc and self._wrapper_proc.poll() is None:
            self.stop_wrapper()

        base_dir = self._wrapper_base_dir()
        base_dir.mkdir(parents=True, exist_ok=True)
        cmd = [str(self.wrapper_bin), "-B", str(base_dir)]

        should_login = force_login or not self._has_saved_session(base_dir)
        if should_login and self.apple_id_email and self.apple_id_password:
            cmd += ["-L", f"{self.apple_id_email}:{self.apple_id_password}"]

        if force_login:
            self._log("Starting wrapper with explicit Apple login...", "wrapper_starting")
        elif should_login:
            self._log("Starting wrapper and logging in...", "wrapper_starting")
        else:
            self._log(f"Starting wrapper using saved session at {base_dir}...", "wrapper_starting")

        # Stream container logs in a background thread so we can apply a timeout
        log_q: queue.Queue = queue.Queue()

        def _read_logs() -> None:
            assert self._wrapper_proc is not None
            assert self._wrapper_proc.stdout is not None
            for line in self._wrapper_proc.stdout:
                log_q.put(("line", line.strip()))
            log_q.put(("eof", None))

        try:
            self._wrapper_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env={**os.environ, "HOME": str(Path.home())},
            )
            self._owns_wrapper_process = True
        except OSError as exc:
            raise DownloadError(f"Failed to start wrapper binary {self.wrapper_bin}: {exc}") from exc

        log_thread = threading.Thread(target=_read_logs, daemon=True)
        log_thread.start()

        deadline = time.monotonic() + 20
        login_failed = False

        while time.monotonic() < deadline:
            try:
                kind, value = log_q.get(timeout=0.25)
            except queue.Empty:
                if self._wrapper_proc.poll() is not None:
                    break
                if self._ports_open():
                    break
                continue

            if kind == "eof":
                break

            line = value
            if line:
                self._log(line, "wrapper_starting")

            if "[!] login failed" in line or "login failed" in line.lower():
                login_failed = True
                break

            if self._ports_open():
                break

        if self._wrapper_proc.poll() is not None and not self._ports_open():
            tail_lines: list[str] = []
            while not log_q.empty():
                kind, value = log_q.get_nowait()
                if kind == "line" and value:
                    tail_lines.append(value)
            tail = "\n".join(tail_lines[-10:])
            self._wrapper_proc = None
            self._owns_wrapper_process = False
            detail = f"\n{tail}" if tail else ""
            raise DownloadError(f"Wrapper exited before becoming ready.{detail}")

        if login_failed:
            self.stop_wrapper()
            raise DownloadError(
                "Wrapper authentication failed — check Apple ID credentials in Settings, "
                "or clear them to use a saved session."
            )

        if not self._ports_open():
            self.stop_wrapper()
            raise DownloadError(
                "Wrapper did not become ready within 20 seconds. "
                f"Check the wrapper session at {base_dir} and verify {self.wrapper_bin} runs locally."
            )

        self._log("Wrapper is authenticated and ready", "wrapper_ready")

    def stop_wrapper(self) -> None:
        """Stop the wrapper container."""
        if self._wrapper_proc and self._wrapper_proc.poll() is None and self._owns_wrapper_process:
            self._wrapper_proc.terminate()
            try:
                self._wrapper_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._wrapper_proc.kill()
                self._wrapper_proc.wait(timeout=5)
        self._wrapper_proc = None
        self._owns_wrapper_process = False

    def download_playlist(self, playlist_url: str) -> Path:
        """
        Download all tracks from an Apple Music playlist URL.

        Streams downloader output line-by-line via on_log.
        Returns the path to the downloader's configured save directory.
        Raises DownloadError if the downloader exits with a non-zero status.
        """
        self._write_downloader_config()

        binary = self.downloader_repo / "apple-music-dl"
        cmd = (
            [str(binary), playlist_url]
            if binary.exists()
            else ["go", "run", "main.go", playlist_url]
        )

        self._log(f"Running downloader: {cmd[0]}", "downloading")

        proc = subprocess.Popen(
            cmd,
            cwd=str(self.downloader_repo),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env={**os.environ, "HOME": str(Path.home())},
        )

        output_lines: list[str] = []
        decrypt_failures: list[str] = []
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                output_lines.append(line)
                self._log(line, "downloading")
                lower = line.lower()
                if (
                    "failed to run v2" in lower
                    or "decryptfragment" in lower
                    or "connection reset by peer" in lower
                ):
                    decrypt_failures.append(line)

        proc.wait()

        if proc.returncode != 0:
            tail = "\n".join(output_lines[-20:]) if output_lines else "(no output)"
            raise DownloadError(
                f"Downloader exited with code {proc.returncode}.\n{tail}"
            )

        if decrypt_failures:
            tail = "\n".join(decrypt_failures[-10:])
            raise DownloadError(
                "Downloader reported decryption failures even though it exited successfully.\n"
                f"{tail}"
            )

        downloads_dir = self._get_downloads_dir()
        if not downloads_dir.exists():
            raise DownloadError(
                f"Downloader succeeded but output directory not found at {downloads_dir}. "
                "Check the alac-save-folder setting in the downloader's config.yaml."
            )

        return downloads_dir
