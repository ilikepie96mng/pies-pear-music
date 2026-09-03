import json
import logging
from typing import Any, Optional
from pydantic import BaseModel, Field, ValidationError
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

_MAX_PROMPT_LENGTH = 2000
_MAX_TRACK_COUNT = 500


class GeminiTrackItem(BaseModel):
    title: str = Field(..., max_length=200)
    artist: str = Field(..., max_length=200)
    album: str = Field(default="", max_length=200)
    rationale: str = Field(default="", max_length=500)


class GeminiPlaylistSchema(BaseModel):
    playlist_title: str = Field(default="AI Curated Mix", max_length=200)
    description: str = Field(default="", max_length=1000)
    vibe_tags: list[str] = Field(default_factory=list, max_length=20)
    tracks: list[GeminiTrackItem] = Field(default_factory=list, max_length=_MAX_TRACK_COUNT)


def list_available_gemini_models(api_key: str, timeout: float = 10.0) -> list[str]:
    """
    Queries Google Generative Language API to discover available models for this key.
    Sends API key in x-goog-api-key header to prevent URL leak in logs/proxies.
    """
    if not api_key:
        return DEFAULT_GEMINI_MODELS

    headers = {"x-goog-api-key": api_key}
    for api_version in ("v1beta", "v1"):
        url = f"https://generativelanguage.googleapis.com/{api_version}/models"
        try:
            resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=False)
            if resp.status_code == 200:
                data = resp.json()
                models = data.get("models", [])
                valid_models = []
                for m in models:
                    methods = m.get("supportedGenerationMethods", [])
                    if "generateContent" in methods:
                        name = m.get("name", "")
                        clean_name = name.replace("models/", "")
                        valid_models.append(clean_name)
                if valid_models:
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
    library_only: bool = False,
    timeout: float = 25.0,
) -> dict[str, Any]:
    """
    Uses Gemini API to curate a thematic playlist with musical rationale.
    Passes API key securely via x-goog-api-key header and validates output against Pydantic schema.
    """
    if not prompt or not prompt.strip():
        return {"error": "Prompt cannot be empty", "tracks": []}
    if not api_key:
        return {"error": "Gemini API key not configured", "tracks": []}

    cleaned_prompt = prompt.strip()[:_MAX_PROMPT_LENGTH]
    clamped_track_count = max(0, min(track_count, _MAX_TRACK_COUNT))

    # Extract user taste context or inventory from library if available
    library_context = ""
    if state is not None:
        try:
            stats = state.get_library_stats()
            tracks = state.get_all_tracks_with_provenance()
            if library_only:
                # Build an inventory list for Gemini to strictly choose from
                inventory_lines = []
                for i, t in enumerate(tracks[:600], start=1):
                    t_title = t.get("title", "")
                    t_artist = t.get("artist", "")
                    t_album = t.get("album", "")
                    if t_title and t_artist:
                        inventory_lines.append(f"{i}. Title: \"{t_title}\" | Artist: \"{t_artist}\" | Album: \"{t_album}\"")
                inventory_str = "\n".join(inventory_lines)
                library_context = (
                    f"AVAILABLE LOCAL LIBRARY INVENTORY ({len(tracks)} total tracks in collection):\n"
                    f"{inventory_str}\n"
                )
            else:
                artists = list({t["artist"] for t in tracks if t.get("artist")})[:20]
                if artists:
                    library_context = f"User's local library contains {stats.get('total_tracks', 0)} tracks across artists like: {', '.join(artists[:10])}."
        except Exception:
            pass

    count_instruction = f"Aim for {clamped_track_count} tracks." if clamped_track_count > 0 else "Select a comprehensive, well-paced track count (e.g. 15 to 40 tracks) that best fulfills the prompt."

    version_rule = (
        "VERSION RULE: Always choose the canonical original studio album version of each song. "
        "Do NOT include alternate versions (such as Instrumental, Acoustic, Live, Remix, Remastered variation, Karaoke, or Demo) "
        "UNLESS the user's prompt explicitly asks for that specific variation (e.g. 'acoustic versions', 'instrumentals only', 'live concert')."
    )

    if library_only:
        system_instruction = (
            "You are an expert audiophile and music curator for a bit-perfect lossless music workstation. "
            "MANDATORY INVENTORY CONSTRAINT: You MUST select tracks ONLY from the provided AVAILABLE LOCAL LIBRARY INVENTORY. "
            "Do NOT invent, hallucinate, or suggest any track or artist that does not appear in the inventory list. "
            f"{version_rule} "
            f"{count_instruction} Provide your output strictly as a valid JSON object with the following schema: "
            "{\"playlist_title\": string, \"description\": string, \"vibe_tags\": [string], \"tracks\": [{\"title\": string, \"artist\": string, \"album\": string, \"rationale\": string}]}"
        )
    else:
        system_instruction = (
            "You are an expert audiophile and music curator for a bit-perfect lossless music workstation. "
            "When given a prompt, generate a cohesive, exceptional tracklist matching the mood, genre, and aesthetic. "
            f"{version_rule} "
            f"{count_instruction} Provide your output strictly as a valid JSON object with the following schema: "
            "{\"playlist_title\": string, \"description\": string, \"vibe_tags\": [string], \"tracks\": [{\"title\": string, \"artist\": string, \"album\": string, \"rationale\": string}]}"
        )

    user_query = f"{library_context}\n\nPrompt: {cleaned_prompt}"

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
            "maxOutputTokens": 8192,
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
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": api_key,
    }

    for target_model in candidate_models:
        for api_version in ("v1beta", "v1"):
            url = f"https://generativelanguage.googleapis.com/{api_version}/models/{target_model}:generateContent"
            try:
                resp = requests.post(url, json=payload, headers=headers, timeout=timeout, allow_redirects=False)
                if resp.status_code == 404:
                    last_error = f"Model {target_model} not found on {api_version}"
                    continue
                if resp.status_code != 200:
                    # Sanitize error message to avoid key/URL leak
                    return {"error": f"Gemini API returned status code {resp.status_code}", "tracks": []}

                res_data = resp.json()
                candidates = res_data.get("candidates", [])
                if not candidates:
                    return {"error": "No response generated by Gemini", "tracks": []}

                content_part = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                raw_json = json.loads(content_part)
                # Schema validation
                validated = GeminiPlaylistSchema.model_validate(raw_json)
                playlist_obj = validated.model_dump()
                break
            except ValidationError as ve:
                logger.warning(f"Gemini output failed schema validation on {target_model}: {ve}")
                last_error = "Model generated invalid schema"
                continue
            except Exception as e:
                logger.debug(f"Gemini request failed on {target_model}/{api_version}: {type(e).__name__}")
                last_error = "Network or parsing error"
                continue
        if playlist_obj is not None:
            break
    else:
        return {"error": f"Gemini curation failed across candidate models: {last_error}", "tracks": []}

    try:
        # Enrich with local library matching and Apple Music catalog matching
        if "tracks" in playlist_obj and isinstance(playlist_obj["tracks"], list):
            local_tracks = state.get_all_tracks_with_provenance() if state else []
            enriched_tracks = []
            for item in playlist_obj["tracks"]:
                t_name = (item.get("title") or "").strip()
                a_name = (item.get("artist") or "").strip()

                # 1. Check if track already exists in local library
                local_match = next(
                    (
                        lt for lt in local_tracks
                        if lt.get("title", "").lower() == t_name.lower()
                        and (not a_name or lt.get("artist", "").lower() == a_name.lower() or a_name.lower() in lt.get("artist", "").lower())
                    ),
                    None,
                )

                # 2. Search Apple Music catalog if bearer token is available
                q = f"{a_name} {t_name}".strip()
                am_match = None
                if bearer_token and q:
                    try:
                        matches = search_apple_music_tracks(q, bearer_token, storefront=storefront, limit=3)
                        if matches:
                            am_match = matches[0]
                    except Exception:
                        pass

                enriched_tracks.append({
                    **item,
                    "local_track": local_match,
                    "in_library": local_match is not None,
                    "am_track": am_match,
                    "matched": local_match is not None or am_match is not None,
                })
            playlist_obj["tracks"] = enriched_tracks

        return playlist_obj
    except Exception as e:
        logger.error(f"Gemini playlist post-processing failed: {e}")
        return {"error": "Failed to process playlist recommendations", "tracks": []}
