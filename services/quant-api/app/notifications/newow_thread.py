"""Keep external notification latency outside reference observation scheduling."""

import logging
from threading import Event, Thread

logger = logging.getLogger(__name__)


class NotificationThread:
    def __init__(self, dispatcher, *, interval_seconds=5.0):
        if not 0 < interval_seconds <= 5:
            raise ValueError("NEWOW_NOTIFICATION_INTERVAL_INVALID")
        self._dispatcher = dispatcher
        self._interval = interval_seconds
        self._stop = Event()
        self._thread = Thread(target=self._run, name="newow-notification", daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._thread.join(timeout=5)

    def is_alive(self):
        return self._thread.is_alive()

    def _run(self):
        while not self._stop.is_set():
            try:
                self._dispatcher.tick()
            except Exception:
                # Provider/DB exceptions may contain secrets. Never log their text.
                logger.error("NEWOW_NOTIFICATION_TICK_FAILED")
            self._stop.wait(self._interval)
