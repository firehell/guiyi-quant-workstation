from contextlib import nullcontext
from dataclasses import asdict
from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path
import plistlib

import pytest

from app.runtime_bindings import (
    BindingRegistry,
    ServiceBinding,
    SERVICES,
    CONTRACTS,
    authorized_program_arguments,
)
from app.runtime_fault_recovery import (
    CALENDARS,
    CONTINUOUS,
    OLD_COMMIT,
    FaultRecoveryError,
    StageAttempt,
    freeze,
    registry,
    run_stage,
    independent_readback,
)
from app.runtime_fault_recovery_host import FaultRecoveryHost


class BoundaryBackend:
    """Effect-order test double, never market/provider acceptance evidence."""

    def __init__(self, tmp):
        self.old_root = tmp / "release-v1.15.3"
        self.new_root = tmp / "release-v1.15.4"
        self.old_root.mkdir()
        self.new_root.mkdir()
        contracts = {name: "a" * 64 for name in CONTRACTS}
        self.old = BindingRegistry(
            1,
            {
                name: ServiceBinding(
                    name, str(self.old_root), "v1.15.3", OLD_COMMIT, 16, True, contracts
                )
                for name in SERVICES
            },
        )
        self.current = self.old
        self.events = []
        self.parked = False
        self.at_tail = True
        self.full_ready = True
        self.scope = {"fixed": "scope-policy-hash"}

    def bindings(self):
        return self.current

    def binding_hash(self):
        return "registry16"

    def contracts(self, root):
        return {name: "b" * 64 for name in CONTRACTS}

    def verify_release(self, *args):
        self.events.append(("verify-release", args[1]))

    def protected(self, old):
        return self.scope.copy()

    def assert_protected(self, plan):
        if self.scope != plan["protected"]:
            raise FaultRecoveryError("PROTECTED_DRIFT")

    def installed(self, old):
        return {"all": "plists"}

    def assert_installed(self, *args):
        pass

    def old_health(self, old):
        return {
            name: {"ready": False, "failure_code": "OLD_FAILURE_RETAINED"}
            for name in CONTINUOUS
        }

    def deployment_guard(self):
        return nullcontext()

    def after_market_guard(self):
        return nullcontext()

    def maintenance_guard(self):
        return nullcontext()

    def owner_guards(self, old):
        assert self.parked
        return nullcontext()

    def request_drain(self, name, generation):
        self.events.append(("drain", name, generation))
        return name + "-request-" + str(generation)

    def await_parked(self, old, effects, seconds):
        self.parked = True
        return {
            "owners": {
                name: {
                    "phase": "parked",
                    "ready": False,
                    "generation": 16,
                    "pid": 100 + index,
                }
                for index, name in enumerate(CONTINUOUS)
            },
            "feed_close": {"verified": True},
        }

    def verify_feed_closed(self, binding, proof):
        assert proof["feed_close"]["verified"]

    def verify_projection_restore(self, plan, effects):
        return {"sha256": "exact-live-restore"}

    def fault_window(self, plan, effects):
        assert self.parked
        return {"kind": "all_old_publishers_closed", "night_session": "TRADING"}

    def assert_parked(self, old, effects):
        assert self.parked

    def assert_idle_or_parked(self, binding, effects):
        assert self.parked

    def stop(self, binding):
        self.events.append(("stop", binding.service))
        return {"stopped": True}

    def assert_old_pids_exited(self, proof):
        self.events.append(("old-pids-exited",))

    def retain_history(self, *args):
        self.events.append(("retained-old-history",))
        return {"source_commit": OLD_COMMIT, "natural": False}

    def install(self, old, new, plan):
        self.events.append(("install", new.service, 17))
        return {"generation": 17}

    def install_launcher(self, *args):
        return {"unchanged": True}

    def commit_bindings(self, new, sha):
        assert {item[1] for item in self.events if item[0] == "stop"} == SERVICES
        assert {item[1] for item in self.events if item[0] == "install"} == SERVICES
        self.current = new
        self.events.append(("one-registry-cas", 17))
        return "registry17"

    def assert_new_installed(self, new):
        pass

    def start(self, binding):
        self.events.append(("start", binding.service))
        return {"bootstrapped": True}

    def await_new_reference_parked(self, binding, request):
        self.events.append(("reference17-parked",))

    def start_calendar(self, binding):
        self.events.append(("calendar-bootstrap-no-kickstart", binding.service))
        return {"idle": True}

    def verify_calendar(self, binding):
        pass

    def verify_partial_started(self, new):
        self.events.append(("not-full-ready-yet",))

    def verify_reference_recovery(self, new, effects):
        return {"180-exact-receipts": "readback"}

    def assert_old_consumers_at_boundary(self, plan, new):
        if not self.at_tail:
            raise FaultRecoveryError("OLD_CONSUMERS_NOT_AT_TAIL")

    def cancel_reference_drain(self, binding, request):
        self.events.append(("resume-reference", request))
        return {"cancelled": True}

    def await_reference_ready(self, binding):
        self.events.append(("reference-ready",))

    def await_full_ready(self, new):
        if not self.full_ready:
            raise FaultRecoveryError("NEW_FULL_READY_FAILED")

    def halt_unknown(self, new):
        self.events.append(("cooperative-halt17-no-kill",))
        return {"force_kill": False}


def setup(tmp_path):
    backend = BoundaryBackend(tmp_path)
    plan = freeze(
        backend,
        candidate_root=backend.new_root,
        candidate_commit="d" * 40,
        projection_readback=tmp_path / "projection.json",
        projection_sha256=None,
    )
    attempt = StageAttempt(tmp_path / "attempt-001", plan)
    return backend, plan, attempt


def test_faulted_old_readiness_is_preserved_but_real_park_required(tmp_path):
    backend, plan, attempt = setup(tmp_path)
    assert all(not value["ready"] for value in plan["old_health"].values())
    run_stage(plan, "drain", backend=backend, attempt=attempt)
    assert backend.parked
    assert plan["old_health"]["live"]["failure_code"] == "OLD_FAILURE_RETAINED"
    assert not any(item[0] in ("stop", "install") for item in backend.events)


def test_ten_cas_after_all_old_exits_ref_park_before_recovery_feed_last(tmp_path):
    backend, plan, attempt = setup(tmp_path)
    for phase in ("drain", "stop-install", "start"):
        state = run_stage(plan, phase, backend=backend, attempt=attempt)
    assert state["phase"] == "reference_recovery_pending"
    starts = [item[1] for item in backend.events if item[0] == "start"]
    assert starts == ["live", "alert", "reference-worker", "api", "web"]
    assert len([item for item in backend.events if item[0] == "one-registry-cas"]) == 1
    assert not any(item == ("start", "market-feed") for item in backend.events)
    state = run_stage(plan, "resume-reference", backend=backend, attempt=attempt)
    ops = [item[0] for item in backend.events]
    assert ops.index("reference17-parked") < ops.index("resume-reference")
    final_starts = [item for item in backend.events if item[0] == "start"]
    assert final_starts[-1] == ("start", "market-feed")
    ops = [item[0] for item in backend.events]
    assert ops.index("resume-reference") < ops.index("calendar-bootstrap-no-kickstart")
    result = independent_readback(plan, backend=backend, attempt=attempt)
    assert result["status"] == "GEN17_RUNTIME_READY"
    assert result["natural_acceptance"] == "PENDING_NEW_COMPLETED_OBSERVATION"
    assert all(item.generation == 17 for item in backend.current.services.values())


def test_changed_scope_blocks_before_first_effect_and_never_overwrites_evidence(
    tmp_path,
):
    backend, plan, attempt = setup(tmp_path)
    backend.scope = {"fixed": "changed-policy"}
    with pytest.raises(FaultRecoveryError, match="PROTECTED_DRIFT"):
        run_stage(plan, "drain", backend=backend, attempt=attempt)
    assert not any(item[0] == "drain" for item in backend.events)
    assert attempt.state()["phase"] == "precondition_blocked"
    assert plan["old_health"]["alert"]["failure_code"] == "OLD_FAILURE_RETAINED"


def test_unknown_install_leaves_known_prefix_and_prohibits_retry(tmp_path):
    backend, plan, attempt = setup(tmp_path)
    run_stage(plan, "drain", backend=backend, attempt=attempt)
    original = backend.install
    calls = []

    def unknown(old, new, plan):
        calls.append(new.service)
        if len(calls) == 2:
            raise RuntimeError("write outcome unknown")
        return original(old, new, plan)

    backend.install = unknown
    with pytest.raises(RuntimeError, match="write outcome unknown"):
        run_stage(plan, "stop-install", backend=backend, attempt=attempt)
    state = attempt.state()
    assert state["phase"] == "outcome_unknown"
    assert len([key for key in state["effects"] if key.startswith("install:")]) == 1
    assert backend.current == backend.old
    with pytest.raises(FaultRecoveryError, match="OUTCOME_UNKNOWN_READBACK_REQUIRED"):
        run_stage(plan, "stop-install", backend=backend, attempt=attempt)
    assert len(calls) == 2
    readback = independent_readback(plan, backend=backend, attempt=attempt)
    assert readback["status"] == "OUTCOME_UNKNOWN_READBACK_ONLY"


def test_not_at_old_tail_cannot_resume_reference_or_start_feed(tmp_path):
    backend, plan, attempt = setup(tmp_path)
    for phase in ("drain", "stop-install", "start"):
        run_stage(plan, phase, backend=backend, attempt=attempt)
    backend.at_tail = False
    with pytest.raises(FaultRecoveryError, match="OLD_CONSUMERS_NOT_AT_TAIL"):
        run_stage(plan, "resume-reference", backend=backend, attempt=attempt)
    assert not any(item[0] == "resume-reference" for item in backend.events)
    assert not any(item == ("start", "market-feed") for item in backend.events)


def test_final_new_ready_failure_halts_exact_new_writers_without_force_kill(tmp_path):
    backend, plan, attempt = setup(tmp_path)
    for phase in ("drain", "stop-install", "start"):
        run_stage(plan, phase, backend=backend, attempt=attempt)
    backend.full_ready = False
    with pytest.raises(FaultRecoveryError, match="NEW_FULL_READY_FAILED"):
        run_stage(plan, "resume-reference", backend=backend, attempt=attempt)
    assert attempt.state()["effects"]["halt_unknown"]["force_kill"] is False
    assert attempt.state()["phase"] == "outcome_unknown"
    assert backend.events[-1] == ("cooperative-halt17-no-kill",)


def test_real_plist_replacement_calendars_idle_and_no_new_natural_status(tmp_path):
    backend, plan, _attempt = setup(tmp_path)
    host = FaultRecoveryHost()
    host.home = tmp_path / "home"
    host.directory = host.home / "Library/Application Support/GuiyiQuant"
    agents = host.home / "Library/LaunchAgents"
    agents.mkdir(parents=True, mode=0o700)
    old, new = backend.old, registry(plan["new"])
    (backend.old_root / ".run").mkdir(mode=0o700)
    (backend.new_root / ".run").mkdir(mode=0o700)
    for marker in (
        "weekly-audit-enabled",
        "reference-worker-enabled",
        "alert-runtime-enabled",
        "market-runtime-enabled",
    ):
        (backend.old_root / ".run" / marker).write_bytes(b"enabled\n")
    installed = {}
    for name, item in old.services.items():
        env = dict(
            GUIYI_PROJECT_ROOT=item.root,
            GUIYI_RUNTIME_TAG=item.tag,
            GUIYI_RUNTIME_COMMIT=item.commit,
            GUIYI_RUNTIME_GENERATION="16",
            GUIYI_RUNTIME_HANDOVER_ENABLED="1",
            GUIYI_OBSERVATION_STREAM_ENABLED="1",
        )
        payload = dict(
            Label=item.label,
            WorkingDirectory=str(host.home) if name in ("api", "web") else item.root,
            EnvironmentVariables=env,
            ProgramArguments=list(authorized_program_arguments(item, host.home)),
        )
        if name in CALENDARS:
            payload.update(
                RunAtLoad=False,
                KeepAlive=False,
                StartCalendarInterval={"Hour": 18, "Minute": 5},
            )
        raw = plistlib.dumps(payload)
        host.path(item).write_bytes(raw)
        installed[name] = {"plist_hex": raw.hex(), "sha256": sha256(raw).hexdigest()}
    plan["installed"] = installed
    for name in SERVICES:
        host.install(old.services[name], new.services[name], plan)
    for item in new.services.values():
        payload = plistlib.loads(host.bytes(host.path(item)))
        assert payload["EnvironmentVariables"]["GUIYI_RUNTIME_GENERATION"] == "17"
        if item.service in CALENDARS:
            assert not payload["RunAtLoad"] and not payload["KeepAlive"]
    assert not (backend.new_root / ".run/after-market-status.json").exists()


def test_feed_close_proof_must_be_real_old_identity_zero_buffers_and_channels(tmp_path):
    backend, _plan, _attempt = setup(tmp_path)
    host = FaultRecoveryHost()
    item = backend.old.services["market-feed"]
    value = dict(
        generated_at=datetime.now(UTC).isoformat(),
        runtime_generation=16,
        runtime_commit=OLD_COMMIT,
        runtime_root=item.root,
        runtime_tag=item.tag,
        input_pending_count=0,
        subscribed_count=0,
        input_failure=None,
    )
    host.verify_feed_closed(item, {"feed_close": value})
    for key, wrong in [
        ("input_pending_count", 1),
        ("subscribed_count", 1),
        ("runtime_generation", 15),
        ("input_failure", "LIVE_PROVIDER_CLOSE_UNKNOWN"),
    ]:
        with pytest.raises(FaultRecoveryError, match="FEED_CLOSE_UNPROVEN"):
            host.verify_feed_closed(item, {"feed_close": {**value, key: wrong}})


def test_restore_receipt_gate_requires_public_success_and_exact_old_binding(tmp_path):
    backend, plan, _attempt = setup(tmp_path)
    receipt = dict(
        status="PROJECTION_RESTORED",
        evidence_class="task_repair",
        source_cursor_unchanged=True,
        completed_prefix_unchanged=True,
        natural_status_unchanged=True,
        remaining_missing_bars=0,
        drain_executed=False,
        runtime={"root": str(backend.old_root), "commit": OLD_COMMIT},
        authority_hash="a" * 64,
        plan_sha256="b" * 64,
        bindings={
            name: asdict(backend.old.services[name])
            for name in (
                "after-market",
                "market-feed",
                "live",
                "alert",
                "reference-worker",
            )
        },
        candidate={"root": str(backend.new_root), "commit": "d" * 40},
        at=datetime.now(UTC).isoformat(),
        source_count=13500,
        completed_count=8937,
        source_cursor="1-0",
        source_tail="2-0",
        natural_status_preimage={
            "after-market-status.json": "status-hash",
            "after-market-history.json": "history-hash",
        },
    )
    path = Path(plan["projection_readback"])
    path.write_text(json.dumps(receipt))
    host = FaultRecoveryHost(projection_sha256=sha256(path.read_bytes()).hexdigest())
    from datetime import timedelta

    effects = {
        "parked_proof": {"at": (datetime.now(UTC) - timedelta(seconds=5)).isoformat()}
    }
    plan["protected"]["files"] = {
        str(backend.old_root / ".run/after-market-status.json"): "status-hash",
        str(backend.old_root / ".run/after-market-history.json"): "history-hash",
    }
    host.projection_journal_readback = lambda: {
        "source_count": 13500,
        "completed_count": 8937,
        "source_cursor": "1-0",
        "source_tail": "2-0",
    }
    assert host.verify_projection_restore(plan, effects)["authority_hash"] == "a" * 64
    valid = dict(receipt)
    for field, wrong, code in [
        (
            "bindings",
            {
                **{k: v for k, v in receipt["bindings"].items() if k != "after-market"},
                "api": asdict(backend.old.services["api"]),
            },
            "RESTORE_BINDING_DRIFT",
        ),
        (
            "candidate",
            {"root": str(backend.old_root), "commit": OLD_COMMIT},
            "RESTORE_CANDIDATE_DRIFT",
        ),
        (
            "at",
            (datetime.now(UTC) - timedelta(seconds=20)).isoformat(),
            "RESTORE_TIME_UNPROVEN",
        ),
        ("source_count", 13499, "RESTORE_JOURNAL_DRIFT"),
        ("source_cursor", "0-0", "RESTORE_JOURNAL_DRIFT"),
        ("completed_count", 8936, "RESTORE_JOURNAL_DRIFT"),
    ]:
        path.write_text(json.dumps({**valid, field: wrong}))
        host.projection_sha256 = sha256(path.read_bytes()).hexdigest()
        with pytest.raises(FaultRecoveryError, match=code):
            host.verify_projection_restore(plan, effects)
    receipt["remaining_missing_bars"] = 1
    path.write_text(json.dumps(receipt))
    host.projection_sha256 = sha256(path.read_bytes()).hexdigest()
    with pytest.raises(FaultRecoveryError, match="PROJECTION_RESTORE_REQUIRED"):
        host.verify_projection_restore(plan, effects)


def test_host_fault_window_accepts_authoritative_night_only_when_fenced(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace
    from datetime import date
    import app.runtime_fault_recovery_host as host_module
    import app.runtime_scheduled as scheduled
    import app.db.session as db
    import app.market_data.market_phase as phases
    import app.market_data.operational_universe as universe
    import app.market_data.composition as composition

    backend, plan, _ = setup(tmp_path)
    host = FaultRecoveryHost()
    host.bindings = lambda: backend.old
    parked = []
    host.assert_parked = lambda old, effects: parked.append(True)
    monkeypatch.setattr(host_module, "owner_lock_available", lambda name: True)
    monkeypatch.setattr(scheduled.ScheduledBackend, "idle", lambda self, binding: True)
    monkeypatch.setattr(db, "SessionLocal", lambda: nullcontext(object()))
    products = [f"P{i}" for i in range(60)]
    monkeypatch.setattr(universe, "load_operational_products", lambda: products)
    phase = SimpleNamespace(
        phase=phases.MarketPhase.TRADING, trading_day=date(2026, 10, 13)
    )
    monkeypatch.setattr(
        phases.MarketPhaseResolver, "resolve", lambda self, product, now: phase
    )
    mapped = []
    monkeypatch.setattr(
        composition,
        "build_market_data_service",
        lambda session: SimpleNamespace(
            dominant_segment_for_day=lambda product, day: mapped.append((product, day))
        ),
    )
    effects = {
        "parked_proof": {
            "feed_close": {
                "input_pending_count": 0,
                "subscribed_count": 0,
                "runtime_generation": 16,
                "runtime_commit": OLD_COMMIT,
            }
        }
    }
    result = host.fault_window(plan, effects)
    assert result["kind"] == "all_old_publishers_closed"
    assert set(result["session_phases"].values()) == {"TRADING"}
    assert len(mapped) == 60 and parked
    phase.phase = phases.MarketPhase.UNKNOWN
    with pytest.raises(FaultRecoveryError, match="SESSION_UNPROVEN"):
        host.fault_window(plan, effects)
    phase.phase = phases.MarketPhase.TRADING
    effects["parked_proof"]["feed_close"]["subscribed_count"] = 1
    with pytest.raises(FaultRecoveryError, match="SEALED_PUBLISHER_UNPROVEN"):
        host.fault_window(plan, effects)
    effects["parked_proof"]["feed_close"]["subscribed_count"] = 0
    monkeypatch.setattr(scheduled.ScheduledBackend, "idle", lambda self, binding: False)
    with pytest.raises(FaultRecoveryError, match="CALENDAR_BUSY"):
        host.fault_window(plan, effects)


def test_new_reference_park_check_accepts_actual_held_guard_and_default_requires_free_lock(
    tmp_path, monkeypatch
):
    import app.runtime_fault_recovery_host as module

    backend, plan, _ = setup(tmp_path)
    binding = registry(plan["new"]).services["reference-worker"]
    host = FaultRecoveryHost()
    host.loaded = lambda item: 42
    monkeypatch.setattr(
        module,
        "read_service_state",
        lambda name: {"phase": "parked", "ready": False, "generation": 17, "pid": 42},
    )
    monkeypatch.setattr(
        module,
        "_read",
        lambda path: {"phase": "drain", "generation": 17, "request_id": "request17"},
    )
    monkeypatch.setattr(module, "owner_lock_available", lambda name: False)
    calls = []
    host.await_new_reference_parked(
        binding, "request17", held_guard=lambda: calls.append("held_inode_checked")
    )
    assert calls == ["held_inode_checked"]
    times = iter([0, 0, 31])
    monkeypatch.setattr(module, "monotonic", lambda: next(times))
    monkeypatch.setattr(module, "sleep", lambda seconds: None)
    with pytest.raises(FaultRecoveryError, match="NEW_REFERENCE_PARK_TIMEOUT"):
        host.await_new_reference_parked(binding, "request17")


def test_new_reference_held_inode_guard_failure_cannot_be_bypassed(
    tmp_path, monkeypatch
):
    backend, plan, _ = setup(tmp_path)
    host = FaultRecoveryHost()

    def changed():
        raise FaultRecoveryError("OWNER_INODE_CHANGED")

    with pytest.raises(FaultRecoveryError, match="OWNER_INODE_CHANGED"):
        host.await_new_reference_parked(
            registry(plan["new"]).services["reference-worker"],
            "request17",
            held_guard=changed,
        )
