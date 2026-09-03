from alac_rip.state import Track


def test_library_profile_omits_local_paths_and_aggregates_tracks(state):
    state.add_track(Track("1", "Song", "Artist", "Album", "/private/music/song.m4a", "2026-01-01T00:00:00"))

    profile = state.get_library_profile()

    assert profile == {
        "track_count": 1,
        "artists": [{"name": "Artist", "track_count": 1}],
        "albums": [{"artist": "Artist", "name": "Album", "track_count": 1}],
    }
    assert "/private" not in str(profile)
