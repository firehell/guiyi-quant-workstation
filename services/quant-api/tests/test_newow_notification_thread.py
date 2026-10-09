from threading import Event

from app.notifications.newow_thread import NotificationThread


def test_network_dispatch_runs_outside_observation_thread_and_stops():
    entered, unblock = Event(), Event()

    class Dispatcher:
        def tick(self):
            entered.set()
            unblock.wait(2)
            return {"enabled": False}

    thread = NotificationThread(Dispatcher(), interval_seconds=0.01)
    thread.start()
    assert entered.wait(1)
    unblock.set()
    thread.stop()
    assert not thread.is_alive()


def test_failure_logging_does_not_disclose_exception(caplog):
    entered = Event()

    class Dispatcher:
        def tick(self):
            entered.set()
            raise RuntimeError("private-token-private-db-url")

    thread = NotificationThread(Dispatcher(), interval_seconds=0.01)
    thread.start()
    assert entered.wait(1)
    thread.stop()
    assert "private-token" not in caplog.text
    assert "NEWOW_NOTIFICATION_TICK_FAILED" in caplog.text
