# Home Page & Last.fm Recommendations Design

## Goal

Add a Home page as the default landing screen showing recently added tracks and Last.fm-powered artist recommendations drawn from the user's library.

## Architecture

Three new pieces:
1. **`alac_rip/lastfm_api.py`** — Last.fm API client
2. **`GET /api/home`** — new backend endpoint
3. **`Home.svelte`** — new frontend component

The Home page is read-only and stateless — it fetches data from `/api/home` on mount and displays it. No new persistent state beyond the Last.fm API key in `config.yaml`.

## Last.fm API Client (`lastfm_api.py`)

**Key:** stored as `lastfm_api_key: <key>` in `config.yaml`. Added to `Config` dataclass and `PUT /config` endpoint.

**Methods:**

`get_similar_artists(artist: str, api_key: str, limit: int = 10) -> list[dict]`
- Calls `http://ws.audioscrobbler.com/2.0/?method=artist.getSimilar&artist=<name>&api_key=<key>&format=json&limit=<limit>`
- Returns list of `{name: str, match: float, url: str}`
- Raises `LastFmError` on network failure or non-200. Returns `[]` if artist not found (Last.fm returns error code 6).

**No auth beyond API key.** Last.fm `artist.getSimilar` is a public endpoint — no user account or OAuth needed.

## Recommendation Logic (in `/api/home` handler)

1. Query DB for all distinct artists across all playlists (`SELECT DISTINCT artist FROM tracks`)
2. Count tracks per artist, take top 10 by track count (most-represented artists in library)
3. For each of those artists, call `get_similar_artists(artist, limit=5)`
4. Flatten results, deduplicate by artist name (case-insensitive), filter out artists already in library
5. Sort by `match` score descending, return top 10
6. If `lastfm_api_key` is not configured, return `recommendations: []` with `recommendations_available: false`

## `/api/home` Endpoint

`GET /api/home` — no auth, returns JSON:

```json
{
  "recent_tracks": [
    {
      "title": "Wanderstop Part 1",
      "artist": "C418",
      "playlist_name": "Game OST",
      "downloaded_at": "2026-04-26T20:00:10",
      "artwork_url": "https://is1-ssl.mzstatic.com/.../8757.jpg/{w}x{h}bb.jpg"
    }
  ],
  "recommendations": [
    {
      "artist": "David Wise",
      "similar_to": "C418",
      "match": 0.87,
      "lastfm_url": "https://www.last.fm/music/David+Wise"
    }
  ],
  "recommendations_available": true,
  "last_sync": {
    "playlist_name": "Game OST",
    "synced_at": "2026-04-26T20:00:10",
    "new_tracks": 3
  }
}
```

`recent_tracks`: last 20 tracks by `downloaded_at` DESC across all playlists.
`last_sync`: most recent sync run from `sync_runs` table.

## Home Page Layout (`Home.svelte`)

Editorial layout — three vertical sections:

**1. Recently Added** (horizontal scroll row)
- 20 tracks rendered as 52×52px artwork cards + title + artist below
- If `artwork_url` is null: amber gradient placeholder square
- Clicking a track navigates to its playlist detail

**2. Recommended for You** (list)
- Only shown if `recommendations_available: true`
- Each row: artist name, "similar to X" in muted text, Last.fm link icon
- If `recommendations_available: false`: show a one-line prompt linking to Settings to add a Last.fm API key

**3. Sync Status Strip** (bottom bar)
- Last sync: playlist name, how long ago, how many tracks added
- "Sync All" button (amber)

## Settings Integration

Add `lastfm_api_key` field to the Settings screen:
- Text input, label "Last.fm API Key", placeholder "Get a free key at last.fm/api"
- Saves via existing `PUT /config` endpoint
- Masked display (password input type)

## Error Handling

- Last.fm API key missing: return empty recommendations with `recommendations_available: false`, no error shown
- Last.fm API rate limit or network failure: return empty recommendations, log warning server-side, do not surface to user
- No tracks in DB yet: `recent_tracks: []`, show "Sync a playlist to get started" message
- `sync_runs` table empty: `last_sync: null`, omit sync status strip

## Testing

- `test_lastfm_api.py`: mock HTTP responses for `get_similar_artists` — success, artist not found (error 6), network failure
- `test_home_endpoint.py`: mock `StateManager` and `lastfm_api` — returns correct shape, handles missing API key, handles empty library
- Manual: verify recommendations appear after adding Last.fm key, verify "no key" prompt links to Settings
