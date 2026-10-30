"""Late-start closure never retries a live operation or erases failure evidence."""

import hashlib
import json
from types import SimpleNamespace as NS
import pytest
from test_trade_switch import m
from test_ordinary_takeover import granted as granted


def fixture(tmp_path):
    tmp_path.chmod(0o700)
    controller = dict(root="/exact/release-v1.16.42", tag="v1.16.42", commit="b" * 40)
    snapshot = dict(
        candidate=dict(commit="a" * 40),
        host=dict(pid=100, run_id="old"),
        ordinary_permit={"schema": "simnow_ordinary_takeover_v3"},
        preimage={"frozen": True},
    )
    plan = dict(schema=m.SCHEMA, snapshot=snapshot, created_at=1, expires_at=61)
    plan["plan_hash"] = m.digest(plan)
    m.write_private(tmp_path / "switch-plan.private.json", plan, exclusive=True)
    intent = dict(
        schema=m.SCHEMA,
        stage="VERIFYING",
        error="READBACK_UNPROVEN",
        plan_hash=plan["plan_hash"],
        snapshot=snapshot,
        at=2,
        native_recovery_complete=False,
    )
    m.write_private(tmp_path / "switch-intent.private.json", intent, exclusive=True)
    (tmp_path / "switch.lock").touch(mode=0o600)

    class Backend:
        calls = []
        bad = None
        reads = 0

        def reconciliation_controller_identity(self, tag):
            assert tag == "v1.16.42"
            return dict(controller)

        def reconcile_preflight(self, source):
            self.calls.append("preflight")
            if self.bad in {"budget", "sdk", "identity"}:
                m.fail("PREIMAGE_CHANGED")
            return dict(
                pid=200,
                run_id="new",
                grant_sha256="c" * 64,
                run_claim_sha256="d" * 64,
                account_anchor_sha256="e" * 64,
            )

        def readback(self, source):
            self.calls.append("readback")
            self.reads += 1
            if self.bad == "second" and self.reads == 2:
                m.fail("READBACK_UNPROVEN")
            return dict(
                verified=True,
                pid=200,
                run_id="new",
                mode="trade",
                dual_locks_held_by_pid=True,
                config_bound=True,
                monitor_bound=True,
                account_takeover_pending=True,
                opening_enabled=False,
            )

    b = Backend()
    b.calls = []
    c = m.Coordinator(b, tmp_path, sleep=lambda _: None)
    return c, b, intent, controller


def test_closure_preserves_original_bytes_and_never_restarts(tmp_path):
    c, b, intent, controller = fixture(tmp_path)
    raw = c.intent.read_bytes()
    result = c.reconcile_started("v1.16.42")
    assert (
        result["stage"] == "COMPLETE"
        and result["result"] == "HOST_SWITCH_LATE_VERIFIED"
    )
    assert (tmp_path / "late-started-beforeimage.private.json").read_bytes() == raw
    updated = json.loads(c.intent.read_bytes())
    assert updated["initial_failure"]["sha256"] == hashlib.sha256(raw).hexdigest()
    assert updated["error"] == "READBACK_UNPROVEN"
    assert (
        updated["reconciliation_receipt"]["sha256"]
        == hashlib.sha256(
            (tmp_path / "late-started-receipt.private.json").read_bytes()
        ).hexdigest()
    )
    receipt = json.loads((tmp_path / "late-started-receipt.private.json").read_bytes())
    assert receipt["controller"] == controller and len(receipt["proofs"]) == 2
    assert "start" not in b.calls and "stop" not in b.calls and "issue" not in b.calls
    before = c.intent.read_bytes()
    with pytest.raises(m.SwitchError):
        c.reconcile_started("v1.16.42")
    assert c.intent.read_bytes() == before


@pytest.mark.parametrize("bad", ["budget", "sdk", "identity", "second"])
def test_drift_or_failed_second_round_never_finalizes_or_claims(tmp_path, bad):
    c, b, intent, controller = fixture(tmp_path)
    b.bad = bad
    before = c.intent.read_bytes()
    with pytest.raises(m.SwitchError):
        c.reconcile_started("v1.16.42")
    assert c.intent.read_bytes() == before
    assert not (tmp_path / "late-started-reconciliation-claim.private.json").exists()
    assert b.calls and "start" not in b.calls


def test_original_coordinator_lock_blocks_all_work(tmp_path):
    import fcntl

    c, b, _, _ = fixture(tmp_path)
    with (tmp_path / "switch.lock").open("rb") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(m.SwitchError, match="SWITCH_BUSY"):
            c.reconcile_started("v1.16.42")
    assert (
        b.calls == []
        and not (tmp_path / "late-started-reconciliation-claim.private.json").exists()
    )


@pytest.mark.parametrize("phase", ["STOPPED", "INSTALLING", "COMPLETE"])
def test_only_unknown_started_phases_are_eligible(tmp_path, phase):
    c, b, intent, _ = fixture(tmp_path)
    intent["stage"] = phase
    m.write_private(c.intent, intent)
    with pytest.raises(m.SwitchError):
        c.reconcile_started("v1.16.42")
    assert b.calls == []


def test_source_plan_drift_before_any_claim(tmp_path):
    c, b, _, _ = fixture(tmp_path)
    p = tmp_path / "switch-plan.private.json"
    plan = json.loads(p.read_bytes())
    plan["plan_hash"] = "0" * 64
    m.write_private(p, plan)
    with pytest.raises(m.SwitchError, match="PLAN_INVALID"):
        c.reconcile_started("v1.16.42")
    assert (
        b.calls == []
        and not (tmp_path / "late-started-reconciliation-claim.private.json").exists()
    )


def test_missing_source_mutex_is_not_created(tmp_path):
    c, b, _, _ = fixture(tmp_path)
    lock = tmp_path / "switch.lock"
    lock.unlink()
    with pytest.raises((m.SwitchError, FileNotFoundError)):
        c.reconcile_started("v1.16.42")
    assert not lock.exists() and b.calls == []


def test_state_drift_between_proofs_and_commit_has_no_claim(tmp_path):
    c, b, _, _ = fixture(tmp_path)
    old = b.reconcile_preflight
    calls = []

    def changing(source):
        result = old(source)
        calls.append(1)
        if len(calls) > 1:
            result["account_anchor_sha256"] = "f" * 64
        return result

    b.reconcile_preflight = changing
    before = c.intent.read_bytes()
    with pytest.raises(m.SwitchError, match="PREIMAGE_CHANGED"):
        c.reconcile_started("v1.16.42")
    assert (
        c.intent.read_bytes() == before
        and not (tmp_path / "late-started-reconciliation-claim.private.json").exists()
    )


def test_claimed_write_failure_cannot_be_retried(tmp_path, monkeypatch):
    c, b, _, _ = fixture(tmp_path)
    before = c.intent.read_bytes()
    write = m.write_private

    def failed(path, *args, **kwargs):
        if path.name == "late-started-receipt.private.json":
            raise OSError("fixture disk failure")
        return write(path, *args, **kwargs)

    monkeypatch.setattr(m, "write_private", failed)
    with pytest.raises(OSError):
        c.reconcile_started("v1.16.42")
    assert c.intent.read_bytes() == before
    assert (tmp_path / "late-started-beforeimage.private.json").read_bytes() == before
    with pytest.raises(m.SwitchError, match="ATTEMPT_CONSUMED"):
        c.reconcile_started("v1.16.42")


@pytest.fixture
def real_preflight(granted, monkeypatch):
    from datetime import datetime

    s, inbox, now, start, intent, record, frozen = granted
    backend = object.__new__(m.MacBackend)
    backend.ordinary = True
    backend.settings = s
    backend.config = s.source_config_path
    backend.candidate_plist = s.source_config_path
    backend.plist = s.source_config_path
    backend.code = s.project_root
    backend.folder = s.state_root / s.account_id
    backend.tag = "v1.16.40"
    backend._verify_historical_anchor = lambda snapshot: None
    backend._candidate = lambda: ("a" * 40, dict(candidate_valid=True))
    backend.identity = lambda *args, **kwargs: "fixed"
    backend.monitor_bound = lambda snapshot: True
    backend._window = lambda: dict(
        policy=m.ORDINARY_POLICY,
        trading_day="20261102",
        authoritative=True,
        product_count=60,
        current_session_absent=True,
        window_open=True,
        next_session_gap_seconds=3600,
    )
    account = dict(today_attempts=0, day_blocked=False, databases=[1, 2, 3, 4])
    backend._account = lambda: dict(account)
    backend._pid = lambda: 200
    backend._prove = lambda *args: None
    backend.release_identity = lambda root: dict(
        root=str(root), tag=backend.tag, commit="a" * 40
    )
    snapshot = dict(
        host=dict(pid=100, run_id="old"),
        candidate=dict(commit="a" * 40, tag=backend.tag),
        preimage={k: "fixed" for k in ("sdk", "config", "plist", "runner")},
        ordinary_permit=frozen,
        account=account,
    )
    m.write_private(
        backend.folder / "continuous.json",
        dict(
            at=now.isoformat(),
            run_id="new",
            status="WAITING_SESSION",
            connection="UNKNOWN",
            account_takeover_pending=True,
            opening_enabled=False,
        ),
        exclusive=True,
    )
    m.write_private(
        s.ordinary_takeover_permit.with_name(
            s.ordinary_takeover_permit.name + ".run-claim"
        ),
        dict(grant_sha256=record["ordinary_grant_sha256"], pid=200, run_id="new"),
        exclusive=True,
    )

    def gone(pid, sig):
        raise ProcessLookupError()

    monkeypatch.setattr(m.os, "kill", gone)
    monkeypatch.setattr(
        m,
        "datetime",
        NS(
            now=lambda zone: now,
            fromisoformat=datetime.fromisoformat,
            strptime=datetime.strptime,
        ),
    )
    monkeypatch.setattr(m.time, "time", lambda: now.timestamp())
    return backend, snapshot, inbox, now


def test_real_preflight_checks_private_grant_and_original_budget(real_preflight):
    backend, snapshot, inbox, now = real_preflight
    proof = backend.reconcile_preflight(snapshot)
    assert proof["pid"] == 200 and proof["run_id"] == "new"
    assert inbox.conn.execute("SELECT * FROM attempts").fetchall() == []


@pytest.mark.parametrize(
    "drift", ["budget", "attempt_claim", "sdk", "status", "old_pid", "window", "claim"]
)
def test_real_preflight_admission_rejects_drift(real_preflight, monkeypatch, drift):
    backend, snapshot, inbox, now = real_preflight
    if drift == "budget":
        inbox.attempt("20261102")
    elif drift == "attempt_claim":
        p = backend.settings.ordinary_takeover_permit
        p.with_name(p.name + ".attempt-1.claim").touch(mode=0o600)
    elif drift == "sdk":
        backend.identity = lambda *args, **kwargs: "changed"
    elif drift == "status":
        p = backend.folder / "continuous.json"
        v = json.loads(p.read_bytes())
        v["opening_enabled"] = True
        m.write_private(p, v)
    elif drift == "old_pid":
        monkeypatch.setattr(m.os, "kill", lambda *args: None)
    elif drift == "window":
        w = backend._window()
        w["next_session_gap_seconds"] = 660
        backend._window = lambda: w
    else:
        p = backend.settings.ordinary_takeover_permit.with_name(
            backend.settings.ordinary_takeover_permit.name + ".run-claim"
        )
        v = json.loads(p.read_bytes())
        v["pid"] = 201
        m.write_private(p, v)
    with pytest.raises((m.SwitchError, ValueError)):
        backend.reconcile_preflight(snapshot)


def test_second_pid_drift_never_claims(tmp_path):
    c, b, _, _ = fixture(tmp_path)
    read = b.readback

    def changed(source):
        result = read(source)
        if b.reads == 2:
            result["pid"] = 201
        return result

    b.readback = changed
    with pytest.raises(m.SwitchError, match="READBACK_UNPROVEN"):
        c.reconcile_started("v1.16.42")
    assert not (tmp_path / "late-started-reconciliation-claim.private.json").exists()


def test_closed_original_intent_satisfies_unchanged_runtime_next_day_contract(
    granted, tmp_path
):
    from guiyi_quant.simnow_execution import ordinary_takeover as ordinary

    s, inbox, now, start, intent, record, frozen = granted
    helper = tmp_path / "controller-helper"
    helper.mkdir(mode=0o700)
    _, backend, _, _ = fixture(helper)
    snapshot = dict(
        record["snapshot"],
        candidate=dict(commit="a" * 40),
        host=dict(pid=100, run_id="old"),
        preimage=dict(frozen=True),
    )
    plan = dict(schema=m.SCHEMA, snapshot=snapshot, created_at=1, expires_at=61)
    plan["plan_hash"] = m.digest(plan)
    grant_path = s.ordinary_takeover_permit
    grant = json.loads(grant_path.read_bytes())
    grant["plan_hash"] = plan["plan_hash"]
    m.write_private(grant_path, grant)
    grant_sha = hashlib.sha256(grant_path.read_bytes()).hexdigest()
    record.update(
        stage="VERIFYING",
        error="READBACK_UNPROVEN",
        native_recovery_complete=False,
        plan_hash=plan["plan_hash"],
        snapshot=snapshot,
    )
    record["ordinary_grant_sha256"] = grant_sha
    m.write_private(intent, record)
    m.write_private(intent.parent / "switch-plan.private.json", plan, exclusive=True)
    (intent.parent / "switch.lock").touch(mode=0o600)
    claim = dict(grant_sha256=grant_sha, pid=200, run_id="new")
    claim_path = grant_path.with_name(grant_path.name + ".run-claim")
    m.write_private(claim_path, claim, exclusive=True)
    c = m.Coordinator(backend, intent.parent, sleep=lambda _: None)
    c.reconcile_started("v1.16.42")
    # This is the same permit_required contract deployed in Runtime41. No
    # runtime code, budget, block, grant or original run claim is modified.
    assert ordinary.permit_required(s, "20261103") is False
    assert json.loads(claim_path.read_bytes()) == claim
    assert inbox.conn.execute("SELECT * FROM attempts").fetchall() == []
    assert inbox.conn.execute("SELECT * FROM blocks").fetchall() == []


@pytest.mark.parametrize("offset", [-9, 1])
def test_real_preflight_rejects_stale_or_future_status(real_preflight, offset):
    from datetime import timedelta

    backend, snapshot, inbox, now = real_preflight
    p = backend.folder / "continuous.json"
    v = json.loads(p.read_bytes())
    v["at"] = (now + timedelta(seconds=offset)).isoformat()
    m.write_private(p, v)
    with pytest.raises(m.SwitchError, match="READBACK_UNPROVEN"):
        backend.reconcile_preflight(snapshot)
