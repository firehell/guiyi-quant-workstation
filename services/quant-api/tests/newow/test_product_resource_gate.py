from threading import Event, Thread

import pytest

from app.market_data.newow.resource_gate import HeavyResourceGate, NewowResourceBusy


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
