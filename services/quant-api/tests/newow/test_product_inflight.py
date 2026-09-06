from threading import Barrier, Event, Thread
from time import sleep

from app.market_data.newow.inflight import (
    InFlightCoordinator,
    NewowComputationCancelled,
)


def test_identical_consumers_share_one_computation():
    coordinator = InFlightCoordinator()
    entered = Event()
    release = Event()
    calls = []
    results = []

    def operation(_cancelled):
        calls.append("called")
        entered.set()
        release.wait(1)
        return "result"

    first = Thread(target=lambda: results.append(coordinator.execute("key", operation)))
    second = Thread(
        target=lambda: results.append(coordinator.execute("key", operation))
    )
    first.start()
    assert entered.wait(1)
    second.start()
    sleep(0.02)
    release.set()
    first.join(1)
    second.join(1)

    assert calls == ["called"]
    assert results == ["result", "result"]


def test_leader_disconnect_does_not_cancel_remaining_consumer():
    coordinator = InFlightCoordinator()
    joined = Barrier(2)
    leader_cancelled = Event()
    release = Event()
    outcomes = []

    def operation(all_cancelled):
        joined.wait(1)
        while not release.is_set():
            assert all_cancelled() is False
            sleep(0.005)
        return "result"

    def leader():
        try:
            coordinator.execute("key", operation, leader_cancelled.is_set)
        except NewowComputationCancelled:
            outcomes.append("leader_cancelled")

    leader_thread = Thread(target=leader)
    follower_thread = Thread(
        target=lambda: outcomes.append(coordinator.execute("key", operation))
    )
    leader_thread.start()
    follower_thread.start()
    joined.wait(1)
    leader_cancelled.set()
    release.set()
    leader_thread.join(1)
    follower_thread.join(1)

    assert sorted(outcomes) == ["leader_cancelled", "result"]
