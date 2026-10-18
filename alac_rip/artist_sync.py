"""
Ultra-fast release checker for subscribed artists on Apple Music and Tidal.

Queries provider catalog APIs to check for newly released albums, EPs, and singles,
diffing against the user's local library and subscription release history.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

import requests

from alac_rip import am_api
from alac_rip.state import StateManager, SubscribedArtist, PendingRelease

try:
    from alac_rip.tidal_api import TidalClient, extract_tidal_artist, format_tidal_image
except ImportError:
    TidalClient = None  # type: ignore
    extract_tidal_artist = None  # type: ignore
    format_tidal_image = None  # type: ignore

logger = logging.getLogger("alac_rip.artist_sync")


def _fetch_apple_music_artist_albums(
    artist_id_or_url: str,
    bearer_token: Optional[str] = None,
    storefront: str = "us",
    timeout: int = 10,
) -> tuple[str, str, Optional[str], list[dict[str, Any]]]:
    """
    Fetch artist information and albums using Apple Music AMP API or iTunes lookup fallback.
    Returns: (artist_name, artist_url, artwork_url, albums_list)
    """
    artist_name = "Unknown Artist"
    artist_url = ""
    artwork_url = None
    albums: list[dict[str, Any]] = []

    # Clean artist ID
    artist_id = str(artist_id_or_url)
    m = re.search(r"/artist/(?:[^/]+/)?(\d+)", artist_id)
    if m:
        artist_id = m.group(1)
    else:
        m_num = re.search(r"(\d+)(?:[/?]|$)", artist_id)
        if m_num:
            artist_id = m_num.group(1)

    # 1. Try AMP API if bearer token is available
    if bearer_token:
        try:
            disco = am_api.fetch_artist_discography(artist_id, bearer_token, storefront=storefront)
            artist_name = disco.get("name") or artist_name
            artist_url = disco.get("url") or f"https://music.apple.com/{storefront}/artist/{artist_id}"
            artwork_url = disco.get("artwork_url")
            for alb in disco.get("albums", []):
                albums.append({
                    "id": str(alb.get("id")),
                    "title": alb.get("title") or "Unknown Title",
                    "artist": alb.get("artist") or artist_name,
                    "release_date": alb.get("release_date"),
                    "track_count": alb.get("track_count") or 0,
                    "is_single": bool(alb.get("is_single")),
                    "url": alb.get("url") or f"https://music.apple.com/{storefront}/album/{alb.get('id')}",
                    "artwork_url": alb.get("artwork_url"),
                })
            return artist_name, artist_url, artwork_url, albums
        except Exception as exc:
            logger.debug(f"AMP API artist fetch failed for {artist_id}, falling back to iTunes lookup: {exc}")

    # 2. Fast iTunes lookup fallback (no bearer token required, ~100-150ms)
    try:
        url = f"https://itunes.apple.com/lookup?id={artist_id}&entity=album&limit=100&country={storefront}"
        r = requests.get(url, timeout=timeout)
        if r.status_code == 200:
            results = r.json().get("results", [])
            for item in results:
                wrapper_type = item.get("wrapperType")
                if wrapper_type == "artist":
                    artist_name = item.get("artistName") or artist_name
                    artist_url = item.get("artistLinkUrl") or artist_url
                elif wrapper_type == "collection":
                    alb_id = str(item.get("collectionId"))
                    alb_name = item.get("collectionName") or "Unknown Title"
                    track_count = int(item.get("trackCount") or 0)
                    is_single = track_count <= 2 or " - Single" in alb_name or " - EP" in alb_name
                    art = item.get("artworkUrl100")
                    if art and "{w}" not in art:
                        art = art.replace("100x100bb", "{w}x{h}bb")
                    albums.append({
                        "id": alb_id,
                        "title": alb_name,
                        "artist": item.get("artistName") or artist_name,
                        "release_date": (item.get("releaseDate") or "")[:10],
                        "track_count": track_count,
                        "is_single": is_single,
                        "url": item.get("collectionViewUrl") or f"https://music.apple.com/{storefront}/album/{alb_id}",
                        "artwork_url": art,
                    })
    except Exception as exc:
        logger.warning(f"iTunes fallback failed for artist {artist_id}: {exc}")

    return artist_name, artist_url, artwork_url, albums


def _fetch_tidal_artist_albums(
    artist_id_or_url: str,
    client: Optional[Any] = None,
) -> tuple[str, str, Optional[str], list[dict[str, Any]]]:
    """
    Fetch artist information and albums using Tidal API.
    Returns: (artist_name, artist_url, artwork_url, albums_list)
    """
    artist_name = "Unknown Artist"
    artist_url = ""
    artwork_url = None
    albums: list[dict[str, Any]] = []

    # Clean artist ID
    artist_id = str(artist_id_or_url).strip()
    if artist_id.startswith("tidal:artist:"):
        artist_id = artist_id.replace("tidal:artist:", "")
    elif artist_id.startswith("tidal:"):
        artist_id = artist_id.replace("tidal:", "")
    elif "tidal.com" in artist_id:
        m = re.search(r"/artist/(\d+)", artist_id)
        if m:
            artist_id = m.group(1)

    if client is None:
        try:
            if TidalClient is not None:
                client = TidalClient()
        except Exception:
            return artist_name, artist_url, artwork_url, albums

    if client is None:
        return artist_name, artist_url, artwork_url, albums

    try:
        art = client.get_artist(artist_id)
        if art:
            artist_name = art.get("name") or artist_name
            artist_url = f"https://tidal.com/browse/artist/{artist_id}"
            pic = art.get("picture")
            if pic and format_tidal_image is not None:
                artwork_url = format_tidal_image(pic)
    except Exception as exc:
        logger.debug(f"Failed to fetch Tidal artist info for {artist_id}: {exc}")

    try:
        raw_albums = client.get_artist_albums(artist_id, limit=100)
        for a in raw_albums:
            alb_id = f"tidal:{a['id']}"
            alb_title = a.get("title") or "Unknown Title"
            art_name = extract_tidal_artist(a, fallback=artist_name) if extract_tidal_artist is not None else artist_name
            release_date = a.get("releaseDate") or str(a.get("year") or "")
            track_count = int(a.get("numberOfTracks") or 0)
            is_single = a.get("type") in ("SINGLE", "EP") or track_count <= 2
            alb_url = f"https://tidal.com/browse/album/{a['id']}"
            cover = a.get("cover")
            art_cover = format_tidal_image(cover) if (cover and format_tidal_image is not None) else None

            albums.append({
                "id": alb_id,
                "title": alb_title,
                "artist": art_name,
                "release_date": release_date[:10] if release_date else None,
                "track_count": track_count,
                "is_single": is_single,
                "url": alb_url,
                "artwork_url": art_cover,
            })
    except Exception as exc:
        logger.warning(f"Failed to fetch Tidal artist albums for {artist_id}: {exc}")

    return artist_name, artist_url, artwork_url, albums


def _is_recent_release(release_date_str: Optional[str], max_days: int = 60) -> bool:
    """Return True if release_date is within max_days or could not be parsed."""
    if not release_date_str:
        return True
    try:
        dt_str = str(release_date_str).strip()[:10]
        if len(dt_str) == 4:
            return int(dt_str) >= datetime.now().year
        rd = datetime.fromisoformat(dt_str)
        return (datetime.now() - rd).days <= max_days
    except Exception:
        return True


class ArtistReleaseChecker:
    """Manages check runs and enqueuing for subscribed artists."""

    def __init__(
        self,
        state: StateManager,
        storefront: str = "us",
        music_dir: Optional[Any] = None,
        tidal_client: Optional[Any] = None,
        get_tidal_client: Optional[Callable[[], Any]] = None,
        on_queue_wake: Optional[Callable[[], None]] = None,
        on_broadcast_event: Optional[Callable[[dict[str, Any]], None]] = None,
    ):
        self.state = state
        self.storefront = storefront or "us"
        self.music_dir = Path(music_dir) if music_dir else None
        self.tidal_client = tidal_client
        self.get_tidal_client = get_tidal_client
        self.on_queue_wake = on_queue_wake
        self.on_broadcast_event = on_broadcast_event

    def clean_existing_pending_releases(self) -> int:
        """Scan available pending releases and dismiss any that are already in library."""
        pending = self.state.get_pending_releases(status="available")
        cleaned_count = 0
        for p in pending:
            if self.state.has_album_in_library(
                p.artist_name,
                p.title,
                is_single=p.is_single,
                music_dir=self.music_dir,
            ):
                self.state.update_pending_release_status(p.id, "dismissed")
                cleaned_count += 1
        return cleaned_count

    def check_artist(
        self,
        artist: SubscribedArtist,
        bearer_token: Optional[str] = None,
        force_auto_download: Optional[bool] = None,
    ) -> dict[str, Any]:
        """
        Check an individual artist for new releases.
        Returns a summary dict with detected releases and enqueued downloads.
        """
        auto_dl = artist.auto_download if force_auto_download is None else force_auto_download
        detected_new: list[dict[str, Any]] = []
        enqueued: list[int] = []

        is_tidal = (artist.service == "tidal") or str(artist.artist_id).startswith("tidal:")

        if is_tidal:
            client = self.tidal_client
            if client is None and self.get_tidal_client is not None:
                try:
                    client = self.get_tidal_client()
                except Exception:
                    client = None
            artist_name, artist_url, art_url, albums = _fetch_tidal_artist_albums(
                artist.artist_id,
                client=client,
            )
        elif artist.service == "apple_music":
            artist_name, artist_url, art_url, albums = _fetch_apple_music_artist_albums(
                artist.artist_id,
                bearer_token=bearer_token,
                storefront=self.storefront,
            )
        else:
            # Service not currently supported for automated catalog polling
            return {
                "artist_id": artist.artist_id,
                "artist_name": artist.name,
                "service": artist.service,
                "new_releases": [],
                "enqueued": [],
                "status": "unsupported_service",
            }

        known_ids = set(artist.known_album_ids or [])
        updated_known_ids = set(known_ids)
        is_first_check = len(known_ids) == 0

        for alb in albums:
            alb_id = str(alb["id"])
            updated_known_ids.add(alb_id)

            # If already known from previous check, skip
            if alb_id in known_ids:
                continue

            # Check if user already has this album in their local library or filesystem
            if self.state.has_album_in_library(
                artist.name,
                alb["title"],
                is_single=alb.get("is_single", False),
                music_dir=self.music_dir,
            ):
                continue

            # On first check / initial baseline:
            # Don't flood the dashboard with older catalog releases (e.g. from 2018-2023).
            # Only treat albums released within the last 60 days (or without date) as new releases.
            if is_first_check:
                rel_date = alb.get("release_date")
                if rel_date and not _is_recent_release(rel_date, max_days=60):
                    continue

            # New release discovered!
            rel = self.state.record_pending_release(
                artist_id=artist.artist_id,
                artist_name=artist.name,
                album_id=alb_id,
                title=alb["title"],
                release_date=alb.get("release_date"),
                track_count=alb.get("track_count", 0),
                is_single=alb.get("is_single", False),
                url=alb["url"],
                artwork_url=alb.get("artwork_url"),
            )
            detected_new.append({
                "id": rel.id,
                "album_id": alb_id,
                "title": alb["title"],
                "release_date": alb.get("release_date"),
                "is_single": alb.get("is_single", False),
                "url": alb["url"],
                "artwork_url": alb.get("artwork_url"),
            })

            # If auto-download is enabled, immediately enqueue into download_queue
            if auto_dl:
                item_is_tidal = is_tidal or ("tidal.com" in alb.get("url", "")) or str(alb.get("url", "")).startswith("tidal:")
                item_format = "FLAC" if item_is_tidal else "ALAC"
                job_id = self.state.enqueue_download_job(
                    url=alb["url"],
                    title=f"{alb['title']} ({alb.get('release_date', '')[:4] or 'New'})",
                    artist=artist.name,
                    album=alb["title"],
                    artwork_url=alb.get("artwork_url"),
                    format=item_format,
                    item_type="album",
                    total_tracks=alb.get("track_count", 0),
                )
                enqueued.append(job_id)
                self.state.update_pending_release_status(rel.id, "downloading")

        # Update artist state
        now_ts = datetime.now().isoformat()
        self.state.update_subscribed_artist(
            artist.artist_id,
            service=artist.service,
            last_checked=now_ts,
            known_album_ids=sorted(updated_known_ids),
        )


        if enqueued and self.on_queue_wake:
            self.on_queue_wake()

        if detected_new and self.on_broadcast_event:
            self.on_broadcast_event({
                "event": "new_artist_releases",
                "artist_name": artist.name,
                "count": len(detected_new),
                "enqueued": len(enqueued),
            })

        return {
            "artist_id": artist.artist_id,
            "artist_name": artist.name,
            "service": artist.service,
            "new_releases": detected_new,
            "new_releases_count": len(detected_new),
            "enqueued_job_ids": enqueued,
            "enqueued_count": len(enqueued),
            "total_catalog_albums": len(albums),
        }

    def check_all_subscribed_artists(
        self,
        bearer_token: Optional[str] = None,
        service: Optional[str] = None,
    ) -> dict[str, Any]:
        """Check all subscribed artists for new releases."""
        artists = self.state.get_subscribed_artists(service=service)
        results = []
        total_new = 0
        total_enqueued = 0

        # Try to obtain bearer token if not provided
        if not bearer_token:
            try:
                bearer_token = am_api.fetch_bearer_token()
            except Exception:
                bearer_token = None

        for artist in artists:
            res = self.check_artist(artist, bearer_token=bearer_token)
            results.append(res)
            total_new += len(res.get("new_releases", []))
            total_enqueued += len(res.get("enqueued_job_ids", []))

        return {
            "checked_artists_count": len(artists),
            "total_new_releases": total_new,
            "total_enqueued": total_enqueued,
            "results": results,
            "checked_at": datetime.now().isoformat(),
        }
