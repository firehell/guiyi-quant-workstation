"""launchctl bootout is asynchronous; only bounded reads may follow its request."""

from dataclasses import asdict
from types import SimpleNamespace

import pytest

from app import runtime_cohort_host as module
from app.runtime_bindings import BindingRegistry
from app.runtime_cohort import CohortError
from app.runtime_cohort_host import CohortHost
from tests.test_runtime_cohort_host import binding


@pytest.fixture
def clock(monkeypatch):
    value = SimpleNamespace(at=0.0)
    monkeypatch.setattr(module, "monotonic", lambda: value.at)
    monkeypatch.setattr(
        module, "sleep", lambda duration: setattr(value, "at", value.at + duration)
    )
    return value


def test_stop_waits_for_async_label_then_old_pid_without_reissuing_bootout(
    tmp_path, monkeypatch, clock
):
    b = binding(tmp_path)
    reg = BindingRegistry(1, {"market-feed": b})
    host = object.__new__(CohortHost)
    host.deadline = 600
    host.session_proof = lambda: {"mode": "closed_idle"}
    calls = []
    host.launch = lambda *args, **_: calls.append(args)
    host.definition_absent = lambda _: clock.at >= 0.2

    def alive(pid, signal):
        assert pid == 6228 and signal == 0
        assert clock.at >= 0.2
        if clock.at >= 0.4:
            raise ProcessLookupError

    monkeypatch.setattr(module.os, "kill", alive)
    monkeypatch.setattr(module, "CONTINUOUS", ("market-feed",))
    proof = {"owners": {"market-feed": {"pid": 6228}}}
    host.stop_old({"old": asdict(reg)}, proof)
    assert clock.at >= 0.4
    assert [args[0] for args in calls].count("bootout") == 1
    assert set(host.bootout_requests) == {"market-feed"}


def test_calendar_bootout_also_waits_for_actual_absence(tmp_path, monkeypatch, clock):
    from app import runtime_scheduled

    b = binding(tmp_path, "after-market")
    reg = BindingRegistry(1, {"after-market": b})
    host = object.__new__(CohortHost)
    host.deadline = 600
    calls = []
    host.launch = lambda *args, **_: calls.append(args)
    host.definition_absent = lambda _: clock.at >= 0.2
    monkeypatch.setattr(module, "CALENDARS", ("after-market",))
    monkeypatch.setattr(
        runtime_scheduled,
        "ScheduledBackend",
        lambda: SimpleNamespace(freeze=lambda _: {}, idle=lambda _: True),
    )
    host.suspend_calendars(
        {"old": asdict(reg), "installed": {"after-market": {"loaded_pid": None}}}
    )
    assert clock.at >= 0.2
    assert [args[0] for args in calls].count("bootout") == 1


def test_stop_budget_timeout_does_not_replay_bootout(tmp_path, monkeypatch, clock):
    b = binding(tmp_path)
    host = object.__new__(CohortHost)
    host.deadline = 0.15
    host.definition_absent = lambda _: False
    calls = []
    host.launch = lambda *args, **_: calls.append(args)
    monkeypatch.setattr(module, "CONTINUOUS", ("market-feed",))
    with pytest.raises(CohortError, match="BOOTOUT_TIMEOUT"):
        host.stop_old(
            {"old": asdict(BindingRegistry(1, {"market-feed": b}))},
            {"owners": {"market-feed": {"pid": 6228}}},
        )
    assert [args[0] for args in calls].count("bootout") == 1
    assert clock.at < 1


def test_restore_waits_teardown_before_cancelling_drain_and_starts_exactly_once(
    tmp_path, monkeypatch, clock
):
    b = binding(tmp_path)
    reg = BindingRegistry(1, {"market-feed": b})
    host = object.__new__(CohortHost)
    host.bindings = lambda: reg
    host.bootout_requests = {"market-feed": {"label": b.label, "pid": 6228}}
    host.drains = {"market-feed": "request"}
    host._replace_plist = lambda *_: None
    host.path = lambda _: tmp_path / "market-feed.plist"
    host.assert_installed = lambda *_: None
    started, calls = [], []
    host.definition_absent = lambda _: not started and clock.at >= 0.2

    def alive(pid, signal):
        assert pid == 6228 and signal == 0
        if clock.at >= 0.4:
            raise ProcessLookupError

    monkeypatch.setattr(module.os, "kill", alive)

    def cancel(*_args, **_kwargs):
        assert clock.at >= 0.4
        calls.append("cancel")

    monkeypatch.setattr(module, "cancel_drain", cancel)
    host.launch = lambda *args, **_: calls.append(args[0])

    def start(_):
        assert clock.at >= 0.4 and calls[0] == "cancel"
        started.append(47191)

    host.start = start
    monkeypatch.setattr(module, "CONTINUOUS", ("market-feed",))
    monkeypatch.setattr(
        module,
        "read_service_state",
        lambda _: {"phase": "active", "generation": b.generation, "pid": 47191},
    )
    monkeypatch.setattr(module, "owner_process_matches", lambda *_: True)
    host.restore_old(
        {
            "old": asdict(reg),
            "new": asdict(reg),
            "installed": {"market-feed": {"plist_hex": b"old".hex(), "loaded": True}},
        }
    )
    assert started == [47191]
    assert "bootout" not in calls


def test_restore_teardown_timeout_never_cancels_drain_or_restarts_again(
    tmp_path, monkeypatch, clock
):
    b = binding(tmp_path)
    reg = BindingRegistry(1, {"market-feed": b})
    host = object.__new__(CohortHost)
    host.bindings = lambda: reg
    host.bootout_requests = {"market-feed": {"label": b.label, "pid": 6228}}
    host.drains = {"market-feed": "request"}
    host.definition_absent = lambda _: False
    host.deadline = (
        0  # The apply budget expired; only the bounded recovery wait remains.
    )
    monkeypatch.setattr(
        module,
        "cancel_drain",
        lambda *_args, **_kwargs: pytest.fail(
            "teardown must finish before drain cancellation"
        ),
    )
    host.start = lambda _: pytest.fail(
        "unresolved teardown must not start another copy"
    )
    with pytest.raises(CohortError, match="BOOTOUT_TIMEOUT"):
        host.restore_old({"old": asdict(reg), "installed": {}})
    assert 60 <= clock.at < 61
