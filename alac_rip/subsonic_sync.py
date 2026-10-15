"""
Subsonic / Navidrome Universal Bidirectional Playlist Synchronization Engine.

Enables seamless real-time playlist synchronization between Navidrome,
Subsonic desktop players (Feishin), mobile clients (Symfonium),
and Pies Pear Music.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
import requests

from alac_rip.integrations import validate_integration_url
from alac_rip.state import Playlist, StateManager, Track

logger = logging.getLogger(__name__)


class SubsonicError(Exception):
    """Raised when a Subsonic API request fails or returns an error response."""
    def __init__(self, message: str, code: Optional[int] = None):
        super().__init__(message)
        self.code = code


class SubsonicClient:
    """
    Subsonic / OpenSubsonic 1.16.1 client for Navidrome playlist management.
    """

    def __init__(
        self,
        server_url: str,
        user: str,
        token: str,
        salt: str = "",
        timeout: float = 10.0,
    ):
        self.raw_url = server_url.strip().rstrip("/") if server_url else ""
        self.user = user.strip() if user else ""
        self.token = token.strip() if token else ""
        self.salt = salt.strip() if salt else ""
        self.timeout = timeout
        self._song_id_cache: dict[str, str] = {}  # local_key -> navidrome_song_id

    @property
    def is_configured(self) -> bool:
        return bool(self.raw_url and self.user and self.token)

    def _get_base_url(self) -> str:
        if not self.raw_url:
            raise SubsonicError("Navidrome server URL is not configured")
        try:
            return validate_integration_url(self.raw_url)
        except ValueError as exc:
            raise SubsonicError(f"Invalid Navidrome server URL: {exc}") from exc

    def _build_params(self, extra: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        params: dict[str, Any] = {
            "u": self.user,
            "v": "1.16.1",
            "c": "PiesPearMusic",
            "f": "json",
        }
        if self.salt:
            params["t"] = self.token
            params["s"] = self.salt
        else:
            params["p"] = self.token

        if extra:
            params.update(extra)
        return params

    def _request(
        self,
        endpoint: str,
        params: Optional[dict[str, Any]] = None,
        method: str = "GET",
    ) -> dict[str, Any]:
        base_url = self._get_base_url()
        url = f"{base_url}/rest/{endpoint.lstrip('/')}"
        query_params = self._build_params(params)

        try:
            if method.upper() == "POST":
                resp = requests.post(url, data=query_params, timeout=self.timeout, allow_redirects=False)
            else:
                resp = requests.get(url, params=query_params, timeout=self.timeout, allow_redirects=False)
        except requests.RequestException as exc:
            raise SubsonicError(f"Network error contacting Navidrome: {exc}") from exc

        if resp.status_code != 200:
            raise SubsonicError(f"Navidrome returned HTTP {resp.status_code}")

        try:
            data = resp.json()
        except Exception as exc:
            raise SubsonicError("Navidrome returned invalid non-JSON response") from exc

        sub_resp = data.get("subsonic-response", {})
        status = sub_resp.get("status")
        if status != "ok":
            err = sub_resp.get("error", {})
            msg = err.get("message", "Unknown Subsonic error")
            code = err.get("code")
            raise SubsonicError(f"Subsonic API error ({code}): {msg}", code=code)

        return sub_resp

    def ping(self) -> tuple[bool, str]:
        """Test server connectivity and credentials."""
        try:
            resp = self._request("ping.view")
            version = resp.get("version", "unknown")
            return True, f"Connected to Subsonic API v{version}"
        except Exception as exc:
            return False, str(exc)

    def get_playlists(self) -> list[dict[str, Any]]:
        """
        Retrieve all playlists from Navidrome.
        Each item contains: id, name, comment, owner, public, songCount, duration, created, changed.
        """
        resp = self._request("getPlaylists.view")
        playlists_data = resp.get("playlists", {})
        playlist_list = playlists_data.get("playlist", [])
        if isinstance(playlist_list, dict):
            playlist_list = [playlist_list]
        return playlist_list

    def get_playlist(self, playlist_id: str) -> dict[str, Any]:
        """
        Retrieve full playlist details including all track entries.
        """
        resp = self._request("getPlaylist.view", {"id": playlist_id})
        playlist = resp.get("playlist", {})
        entries = playlist.get("entry", [])
        if isinstance(entries, dict):
            entries = [entries]
        playlist["entry"] = entries
        return playlist

    def create_playlist(
        self,
        name: str,
        song_ids: Optional[list[str]] = None,
        playlist_id: Optional[str] = None,
    ) -> str:
        """
        Create a new playlist or replace the tracklist of an existing playlist.
        In OpenSubsonic, passing playlistId updates that playlist with the given songIds.
        """
        params: dict[str, Any] = {}
        if playlist_id:
            params["playlistId"] = playlist_id
        if name:
            params["name"] = name
        if song_ids:
            params["songId"] = song_ids

        resp = self._request("createPlaylist.view", params)
        pl = resp.get("playlist", {})
        returned_id = pl.get("id") or playlist_id or ""
        return str(returned_id)

    def update_playlist(
        self,
        playlist_id: str,
        name: Optional[str] = None,
        comment: Optional[str] = None,
        public: Optional[bool] = None,
        song_ids_to_add: Optional[list[str]] = None,
        song_indices_to_remove: Optional[list[int]] = None,
    ) -> bool:
        """
        Update metadata or perform incremental adds/removals on a playlist.
        """
        params: dict[str, Any] = {"playlistId": playlist_id}
        if name is not None:
            params["name"] = name
        if comment is not None:
            params["comment"] = comment
        if public is not None:
            params["public"] = "true" if public else "false"
        if song_ids_to_add:
            params["songIdToAdd"] = song_ids_to_add
        if song_indices_to_remove:
            params["songIndexToRemove"] = song_indices_to_remove

        self._request("updatePlaylist.view", params)
        return True

    def delete_playlist(self, playlist_id: str) -> bool:
        """Delete a playlist from Navidrome."""
        self._request("deletePlaylist.view", {"id": playlist_id})
        return True

    def search_songs(self, query: str, count: int = 20) -> list[dict[str, Any]]:
        """Search songs in Navidrome catalog by query string."""
        if not query.strip():
            return []
        try:
            resp = self._request("search3.view", {"query": query.strip(), "songCount": count})
            songs = resp.get("searchResult3", {}).get("song", [])
            if isinstance(songs, dict):
                songs = [songs]
            return songs
        except Exception as exc:
            logger.debug(f"Subsonic song search error for '{query}': {exc}")
            return []

    def resolve_song_id(self, track: Track) -> Optional[str]:
        """
        Find the Navidrome songId corresponding to a local library Track.
        Matches by relative path first, then by artist + title.
        """
        cache_key = track.local_path or f"{track.artist}::{track.title}"
        if cache_key in self._song_id_cache:
            return self._song_id_cache[cache_key]

        # Extract normalized relative path (e.g. "artists/Artist/Album/01 - Title.flac")
        rel_path = ""
        if track.local_path:
            norm_path = track.local_path.replace("\\", "/")
            if "/artists/" in norm_path:
                rel_path = "artists/" + norm_path.split("/artists/", 1)[1]
            elif "artists/" in norm_path:
                rel_path = "artists/" + norm_path.split("artists/", 1)[1]

        # Search Navidrome by title and artist
        search_query = f"{track.artist} {track.title}".strip()
        candidates = self.search_songs(search_query, count=15)

        # 1. Match by relative path suffix
        if rel_path:
            for c in candidates:
                c_path = (c.get("path") or "").replace("\\", "/")
                if c_path.endswith(rel_path) or rel_path.endswith(c_path):
                    song_id = str(c.get("id"))
                    self._song_id_cache[cache_key] = song_id
                    return song_id

        # 2. Match by exact normalized title + artist
        t_clean = _normalize_text(track.title)
        a_clean = _normalize_text(track.artist)
        for c in candidates:
            c_title = _normalize_text(c.get("title", ""))
            c_artist = _normalize_text(c.get("artist", ""))
            if c_title == t_clean and c_artist == a_clean:
                song_id = str(c.get("id"))
                self._song_id_cache[cache_key] = song_id
                return song_id

        # 3. Fallback: first candidate if title matches
        for c in candidates:
            c_title = _normalize_text(c.get("title", ""))
            if c_title == t_clean:
                song_id = str(c.get("id"))
                self._song_id_cache[cache_key] = song_id
                return song_id

        return None


def _normalize_text(text: str) -> str:
    """Lowercase and strip non-alphanumeric noise for robust audio metadata comparison."""
    if not text:
        return ""
    clean = re.sub(r"[^\w\s]", "", text.lower())
    return " ".join(clean.split())


class SubsonicSyncEngine:
    """
    Bidirectional synchronization engine between Navidrome Subsonic playlists
    and Pies Pear Music local library state.
    """

    def __init__(
        self,
        state: StateManager,
        client: SubsonicClient,
        music_dir: Optional[Path] = None,
    ):
        self.state = state
        self.client = client
        self.music_dir = music_dir

    def sync_all(self) -> dict[str, Any]:
        """
        Execute a full bidirectional sync cycle between Navidrome and Pear Music.
        """
        if not self.client.is_configured:
            return {"status": "skipped", "message": "Navidrome client not configured"}

        results = {
            "status": "ok",
            "imported_from_remote": 0,
            "updated_local": 0,
            "pushed_to_remote": 0,
            "errors": [],
        }

        try:
            remote_playlists = self.client.get_playlists()
        except Exception as exc:
            logger.warning(f"Subsonic sync: failed to fetch remote playlists: {exc}")
            results["status"] = "error"
            results["errors"].append(str(exc))
            return results

        remote_by_id: dict[str, dict[str, Any]] = {str(p["id"]): p for p in remote_playlists if "id" in p}
        remote_by_name: dict[str, dict[str, Any]] = {p.get("name", ""): p for p in remote_playlists if p.get("name")}

        local_playlists = self.state.get_playlists()
        local_by_name: dict[str, Playlist] = {p.name: p for p in local_playlists}
        local_by_nav_id: dict[str, Playlist] = {p.navidrome_id: p for p in local_playlists if p.navidrome_id}

        # ── Step 1: Inbound sync (Remote -> Local) ───────────────────────────
        for remote_id, r_pl in remote_by_id.items():
            r_name = r_pl.get("name", "").strip()
            if not r_name:
                continue

            r_changed = r_pl.get("changed") or r_pl.get("created") or ""
            local_match = local_by_nav_id.get(remote_id) or local_by_name.get(r_name)

            if local_match is None:
                # New playlist created on Navidrome / Feishin / Symfonium -> Import to Pear Music
                try:
                    self._import_remote_playlist(r_name, remote_id, r_changed)
                    results["imported_from_remote"] += 1
                except Exception as exc:
                    logger.error(f"Failed to import remote playlist '{r_name}': {exc}")
                    results["errors"].append(f"Import {r_name}: {exc}")
            else:
                # Existing playlist: compare timestamps for bidirectional reconciliation
                try:
                    updated = self._reconcile_existing_playlist(local_match, remote_id, r_name, r_changed)
                    if updated == "pulled":
                        results["updated_local"] += 1
                    elif updated == "pushed":
                        results["pushed_to_remote"] += 1
                except Exception as exc:
                    logger.error(f"Failed to reconcile playlist '{r_name}': {exc}")
                    results["errors"].append(f"Reconcile {r_name}: {exc}")

        # ── Step 2: Outbound sync (Local-only -> Remote) ─────────────────────
        # Find any playlists created in Pear Music that aren't on Navidrome yet
        for local_name, l_pl in local_by_name.items():
            if not l_pl.navidrome_id and local_name not in remote_by_name:
                try:
                    new_nav_id = self.push_local_playlist_to_remote(local_name)
                    if new_nav_id:
                        results["pushed_to_remote"] += 1
                except Exception as exc:
                    logger.error(f"Failed to push new local playlist '{local_name}' to Navidrome: {exc}")
                    results["errors"].append(f"Push {local_name}: {exc}")

        return results

    def _import_remote_playlist(self, name: str, remote_id: str, remote_changed: str) -> None:
        """Import a newly discovered Navidrome playlist into local library state."""
        full_remote = self.client.get_playlist(remote_id)
        entries = full_remote.get("entry", [])

        # Map remote songs to local tracks
        matched_track_ids = self._resolve_remote_entries_to_local_ids(entries)

        # Create playlist in local database
        dummy_url = f"https://subsonic.local/playlist/{remote_id}"
        self.state.add_playlist(name, dummy_url)
        self.state.link_playlist_navidrome(name, remote_id, remote_changed)
        self.state.set_playlist_tracks(name, matched_track_ids)
        logger.info(f"Subsonic sync: imported '{name}' ({len(matched_track_ids)} tracks) from Navidrome")

    def _reconcile_existing_playlist(
        self,
        local: Playlist,
        remote_id: str,
        remote_name: str,
        remote_changed: str,
    ) -> str:
        """
        Reconcile a playlist that exists both locally and on Navidrome using timestamp diffing.
        Returns: 'pulled', 'pushed', or 'noop'
        """
        # Ensure local link is recorded
        if local.navidrome_id != remote_id:
            self.state.link_playlist_navidrome(local.name, remote_id, remote_changed)

        remote_dt = _parse_iso_datetime(remote_changed)
        last_synced_dt = _parse_iso_datetime(local.remote_changed_at)
        local_modified_dt = _parse_iso_datetime(local.last_local_modified)

        # Check if remote was changed after our last sync
        remote_is_newer = False
        if remote_dt:
            if not last_synced_dt or remote_dt > last_synced_dt:
                remote_is_newer = True

        # Check if local was modified after our last sync
        local_is_newer = False
        if local_modified_dt:
            if not last_synced_dt or local_modified_dt > last_synced_dt:
                local_is_newer = True

        # Conflict Resolution:
        # If remote is newer and local wasn't touched, or remote is strictly newer than local edit -> Pull
        if remote_is_newer and (not local_is_newer or (remote_dt and local_modified_dt and remote_dt >= local_modified_dt)):
            full_remote = self.client.get_playlist(remote_id)
            entries = full_remote.get("entry", [])
            matched_track_ids = self._resolve_remote_entries_to_local_ids(entries)
            self.state.set_playlist_tracks(local.name, matched_track_ids)
            self.state.update_playlist_remote_metadata(local.name, remote_changed)
            logger.info(f"Subsonic sync: pulled updates for '{local.name}' ({len(matched_track_ids)} tracks)")
            return "pulled"

        # If local was edited after the last sync -> Push to Navidrome
        if local_is_newer and (not remote_is_newer or (local_modified_dt and remote_dt and local_modified_dt > remote_dt)):
            self.push_local_playlist_to_remote(local.name, remote_id=remote_id)
            return "pushed"

        return "noop"

    def _resolve_remote_entries_to_local_ids(self, entries: list[dict[str, Any]]) -> list[str]:
        """Convert a list of Subsonic track dicts into local Track IDs."""
        matched_ids: list[str] = []
        for e in entries:
            path = e.get("path") or ""
            title = e.get("title") or ""
            artist = e.get("artist") or ""

            # 1. Match by path
            track = self.state.find_track_by_path(path)
            # 2. Fallback to artist + title
            if not track and title and artist:
                track = self.state.find_track_by_title_artist(title, artist)

            if track:
                matched_ids.append(track.track_id)
            else:
                logger.debug(f"Subsonic sync: track '{artist} - {title}' ({path}) not found in local library")
        return matched_ids

    def push_local_playlist_to_remote(self, name: str, remote_id: Optional[str] = None) -> Optional[str]:
        """
        Push local playlist tracks and metadata to Navidrome.
        If remote_id is provided, updates the existing playlist; otherwise creates a new one.
        """
        local_tracks = self.state.get_playlist_tracks(name)
        song_ids: list[str] = []

        for t in local_tracks:
            sid = self.client.resolve_song_id(t)
            if sid:
                song_ids.append(sid)

        target_id = remote_id or (self.state.get_playlist(name).navidrome_id if self.state.get_playlist(name) else None)

        if target_id:
            # Update existing playlist on Navidrome
            self.client.create_playlist(name=name, song_ids=song_ids, playlist_id=target_id)
            now_iso = datetime.now().isoformat()
            self.state.update_playlist_remote_metadata(name, now_iso)
            logger.info(f"Subsonic sync: pushed {len(song_ids)} tracks to existing Navidrome playlist '{name}' ({target_id})")
            return target_id
        else:
            # Create new playlist on Navidrome
            new_id = self.client.create_playlist(name=name, song_ids=song_ids)
            now_iso = datetime.now().isoformat()
            self.state.link_playlist_navidrome(name, new_id, now_iso)
            logger.info(f"Subsonic sync: created Navidrome playlist '{name}' with {len(song_ids)} tracks (ID: {new_id})")
            return new_id


def _parse_iso_datetime(dt_str: Optional[str]) -> Optional[datetime]:
    """Parse common ISO 8601 timestamps gracefully."""
    if not dt_str:
        return None
    clean = dt_str.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(clean)
    except Exception:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(dt_str[:19], fmt)
        except Exception:
            continue
    return None
