import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from alac_rip.state import StateManager


# Supported fields for rules:
# - title (string)
# - artist (string)
# - album (string)
# - local_path (string)
# - downloaded_at (date/string ISO)
# - playlist (string, match membership)
# - format (string, inferred from extension or local_path e.g. ALAC, FLAC, M4A, AAC, MP3)

# Supported operators:
# - equals / not_equals
# - contains / not_contains
# - starts_with / ends_with
# - regex
# - in_past_days (numeric days for downloaded_at)
# - before_date / after_date (YYYY-MM-DD or ISO)
# - is_empty / is_not_empty


def _match_rule(track: dict, rule: dict) -> bool:
    field = rule.get("field", "").lower()
    operator = rule.get("operator", "contains").lower()
    val = rule.get("value", "")

    # Extract track value
    track_val: Any = ""
    if field == "title":
        track_val = track.get("title") or ""
    elif field == "artist":
        track_val = track.get("artist") or ""
    elif field == "album":
        track_val = track.get("album") or ""
    elif field == "local_path":
        track_val = track.get("local_path") or ""
    elif field == "downloaded_at":
        track_val = track.get("downloaded_at") or ""
    elif field == "playlist":
        # Check against list of playlists
        playlists = track.get("playlists") or []
        track_val = playlists
    elif field == "format":
        lp = track.get("local_path") or ""
        ext = lp.rsplit(".", 1)[-1].upper() if "." in lp else ""
        track_val = ext
    else:
        track_val = str(track.get(field, ""))

    # Playlist list matching
    if field == "playlist":
        pls = [p.lower() for p in track_val] if isinstance(track_val, list) else [str(track_val).lower()]
        target = str(val).lower()
        if operator == "equals":
            return target in pls
        elif operator == "not_equals":
            return target not in pls
        elif operator == "contains":
            return any(target in p for p in pls)
        elif operator == "not_contains":
            return not any(target in p for p in pls)
        elif operator == "is_empty":
            return len(pls) == 0
        elif operator == "is_not_empty":
            return len(pls) > 0
        return False

    # String operations
    s_val = str(track_val)
    target_val = str(val)

    if operator == "equals":
        return s_val.lower() == target_val.lower()
    elif operator == "not_equals":
        return s_val.lower() != target_val.lower()
    elif operator == "contains":
        return target_val.lower() in s_val.lower()
    elif operator == "not_contains":
        return target_val.lower() not in s_val.lower()
    elif operator == "starts_with":
        return s_val.lower().startswith(target_val.lower())
    elif operator == "ends_with":
        return s_val.lower().endswith(target_val.lower())
    elif operator == "regex":
        try:
            return bool(re.search(target_val, s_val, re.IGNORECASE))
        except re.error:
            return False
    elif operator == "is_empty":
        return not bool(s_val.strip())
    elif operator == "is_not_empty":
        return bool(s_val.strip())
    elif operator == "in_past_days":
        if not s_val:
            return False
        try:
            days = float(target_val)
            # Parse ISO date
            dt = datetime.fromisoformat(s_val.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            return (now - dt) <= timedelta(days=days)
        except (ValueError, TypeError):
            return False
    elif operator in ("before_date", "less_than"):
        if not s_val:
            return False
        try:
            dt = datetime.fromisoformat(s_val.replace("Z", "+00:00"))
            target_dt = datetime.fromisoformat(target_val.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if target_dt.tzinfo is None:
                target_dt = target_dt.replace(tzinfo=timezone.utc)
            return dt < target_dt
        except (ValueError, TypeError):
            return s_val < target_val
    elif operator in ("after_date", "greater_than"):
        if not s_val:
            return False
        try:
            dt = datetime.fromisoformat(s_val.replace("Z", "+00:00"))
            target_dt = datetime.fromisoformat(target_val.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if target_dt.tzinfo is None:
                target_dt = target_dt.replace(tzinfo=timezone.utc)
            return dt > target_dt
        except (ValueError, TypeError):
            return s_val > target_val

    return True


def evaluate_rules(tracks: list[dict], rules_config: dict) -> list[dict]:
    """
    rules_config schema:
    {
        "match": "all" | "any",  # default "all"
        "rules": [
            { "field": "artist", "operator": "contains", "value": "Beatles" },
            { "field": "format", "operator": "equals", "value": "M4A" }
        ],
        "sort_by": "downloaded_at" | "title" | "artist" | "album" | "random",
        "sort_order": "asc" | "desc",
        "limit": Optional[int]
    }
    """
    match_mode = rules_config.get("match", "all").lower()
    rules = rules_config.get("rules", [])
    sort_by = rules_config.get("sort_by", "downloaded_at")
    sort_order = rules_config.get("sort_order", "desc").lower()
    limit = rules_config.get("limit")

    filtered: list[dict] = []

    for t in tracks:
        if not rules:
            filtered.append(t)
            continue

        if match_mode == "any":
            if any(_match_rule(t, r) for r in rules):
                filtered.append(t)
        else:  # "all"
            if all(_match_rule(t, r) for r in rules):
                filtered.append(t)

    # Sort
    if sort_by == "random":
        import random
        # deterministic or random
        random.shuffle(filtered)
    else:
        reverse = (sort_order == "desc")
        def _get_key(item: dict) -> Any:
            v = item.get(sort_by)
            return ("" if v is None else str(v)).lower()

        filtered.sort(key=_get_key, reverse=reverse)

    if limit is not None and isinstance(limit, int) and limit > 0:
        filtered = filtered[:limit]

    return filtered


def evaluate_smart_playlist(state: StateManager, sp_id: int) -> dict:
    sp = state.get_smart_playlist(sp_id)
    if not sp:
        raise ValueError(f"Smart playlist with ID {sp_id} not found")

    try:
        rules_cfg = json.loads(sp["rules_json"])
    except json.JSONDecodeError:
        rules_cfg = {}

    all_tracks = state.get_all_tracks_with_provenance()
    matching_tracks = evaluate_rules(all_tracks, rules_cfg)

    return {
        "smart_playlist": sp,
        "tracks": matching_tracks,
        "count": len(matching_tracks),
    }
