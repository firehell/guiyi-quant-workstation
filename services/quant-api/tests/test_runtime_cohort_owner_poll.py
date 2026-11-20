"""Exercise strict owner readback around a single verified intake pair."""

from datetime import timedelta

import pytest

from app import runtime_cohort_recovery as recovery
from tests.reference_trading.test_receiving_liveness import NOW
from tests.test_runtime_cohort_forward_recovery import timed_receiving_case


def intake_case(tmp_path, monkeypatch):
    host, source, audit, samples = timed_receiving_case(
        tmp_path, monkeypatch, offsets=(0, 1, 3, 4)
    )
    sample_clock = host.monotonic
    delay = [0.0]

    def advance(seconds):
        delay[0] += seconds

    host.monotonic = lambda: sample_clock() + delay[0]
    host.now = lambda: NOW + timedelta(seconds=host.monotonic())
    monkeypatch.setattr(recovery, "sleep", advance)
    return host, source, audit, samples, advance


@pytest.mark.parametrize("at_final", [False, True], ids=["before-fixed", "after-fixed"])
def test_intake_observes_live_ready_after_two_second_poll(tmp_path, monkeypatch, at_final):
    host, source, audit, samples, _ = intake_case(tmp_path, monkeypatch)
    active, window = host._active, host.recovery_window
    start = []
    observed = []

    def recovery_window(**kwargs):
        if not at_final:
            start.append(host.monotonic())
        return window(**kwargs)

    def fixed(*args):
        if at_final:
            start.append(host.monotonic())

    def live_owner(binding):
        state = active(binding)
        if binding.service == "live" and start:
            age = host.monotonic() - start[0]
            state["ready"] = age >= 2
            observed.append((age, state["ready"]))
        return state

    host.recovery_window, host._fixed, host._active = recovery_window, fixed, live_owner
    result = host.await_consumers(source, audit, lambda: None)
    assert len(start) == 1
    assert len(samples) == 2
    assert any(1 <= age < 2 and not ready for age, ready in observed)
    assert observed[-1][1] and 2 <= observed[-1][0] < 5
    assert result["after_sha256"] == samples[1]["snapshot_sha256"]


@pytest.mark.parametrize("condition", ["not_ready", "failed", "sample_expired", "session_expired"])
def test_intake_rejects_unusable_pinned_candidate(tmp_path, monkeypatch, condition):
    host, source, audit, samples, advance = intake_case(tmp_path, monkeypatch)
    active, window = host._active, host.recovery_window
    polls = []
    start = []

    def recovery_window(**kwargs):
        start.append(host.monotonic())
        value, valid_until = window(**kwargs)
        if condition == "sample_expired":
            advance(28)
        if condition == "session_expired":
            valid_until = host.now() + timedelta(seconds=1)
        return value, valid_until

    def live_owner(binding):
        state = active(binding)
        if binding.service == "live" and start:
            age = host.monotonic() - start[0]
            polls.append(age)
            state["ready"] = (
                condition == "sample_expired" and age >= 31
                or condition == "session_expired" and age >= 2
                or condition == "failed" and len(polls) > 1
            )
            if condition == "failed" and len(polls) == 1:
                state["proof"]["failure_code"] = "POLL_FAILED"
        return state

    # This test presents exactly one pair. Each subsequent sampling round has
    # no new owner report, so it cannot supply an independent replacement pair.
    snapshot = host._snapshot

    def sample(*args, **kwargs):
        if len(samples) == 2:
            raise recovery.CohortError("COHORT_FORWARD_DEADLINE_EXCEEDED")
        return snapshot(*args, **kwargs)

    def budget():
        if start and host.monotonic() - start[0] >= 35:
            raise recovery.CohortError("COHORT_FORWARD_DEADLINE_EXCEEDED")

    host.recovery_window, host._active, host._snapshot = recovery_window, live_owner, sample
    with pytest.raises(recovery.CohortError, match="COHORT_FORWARD_DEADLINE_EXCEEDED"):
        host.await_consumers(source, audit, budget)
    assert len(samples) == 2 and polls


@pytest.mark.parametrize("expires_during_owner_check", [False, True])
def test_reference_pid_change_requires_two_new_owner_cycles(
    tmp_path, monkeypatch, expires_during_owner_check
):
    host, source, audit, samples = timed_receiving_case(
        tmp_path, monkeypatch, offsets=(0, 1, 28, 29)
    )
    sample_clock = host.monotonic
    minimum_time = [0]
    host.monotonic = lambda: max(sample_clock(), minimum_time[0])
    host.now = lambda: NOW + timedelta(seconds=host.monotonic())
    original_active = host._active
    replaced = []

    def fixed(*args):
        replaced.append(True)

    def owner(binding):
        state = original_active(binding)
        if binding.service == "reference-worker" and replaced:
            state["pid"] += 1
            if expires_during_owner_check:
                minimum_time[0] = 32
        return state

    host._fixed, host._active = fixed, owner
    proof = host.await_consumers(source, audit, lambda: None)
    assert len(samples) == 4
    assert proof["before_sha256"] == samples[2]["snapshot_sha256"]
    assert proof["after_sha256"] == samples[3]["snapshot_sha256"]


def test_reference_pid_change_preserves_durable_ack_prefix_check(tmp_path, monkeypatch):
    from app.reference_trading.receiving_liveness import ReceivingLivenessError

    host, source, audit, samples = timed_receiving_case(
        tmp_path, monkeypatch, regress=True, offsets=(0, 1)
    )
    original_active = host._active

    def owner(binding):
        state = original_active(binding)
        if binding.service == "reference-worker" and samples:
            state["pid"] += 1
        return state

    host._active = owner
    with pytest.raises(ReceivingLivenessError, match="REFERENCE_RECEIVING_LIVENESS_UNPROVEN"):
        host.await_consumers(source, audit, lambda: None)
    assert len(samples) == 2
