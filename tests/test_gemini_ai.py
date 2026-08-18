import json
from unittest.mock import patch, MagicMock
from alac_rip import gemini_ai


def test_generate_smart_playlist_success():
    with patch("requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": json.dumps({
                                    "playlist_title": "Night Drive Synthwave",
                                    "description": "Cruising under neon lights",
                                    "vibe_tags": ["synthwave", "retro", "chill"],
                                    "tracks": [
                                        {
                                            "title": "Resonance",
                                            "artist": "HOME",
                                            "album": "Odyssey",
                                            "rationale": "Pinnacle chillwave synth anthem"
                                        }
                                    ]
                                })
                            }
                        ]
                    }
                }
            ]
        }
        mock_post.return_value = mock_resp

        res = gemini_ai.generate_smart_playlist(
            prompt="chill retro synthwave",
            api_key="fake-key",
        )

        assert res.get("playlist_title") == "Night Drive Synthwave"
        assert len(res.get("tracks", [])) == 1
        assert res["tracks"][0]["title"] == "Resonance"


def test_generate_smart_playlist_missing_key():
    res = gemini_ai.generate_smart_playlist(
        prompt="ambient piano",
        api_key="",
    )
    assert "error" in res
    assert "API key" in res["error"]


def test_generate_smart_playlist_library_only():
    with patch("requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": json.dumps({
                                    "playlist_title": "Library Rock Classics",
                                    "description": "Selected from local disks",
                                    "vibe_tags": ["rock"],
                                    "tracks": [
                                        {
                                            "title": "Hotel California",
                                            "artist": "Eagles",
                                            "album": "Hotel California",
                                            "rationale": "Classic acoustic intro"
                                        }
                                    ]
                                })
                            }
                        ]
                    }
                }
            ]
        }
        mock_post.return_value = mock_resp

        mock_state = MagicMock()
        mock_state.get_library_stats.return_value = {"total_tracks": 1}
        mock_state.get_all_tracks_with_provenance.return_value = [
            {"title": "Hotel California", "artist": "Eagles", "album": "Hotel California", "local_path": "/path/to/song.flac"}
        ]

        res = gemini_ai.generate_smart_playlist(
            prompt="rock essentials",
            api_key="fake-key",
            state=mock_state,
            library_only=True,
        )

        assert res.get("playlist_title") == "Library Rock Classics"
        assert len(res.get("tracks", [])) == 1
        assert res["tracks"][0]["in_library"] is True
        assert res["tracks"][0]["matched"] is True

        # Verify inventory was sent in prompt payload
        call_args = mock_post.call_args[1]
        sent_json = call_args["json"]
        prompt_text = sent_json["contents"][0]["parts"][0]["text"]
        assert "MANDATORY INVENTORY CONSTRAINT" in prompt_text
        assert "Hotel California" in prompt_text

