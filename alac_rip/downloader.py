import os
import re
import subprocess
import time
from pathlib import Path
from typing import Optional

import yaml


class DownloadError(Exception):
    pass


class Downloader:
    """Wraps zhaarey's apple-music-downloader Go binary and the wrapper decryption service."""

    def __init__(
        self,
        downloader_repo: Path,
        wrapper_bin: Path,
        media_user_token: str,
    ):
        self.downloader_repo = downloader_repo
        self.wrapper_bin = wrapper_bin
        self.media_user_token = media_user_token
        self._wrapper_proc: Optional[subprocess.Popen] = None

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

    def start_wrapper(self) -> None:
        """Start the wrapper decryption service in the background."""
        if self._wrapper_proc and self._wrapper_proc.poll() is None:
            return  # already running
        self._wrapper_proc = subprocess.Popen(
            [str(self.wrapper_bin)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(1)  # give wrapper a moment to bind its port

    def stop_wrapper(self) -> None:
        """Stop the wrapper decryption service."""
        if self._wrapper_proc and self._wrapper_proc.poll() is None:
            self._wrapper_proc.terminate()
            self._wrapper_proc.wait(timeout=5)
        self._wrapper_proc = None

    def download_playlist(self, playlist_url: str) -> Path:
        """
        Download all tracks from an Apple Music playlist URL.

        Returns the path to the downloader's configured save directory.
        Raises DownloadError if the downloader exits with a non-zero status.
        """
        self._write_downloader_config()

        # Prefer the pre-built binary; fall back to go run for dev environments
        binary = self.downloader_repo / "apple-music-dl"
        cmd = (
            [str(binary), playlist_url]
            if binary.exists()
            else ["go", "run", "main.go", playlist_url]
        )

        result = subprocess.run(
            cmd,
            cwd=str(self.downloader_repo),
            capture_output=True,
            text=True,
            env={**os.environ, "HOME": str(Path.home())},
        )

        if result.returncode != 0:
            raise DownloadError(
                f"Downloader exited with code {result.returncode}.\n"
                f"stderr: {result.stderr}\n"
                f"stdout: {result.stdout}"
            )

        downloads_dir = self._get_downloads_dir()
        if not downloads_dir.exists():
            raise DownloadError(
                f"Downloader succeeded but output directory not found at {downloads_dir}. "
                "Check the alac-save-folder setting in the downloader's config.yaml."
            )

        return downloads_dir
