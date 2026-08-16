import json
import logging
from typing import Any, Optional
import requests
from alac_rip.am_api import search_apple_music_tracks
from alac_rip.state import StateManager

logger = logging.getLogger(__name__)

DEFAULT_GEMINI_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.0-flash-lite",
    "gemini-2.0-flash",
    "gemini-1.5-flash-8b",
    "gemini-1.5-flash",
    "gemini-1.5-flash-latest",
    "gemini-2.5-pro",
    "gemini-1.5-pro",
]


def list_available_gemini_models(api_key: str, timeout: float = 10.0) -> list[str]:
    """
    Queries Google Generative Language API to discover available models for this key.
    Returns a sorted list of model names supporting generateContent.
    """
    if not api_key:
        return DEFAULT_GEMINI_MODELS

    for api_version in ("v1beta", "v1"):
        url = f"https://generativelanguage.googleapis.com/{api_version}/models?key={api_key}"
        try:
            resp = requests.get(url, timeout=timeout)
            if resp.status_code == 200:
                data = resp.json()
                models = data.get("models", [])
                valid_models = []
                for m in models:
                    methods = m.get("supportedGenerationMethods", [])
                    if "generateContent" in methods:
                        name = m.get("name", "")
                        # name is usually 'models/gemini-2.0-flash'
                        clean_name = name.replace("models/", "")
                        valid_models.append(clean_name)
                if valid_models:
                    # Sort flash / lite models first for cost-effectiveness
                    def _sort_key(m: str) -> int:
                        m_low = m.lower()
                        if "flash-lite" in m_low or "flash-8b" in m_low:
                            return 0
                        if "2.0-flash" in m_low or "2.5-flash" in m_low:
                            return 1
                        if "flash" in m_low:
                            return 2
                        if "pro" in m_low:
                            return 3
                        return 4
                    valid_models.sort(key=_sort_key)
                    return valid_models
        except Exception as e:
            logger.debug(f"Failed to query Gemini models on {api_version}: {e}")
            continue

    return DEFAULT_GEMINI_MODELS


def generate_smart_playlist(
    prompt: str,
    api_key: str,
    state: Optional[StateManager] = None,
    track_count: int = 20,
    bearer_token: Optional[str] = None,
    storefront: str = "us",
    model: Optional[str] = None,
    timeout: float = 25.0,
) -> dict[str, Any]:
    """
    Uses Gemini API to curate a thematic playlist with musical rationale.
    Optionally enriches results by searching Apple Music if bearer_token is provided.
    Dynamically discovers available models to guarantee 100% compatibility.
    """
    if not prompt or not prompt.strip():
        return {"error": "Prompt cannot be empty", "tracks": []}
    if not api_key:
        return {"error": "Gemini API key not configured", "tracks": []}

    # Extract user taste context from library if available
    library_context = ""
    if state is not None:
        try:
            stats = state.get_library_stats()
            tracks = state.get_all_tracks_with_provenance()
            artists = list({t["artist"] for t in tracks if t.get("artist")})[:20]
            if artists:
                library_context = f"User's local library contains {stats.get('total_tracks', 0)} tracks across artists like: {', '.join(artists[:10])}."
        except Exception:
            pass

    system_instruction = (
        "You are an expert audiophile and music curator for a bit-perfect lossless music workstation. "
        "When given a prompt, generate a cohesive, exceptional tracklist matching the mood, genre, and aesthetic. "
        f"Aim for {track_count} tracks. Provide your output strictly as a valid JSON object with the following schema: "
        "{\"playlist_title\": string, \"description\": string, \"vibe_tags\": [string], \"tracks\": [{\"title\": string, \"artist\": string, \"album\": string, \"rationale\": string}]}"
    )

    user_query = f"{library_context}\n\nPrompt: {prompt.strip()}"

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": f"{system_instruction}\n\n{user_query}"}
                ]
            }
        ],
        "generationConfig": {
            "response_mime_type": "application/json",
            "temperature": 0.7,
        }
    }

    # Determine candidate models to try
    candidate_models: list[str] = []
    if model and model.strip():
        clean_user_model = model.strip().replace("models/", "")
        candidate_models.append(clean_user_model)

    # Add discovered online models
    discovered = list_available_gemini_models(api_key)
    for dm in discovered:
        if dm not in candidate_models:
            candidate_models.append(dm)

    # Fallback to defaults if empty
    for df in DEFAULT_GEMINI_MODELS:
        if df not in candidate_models:
            candidate_models.append(df)

    last_error = "No response from Gemini"
    playlist_obj = None
    for target_model in candidate_models:
        for api_version in ("v1beta", "v1"):
            url = f"https://generativelanguage.googleapis.com/{api_version}/models/{target_model}:generateContent?key={api_key}"
            try:
                resp = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=timeout)
                if resp.status_code == 404:
                    last_error = f"Model {target_model} not found on {api_version}"
                    continue
                if resp.status_code != 200:
                    return {"error": f"Gemini API returned HTTP {resp.status_code}: {resp.text}", "tracks": []}

                res_data = resp.json()
                candidates = res_data.get("candidates", [])
                if not candidates:
                    return {"error": "No response generated by Gemini", "tracks": []}

                content_part = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                playlist_obj = json.loads(content_part)
                break
            except Exception as e:
                last_error = str(e)
                continue
        if playlist_obj is not None:
            break
    else:
        return {"error": f"Gemini curation failed across candidate models: {last_error}", "tracks": []}

    try:
        # Enrich with Apple Music matching if bearer token is supplied
        if bearer_token and "tracks" in playlist_obj and isinstance(playlist_obj["tracks"], list):
            enriched_tracks = []
            for item in playlist_obj["tracks"]:
                t_name = item.get("title", "")
                a_name = item.get("artist", "")
                q = f"{a_name} {t_name}".strip()
                am_match = None
                if q:
                    try:
                        matches = search_apple_music_tracks(q, bearer_token, storefront=storefront, limit=3)
                        if matches:
                            am_match = matches[0]
                    except Exception:
                        pass
                enriched_tracks.append({
                    **item,
                    "am_track": am_match,
                    "matched": am_match is not None,
                })
            playlist_obj["tracks"] = enriched_tracks

        return playlist_obj
    except Exception as e:
        logger.error(f"Gemini playlist post-processing failed: {e}")
        return {"error": str(e), "tracks": []}
