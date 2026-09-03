import pytest
from pydantic import ValidationError

from alac_rip.server import ConfigUpdate


def test_config_update_accepts_absolute_and_home_relative_paths():
    update = ConfigUpdate(
        music_dir="~/Music/Pies Pear Music",
        state_dir="/var/tmp/pies-state",
        alac_rip_dir="/opt/pies-tools",
        log_retention_days=30,
    )
    assert update.log_retention_days == 30


@pytest.mark.parametrize("field,value", [
    ("music_dir", "relative/music"),
    ("state_dir", ""),
    ("alac_rip_dir", "tools"),
    ("music_dir", "/tmp/has\x00null"),
])
def test_config_update_rejects_unsafe_paths(field, value):
    with pytest.raises(ValidationError):
        ConfigUpdate(**{field: value})


@pytest.mark.parametrize("days", [-1, 3651])
def test_config_update_rejects_unreasonable_log_retention(days):
    with pytest.raises(ValidationError):
        ConfigUpdate(log_retention_days=days)
