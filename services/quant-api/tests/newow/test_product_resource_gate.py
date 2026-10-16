from threading import Event, Thread
from time import monotonic, sleep

import pytest

from app.market_data.newow.resource_gate import HeavyResourceGate, NewowResourceBusy


def _wait_for(predicate):
    deadline = monotonic() + 1
    while not predicate():
        assert monotonic() < deadline
        sleep(0.001)


def test_foreground_overtakes_waiting_details_without_preempting_running_work():
    gate = HeavyResourceGate(wait_timeout=1)
    running = gate.acquire()
    order = []

    def run(label, priority):
        with gate.acquire(priority=priority):
            order.append(label)

    detail = Thread(target=run, args=("detail", 2))
    chart = Thread(target=run, args=("chart", 0))
    detail.start()
    _wait_for(lambda: gate.waiting == 1)
    chart.start()
    _wait_for(lambda: gate.waiting == 2)
    assert order == []
    running.release()
    detail.join(1)
    chart.join(1)
    assert order == ["chart", "detail"]
    assert gate.running == gate.waiting == 0


def test_equal_priority_is_fifo_and_cancelled_waiter_never_acquires():
    gate = HeavyResourceGate(max_waiting=3, wait_timeout=1)
    running = gate.acquire()
    cancelled = Event()
    order, errors = [], []

    def run(label, priority, cancel=None):
        try:
            with gate.acquire(cancel, priority=priority):
                order.append(label)
        except NewowResourceBusy as error:
            errors.append(str(error))

    threads = [Thread(target=run, args=args) for args in
               [("first", 2), ("second", 2), ("cancelled", 0, cancelled.is_set)]]
    for count, thread in enumerate(threads, 1):
        thread.start()
        _wait_for(lambda: gate.waiting == count)
    cancelled.set()
    _wait_for(lambda: gate.waiting == 2)
    running.release()
    for thread in threads:
        thread.join(1)
    assert order == ["first", "second"]
    assert errors == ["NEWOW_RESOURCE_CANCELLED"]


def test_expired_waiter_cannot_acquire_when_release_and_deadline_coincide():
    gate = HeavyResourceGate(wait_timeout=0.03)
    running = gate.acquire()
    outcomes = []

    def wait():
        try:
            with gate.acquire(priority=0):
                outcomes.append("acquired")
        except NewowResourceBusy as error:
            outcomes.append(str(error))

    waiter = Thread(target=wait)
    waiter.start()
    _wait_for(lambda: gate.waiting == 1)
    # Hold the condition across the deadline, releasing the running lease just
    # before the waiter can regain the lock. No scheduler race is required.
    with gate._condition:
        sleep(0.05)
        running.release()
    waiter.join(1)
    assert outcomes == ["NEWOW_RESOURCE_BUSY"]
    assert gate.running == gate.waiting == 0


def test_gate_rejects_third_waiter_and_releases_cancelled_waiter():
    gate = HeavyResourceGate(max_running=1, max_waiting=2, wait_timeout=0.2)
    running = gate.acquire()
    acquired = Event()
    release = Event()

    def wait_then_release():
        with gate.acquire():
            acquired.set()
            release.wait(1)

    first = Thread(target=wait_then_release)
    second = Thread(target=wait_then_release)
    first.start()
    second.start()
    while gate.waiting < 2:
        pass
    with pytest.raises(NewowResourceBusy):
        gate.acquire()
    running.release()
    assert acquired.wait(1)
    release.set()
    first.join(1)
    second.join(1)
    assert gate.running == 0
    assert gate.waiting == 0
