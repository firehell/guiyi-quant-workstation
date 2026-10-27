"""A new post-CAS recovery never replays or rewrites the consumed cohort."""

from contextlib import nullcontext
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
import json

import pytest

from app.runtime_handover import _write
from tests.test_runtime_cohort import Host, plan


def fixture(tmp_path):
    host = Host(tmp_path)
    source = plan(host)
    path = tmp_path / "source.json"
    _write(path, source)
    host.registry = __import__("app.runtime_cohort", fromlist=["registry"]).registry(
        source["new"]
    )
    directory = host.directory / "cohort-attempts" / source["plan_sha256"]
    directory.mkdir(parents=True, mode=0o700)
    directory.parent.chmod(0o700)
    state = {
        "schema_version": 1,
        "plan_sha256": source["plan_sha256"],
        "phase": "outcome_unknown",
        "effects": {
            "drain": {"owners": {}, "progress": {}},
            "install": {},
            "consumers": {},
        },
        "error_code": "COHORT_WINDOW_TOO_SHORT_OR_UNKNOWN",
    }
    _write(directory / "state.json", state)
    _write(host.directory / "cohort-release.json", state)
    audit = {
        "registry_sha256": host.binding_hash(),
        "installed_sha256": "a" * 64,
        "old_exited_sha256": "b" * 64,
        "protected": source["protected"],
        "new_protected": {"scope": "new-frozen"},
        "owners": {"reference-worker": {"pid": 100, "generation": 29}},
        "controls": {"reference-worker": {"request_id": "c" * 32}},
        "receiving": {"kind": "test_source_proof", "cursor": 10},
        "window": host.session_proof(),
        "controller": {
            "root": str(host.root),
            "tag": "v1.16.15",
            "commit": "d" * 40,
            "tracked_sha256": "e" * 64,
        },
    }
    host._controller = lambda: deepcopy(audit["controller"])

    def check_protected(source, frozen):
        module().require(
            audit["new_protected"] == frozen["new_protected"],
            "COHORT_FORWARD_NEW_PROTECTED_DRIFT",
        )

    host.check_protected_forward = check_protected
    host.audit_forward = lambda source, check_budget, **kwargs: deepcopy(audit)
    host.forward_guards = lambda source: nullcontext()
    host.resume_consumers = lambda *args: (
        host.calls.append("consumers") or {"resumed": True}
    )
    host.await_consumers = lambda *args: (
        host.calls.append("intake")
        or {"kind": "typed_intake_liveness", "calculation_ready": False}
    )
    host.resume_feed = lambda *args: host.calls.append("feed") or {"started": True}
    host.verify_forward = lambda *args: (
        host.calls.append("verified")
        or {"identity": "matched", "calculation_ready": False}
    )
    host.forward_calendars = lambda *args: (
        host.calls.append("calendars") or {"registered": True}
    )
    host.halt_unknown = lambda *args: host.calls.append("halt")
    host.monotonic = lambda: 0.0
    return host, source, path, directory, state, audit


def module():
    from app import runtime_cohort_recovery

    return runtime_cohort_recovery


def test_forward_recovery_has_new_identity_keeps_original_unknown_and_never_cas(
    tmp_path,
):
    host, source, path, attempt, state, _ = fixture(tmp_path)
    original = (attempt / "state.json").read_bytes()
    frozen = module().freeze_forward_recovery(host, path)
    assert frozen["kind"] == "postcas_forward_recovery_v1"
    assert frozen["plan_sha256"] != source["plan_sha256"]
    assert frozen["source"]["attempt_bytes_sha256"] == sha256(original).hexdigest()
    target = tmp_path / "recovery.json"
    _write(target, frozen)
    result = module().apply_forward_recovery(host, target)
    assert result["status"] == "recovered"
    assert host.calls == ["consumers", "intake", "feed", "verified", "calendars"]
    assert (attempt / "state.json").read_bytes() == original
    global_state = json.loads((host.directory / "cohort-release.json").read_bytes())
    assert global_state["kind"] == "postcas_forward_recovery_result"
    assert global_state["source_phase"] == state["phase"] == "outcome_unknown"
    assert global_state["phase"] == "switched"
    receipt = (
        host.directory
        / "cohort-forward-recoveries"
        / frozen["plan_sha256"]
        / "receipt.json"
    )
    assert sha256(receipt.read_bytes()).hexdigest() == global_state["receipt_sha256"]
    assert result["natural_acceptance"] == "pending"


@pytest.mark.parametrize(
    "phase", ["restore_unknown", "switched", "committed", "cancelled"]
)
def test_only_postcas_unknown_can_be_frozen(tmp_path, phase):
    host, _, path, attempt, state, _ = fixture(tmp_path)
    state["phase"] = phase
    _write(attempt / "state.json", state)
    _write(host.directory / "cohort-release.json", state)
    with pytest.raises(ValueError, match="FORWARD_SOURCE_INVALID"):
        module().freeze_forward_recovery(host, path)
    assert host.calls == []


def test_old_or_other_registry_never_enters_forward_recovery(tmp_path):
    host, _, path, _, _, _ = fixture(tmp_path)
    host.registry = host.old
    with pytest.raises(ValueError, match="FORWARD_REGISTRY_DRIFT"):
        module().freeze_forward_recovery(host, path)


@pytest.mark.parametrize(
    "field",
    [
        "installed_sha256",
        "old_exited_sha256",
        "controls",
        "owners",
        "receiving",
        "protected",
    ],
)
def test_fresh_audit_drift_before_effects_rejects(tmp_path, field):
    host, _, path, attempt, _, audit = fixture(tmp_path)
    frozen = module().freeze_forward_recovery(host, path)
    target = tmp_path / "recovery.json"
    _write(target, frozen)
    audit[field] = "changed"
    before = (attempt / "state.json").read_bytes()
    with pytest.raises(ValueError, match="FORWARD_AUDIT_DRIFT"):
        module().apply_forward_recovery(host, target)
    assert not host.calls
    assert (attempt / "state.json").read_bytes() == before


def test_original_unknown_drift_is_never_overwritten(tmp_path):
    host, _, path, attempt, state, _ = fixture(tmp_path)
    target = tmp_path / "recovery.json"
    _write(target, module().freeze_forward_recovery(host, path))
    _write(attempt / "state.json", {**state, "error_code": "DIFFERENT"})
    with pytest.raises(ValueError, match="FORWARD_SOURCE_(DRIFT|INVALID)"):
        module().apply_forward_recovery(host, target)
    assert host.calls == []


def test_failed_new_resume_preserves_both_unknown_attempts_and_never_restores(tmp_path):
    host, _, path, attempt, _, _ = fixture(tmp_path)
    original = (attempt / "state.json").read_bytes()
    global_original = (host.directory / "cohort-release.json").read_bytes()
    target = tmp_path / "recovery.json"
    frozen = module().freeze_forward_recovery(host, path)
    _write(target, frozen)

    def fail(*args):
        raise RuntimeError("private error must not be persisted")

    host.await_consumers = fail
    with pytest.raises(ValueError, match="FORWARD_OUTCOME_UNKNOWN"):
        module().apply_forward_recovery(host, target)
    assert host.calls == ["consumers", "halt"]
    assert (attempt / "state.json").read_bytes() == original
    assert (host.directory / "cohort-release.json").read_bytes() == global_original
    recovery = (
        host.directory
        / "cohort-forward-recoveries"
        / frozen["plan_sha256"]
        / "state.json"
    )
    assert json.loads(recovery.read_bytes())["phase"] == "outcome_unknown"
    assert b"private error" not in recovery.read_bytes()
    with pytest.raises(ValueError, match="FORWARD_ATTEMPT_ALREADY_EXISTS"):
        module().apply_forward_recovery(host, target)


def test_expired_new_plan_cannot_resume_old_consumed_plan(tmp_path):
    host, _, path, _, _, _ = fixture(tmp_path)
    target = tmp_path / "recovery.json"
    _write(target, module().freeze_forward_recovery(host, path))
    now = host.now()
    host.now = lambda: now + timedelta(minutes=15)
    with pytest.raises(ValueError, match="FORWARD_PLAN_EXPIRED"):
        module().apply_forward_recovery(host, target)
    assert host.calls == []


def test_slow_fresh_audit_cannot_cross_budget_then_resume(tmp_path):
    host, _, path, _, _, audit = fixture(tmp_path)
    target = tmp_path / "recovery.json"
    _write(target, module().freeze_forward_recovery(host, path))
    clock = [0]
    host.monotonic = lambda: clock[0]

    def slow(*args, **kwargs):
        clock[0] = 601
        return deepcopy(audit)

    host.audit_forward = slow
    with pytest.raises(ValueError, match="FORWARD_DEADLINE_EXCEEDED"):
        module().apply_forward_recovery(host, target)
    assert host.calls == []


def native(tmp_path):
    from app.runtime_cohort_recovery import ForwardRecoveryHost

    host = ForwardRecoveryHost()
    host.directory = tmp_path
    return host


def test_native_parked_proof_requires_actual_matching_pid_and_free_lock(
    tmp_path, monkeypatch
):
    from app import runtime_cohort_recovery as m

    host, source, _, _, _, _ = fixture(tmp_path)
    current = native(tmp_path)
    current.loaded = lambda binding, **kwargs: (
        100 if binding.service != "market-feed" else None
    )
    current.definition_absent = lambda binding: binding.service == "market-feed"
    monkeypatch.setattr(
        m,
        "read_service_state",
        lambda service, **kwargs: {"phase": "parked", "pid": 100, "generation": 29},
    )
    monkeypatch.setattr(m, "owner_process_matches", lambda *args: True)
    monkeypatch.setattr(m, "owner_lock_available", lambda *args, **kwargs: True)
    proof = current._parked_owners(source)
    assert proof["reference-worker"]["pid"] == 100
    monkeypatch.setattr(m, "owner_lock_available", lambda *args, **kwargs: False)
    with pytest.raises(ValueError, match="FORWARD_OWNER_UNPROVEN"):
        current._parked_owners(source)


@pytest.mark.parametrize(
    "field,value", [("generation", 28), ("phase", "active"), ("pid", 99)]
)
def test_native_no_parked_label_or_stale_owner_shortcut(
    tmp_path, monkeypatch, field, value
):
    from app import runtime_cohort_recovery as m

    _, source, _, _, _, _ = fixture(tmp_path)
    current = native(tmp_path)
    current.loaded = lambda binding, **kwargs: (
        100 if binding.service != "market-feed" else None
    )
    current.definition_absent = lambda binding: binding.service == "market-feed"
    state = {"phase": "parked", "pid": 100, "generation": 29, field: value}
    monkeypatch.setattr(m, "read_service_state", lambda *args, **kwargs: state)
    monkeypatch.setattr(m, "owner_process_matches", lambda *args: True)
    monkeypatch.setattr(m, "owner_lock_available", lambda *args, **kwargs: True)
    with pytest.raises(ValueError, match="FORWARD_OWNER_UNPROVEN"):
        current._parked_owners(source)


def test_native_control_proof_freezes_request_and_generation(tmp_path):
    _, source, _, _, _, _ = fixture(tmp_path)
    current = native(tmp_path)
    for service in ("market-feed", "live", "alert", "reference-worker", "api", "web"):
        _write(
            tmp_path / (service + ".handover.json"),
            {
                "schema_version": 1,
                "service": service,
                "generation": 29,
                "phase": "drain",
                "request_id": "a" * 32,
            },
        )
    proof = current._controls(source)
    assert proof["reference-worker"]["request_id"] == "a" * 32
    _write(
        tmp_path / "reference-worker.handover.json",
        {**proof["reference-worker"], "generation": 28},
    )
    with pytest.raises(ValueError, match="FORWARD_DRAIN_UNPROVEN"):
        current._controls(source)


@pytest.mark.parametrize("phase", ["TRADING", "BREAK", "CLOSED"])
def test_samegen_startup_accepts_authoritative_current_day_without_promotion_rest(
    tmp_path, phase
):
    from datetime import date
    from types import SimpleNamespace
    from app.market_data.market_phase import MarketPhase

    now = Host(tmp_path).now()
    day = now.date()
    session = (
        SimpleNamespace(
            start=now - timedelta(minutes=1), end=now + timedelta(minutes=1)
        )
        if phase == "TRADING"
        else None
    )
    row = SimpleNamespace(
        symbol="rb",
        phase=MarketPhase(phase),
        trading_day=day,
        current_session=session,
        next_session_start=now + timedelta(seconds=1),
    )
    resolver = SimpleNamespace(
        resolve=lambda *args: row, completed_observation_trading_day=lambda *args: day
    )
    result = module().prove_same_generation_startup(
        now=now,
        products=("rb",),
        resolver=resolver,
        registered_day=day,
        subscriptions={"rb": "RB2701"},
        dominant=lambda *args: "RB2701",
        sessions=lambda *args: (object(),),
    )
    assert result["mode"] == "same_generation_startup"
    assert result["registered_trading_day"] == date.isoformat(day)


@pytest.mark.parametrize(
    "drift", ["unknown", "ownerday", "rank1", "subscription", "sessions", "no_owner"]
)
def test_samegen_startup_rejects_authority_drift_and_never_guesses_closed_day(
    tmp_path, drift
):
    from types import SimpleNamespace
    from app.market_data.market_phase import MarketPhase

    now = Host(tmp_path).now()
    day = now.date()
    row = SimpleNamespace(
        symbol="rb",
        phase=MarketPhase.UNKNOWN if drift == "unknown" else MarketPhase.CLOSED,
        trading_day=None
        if drift == "no_owner"
        else day + timedelta(days=1)
        if drift == "ownerday"
        else day,
        current_session=None,
        next_session_start=now + timedelta(seconds=1),
    )
    resolver = SimpleNamespace(
        resolve=lambda *args: row,
        completed_observation_trading_day=lambda *args: (
            None if drift in {"ownerday", "no_owner"} else day
        ),
    )
    with pytest.raises(ValueError):
        module().prove_same_generation_startup(
            now=now,
            products=("rb",),
            resolver=resolver,
            registered_day=day,
            subscriptions={"rb": "RB2605"}
            if drift == "subscription"
            else {"rb": "RB2701"},
            dominant=lambda *args: "RB2605" if drift == "rank1" else "RB2701",
            sessions=lambda *args: () if drift == "sessions" else (object(),),
        )


def test_native_startup_uses_only_native_source_and_completed_registrations(
    tmp_path, monkeypatch
):
    from contextlib import nullcontext
    from fnmatch import fnmatchcase
    from types import SimpleNamespace
    from app.market_data.observation_stream import ObservationStream
    from app.market_data.market_phase import MarketPhase
    from app.market_data.operational_universe import load_operational_products
    import app.db.session as database
    import app.db.readonly as readonly
    import app.market_data.composition as composition

    current = native(tmp_path)
    now = Host(tmp_path).now()
    current.now = lambda: now
    day = now.date()
    products = load_operational_products()

    class Redis:
        def __init__(self):
            self.values = {
                "live:observations:registered:source:live": day.isoformat(),
                "live:observations:registered:completed:alert": day.isoformat(),
                "live:observations:registered:completed:reference": day.isoformat(),
            }

        def get(self, key):
            return self.values.get(key)

        def scan_iter(self, *, match):
            return (key for key in self.values if fnmatchcase(key, match))

        def close(self):
            pass

    redis = Redis()
    source = ObservationStream(redis, kind="source")
    contracts = {p: p.upper() + "2701" for p in products}
    resolver = SimpleNamespace(
        resolve=lambda p, n: SimpleNamespace(
            symbol=p,
            phase=MarketPhase.TRADING,
            trading_day=day,
            current_session=SimpleNamespace(
                start=now - timedelta(seconds=1), end=now + timedelta(minutes=1)
            ),
        )
    )
    feed = SimpleNamespace(
        _products=products,
        source_stream=source,
        _phase_resolver=resolver,
        _store=SimpleNamespace(_redis=redis, subscriptions=lambda day: contracts),
        _dominant_source=SimpleNamespace(dominant_for_day=lambda p, d: contracts[p]),
        _coverage_session_source=lambda *args: (object(),),
    )
    monkeypatch.setattr(database, "SessionLocal", lambda: nullcontext(object()))
    monkeypatch.setattr(
        readonly, "readonly_transaction", lambda *args, **kwargs: nullcontext()
    )
    monkeypatch.setattr(composition, "build_market_feed_service", lambda s: feed)
    assert current.recovery_window()["registered_trading_day"] == day.isoformat()


def test_resume_releases_kernel_owner_locks_before_cancelling_parked_process(
    tmp_path, monkeypatch
):
    import fcntl
    import os
    from threading import Thread
    from app import runtime_cohort_recovery as m
    import app.reference_trading.receiving_liveness as liveness

    _, source, _, _, _, _ = fixture(tmp_path)
    current = native(tmp_path)
    fixed = {"all": "exact"}
    audit = {
        "controller": {"fixed": "controller"},
        "controls": {},
        "owners": {"parked": "proven"},
        "installed_sha256": m.digest(fixed),
        "receiving": "proof",
    }
    for name in m.CONTINUOUS:
        (tmp_path / (name + ".owner.lock")).write_bytes(b"")
        (tmp_path / (name + ".owner.lock")).chmod(0o600)
        control = {
            "schema_version": 1,
            "service": name,
            "generation": 29,
            "phase": "drain",
            "request_id": "a" * 32,
        }
        _write(tmp_path / (name + ".handover.json"), control)
        audit["controls"][name] = control
    current.forward_guards = lambda *args: nullcontext()
    current._controls = lambda *args: deepcopy(audit["controls"])
    current._parked_owners = lambda *args, **kwargs: audit["owners"]
    current._controller = lambda: audit["controller"]
    current.bindings = lambda: m.registry(source["new"])
    current.check_protected_forward = lambda *args: None
    current._fixed = lambda *args: fixed
    current._snapshot = lambda *args: {}
    current._old_exited = lambda *args: None
    current._calculation_boundary = lambda: None
    current.recovery_window = lambda: None
    monkeypatch.setattr(liveness, "receiving_snapshot_identity", lambda v: "proof")
    results = []

    def cancel(name, **kwargs):
        def parked_resume():
            fd = os.open(tmp_path / (name + ".owner.lock"), os.O_RDWR)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                results.append("resumed")
            except BlockingIOError:
                results.append("RUNTIME_OWNER_BUSY")
            finally:
                os.close(fd)

        thread = Thread(target=parked_resume)
        thread.start()
        thread.join(2)

    monkeypatch.setattr(m, "cancel_drain", cancel)
    current.resume_consumers(source, audit, lambda: None)
    assert results == ["resumed"] * 5


def test_cli_errors_never_echo_private_exception(tmp_path, monkeypatch, capsys):
    m = module()
    monkeypatch.setattr(m, "ForwardRecoveryHost", lambda: object())

    def fail(*args):
        raise RuntimeError("private://password")

    monkeypatch.setattr(m, "freeze_forward_recovery", fail)
    assert (
        m.main(
            [
                "plan",
                "--source-plan",
                str(tmp_path / "input"),
                "--output",
                str(tmp_path / "output"),
            ]
        )
        == 2
    )
    captured = capsys.readouterr()
    assert not captured.out
    assert json.loads(captured.err) == {
        "status": "blocked",
        "code": "COHORT_FORWARD_OPERATION_FAILED",
    }


def test_clean_but_different_controller_after_atomic_step_is_rejected(tmp_path):
    host, _, path, _, _, audit = fixture(tmp_path)
    target = tmp_path / "recovery.json"
    _write(target, module().freeze_forward_recovery(host, path))

    def drift(*args):
        host.calls.append("consumers")
        host._controller = lambda: {**audit["controller"], "commit": "f" * 40}
        return {"resumed": True}

    host.resume_consumers = drift
    with pytest.raises(ValueError, match="FORWARD_OUTCOME_UNKNOWN"):
        module().apply_forward_recovery(host, target)
    assert host.calls == ["consumers", "halt"]


def test_active_capture_calculation_interleave_waits_for_fresh_round_within_budget(
    tmp_path, monkeypatch
):
    from app import runtime_cohort_recovery as m
    import app.reference_trading.receiving_liveness as liveness

    host, source, _, _, _, _ = fixture(tmp_path)
    current = native(host.directory)
    current.now = host.now
    current.monotonic = lambda: 0.0
    current.recovery_window = lambda: {
        "mode": "same_generation_startup",
        "closed_idle": False,
    }
    current._active = lambda binding: {
        "phase": "active",
        "ready": True,
        "proof": {
            "receiving": {"protocol_version": 2, "intake_error": None},
            "reference_runtime": {"stage": "receiving_cycle"},
        },
    }
    pending = iter([(1, 0), (0, 0), (0, 0)])
    current._read_calculation_boundary = lambda: next(pending)
    count = [0]

    def snapshot(*args, **kwargs):
        count[0] += 1
        return {"owner_cycle_at": str(count[0])}

    current._snapshot = snapshot
    current._fixed = lambda *args: None
    monkeypatch.setattr(m, "port_is_ready", lambda name: True)
    monkeypatch.setattr(m, "sleep", lambda seconds: None)
    monkeypatch.setattr(
        liveness,
        "prove_receiving_liveness",
        lambda *args, **kwargs: {
            "mode": "durable_receiving",
            "calculation_ready": False,
        },
    )
    result = current.await_consumers(source, {}, lambda: None)
    assert result["calculation_ready"] is False
    assert count[0] == 2  # No sample accepted in the legal capture->calculation gap.


def test_calculation_unknown_is_rejected_in_both_parked_and_active_modes(tmp_path):
    current = native(tmp_path)
    current._read_calculation_boundary = lambda: (0, 1)
    for active in (False, True):
        with pytest.raises(ValueError, match="FORWARD_CALCULATION_UNKNOWN"):
            current._calculation_boundary(active=active)


def test_unresolved_new_recovery_cannot_be_hidden_by_freezing_another_plan(tmp_path):
    host, _, path, _, _, _ = fixture(tmp_path)
    root = host.directory / "cohort-forward-recoveries"
    root.mkdir(mode=0o700)
    attempt = root / ("f" * 64)
    attempt.mkdir(mode=0o700)
    _write(attempt / "state.json", {"phase": "outcome_unknown"})
    with pytest.raises(ValueError, match="FORWARD_RECOVERY_READBACK_REQUIRED"):
        module().freeze_forward_recovery(host, path)


def test_native_verify_preserves_api_version_gate(tmp_path, monkeypatch):
    import app.services.deployment_identity as identities
    import urllib.request

    host, source, _, _, _, _ = fixture(tmp_path)
    current = native(host.directory)
    current._await = lambda *args, **kwargs: {"mode": "durable_receiving"}
    current._fixed = lambda *args: None
    monkeypatch.setattr(
        identities,
        "deployment_identity_health",
        lambda **kwargs: {
            "services": {
                module().IDENTITY_NAMES.get(name, name): {"status": "matched"}
                for name in module().CONTINUOUS
            }
        },
    )

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self):
            return b'{"version":"0.0.0"}'

    monkeypatch.setattr(urllib.request, "urlopen", lambda *args, **kwargs: Response())
    with pytest.raises(ValueError, match="FORWARD_API_VERSION_MISMATCH"):
        current.verify_forward(source, {}, lambda: None)


def test_explicit_live_teardown_is_recorded_before_any_bootout_or_resume(tmp_path):
    host, _, path, _, _, audit = fixture(tmp_path)
    audit["live_restart_intent"] = {
        "kind": "draining_live_teardown_v1",
        "observed_pids": [101, 102],
    }
    target = tmp_path / "recovery.json"
    frozen = module().freeze_forward_recovery(host, path)
    _write(target, frozen)

    def stop(source, audit, budget, record):
        record({"phase": "bootout_requested", "observed_pids": [101, 102, 103]})
        journal = (
            host.directory
            / "cohort-forward-recoveries"
            / frozen["plan_sha256"]
            / "state.json"
        )
        assert json.loads(journal.read_bytes())["effects"]["live_stop"][
            "observed_pids"
        ] == [101, 102, 103]
        host.calls.append("bootout_once")
        return {"phase": "absent_exited", "observed_pids": [101, 102, 103]}

    host.stop_draining_live = stop
    module().apply_forward_recovery(host, target)
    assert host.calls == [
        "bootout_once",
        "consumers",
        "intake",
        "feed",
        "verified",
        "calendars",
    ]


def test_live_restart_pid_drift_only_inside_exact_compatible_intent():
    base = {
        "kind": "draining_live_teardown_v1",
        "failure_code": "COHORT_FORWARD_LIVE_DRAIN_RESTART_LOOP",
        "binding_sha256": "a" * 64,
        "installed_sha256": "b" * 64,
        "control_sha256": "c" * 64,
        "observed_pids": [101, 102],
        "owned_pids": [101, 102],
        "minimum_runs": 141,
    }
    current = {
        **base,
        "observed_pids": [103, 104],
        "owned_pids": [103, 104],
        "minimum_runs": 143,
    }
    assert module().compatible_live_restart_intent(current, base)
    for field, value in [
        ("control_sha256", "d" * 64),
        ("binding_sha256", "d" * 64),
        ("installed_sha256", "d" * 64),
        ("minimum_runs", 140),
    ]:
        assert not module().compatible_live_restart_intent(
            {**current, field: value}, base
        )


def prepared_native_stop(tmp_path, monkeypatch):
    m = module()
    host, source, _, _, _, audit = fixture(tmp_path)
    current = native(host.directory)
    intent = {
        "kind": "draining_live_teardown_v1",
        "failure_code": "COHORT_FORWARD_LIVE_DRAIN_RESTART_LOOP",
        "binding_sha256": "a" * 64,
        "installed_sha256": "b" * 64,
        "control_sha256": "c" * 64,
        "observed_pids": [101, 102],
        "owned_pids": [101, 102],
        "minimum_runs": 141,
    }
    audit["live_restart_intent"] = intent
    audit["controls"]["live"] = {"request_id": "c" * 32}
    current.forward_guards = lambda *args: nullcontext()
    current.check_protected_forward = lambda *args: None
    current._fixed = lambda *args: {"live": {"sha256": "b" * 64}}
    audit["installed_sha256"] = m.digest(current._fixed())
    current._controls = lambda *args: audit["controls"]
    current._live_launchd_sample = lambda *args: {"pid": 104, "runs": 143}
    current._live_restart_intent = lambda *args, **kwargs: {
        **intent,
        "observed_pids": [103, 104],
        "owned_pids": [103, 104],
        "minimum_runs": 143,
    }
    current._parked_owners = lambda *args, **kwargs: audit["owners"]
    current._snapshot = lambda *args: {}
    current._calculation_boundary = lambda: True
    current._old_exited = lambda *args: None
    current.recovery_window = lambda: {"mode": "same_generation_startup"}
    current.monotonic = lambda: 0
    current._controller = lambda: audit["controller"]
    calls = []
    absent = [False]

    def launch(*args, **kwargs):
        calls.append(args[0])
        absent[0] = True

    current.launch = launch
    current.definition_absent = lambda *args: absent[0]
    monkeypatch.setattr(m, "owner_lock_available", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        m.os, "kill", lambda pid, signal: (_ for _ in ()).throw(ProcessLookupError())
    )
    import app.reference_trading.receiving_liveness as liveness

    monkeypatch.setattr(
        liveness, "receiving_snapshot_identity", lambda value: audit["receiving"]
    )
    recorded = []
    return current, source, audit, calls, recorded


def test_native_stop_issues_one_bootout_tracks_all_pids_and_requires_exit_before_resume(
    tmp_path, monkeypatch
):
    current, source, audit, calls, recorded = prepared_native_stop(
        tmp_path, monkeypatch
    )
    result = current.stop_draining_live(
        source, audit, lambda: None, lambda value: recorded.append(deepcopy(value))
    )
    assert calls == ["bootout"]
    assert recorded[0]["phase"] == "bootout_requested"
    assert result["observed_pids"] == [101, 102, 103, 104]
    assert result["phase"] == "absent_exited"
    assert current._live_stopped is True


@pytest.mark.parametrize(
    "state,drift",
    [
        ("spawn scheduled", None),
        ("running", None),
        ("running", "command"),
        ("spawn scheduled", "root"),
        ("running", "generation"),
    ],
)
def test_live_sample_known_restart_state_preserves_every_identity_check(
    tmp_path, monkeypatch, state, drift
):
    from app import runtime_cohort_recovery as m
    import app.runtime_identity as identity
    from app.runtime_bindings import authorized_program_arguments

    host, source, _, _, _, _ = fixture(tmp_path)
    current = native(host.directory)
    binding = m.registry(source["new"]).services["live"]
    arguments = authorized_program_arguments(binding, current.home)
    if drift == "command":
        arguments = ("/bin/bash", "/foreign/launcher", "live")
    root = "/foreign/root" if drift == "root" else binding.root
    generation = 28 if drift == "generation" else binding.generation
    lines = [
        binding.label + " = {",
        " state = " + state,
        " working directory = " + binding.root,
        " runs = 141",
        " last exit code = 1",
    ]
    if state == "running":
        lines.append(" pid = 101")
    lines += [
        " arguments = {",
        *arguments,
        " }",
        " environment = {",
        " GUIYI_PROJECT_ROOT => " + root,
        " GUIYI_RUNTIME_COMMIT => " + binding.commit,
        " GUIYI_RUNTIME_TAG => " + binding.tag,
        " GUIYI_RUNTIME_GENERATION => " + str(generation),
        " }",
        "}",
    ]
    monkeypatch.setattr(
        identity, "read_launchd_service", lambda *args, **kwargs: "\n".join(lines)
    )
    monkeypatch.setattr(
        m,
        "read_service_state",
        lambda *args, **kwargs: {
            "phase": "active",
            "pid": 101,
            "generation": binding.generation,
        },
    )
    monkeypatch.setattr(m, "owner_lock_available", lambda *args, **kwargs: False)
    if drift:
        with pytest.raises(ValueError):
            current._live_launchd_sample(source)
    else:
        sample = current._live_launchd_sample(source)
        assert sample["pid"] == (101 if state == "running" else None)
        assert sample["runs"] == 141


def test_unknown_bootout_result_never_retries_or_resumes_other_services(tmp_path):
    host, _, path, attempt, _, audit = fixture(tmp_path)
    original = (attempt / "state.json").read_bytes()
    audit["live_restart_intent"] = {
        "kind": "draining_live_teardown_v1",
        "observed_pids": [101, 102],
    }
    frozen = module().freeze_forward_recovery(host, path)
    target = tmp_path / "recovery.json"
    _write(target, frozen)

    def uncertain(source, audit, budget, record):
        record({"phase": "bootout_requested", "observed_pids": [101, 102]})
        host.calls.append("bootout_once")
        raise OSError("private command output")

    host.stop_draining_live = uncertain
    with pytest.raises(ValueError, match="FORWARD_OUTCOME_UNKNOWN"):
        module().apply_forward_recovery(host, target)
    assert host.calls == ["bootout_once", "halt"]
    assert (attempt / "state.json").read_bytes() == original
    state = json.loads(
        (
            host.directory
            / "cohort-forward-recoveries"
            / frozen["plan_sha256"]
            / "state.json"
        ).read_bytes()
    )
    assert state["phase"] == "outcome_unknown"
    assert state["effects"]["live_stop"]["phase"] == "bootout_requested"


def test_live_intent_keeps_unowned_observed_pid_and_requires_two_owned(
    tmp_path, monkeypatch
):
    m = module()
    host, source, _, _, _, _ = fixture(tmp_path)
    current = native(host.directory)
    current.monotonic = lambda: 0
    current._controls = lambda source: {"live": {"fixed": "control"}}
    samples = iter(
        [
            {"pid": None, "observed_pid": 101, "runs": 141},
            {"pid": 102, "observed_pid": 102, "runs": 142},
            {"pid": 103, "observed_pid": 103, "runs": 143},
        ]
    )
    current._live_launchd_sample = lambda source: next(samples)
    monkeypatch.setattr(m, "sleep", lambda seconds: None)
    result = current._live_restart_intent(
        source, "b" * 64, {"fixed": "control"}, lambda: None
    )
    assert result["owned_pids"] == [102, 103]
    assert result["observed_pids"] == [101, 102, 103]
    assert current._observed_live_pids == {101, 102, 103}


def test_label_absent_but_unowned_inflight_pid_alive_never_allows_resume(
    tmp_path, monkeypatch
):
    m = module()
    current, source, audit, calls, recorded = prepared_native_stop(
        tmp_path, monkeypatch
    )
    current._observed_live_pids = {
        99
    }  # Earlier fresh apply-audit sample must also survive normalization.
    current._live_launchd_sample = lambda source: {
        "pid": None,
        "observed_pid": 105,
        "runs": 144,
    }

    def kill(pid, signal):
        if pid == 105:
            return None
        raise ProcessLookupError()

    monkeypatch.setattr(m.os, "kill", kill)
    monkeypatch.setattr(m, "sleep", lambda seconds: None)
    checks = [0]

    def budget():
        checks[0] += 1
        if checks[0] > 20:
            raise m.CohortError("COHORT_FORWARD_DEADLINE_EXCEEDED")

    with pytest.raises(ValueError, match="DEADLINE_EXCEEDED"):
        current.stop_draining_live(
            source, audit, budget, lambda value: recorded.append(deepcopy(value))
        )
    assert calls == ["bootout"]
    assert set(recorded[0]["observed_pids"]) == {99, 101, 102, 103, 104, 105}
    assert not getattr(current, "_live_stopped", False)


def test_second_prefrozen_plan_cannot_retry_first_unknown_recovery(tmp_path):
    host, _, path, _, _, _ = fixture(tmp_path)
    first = module().freeze_forward_recovery(host, path)
    now = host.now()
    host.now = lambda: now + timedelta(seconds=1)
    second = module().freeze_forward_recovery(host, path)
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    _write(a, first)
    _write(b, second)

    def fail(*args):
        raise RuntimeError("failure")

    host.await_consumers = fail
    with pytest.raises(ValueError, match="FORWARD_OUTCOME_UNKNOWN"):
        module().apply_forward_recovery(host, a)
    host.calls = []
    with pytest.raises(ValueError, match="FORWARD_RECOVERY_READBACK_REQUIRED"):
        module().apply_forward_recovery(host, b)
    assert not host.calls


def protected_native(tmp_path):
    import plistlib

    m = module()
    host, source, _, _, _, _ = fixture(tmp_path)
    current = native(host.directory)
    old, new = m.registry(source["old"]), m.registry(source["new"])
    old_root, new_root = (
        host.old.services["live"].root,
        host.registry.services["live"].root,
    )
    markers = (
        "market-runtime-enabled",
        "alert-runtime-enabled",
        "reference-worker-enabled",
        "weekly-audit-enabled",
    )
    for root in (old_root, new_root):
        run = __import__("pathlib").Path(root) / ".run"
        run.mkdir()
        for name in markers:
            (run / name).write_bytes(b"enabled\n")
        (run / "after-market-history.json").write_bytes(
            ("old-original" if root == old_root else "promoted-copy").encode()
        )
    shared = current.directory / "private-state.json"
    shared.write_bytes(b"private-unchanged")
    snapshots = {}
    for reg, root in ((old, old_root), (new, new_root)):
        run = __import__("pathlib").Path(root) / ".run"
        snapshots[root] = {
            "db_scope_policy_identity_sha256": "a" * 64,
            "files": {
                str(path): sha256(path.read_bytes()).hexdigest()
                for path in (*run.iterdir(), shared)
            },
        }
    source["protected"] = deepcopy(snapshots[old_root])
    current._controller = lambda: {"fixed": "controller"}
    current.bindings = lambda: new
    current.verify_release = lambda *args: None
    current.contracts = lambda root: new.services["live"].contracts
    current.protected = lambda reg: deepcopy(
        snapshots[next(iter(reg.services.values())).root]
    )
    current.check_schema_compatibility = lambda source: None
    current.path = lambda binding: current.directory / (binding.service + ".plist")
    for binding in new.services.values():
        current.path(binding).write_bytes(plistlib.dumps({}))
    launcher = current.directory / "run-local-service.sh"
    launcher.write_bytes(b"launcher")
    source["installed"]["launcher_sha256"] = sha256(launcher.read_bytes()).hexdigest()
    current.bytes = lambda path: __import__("pathlib").Path(path).read_bytes()
    current.verify_plist = lambda *args: None
    return current, source, snapshots, old_root, new_root


def test_native_fixed_preserves_old_and_independently_pins_new_root_state(tmp_path):
    current, source, snapshots, old_root, new_root = protected_native(tmp_path)
    assert (
        snapshots[old_root] != snapshots[new_root]
    )  # History hashes may differ; identities keep real paths.
    current._fixed(source, lambda: None)
    current.check_protected_forward(source, {"new_protected": snapshots[new_root]})
    assert source["protected"] == snapshots[old_root]


@pytest.mark.parametrize(
    "drift",
    [
        "old_history",
        "old_stable",
        "db_scope",
        "new_private_added",
        "shared_missing",
        "new_history_after_freeze",
        "marker_bad",
        "marker_missing",
    ],
)
def test_native_protected_preimages_reject_every_non_root_drift(tmp_path, drift):
    from pathlib import Path

    current, source, snapshots, old_root, new_root = protected_native(tmp_path)
    frozen = deepcopy(snapshots[new_root])
    if drift == "old_history":
        snapshots[old_root]["files"][
            str(Path(old_root) / ".run/after-market-history.json")
        ] = "f" * 64
    elif drift == "old_stable":
        snapshots[old_root]["files"][str(current.directory / "private-state.json")] = (
            "f" * 64
        )
    elif drift == "db_scope":
        snapshots[new_root]["db_scope_policy_identity_sha256"] = "f" * 64
    elif drift == "new_private_added":
        snapshots[new_root]["files"][
            str(Path(new_root) / "notification-private.json")
        ] = "f" * 64
    elif drift == "shared_missing":
        snapshots[new_root]["files"].pop(str(current.directory / "private-state.json"))
    elif drift == "new_history_after_freeze":
        snapshots[new_root]["files"][
            str(Path(new_root) / ".run/after-market-history.json")
        ] = "f" * 64
    elif drift == "marker_bad":
        (Path(new_root) / ".run/market-runtime-enabled").write_bytes(b"other\n")
    elif drift == "marker_missing":
        (Path(new_root) / ".run/market-runtime-enabled").unlink()
    current._expected_new_protected = frozen
    with pytest.raises(ValueError, match="PROTECTED|ACTIVATION"):
        current._fixed(source, lambda: None)


def test_new_protected_drift_after_resume_stops_before_feed_and_keeps_original(
    tmp_path,
):
    host, _, path, attempt, _, audit = fixture(tmp_path)
    original = (attempt / "state.json").read_bytes()
    target = tmp_path / "recovery.json"
    _write(target, module().freeze_forward_recovery(host, path))

    def drift(*args):
        host.calls.append("consumers")
        audit["new_protected"] = {"scope": "changed"}
        return {"resumed": True}

    host.resume_consumers = drift
    with pytest.raises(ValueError, match="FORWARD_OUTCOME_UNKNOWN"):
        module().apply_forward_recovery(host, target)
    assert host.calls == ["consumers", "halt"]
    assert (attempt / "state.json").read_bytes() == original
