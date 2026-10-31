"""Completed receiver reports are independent of calculation readiness."""

from dataclasses import asdict
from datetime import timedelta

import pytest

from app import runtime_cohort_host as cohort
from app import runtime_cohort_recovery as recovery
from app.reference_trading import receiving_liveness as receiving
from app.runtime_bindings import BindingRegistry
from tests.reference_trading.test_receiving_liveness import _setup, NOW
from tests.test_runtime_cohort_forward_recovery import timed_receiving_case
from tests.test_runtime_cohort_host import binding


def report(stage="cycle"):
    return {
        "ready": False,
        "proof": {
            "reference_runtime": {"stage": stage, "ready": False, "blocked_count": 44},
            "receiving": {"protocol_version": 2, "intake_error": None},
        },
    }


@pytest.mark.parametrize("stage", ["cycle", "receiving_cycle"])
def test_recovery_completed_receiver_report_does_not_wait_for_calculation(
    tmp_path, monkeypatch, stage
):
    host, source, audit, samples = timed_receiving_case(
        tmp_path, monkeypatch, offsets=(0, 1)
    )
    tick = [0]
    host.monotonic = lambda: tick[0]
    active = host._active
    host._active = lambda b: (
        report(stage) if b.service == "reference-worker" else active(b)
    )
    host._calculation_boundary = lambda **kwargs: (
        False
    )  # Known pending capture, no UNKNOWN.
    monkeypatch.setattr(recovery, "sleep", lambda _: tick.__setitem__(0, tick[0] + 1))
    proof = host.await_consumers(source, audit, lambda: None)
    assert proof["calculation_ready"] is False
    assert len(samples) == 2


@pytest.mark.parametrize("stage", ["scan", "draining", "drained", "error"])
def test_noncompleted_report_cannot_supply_receiving_authority(stage):
    assert not receiving.completed_receiving_report(report(stage))


@pytest.mark.parametrize(
    "stage,offsets",
    [
        (stage, offsets)
        for stage in ("cycle", "receiving_cycle")
        for offsets in ((0, 1), (0, 31, 32), (0, 1, 2))
    ]
    + [("mixed", (0, 1, 2))],
)
def test_normal_cohort_uses_two_verified_receiving_reports(
    tmp_path, monkeypatch, stage, offsets
):
    data = tmp_path / "data"
    data.mkdir(mode=0o700)
    _, _, _, _, _, capture, sample = _setup(data)
    b = binding(tmp_path, "reference-worker")
    host = object.__new__(cohort.CohortHost)
    tick = [0]
    host.deadline = 100
    host.now = lambda: NOW + timedelta(seconds=tick[0])
    host.session_proof = lambda: {}
    monkeypatch.setattr(cohort, "monotonic", lambda: tick[0])
    monkeypatch.setattr(cohort, "sleep", lambda _: tick.__setitem__(0, tick[0] + 1))
    monkeypatch.setattr(cohort, "owner_process_matches", lambda *_: True)
    monkeypatch.setattr(cohort, "owner_lock_available", lambda *_: False)
    monkeypatch.setattr(
        cohort,
        "read_service_state",
        lambda _: {
            **report(
                ("receiving_cycle", "cycle", "receiving_cycle")[len(snapshots)]
                if stage == "mixed"
                else stage
            ),
            "phase": "active",
            "generation": b.generation,
            "pid": 123,
            "at": host.now().isoformat(),
        },
    )
    monkeypatch.setattr(cohort, "observation_progress", lambda *_: {})
    monkeypatch.setattr(
        cohort, "progress_reached", lambda *a, **k: pytest.fail("legacy tail gate")
    )
    snapshots = []

    def snapshot(*args):
        index = len(snapshots)
        tick[0] = offsets[index]
        if index:
            capture("11-0" if index == 1 else "12-0")
        value = sample(tick[0])
        if offsets == (0, 1, 2) and index == 1 and stage != "mixed":
            from app.reference_trading.inbox import _digest

            value["owner_cycle_at"] = NOW.isoformat()
            value["snapshot_sha256"] = _digest(
                {k: v for k, v in value.items() if k != "snapshot_sha256"}
            )
        snapshots.append(value)
        return value

    host._receiving_snapshot = snapshot
    plan = {
        "new": asdict(BindingRegistry(1, {"reference-worker": b})),
        "reference_receiving_handover": {"frozen": True},
    }
    result = host._await_names(
        plan, ("reference-worker",), {"progress": {"reference-worker": {}}}, 60
    )
    assert result["reference-worker"].startswith("durable_receiving")
    assert len(snapshots) == len(offsets)


def test_safe_wait_diagnostic_only_exposes_bounded_reason_counts_and_stage():
    host = type("Host", (), {})()
    host.now = lambda: NOW
    recovery._verification_substep(
        host,
        "owner_readiness",
        reason="reference_report_incomplete",
        report_stage="scan",
        pending_count=97,
        unknown_count=0,
        service="reference-worker",
        private="secret",
    )
    value = recovery._safe_verification_diagnostic(host)
    assert value["reason"] == "reference_report_incomplete"
    assert value["report_stage"] == "scan"
    assert value["pending_count"] == 97
    assert value["service"] == "reference-worker"
    assert "private" not in value
    host._forward_diagnostic.update(
        reason="secret",
        report_stage="private arbitrary",
        pending_count=True,
        service="private host",
    )
    value = recovery._safe_verification_diagnostic(host)
    assert not {"reason", "report_stage", "pending_count", "service"} & value.keys()


@pytest.mark.parametrize(
    "intake", [{"protocol_version": 2.0, "intake_error": None}, {"protocol_version": 2}]
)
def test_completed_report_requires_typed_version_and_explicit_error_field(intake):
    state = report()
    state["proof"]["receiving"] = intake
    assert not receiving.completed_receiving_report(state)


@pytest.mark.parametrize(
    "reason",
    ["owner_unavailable", "service_not_ready", "progress_pending", "http_unavailable"],
)
def test_wait_timeout_identifies_first_blocking_service_without_raw_details(
    tmp_path, monkeypatch, reason
):
    host, source, audit, _ = timed_receiving_case(tmp_path, monkeypatch)
    tick = [0]
    host.monotonic = lambda: tick[0]
    active = host._active

    def state(binding):
        value = active(binding)
        if binding.service == "api":
            if reason == "owner_unavailable":
                return None
            if reason == "service_not_ready":
                value["ready"] = False
        return value

    host._active = state
    read_source = recovery._resolution_source

    def source_state(path):
        raw, value = read_source(path)
        if reason == "progress_pending":
            value["effects"]["drain"]["progress"]["api"] = {}
        return raw, value

    monkeypatch.setattr(recovery, "_resolution_source", source_state)
    monkeypatch.setattr(recovery, "observation_progress", lambda *_: {})
    monkeypatch.setattr(recovery, "progress_reached", lambda *a, **k: False)
    monkeypatch.setattr(
        recovery,
        "port_is_ready",
        lambda name: not (name == "api" and reason == "http_unavailable"),
    )
    monkeypatch.setattr(recovery, "sleep", lambda _: tick.__setitem__(0, 241))
    with pytest.raises(recovery.CohortError, match="COHORT_FORWARD_READY_TIMEOUT"):
        host.await_consumers(source, audit, lambda: None)
    diagnostic = recovery._safe_verification_diagnostic(host)
    assert diagnostic["service"] == "api"
    assert diagnostic["reason"] == reason


def test_recovery_two_phases_of_one_poll_are_not_two_receiving_rounds(
    tmp_path, monkeypatch
):
    host, source, audit, samples = timed_receiving_case(
        tmp_path, monkeypatch, offsets=(0, 1, 2)
    )
    active = host._active
    stages = ("receiving_cycle", "cycle", "receiving_cycle")
    host._active = lambda b: (
        report(stages[min(len(samples), len(stages) - 1)])
        if b.service == "reference-worker"
        else active(b)
    )
    proof = host.await_consumers(source, audit, lambda: None)
    assert len(samples) == 3
    assert proof["before_sha256"] == samples[0]["snapshot_sha256"]
    assert proof["after_sha256"] == samples[2]["snapshot_sha256"]


def test_next_substep_does_not_retain_previous_rejection_facts():
    host = type("Host", (), {"now": lambda _: NOW})()
    recovery._verification_substep(
        host,
        "owner_readiness",
        reason="progress_pending",
        service="live",
        report_stage="scan",
        pending_count=4,
        unknown_count=0,
    )
    recovery._verification_substep(host, "receiving_snapshot")
    assert recovery._safe_verification_diagnostic(host) == {
        "substep": "receiving_snapshot",
        "observed_at": NOW.isoformat(),
    }
