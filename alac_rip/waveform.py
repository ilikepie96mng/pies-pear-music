import array
import logging
import math
import shutil
import subprocess
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from alac_rip.state import StateManager

logger = logging.getLogger(__name__)


class WaveformExtractionError(Exception):
    """Raised when waveform extraction fails."""
    pass


def extract_waveform(file_path: Path | str, points: int = 100) -> tuple[list[float], float]:
    """
    Extract downsampled audio waveform amplitude peaks normalized between 0.0 and 1.0.

    Uses ffmpeg to decode the audio stream into 8000Hz 16-bit mono PCM,
    then calculates the maximum absolute amplitude peak for each of the `points` buckets.

    Returns:
        tuple of (peaks: list[float], duration: float)
    """
    path = Path(file_path).expanduser().resolve()
    if not path.is_file():
        raise WaveformExtractionError(f"Audio file not found: {path}")

    # Clamp points to reasonable bounds
    points = max(10, min(points, 1000))

    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin:
        raise WaveformExtractionError("ffmpeg binary not found in PATH")

    cmd = [
        ffmpeg_bin,
        "-nostdin",
        "-threads", "1",
        "-t", "7200",
        "-i", str(path),
        "-ac", "1",
        "-ar", "8000",
        "-f", "s16le",
        "-vn",
        "-sn",
        "-",
    ]

    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=45,
        )
    except subprocess.TimeoutExpired as e:
        raise WaveformExtractionError("Waveform extraction timed out") from e
    except Exception as e:
        raise WaveformExtractionError(f"FFmpeg execution error: {e}") from e

    if proc.returncode != 0 and not proc.stdout:
        err_msg = proc.stderr.decode("utf-8", errors="replace").strip()
        raise WaveformExtractionError(f"FFmpeg failed with code {proc.returncode}: {err_msg[:200]}")

    raw_bytes = proc.stdout
    if not raw_bytes:
        return [0.0] * points, 0.0

    samples = array.array("h")
    # Ensure byte length is even for 16-bit shorts
    if len(raw_bytes) % 2 != 0:
        raw_bytes = raw_bytes[: len(raw_bytes) - (len(raw_bytes) % 2)]
    samples.frombytes(raw_bytes)

    total_samples = len(samples)
    if total_samples == 0:
        return [0.0] * points, 0.0

    duration = round(total_samples / 8000.0, 2)
    bucket_size = total_samples / float(points)
    peaks: list[float] = []

    for i in range(points):
        start_idx = int(math.floor(i * bucket_size))
        end_idx = int(math.floor((i + 1) * bucket_size))
        if start_idx >= total_samples:
            peaks.append(0.0)
            continue
        end_idx = min(total_samples, max(start_idx + 1, end_idx))
        chunk = samples[start_idx:end_idx]
        if chunk:
            max_amp = max(abs(s) for s in chunk)
            normalized = round(min(1.0, max_amp / 32768.0), 4)
            peaks.append(normalized)
        else:
            peaks.append(0.0)

    return peaks, duration


def get_or_extract_waveform(
    track_id: str,
    file_path: Path | str,
    state_mgr: Optional["StateManager"] = None,
    points: int = 100,
) -> dict:
    """
    Retrieve cached waveform from StateManager or compute and cache it.
    """
    points = max(10, min(points, 1000))

    if state_mgr is not None:
        cached = state_mgr.get_waveform(track_id, points=points)
        if cached is not None:
            return cached

    peaks, duration = extract_waveform(file_path, points=points)

    if state_mgr is not None:
        return state_mgr.save_waveform(track_id, points, duration, peaks)

    return {
        "track_id": track_id,
        "points": points,
        "duration": duration,
        "peaks": peaks,
    }
