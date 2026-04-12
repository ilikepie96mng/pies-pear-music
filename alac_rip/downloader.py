import os
import subprocess
import time
from pathlib import Path
from typing import Optional


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
        """Write the zhaarey downloader's config.yaml with the current media-user-token."""
        config_path = self.downloader_repo / "config.yaml"
        config_path.write_text(f"media-user-token: {self.media_user_token}\n")

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

        The zhaarey downloader writes output to ./downloads/ relative to its repo dir.
        Returns the path to that downloads directory.

        Raises DownloadError if the downloader exits with a non-zero status.
        """
        self._write_downloader_config()

        result = subprocess.run(
            ["go", "run", "main.go", playlist_url],
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

        downloads_dir = self.downloader_repo / "downloads"
        if not downloads_dir.exists():
            raise DownloadError(
                f"Downloader succeeded but ./downloads/ dir not found at {downloads_dir}. "
                "Check the downloader's actual output directory."
            )

        return downloads_dir
