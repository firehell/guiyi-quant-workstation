from dataclasses import asdict
from datetime import UTC, datetime

import pytest

from app.runtime_bindings import BindingRegistry, ServiceBinding, CONTRACTS
from app.runtime_cohort import CohortError
from app.runtime_cohort_host import CohortHost

NOW = datetime.now(UTC)


def setup(tmp_path, monkeypatch, *, alternative="durable_receiving_waiting_history", ready=False, blocked=1, owner=True, progress=True):
    from app import runtime_cohort_host as cohort
    from app import runtime_deployment as deployment
    from app.reference_trading import operational_readiness
    from app.services import deployment_identity
    binding = ServiceBinding("reference-worker", str(tmp_path), "v1.16.12", "a" * 40, 31, True,
                              {key: "b" * 64 for key in CONTRACTS})
    state = {"phase": "active", "generation": binding.generation, "pid": 123, "at": NOW.isoformat(), "ready": ready,
             "proof": {"reference_runtime": {"stage": "cycle", "ready": ready, "blocked_count": blocked}, "receiving": {}}}
    clock = [0.0]
    checks = []
    def mode(value):
        checks.append("receiving proof")
        return alternative
    monkeypatch.setattr(operational_readiness, "reference_waiting_history_mode", mode)
    for module in (cohort, deployment):
        monkeypatch.setattr(module, "read_service_state", lambda service: state)
        monkeypatch.setattr(module, "owner_process_matches", lambda *args: owner)
        monkeypatch.setattr(module, "observation_progress", lambda *args: {"day": "10-0"})
        monkeypatch.setattr(module, "progress_reached", lambda *args, **kwargs: checks.append("progress") or progress)
        monkeypatch.setattr(module, "monotonic", lambda: clock[0])
        monkeypatch.setattr(module, "sleep", lambda value: clock.__setitem__(0, clock[0] + 20))
    monkeypatch.setattr(deployment_identity, "deployment_identity_health", lambda **kwargs:
                        {"services": {"reference_worker": {"status": "matched"}}})
    host = object.__new__(CohortHost)
    host.deadline = 100
    host.now = lambda: NOW
    host.session_proof = lambda: {"mode": "closed_idle"}
    plan = {"new": asdict(BindingRegistry(1, {"reference-worker": binding}))}
    backend = deployment.LaunchdBackend()
    backend.candidates["reference-worker"] = binding
    backend.boundaries["reference-worker"] = {"day": "9-0"}
    return host, backend, plan, binding, state, clock, checks


@pytest.mark.parametrize("mode", ("durable_receiving_waiting_history", "durable_receiving_backlog", "durable_receiving"))
def test_receiving_only_mode_preserves_owner_and_progress_checks(tmp_path, monkeypatch, mode):
    host, backend, plan, binding, state, clock, checks = setup(tmp_path, monkeypatch, alternative=mode)
    assert host._await_names(plan, ("reference-worker",), {"progress": {"reference-worker": {"day": "9-0"}}}, 10) == {"reference-worker": mode}
    assert backend.verify("reference-worker", binding, "request") is True
    assert checks.count("progress") == 2
    assert state["proof"]["reference_runtime"]["ready"] is False
    assert state["proof"]["reference_runtime"]["blocked_count"] == 1


@pytest.mark.parametrize("owner,progress,mode", ((False, True, "durable_receiving"), (True, False, "durable_receiving"),
                                                (True, True, None)))
def test_receiving_alternative_does_not_bypass_identity_progress_or_legacy_gate(tmp_path, monkeypatch, owner, progress, mode):
    host, backend, plan, binding, state, clock, checks = setup(tmp_path, monkeypatch, alternative=mode, owner=owner, progress=progress)
    with pytest.raises(CohortError, match="NEW_READY_TIMEOUT"):
        host._await_names(plan, ("reference-worker",), {"progress": {"reference-worker": {"day": "9-0"}}}, 10)
    clock[0] = 0
    assert backend.verify("reference-worker", binding, "request") is False


def test_legacy_calculation_ready_path_is_unchanged(tmp_path, monkeypatch):
    host, backend, plan, binding, state, clock, checks = setup(tmp_path, monkeypatch, alternative=None, ready=True, blocked=0)
    state["proof"].pop("receiving")
    assert host._await_names(plan, ("reference-worker",), {"progress": {}}, 10) == {"reference-worker": "active"}
    assert backend.verify("reference-worker", binding, "request") is True
    assert "receiving proof" not in checks


@pytest.mark.parametrize("gate", ("cohort", "deployment"))
def test_slow_independent_receiving_proof_cannot_cross_original_deadline(tmp_path, monkeypatch, gate):
    from app.reference_trading import operational_readiness
    host, backend, plan, binding, state, clock, checks = setup(tmp_path, monkeypatch)
    def slow_mode(state):
        clock[0] = 101
        return "durable_receiving_waiting_history"
    monkeypatch.setattr(operational_readiness, "reference_waiting_history_mode", slow_mode)
    if gate == "cohort":
        with pytest.raises(CohortError, match="NEW_READY_TIMEOUT"):
            host._await_names(plan, ("reference-worker",), {"progress": {}}, 10)
    else:
        assert backend.verify("reference-worker", binding, "request") is False


def test_legacy_deployment_ready_without_runtime_detail_preserves_old_behavior(tmp_path, monkeypatch):
    host, backend, plan, binding, state, clock, checks = setup(tmp_path, monkeypatch, alternative=None, ready=True, blocked=0)
    state["proof"] = {}
    assert backend.verify("reference-worker", binding, "request") is True
    assert "receiving proof" not in checks


def test_invalid_receiving_never_falls_back_to_calculation_ready(tmp_path, monkeypatch):
    host, backend, plan, binding, state, clock, checks = setup(tmp_path, monkeypatch, alternative=None, ready=True, blocked=0)
    with pytest.raises(CohortError, match="NEW_READY_TIMEOUT"):
        host._await_names(plan, ("reference-worker",), {"progress": {}}, 10)
    clock[0] = 0
    assert backend.verify("reference-worker", binding, "request") is False
