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
