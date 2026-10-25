"""The recovery checkpoint requires actual old-runtime facts, never just a flag."""

from copy import deepcopy
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
import pytest
from app.runtime_bindings import BindingRegistry
from app.runtime_cohort import CONTINUOUS, CohortError
from app.runtime_cohort_host import CohortHost
from test_runtime_cohort import Host

NOW = datetime(2026, 10, 26, 1, tzinfo=UTC)


def setup_host(tmp_path, monkeypatch):
    from app import runtime_cohort_host as module
    from app import runtime_handover, runtime_scheduled

    base = Host(tmp_path)
    root1 = tmp_path / "release-v1.16.1"
    root1.mkdir()
    old_services = {}
    candidates = {"api": "a", "web": "b", "reference-worker": "c"}
    for name, value in base.old.services.items():
        if name in {"market-feed", "live", "alert"}:
            value = replace(
                value, root=str(root1), tag="v1.16.1", commit="1" * 40, generation=25
            )
        elif name not in {"api", "web"}:
            value = replace(value, generation=26)
        if name in candidates:
            value = replace(
                value,
                launchd_label=f"com.guiyi.quant-{name}-candidate-"
                + candidates[name] * 32,
            )
        old_services[name] = value
    old = BindingRegistry(1, old_services)
    new = BindingRegistry(
        1,
        {
            name: replace(
                value,
                root=str(base.root),
                tag="v1.16.5",
                commit="e" * 40,
                generation=29,
                launchd_label=None,
            )
            for name, value in old_services.items()
        },
    )
    installed = {"launcher_sha256": "a" * 64}
    states = {}
    requests = {}
    for index, (name, value) in enumerate(old_services.items()):
        pid = (
            (47191 if name == "market-feed" else 1000 + index)
            if name in CONTINUOUS
            else None
        )
        installed[name] = {
            "sha256": "b" * 64,
            "plist_hex": name.encode().hex(),
            "loaded": True,
            "loaded_pid": str(pid) if pid else None,
        }
        if pid:
            states[name] = {
                "schema_version": 1,
                "service": name,
                "generation": value.generation,
                "phase": "active",
                "pid": pid,
                "at": NOW.isoformat(),
                "ready": False,
            }
            requests[name] = {
                "schema_version": 1,
                "service": name,
                "generation": value.generation,
                "phase": "cancelled",
                "request_id": "a" * 32,
            }
    frozen = deepcopy(installed)
    frozen["market-feed"]["loaded_pid"] = "6228"
    protected = {
        "db_scope_policy_identity_sha256": "c" * 64,
        "files": {"private-config": "d" * 64},
    }
    plan = {
        "old": asdict(old),
        "new": asdict(new),
        "registry_sha256": "c" * 64,
        "installed": frozen,
        "protected": deepcopy(protected),
    }
    host = object.__new__(CohortHost)
    host.directory = base.directory
    host.now = lambda: NOW
    host.bindings = lambda: old
    host.binding_hash = lambda: "c" * 64
    host.protected = lambda _: deepcopy(protected)
    host.installed = lambda _: deepcopy(installed)
    host.verify_release = lambda *_: None
    old_labels = {b.label for b in old.services.values()}
    host.definition_absent = lambda b: b.label not in old_labels
    host.start = lambda *_: pytest.fail("readback must never start a process")
    host.launch = lambda *_: pytest.fail("readback must never mutate launchd")
    monkeypatch.setattr(
        module,
        "contract_fingerprints",
        lambda _: next(iter(old.services.values())).contracts,
    )
    monkeypatch.setattr(
        module, "read_service_state", lambda service, **_: deepcopy(states[service])
    )
    monkeypatch.setattr(module, "owner_process_matches", lambda *_: True)
    monkeypatch.setattr(module, "owner_lock_available", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(module.os, "kill", lambda *_: None)
    monkeypatch.setattr(
        runtime_handover, "_read", lambda p: deepcopy(requests[p.name.split(".")[0]])
    )
    monkeypatch.setattr(runtime_scheduled.ScheduledBackend, "idle", lambda *_: True)
    return host, plan, installed, states, requests, protected


def test_actual_restored_pid_is_allowed_and_transient_ready_time_does_not_change_identity(
    tmp_path, monkeypatch
):
    host, plan, _, states, _, _ = setup_host(tmp_path, monkeypatch)
    first = host.verify_old_restored(plan)
    assert first["owners"]["market-feed"]["pid"] == 47191
    assert first["identity"]["services"]["market-feed"]["generation"] == 25
    assert len(first["identity"]["new_labels_absent"]) == 3
    assert len(first["identity"]["services"]) == 10
    for state in states.values():
        state.update(at=(NOW + timedelta(seconds=1)).isoformat(), ready=True)
    host.now = lambda: NOW + timedelta(seconds=1)
    assert host.verify_old_restored(plan)["identity_sha256"] == first["identity_sha256"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("phase", "parked"),
        ("generation", 29),
        ("pid", 9999),
        ("at", (NOW - timedelta(seconds=31)).isoformat()),
        ("at", (NOW + timedelta(seconds=1)).isoformat()),
        ("at", NOW.replace(tzinfo=None).isoformat()),
    ],
)
def test_invalid_or_stale_owner_never_clears_unknown(
    tmp_path, monkeypatch, field, value
):
    host, plan, _, states, _, _ = setup_host(tmp_path, monkeypatch)
    states["market-feed"][field] = value
    with pytest.raises(CohortError, match="OWNER_UNPROVEN"):
        host.verify_old_restored(plan)


@pytest.mark.parametrize(
    "condition",
    ["process_identity", "pid_dead", "lock_free", "calendar_busy", "new_label"],
)
def test_current_runtime_observations_are_all_required(
    tmp_path, monkeypatch, condition
):
    from app import runtime_cohort_host as module, runtime_scheduled

    host, plan, *_ = setup_host(tmp_path, monkeypatch)
    if condition == "process_identity":
        monkeypatch.setattr(module, "owner_process_matches", lambda *_: False)
    elif condition == "pid_dead":

        def gone(*_):
            raise ProcessLookupError

        monkeypatch.setattr(module.os, "kill", gone)
    elif condition == "lock_free":
        monkeypatch.setattr(
            module, "owner_lock_available", lambda *_args, **_kwargs: True
        )
    elif condition == "calendar_busy":
        monkeypatch.setattr(
            runtime_scheduled.ScheduledBackend, "idle", lambda *_: False
        )
    else:
        host.definition_absent = lambda _: False
    with pytest.raises(CohortError):
        host.verify_old_restored(plan)


@pytest.mark.parametrize(
    "field,value", [("loaded", False), ("sha256", "e" * 64), ("plist_hex", "00")]
)
def test_original_loaded_state_and_plist_bytes_are_required(
    tmp_path, monkeypatch, field, value
):
    host, plan, installed, *_ = setup_host(tmp_path, monkeypatch)
    installed["api"][field] = value
    with pytest.raises(CohortError, match="INSTALLED_DRIFT"):
        host.verify_old_restored(plan)


@pytest.mark.parametrize(
    "mutation",
    [
        "active",
        "wrong_schema",
        "wrong_service",
        "bad_id",
        "bad_generation",
        "bad_phase",
    ],
)
def test_handover_structure_and_absence_of_effective_drain_are_required(
    tmp_path, monkeypatch, mutation
):
    host, plan, _, _, requests, _ = setup_host(tmp_path, monkeypatch)
    request = requests["market-feed"]
    changes = {
        "active": ("phase", "drain"),
        "wrong_schema": ("schema_version", 99),
        "wrong_service": ("service", "api"),
        "bad_id": ("request_id", "x"),
        "bad_generation": ("generation", "25"),
        "bad_phase": ("phase", "unknown"),
    }
    key, value = changes[mutation]
    request[key] = value
    with pytest.raises(CohortError, match="DRAIN_ACTIVE"):
        host.verify_old_restored(plan)


def test_second_snapshot_catches_process_restart_during_readback(tmp_path, monkeypatch):
    host, plan, installed, *_ = setup_host(tmp_path, monkeypatch)
    calls = [0]

    def observed(_):
        calls[0] += 1
        result = deepcopy(installed)
        if calls[0] > 1:
            result["market-feed"]["loaded_pid"] = "47192"
        return result

    host.installed = observed
    with pytest.raises(CohortError, match="READBACK_DRIFT"):
        host.verify_old_restored(plan)


def test_scope_change_during_readback_is_not_resolved(tmp_path, monkeypatch):
    host, plan, _, _, _, protected = setup_host(tmp_path, monkeypatch)
    calls = [0]

    def observed(_):
        calls[0] += 1
        result = deepcopy(protected)
        if calls[0] > 1:
            result["db_scope_policy_identity_sha256"] = "e" * 64
        return result

    host.protected = observed
    with pytest.raises(CohortError, match="READBACK_DRIFT"):
        host.verify_old_restored(plan)
