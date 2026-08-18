import json
import pytest
from pathlib import Path
from alac_rip.state import StateManager, Track
from alac_rip.smart_playlists import evaluate_rules, evaluate_smart_playlist


@pytest.fixture
def temp_state(tmp_path: Path) -> StateManager:
    db_file = tmp_path / "test_smart_playlists.db"
    state = StateManager(db_file)
    # Seed tracks
    now_iso = "2026-08-15T12:00:00"
    older_iso = "2026-07-01T08:00:00"
    state.add_track(Track("t1", "Come Together", "The Beatles", "Abbey Road", "/music/beatles/come_together.m4a", now_iso))
    state.add_track(Track("t2", "Something", "The Beatles", "Abbey Road", "/music/beatles/something.flac", older_iso))
    state.add_track(Track("t3", "Get Lucky", "Daft Punk", "Random Access Memories", "/music/daft/get_lucky.m4a", now_iso))
    state.add_track(Track("t4", "Starboy", "The Weeknd", "Starboy", "/music/weeknd/starboy.mp3", older_iso))

    # Seed playlist relationships
    state.add_playlist("Rock Classics", "https://music.apple.com/us/playlist/rock-classics")
    state.add_track_to_playlist("Rock Classics", "t1")
    state.add_track_to_playlist("Rock Classics", "t2")
    return state


def test_smart_playlist_crud(temp_state: StateManager):
    rules = {
        "match": "all",
        "rules": [{"field": "artist", "operator": "contains", "value": "Beatles"}],
        "sort_by": "title",
        "sort_order": "asc",
    }
    rules_json = json.dumps(rules)

    # Create
    sp = temp_state.create_smart_playlist("Beatles Best", "All Beatles tracks", rules_json)
    assert sp["id"] is not None
    assert sp["name"] == "Beatles Best"
    assert sp["description"] == "All Beatles tracks"

    # Get list
    all_sps = temp_state.get_smart_playlists()
    assert len(all_sps) == 1
    assert all_sps[0]["name"] == "Beatles Best"

    # Get single
    fetched = temp_state.get_smart_playlist(sp["id"])
    assert fetched is not None
    assert fetched["name"] == "Beatles Best"

    # Update
    updated = temp_state.update_smart_playlist(sp["id"], name="The Beatles Only", description="Updated")
    assert updated is not None
    assert updated["name"] == "The Beatles Only"
    assert updated["description"] == "Updated"

    # Delete
    deleted = temp_state.delete_smart_playlist(sp["id"])
    assert deleted is True
    assert temp_state.get_smart_playlist(sp["id"]) is None


def test_evaluate_rules_artist_filter(temp_state: StateManager):
    tracks = temp_state.get_all_tracks_with_provenance()
    rules = {
        "match": "all",
        "rules": [{"field": "artist", "operator": "contains", "value": "Beatles"}],
        "sort_by": "title",
        "sort_order": "asc",
    }
    matched = evaluate_rules(tracks, rules)
    assert len(matched) == 2
    assert matched[0]["title"] == "Come Together"
    assert matched[1]["title"] == "Something"


def test_evaluate_rules_or_match(temp_state: StateManager):
    tracks = temp_state.get_all_tracks_with_provenance()
    rules = {
        "match": "any",
        "rules": [
            {"field": "artist", "operator": "equals", "value": "Daft Punk"},
            {"field": "album", "operator": "equals", "value": "Starboy"},
        ],
        "sort_by": "title",
        "sort_order": "asc",
    }
    matched = evaluate_rules(tracks, rules)
    assert len(matched) == 2
    titles = {t["title"] for t in matched}
    assert titles == {"Get Lucky", "Starboy"}


def test_evaluate_rules_format_and_playlist(temp_state: StateManager):
    tracks = temp_state.get_all_tracks_with_provenance()
    rules = {
        "match": "all",
        "rules": [
            {"field": "playlist", "operator": "equals", "value": "Rock Classics"},
            {"field": "format", "operator": "equals", "value": "FLAC"},
        ],
    }
    matched = evaluate_rules(tracks, rules)
    assert len(matched) == 1
    assert matched[0]["title"] == "Something"


def test_evaluate_smart_playlist_via_state(temp_state: StateManager):
    rules = {
        "match": "all",
        "rules": [{"field": "title", "operator": "starts_with", "value": "Come"}],
    }
    sp = temp_state.create_smart_playlist("Starts with Come", None, json.dumps(rules))
    res = evaluate_smart_playlist(temp_state, sp["id"])
    assert res["count"] == 1
    assert res["tracks"][0]["title"] == "Come Together"


def test_server_smart_playlist_endpoints(temp_state: StateManager, monkeypatch):
    from fastapi.testclient import TestClient
    from alac_rip import server
    monkeypatch.setattr(server, "state", temp_state)

    client = TestClient(server.app)

    # 1. Preview
    prev_resp = client.post("/smart-playlists/preview", json={
        "rules": {
            "match": "all",
            "rules": [{"field": "artist", "operator": "contains", "value": "Daft"}],
        }
    })
    assert prev_resp.status_code == 200
    assert prev_resp.json()["track_count"] == 1

    # 2. Create
    create_resp = client.post("/smart-playlists", json={
        "name": "Electronic Vibes",
        "description": "Daft punk & more",
        "rules": {
            "match": "all",
            "rules": [{"field": "artist", "operator": "contains", "value": "Daft Punk"}],
        }
    })
    assert create_resp.status_code == 201
    sp_id = create_resp.json()["id"]

    # 3. List
    list_resp = client.get("/smart-playlists")
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1

    # 4. Details
    detail_resp = client.get(f"/smart-playlists/{sp_id}")
    assert detail_resp.status_code == 200
    assert detail_resp.json()["track_count"] == 1

    # 5. Update
    patch_resp = client.patch(f"/smart-playlists/{sp_id}", json={
        "name": "Electronic & Modern",
        "rules": {
            "match": "any",
            "rules": [
                {"field": "artist", "operator": "contains", "value": "Daft Punk"},
                {"field": "artist", "operator": "contains", "value": "The Weeknd"},
            ],
        }
    })
    assert patch_resp.status_code == 200
    assert patch_resp.json()["track_count"] == 2

    # 6. Delete
    del_resp = client.delete(f"/smart-playlists/{sp_id}")
    assert del_resp.status_code == 204
