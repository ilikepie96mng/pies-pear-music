from alac_rip.state import StateManager


def test_recommendation_artist_can_be_hidden_and_restored(tmp_path):
    state = StateManager(tmp_path / "state.db")

    state.exclude_recommendation_artist("Example Artist")
    assert state.get_recommendation_exclusions() == ["Example Artist"]

    state.include_recommendation_artist("Example Artist")
    assert state.get_recommendation_exclusions() == []


def test_recommendation_controls_can_be_reset_and_store_genres(tmp_path):
    state = StateManager(tmp_path / "state.db")
    state.exclude_recommendation_artist("Example Artist")
    state.clear_recommendation_exclusions()
    assert state.get_recommendation_exclusions() == []

    state.set_recommendation_genres(["ambient", "jazz"])
    assert state.get_recommendation_genres() == ["ambient", "jazz"]
