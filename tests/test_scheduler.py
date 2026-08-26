import time
from unittest.mock import MagicMock

from alac_rip.scheduler import BackgroundSyncScheduler


def test_scheduler_lifecycle():
    callback = MagicMock(return_value="Synced 5 tracks")
    scheduler = BackgroundSyncScheduler(interval_minutes=1, sync_callback=callback, enabled=True)

    assert not scheduler.is_running()
    status = scheduler.get_status()
    assert status["enabled"] is True
    assert status["running"] is False
    assert status["interval_minutes"] == 1
    assert status["run_count"] == 0

    scheduler.start()
    assert scheduler.is_running()

    # Trigger manual execution
    scheduler.trigger_now()
    time.sleep(0.1)

    assert callback.call_count >= 1
    status = scheduler.get_status()
    assert status["run_count"] >= 1
    assert status["last_run_status"] == "success"
    assert "Synced 5 tracks" in status["last_run_message"]

    scheduler.stop()
    assert not scheduler.is_running()


def test_scheduler_disabled_behavior():
    callback = MagicMock()
    scheduler = BackgroundSyncScheduler(interval_minutes=1, sync_callback=callback, enabled=False)

    scheduler.start()
    status = scheduler.get_status()
    assert status["enabled"] is False
    assert status["running"] is True

    # Update config to enable
    scheduler.update_config(enabled=True, interval_minutes=30)
    status = scheduler.get_status()
    assert status["enabled"] is True
    assert status["interval_minutes"] == 30

    scheduler.stop()
