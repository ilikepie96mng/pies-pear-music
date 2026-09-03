import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


class BackgroundSyncScheduler:
    """
    Background worker that runs scheduled synchronization or maintenance tasks
    at configurable intervals.
    """

    def __init__(
        self,
        interval_minutes: int = 60,
        sync_callback: Optional[Callable[[], Any]] = None,
        enabled: bool = False,
    ):
        self.interval_seconds = max(60, interval_minutes * 60)
        self.sync_callback = sync_callback
        self.enabled = enabled
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._trigger_event = threading.Event()
        self._last_run_time: Optional[datetime] = None
        self._last_run_status: str = "never"
        self._last_run_message: str = ""
        self._run_count: int = 0
        self._lock = threading.Lock()

    def start(self) -> None:
        """Start the background scheduler thread."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._trigger_event.clear()
            self._thread = threading.Thread(target=self._run_loop, daemon=True, name="pies-sync-scheduler")
            self._thread.start()
            logger.info("BackgroundSyncScheduler started (interval: %d min)", self.interval_seconds // 60)

    def stop(self) -> None:
        """Stop the background scheduler thread."""
        with self._lock:
            self._stop_event.set()
            self._trigger_event.set()
            if self._thread is not None and self._thread.is_alive():
                self._thread.join(timeout=2.0)
            self._thread = None
            logger.info("BackgroundSyncScheduler stopped")

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def update_config(self, enabled: bool, interval_minutes: int) -> None:
        """Update scheduler interval and enabled state."""
        with self._lock:
            self.enabled = enabled
            self.interval_seconds = max(60, interval_minutes * 60)
        logger.info("BackgroundSyncScheduler config updated: enabled=%s, interval=%d min", enabled, interval_minutes)

    def trigger_now(self) -> bool:
        """Force an immediate execution of the sync job."""
        if not self.is_running():
            self.start()
        self._trigger_event.set()
        return True

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "enabled": self.enabled,
                "running": self.is_running(),
                "interval_minutes": self.interval_seconds // 60,
                "last_run_time": self._last_run_time.isoformat() if self._last_run_time else None,
                "last_run_status": self._last_run_status,
                "last_run_message": self._last_run_message,
                "run_count": self._run_count,
            }

    def _run_loop(self) -> None:
        last_check = time.time()
        while not self._stop_event.is_set():
            # Wait for next interval or explicit manual trigger
            wait_time = self.interval_seconds if self.enabled else 60
            triggered = self._trigger_event.wait(timeout=wait_time)
            self._trigger_event.clear()

            if self._stop_event.is_set():
                break

            if triggered or (self.enabled and (time.time() - last_check >= self.interval_seconds)):
                last_check = time.time()
                self._execute_sync()

    def _execute_sync(self) -> None:
        if not self.sync_callback:
            return

        run_time = datetime.now(timezone.utc)
        logger.info("Starting scheduled sync run at %s", run_time.isoformat())
        try:
            result = self.sync_callback()
            with self._lock:
                self._last_run_time = run_time
                self._last_run_status = "success"
                self._last_run_message = str(result) if result is not None else "Completed successfully"
                self._run_count += 1
            logger.info("Scheduled sync completed: %s", self._last_run_message)
        except Exception as e:
            with self._lock:
                self._last_run_time = run_time
                self._last_run_status = "error"
                self._last_run_message = f"Error during scheduled sync: {e}"
                self._run_count += 1
            logger.error("Scheduled sync error: %s", e, exc_info=True)
