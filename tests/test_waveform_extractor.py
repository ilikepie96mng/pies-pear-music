import array
import math
import struct
import subprocess
import wave
from datetime import datetime
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

import alac_rip.server as server_mod
from alac_rip.server import app
from alac_rip.state import StateManager, Track
from alac_rip.waveform import (
    WaveformExtractionError,
    extract_waveform,
    get_or_extract_waveform,
)


def _generate_test_wav(file_path: Path, duration_sec: float = 1.0, freq: float = 440.0) -> None:
    """Generate a valid PCM sine wave audio file for testing."""
    sample_rate = 8000
    n_samples = int(sample_rate * duration_sec)
    with wave.open(str(file_path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        frames = bytearray()
        for i in range(n_samples):
            val = int(16000 * math.sin(2 * math.pi * freq * (i / sample_rate)))
            frames.extend(struct.pack("<h", val))
        wf.writeframes(frames)


@pytest.fixture
def temp_state(tmp_path: Path) -> StateManager:
    db_file = tmp_path / "test_waveform.db"
    return StateManager(db_file)


@pytest.fixture
def server_client(tmp_path: Path, monkeypatch):
    music_dir = tmp_path / "Music"
    music_dir.mkdir(parents=True, exist_ok=True)
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)

    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        f"music_dir: {music_dir}\n"
        f"state_dir: {state_dir}\n"
    )
    monkeypatch.setattr(server_mod, "DEFAULT_CONFIG_PATH", cfg_file)
    with TestClient(app) as c:
        yield c, music_dir


def test_waveform_extraction_real_wav(tmp_path: Path):
    audio_file = tmp_path / "test_tone.wav"
    _generate_test_wav(audio_file, duration_sec=1.5, freq=440.0)

    peaks, duration = extract_waveform(audio_file, points=50)
    assert len(peaks) == 50
    assert duration >= 1.4 and duration <= 1.6
    # Sine wave amplitude is ~16000 / 32768 = ~0.488
    for p in peaks:
        assert 0.0 <= p <= 1.0
        assert p > 0.3


def test_waveform_extraction_missing_file(tmp_path: Path):
    missing_file = tmp_path / "non_existent.m4a"
    with pytest.raises(WaveformExtractionError, match="Audio file not found"):
        extract_waveform(missing_file)


def test_waveform_extraction_points_clamping(tmp_path: Path):
    audio_file = tmp_path / "test_tone.wav"
    _generate_test_wav(audio_file, duration_sec=0.5)

    # Below min (10) -> clamped to 10
    peaks_low, _ = extract_waveform(audio_file, points=2)
    assert len(peaks_low) == 10

    # Above max (1000) -> clamped to 1000
    peaks_high, _ = extract_waveform(audio_file, points=2000)
    assert len(peaks_high) == 1000


def test_waveform_ffmpeg_timeout(tmp_path: Path, monkeypatch):
    audio_file = tmp_path / "test_tone.wav"
    _generate_test_wav(audio_file, duration_sec=0.5)

    def mock_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="ffmpeg", timeout=1)

    monkeypatch.setattr(subprocess, "run", mock_run)
    with pytest.raises(WaveformExtractionError, match="Waveform extraction timed out"):
        extract_waveform(audio_file)


def test_waveform_ffmpeg_error(tmp_path: Path, monkeypatch):
    audio_file = tmp_path / "test_tone.wav"
    _generate_test_wav(audio_file, duration_sec=0.5)

    class MockProc:
        returncode = 1
        stdout = b""
        stderr = b"Corrupt file"

    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: MockProc())
    with pytest.raises(WaveformExtractionError, match="FFmpeg failed"):
        extract_waveform(audio_file)


def test_state_waveform_caching(temp_state: StateManager):
    track_id = "test_track_1"
    sample_peaks = [0.1, 0.45, 0.82, 0.33, 0.95]

    # Cache miss
    assert temp_state.get_waveform(track_id, points=5) is None

    # Save
    saved = temp_state.save_waveform(track_id, points=5, duration=3.5, peaks=sample_peaks)
    assert saved["track_id"] == track_id
    assert saved["points"] == 5
    assert saved["duration"] == 3.5
    assert saved["peaks"] == sample_peaks

    # Cache hit
    cached = temp_state.get_waveform(track_id, points=5)
    assert cached is not None
    assert cached["peaks"] == sample_peaks
    assert cached["duration"] == 3.5

    # Cache miss for different point resolution
    assert temp_state.get_waveform(track_id, points=10) is None

    # Update (conflict overwrite)
    updated_peaks = [0.2, 0.4, 0.6, 0.8, 1.0]
    temp_state.save_waveform(track_id, points=5, duration=3.5, peaks=updated_peaks)
    cached2 = temp_state.get_waveform(track_id, points=5)
    assert cached2 is not None
    assert cached2["peaks"] == updated_peaks

    # Delete
    assert temp_state.delete_waveform(track_id) is True
    assert temp_state.get_waveform(track_id, points=5) is None


def test_get_or_extract_waveform_with_cache(tmp_path: Path, temp_state: StateManager):
    audio_file = tmp_path / "track_cached.wav"
    _generate_test_wav(audio_file, duration_sec=1.0)
    track_id = "trk_cached_1"

    # First call: computes and caches
    res1 = get_or_extract_waveform(track_id, audio_file, state_mgr=temp_state, points=20)
    assert len(res1["peaks"]) == 20
    assert res1["duration"] >= 0.9

    # Verify cached in database
    db_row = temp_state.get_waveform(track_id, points=20)
    assert db_row is not None
    assert db_row["peaks"] == res1["peaks"]

    # Second call returns cached dict without re-extracting
    res2 = get_or_extract_waveform(track_id, audio_file, state_mgr=temp_state, points=20)
    assert res2["peaks"] == res1["peaks"]


def test_api_waveform_endpoint(server_client, monkeypatch):
    client, music_dir = server_client
    monkeypatch.setattr(server_mod, "_api_capability", "fixture-waveform-token")
    headers = {"X-Pies-Api-Token": "fixture-waveform-token"}

    # 1. Missing track_id -> 400
    r = client.get("/api/v1/waveform", headers=headers)
    assert r.status_code == 400

    # 2. Track not in state -> 404
    r = client.get("/api/v1/waveform?track_id=unknown_123", headers=headers)
    assert r.status_code == 404

    # Create real track file in music_dir
    track_file = music_dir / "artist" / "album" / "track.wav"
    track_file.parent.mkdir(parents=True, exist_ok=True)
    _generate_test_wav(track_file, duration_sec=1.2)

    now_iso = datetime.now().isoformat()
    server_mod.state.add_track(
        Track(
            track_id="api_trk_1",
            title="Waveform Test Track",
            artist="Audio Artist",
            album="Sound Waves",
            local_path=str(track_file),
            downloaded_at=now_iso,
        )
    )

    # 3. Successful waveform extraction
    r = client.get("/api/v1/waveform?track_id=api_trk_1&points=40", headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert data["track_id"] == "api_trk_1"
    assert data["points"] == 40
    assert len(data["peaks"]) == 40
    assert data["duration"] >= 1.1

    # 4. Path-based route also works
    r_path = client.get("/api/v1/waveform/api_trk_1?points=40", headers=headers)
    assert r_path.status_code == 200
    assert r_path.json()["peaks"] == data["peaks"]

    # 5. Invalid points bound (< 10) -> 422
    r_invalid = client.get("/api/v1/waveform?track_id=api_trk_1&points=3", headers=headers)
    assert r_invalid.status_code == 422
