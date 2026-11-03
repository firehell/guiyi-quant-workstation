"""Exact held-source read-only failure handoff, using private temporary SQLite/FDs."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace as NS
import hashlib
import json
import os
import sqlite3

import pytest
from test_trade_switch import m
from test_supervisor import native_fixture

from guiyi_quant import htdy_account_execution as account
from guiyi_quant.htdy_account_execution import model
from guiyi_quant.htdy_account_execution.codec import digest as ledger_digest
from guiyi_quant.simnow_execution import Journal
from guiyi_quant.simnow_execution.evidence import Evidence
from guiyi_quant.simnow_execution.inbox import SignalInbox
from guiyi_quant.simnow_execution.inventory import read_snapshot
import importlib.util

WIRE_SPEC = importlib.util.spec_from_file_location(
    "held_failure_wire_fixture",
    Path(__file__).parents[1] / "simnow_execution/test_adapter.py",
)
wire = importlib.util.module_from_spec(WIRE_SPEC)
WIRE_SPEC.loader.exec_module(wire)

SOURCE = "7794c49ff2381fd989d839c079a53d4caef321cb"
RUN = "a" * 32


def write(path, value):
    path.write_text(json.dumps(value))
    path.chmod(0o600)


@pytest.fixture
def held_failure(tmp_path, monkeypatch):
    now = datetime.now(UTC)
    root = tmp_path / "account-root"
    root.mkdir(mode=0o700)
    folder = root / wire.ACCOUNT
    folder.mkdir(mode=0o700)
    products = tuple(
        line.strip().upper()
        for line in (
            Path(__file__).parents[3] / "data/universe/operational_products.txt"
        )
        .read_text()
        .splitlines()
        if line.strip() and not line.startswith("#")
    )
    original_start = account.start
    monkeypatch.setattr(
        account,
        "start",
        lambda identity, _products, at, rb: original_start(identity, products, at, rb),
    )
    adapter, effect, _, _, _, at, _ = wire.setup(folder)
    adapter.store.execute(
        "aborted-never-sent",
        model.AbortUnsent(
            wire.ACCOUNT,
            effect.order.order_id,
            at + timedelta(seconds=1),
            "fixture-unsent",
            "RESTART_VERIFIED_NEVER_CLAIMED",
        ),
        unsent_proof=lambda _: True,
    )
    state = adapter.store.current()
    adapter.store.close()
    adapter.journal.close()
    (folder / "account.db").rename(folder / "account.sqlite")
    (folder / "dispatch.db").rename(folder / "dispatch.sqlite")
    journal = Journal(folder / "dispatch.sqlite", wire.ACCOUNT)
    failure_at = now - timedelta(seconds=4)
    for stamp in (now - timedelta(hours=1), failure_at + timedelta(seconds=1)):
        journal.event(
            "ctp-disconnect:" + stamp.isoformat(), dict(kind="disconnect"), stamp
        )
    journal.close()
    inbox = SignalInbox(folder / "signals.sqlite", wire.ACCOUNT, products)
    inbox.conn.execute("INSERT INTO attempts VALUES ('20261103',3)")
    inbox.block("20261103", "CONTINUOUS_RECOVERY_REQUIRED")
    inbox.close()
    report = native_fixture.report()
    report.update(account_fingerprint=wire.ACCOUNT, trading_day="20261103")
    for index, item in enumerate(report["rounds"]):
        start = now - timedelta(seconds=30 - index * 10)
        item.update(
            started_at=start.isoformat(),
            completed_at=(start + timedelta(seconds=2)).isoformat(),
        )
        for query in item["queries"].values():
            query.update(
                started_at=start.isoformat(),
                completed_at=(start + timedelta(seconds=1)).isoformat(),
            )
        item["queries"]["funds"]["rows"][0]["TradingDay"] = "20261103"
    from guiyi_quant.simnow_execution.inventory import native_hash

    report["round_hashes"] = [
        native_hash(
            {
                key: query["rows"]
                for key, query in report["rounds"][0]["queries"].items()
            }
        )
    ] * 2
    evidence = Evidence(folder / "native-evidence.sqlite", wire.ACCOUNT)
    evidence.append(read_snapshot(report))
    evidence.close()
    control = dict(
        schema="simnow_continuous_v2",
        mode="trade",
        status="RECOVERY_BLOCKED",
        run_id=RUN,
        account_recovery_hold=True,
        auto_order=False,
        opening_enabled=False,
        account_takeover_pending=True,
        trading_day="20261103",
        at=(now - timedelta(seconds=1)).isoformat(),
    )
    write(folder / "continuous.json", control)
    write(
        root / "monitor.json",
        dict(run_id=RUN, account_id=wire.ACCOUNT, status="STARTING"),
    )
    failure = folder / ("failure-" + RUN + "-42.json")
    write(
        failure,
        dict(
            schema="simnow_continuous_failure_v1",
            code="CONTINUOUS_RECOVERY_REQUIRED",
            at=failure_at.isoformat(),
            diagnostic=dict(
                stage="ACCOUNT_SNAPSHOT",
                recovery_stage="READY",
                recovery_error_code="RECOVERY_ERROR_UNCLASSIFIED",
                dispatch=None,
            ),
        ),
    )
    old_config = tmp_path / "old.private.json"
    old_code = tmp_path / "old-v69"
    (old_code / "scripts/broker").mkdir(parents=True)
    (old_code / "scripts/broker/simnow_supervisor.py").write_text("fixture source\n")
    sdk = tmp_path / "sdk-python"
    sdk.write_text("fixture executable\n")
    sdk.chmod(0o700)
    profile = dict(
        profile_id="original_anchor_v1",
        account_id=wire.ACCOUNT,
        initial_readback_sha256=ledger_digest(state.initial_readback),
    )
    write(
        old_config,
        dict(
            schema=2,
            mode="trade",
            enabled=True,
            account_takeover_pending=True,
            account_recovery_hold=True,
            account_id=wire.ACCOUNT,
            state_root=str(root),
            project_root=str(old_code),
            account_profile=profile,
            sdk_python=str(sdk),
        ),
    )
    b = m.MacBackend.__new__(m.MacBackend)
    b.ordinary = b.enable_auto_order = b.recover_held_readonly_source = (
        b._old_recovery_hold
    ) = True
    b.folder, b.old_config = folder, old_config
    b.settings = NS(
        schema=2,
        mode="trade",
        enabled=True,
        account_takeover_pending=True,
        account_recovery_hold=False,
        account_id=wire.ACCOUNT,
        state_root=root,
        account_profile=dict(
            profile_id="original_anchor_v1",
            account_id=wire.ACCOUNT,
            initial_readback_sha256=ledger_digest(state.initial_readback),
        ),
    )
    b._profile = lambda: b.settings.account_profile
    window = dict(
        policy=m.ORDINARY_POLICY,
        trading_day="20261104",
        authoritative=True,
        product_count=60,
        current_session_absent=True,
        window_open=True,
        next_session_gap_seconds=3600,
        session_facts_sha256="f" * 64,
        sessions=[
            dict(
                start=(now + timedelta(hours=1)).isoformat(),
                end=(now + timedelta(hours=2)).isoformat(),
            )
        ],
    )
    b._window = lambda: window
    b._pid = lambda: 29975
    b.run = lambda args: NS(returncode=0, stdout="Tue Nov 3 14:00:00 2026\n", stderr="")
    local_account = b._account()
    preimage = dict(
        old_release=dict(tag="v1.16.69", commit=SOURCE, root=str(old_code)),
        old_config=b.identity(old_config),
        old_runner=b.identity(
            old_code / "scripts/broker/simnow_supervisor.py", interpreter=True
        ),
        old_sdk=b.identity(sdk, interpreter=True),
        account=local_account,
        host_pid=29975,
        host_run_id=RUN,
    )
    return NS(
        b=b,
        control=control,
        preimage=preimage,
        account=local_account,
        window=window,
        failure=failure,
        folder=folder,
        root=root,
    )


def proof(f, *, stopped_snapshot=None):
    return f.b._held_readonly_source_proof(
        f.control, f.preimage, f.account, f.window, stopped_snapshot=stopped_snapshot
    )


def test_explicit_exact_held_failure_can_build_only_next_day_proof(held_failure):
    f = held_failure
    assert f.b._source_hold(f.control) is True
    value = proof(f)
    assert value["policy"] == "simnow_held_readonly_handoff_v1"
    assert (
        value["failure"]["sha256"] == hashlib.sha256(f.failure.read_bytes()).hexdigest()
    )
    assert value["source_process"]["pid"] == 29975
    assert value["source_process"]["run_id"] == RUN
    assert value["target_day"] == "20261104"
    assert value["cleanup_returned"] is True


def test_default_failure_rejection_is_unchanged(held_failure):
    f = held_failure
    f.b.recover_held_readonly_source = False
    with pytest.raises(m.SwitchError, match="HOST_UNPROVEN"):
        f.b._source_hold(f.control)


@pytest.mark.parametrize(
    "change",
    [
        "source_code",
        "pid",
        "hold",
        "failure_stage",
        "failure_code",
        "dispatch",
        "second_failure",
        "stale",
        "before_failure",
        "same_day",
        "target_block",
        "actions",
        "fault",
    ],
)
def test_other_failure_or_preimage_never_gets_the_exception(held_failure, change):
    f = held_failure
    if change == "source_code":
        f.preimage["old_release"]["commit"] = "d" * 40
    if change == "pid":
        f.b._pid = lambda: 29976
    if change == "hold":
        f.control["account_recovery_hold"] = False
    if change in {"failure_stage", "failure_code", "dispatch"}:
        value = json.loads(f.failure.read_text())
        if change == "failure_stage":
            value["diagnostic"]["stage"] = "SETTLEMENT_CONFIRMATION"
        if change == "failure_code":
            value["diagnostic"]["recovery_error_code"] = "NATIVE_TRANSPORT_FAILED"
        if change == "dispatch":
            value["diagnostic"]["dispatch"] = {"stage": "DISPATCH_START"}
        write(f.failure, value)
    if change == "second_failure":
        write(f.folder / ("failure-" + RUN + "-43.json"), {})
    if change == "stale":
        f.control["at"] = (datetime.now(UTC) - timedelta(seconds=10)).isoformat()
    if change == "before_failure":
        f.control["at"] = (datetime.now(UTC) - timedelta(seconds=10)).isoformat()
    if change == "same_day":
        f.window["trading_day"] = f.account["budget_day"] = "20261103"
    if change == "target_block":
        f.account["day_blocked"] = True
    if change == "actions":
        with sqlite3.connect(f.folder / "dispatch.sqlite") as conn:
            conn.execute("INSERT INTO results VALUES (1,'UNKNOWN')")
    if change == "fault":
        journal = Journal(f.folder / "dispatch.sqlite", wire.ACCOUNT)
        journal.event("fault", {"kind": "fault"}, datetime.now(UTC))
        journal.close()
    with pytest.raises(m.SwitchError):
        proof(f)


def test_failure_fd_replacement_during_read_is_rejected(held_failure, monkeypatch):
    f = held_failure
    original = m.os.read
    replaced = []

    def read(fd, count):
        raw = original(fd, count)
        if not replaced:
            replaced.append(True)
            alternate = f.failure.with_name("replacement.private.json")
            alternate.write_bytes(f.failure.read_bytes())
            alternate.chmod(0o600)
            alternate.replace(f.failure)
        return raw

    monkeypatch.setattr(m.os, "read", read)
    with pytest.raises(m.SwitchError, match="HOST_UNPROVEN"):
        f.b._held_readonly_failure(f.control)


def test_stopped_proof_uses_real_dual_locks_and_never_requires_live_freshness(
    held_failure, monkeypatch
):
    f = held_failure
    live = proof(f)
    locks = [f.root / "global.lock", f.folder / "host.lock"]
    for path in locks:
        path.touch(mode=0o600)
    f.b.locks = locks
    f.preimage["locks"] = [
        dict(path=str(p), device=p.stat().st_dev, inode=p.stat().st_ino) for p in locks
    ]
    f.preimage["held_readonly_handoff"] = live
    snapshot = dict(
        preimage=f.preimage,
        host=dict(pid=29975, run_id=RUN, mode="trade", account_recovery_hold=True),
    )
    f.control.update(status="STOPPED", at=datetime.now(UTC).isoformat())
    write(f.folder / "continuous.json", f.control)

    def gone(pid, signal):
        assert signal == 0
        raise ProcessLookupError()

    monkeypatch.setattr(m.os, "kill", gone)
    later = datetime.now(UTC) + timedelta(seconds=30)

    class Later(datetime):
        @classmethod
        def now(cls, tz=None):
            return later

    monkeypatch.setattr(m, "datetime", Later)
    with pytest.raises(m.SwitchError, match="STOP_UNPROVEN"):
        proof(f, stopped_snapshot=snapshot)
    import fcntl

    held = os.open(locks[0], os.O_RDONLY)
    try:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(m.SwitchError, match="WRITER_NOT_IDLE"):
            with f.b.offline_guard(snapshot):
                pass
    finally:
        os.close(held)
    with f.b.offline_guard(snapshot):
        assert proof(f, stopped_snapshot=snapshot) == live
    assert f.b._offline_held is False


def test_proof_drift_before_sigterm_has_no_side_effect(held_failure, monkeypatch):
    f = held_failure
    f.b._stop_held_readonly_handoff = proof(f)
    f.b._prove = lambda *_: None
    f.b._stop_signals = f.b.identity(f.folder / "signals.sqlite")
    f.b._preimage = lambda: dict(f.preimage)
    value = json.loads(f.failure.read_text())
    value["extra_preserved_fact"] = True
    write(f.failure, value)
    signals = []
    monkeypatch.setattr(m.os, "kill", lambda *args: signals.append(args))
    with pytest.raises(m.SwitchError, match="PREIMAGE_CHANGED"):
        f.b.stop(29975, expires_at=m.time.time() + 60)
    assert signals == []


def test_plan_and_apply_each_require_both_explicit_flags(held_failure, tmp_path):
    from test_trade_switch import Backend
    from test_owner_auto_enable import enabled_snapshot

    f = held_failure
    source_proof = proof(f)
    value = enabled_snapshot()
    value["account"].update(
        ledger_hash=f.account["ledger_hash"],
        attempts_hash=f.account["attempts_hash"],
        blocks_hash=f.account["blocks_hash"],
        budget_day="20261104",
    )
    value["host"]["pid"], value["host"]["run_id"] = 29975, RUN
    value["window"].update(
        trading_day="20261104",
        sessions=f.window["sessions"],
        session_facts_sha256=f.window["session_facts_sha256"],
    )
    value["ordinary_permit"]["window"]["trading_day"] = "20261104"
    value["preimage"]["held_readonly_handoff"] = source_proof
    directory = tmp_path / "coordinator"
    directory.mkdir(mode=0o700)
    value["ordinary_permit"]["state_dir"] = str(directory)
    backend = Backend()
    backend.value = value
    coordinator = m.Coordinator(backend, directory, clock=lambda: 1000)
    for enable, recover in ((False, False), (True, False), (False, True)):
        backend.enable_auto_order, backend.recover_held_readonly_source = (
            enable,
            recover,
        )
        with pytest.raises(m.SwitchError, match="PLAN_INVALID"):
            coordinator.plan()
    backend.enable_auto_order = backend.recover_held_readonly_source = True
    plan = coordinator.plan()
    backend.recover_held_readonly_source = False
    with pytest.raises(m.SwitchError, match="PLAN_INVALID"):
        coordinator.apply(plan)
    assert backend.calls == [] and not coordinator.intent.exists()


@pytest.mark.parametrize("cleanup_fails", [False, True])
@pytest.mark.parametrize("next_day_waiting", [False, True])
def test_real_supervisor_exposes_post_cleanup_blocked_or_waiting_only_after_normal_return(
    tmp_path, monkeypatch, cleanup_fails, next_day_waiting
):
    from datetime import date
    from test_trade_end_to_end import seeded_account, Driver
    from guiyi_quant.simnow_execution import supervisor

    settings, folder, clock, market = seeded_account(tmp_path)
    settings.account_recovery_hold = settings.account_takeover_pending = True
    snapshots = []
    published = []
    original = supervisor.publish_status

    def publish(folder, value):
        published.append(value)
        original(folder, value)

    monkeypatch.setattr(supervisor, "publish_status", publish)

    class FailedReadback(Driver):
        def snapshot(self):
            snapshots.append(1)
            if len(snapshots) == 4:
                raise RuntimeError("fixture read-only failure")
            return super().snapshot()

        def failure_diagnostics(self):
            return {"stage": "ACCOUNT_SNAPSHOT"}

        def close(self):
            super().close()
            if cleanup_fails:
                raise RuntimeError("fixture cleanup unknown")

    def sleep(seconds):
        if (
            any(r["status"] == "CONTINUOUS_RECOVERY_REQUIRED" for r in published)
            and next_day_waiting
        ):
            market.plan = lambda now: NS(
                trading_day=date(2026, 10, 28), active=False, connect_allowed=False
            )
        clock.sleep(seconds)

    host = supervisor.Supervisor(
        settings,
        ("JM", "RB"),
        market,
        lambda s, f: FailedReadback(s, f, clock),
        clock=clock.now,
        sleep=sleep,
    )
    if cleanup_fails:
        with pytest.raises(ValueError, match="CONTINUOUS_CLEANUP_UNCERTAIN"):
            host.run(max_cycles=3)
    else:
        assert host.run(max_cycles=3) == "STOPPED"
    failures = [
        p for p in folder.iterdir() if p.name.startswith("failure-" + host.run_id + "-")
    ]
    assert len(failures) == 1
    failure = json.loads(failures[0].read_bytes())
    assert failure["diagnostic"]["stage"] == "ACCOUNT_SNAPSHOT"
    assert failure["diagnostic"]["recovery_stage"] == "READY"
    assert failure["diagnostic"]["recovery_error_code"] == "RECOVERY_ERROR_UNCLASSIFIED"
    assert failure["diagnostic"]["dispatch"] is None
    status = "WAITING_SESSION" if next_day_waiting else "RECOVERY_BLOCKED"
    later = [r for r in published if r["status"] == status]
    assert bool(later) is not cleanup_fails
    if later:
        assert later[0]["run_id"] == host.run_id
        assert later[0]["at"] > failure["at"]
        assert later[0]["account_takeover_pending"] is True
        assert later[0]["account_recovery_hold"] is True
        assert later[0]["auto_order"] is later[0]["opening_enabled"] is False


def test_slow_process_proof_cannot_reuse_entry_freshness(held_failure, monkeypatch):
    f = held_failure
    clock = NS(at=datetime.now(UTC))

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock.at

    monkeypatch.setattr(m, "datetime", Clock)
    run = f.b.run

    def slow(args):
        result = run(args)
        clock.at += timedelta(seconds=9)
        return result

    f.b.run = slow
    with pytest.raises(m.SwitchError, match="HOST_UNPROVEN"):
        proof(f)


@pytest.mark.parametrize("refresh", ["stale", "fresh", "drift"])
@pytest.mark.parametrize("stage", ["state", "profile"])
def test_slow_state_requires_real_fresh_control_read_with_same_identity(
    held_failure, monkeypatch, refresh, stage
):
    from guiyi_quant.simnow_execution import account_binding

    f = held_failure
    clock = NS(at=datetime.now(UTC), checked=False)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock.at

    monkeypatch.setattr(m, "datetime", Clock)
    existing = account_binding.existing_account

    def slow_state(*args):
        value = existing(*args)
        clock.at += timedelta(seconds=10)
        clock.checked = True
        return value

    if stage == "state":
        monkeypatch.setattr(account_binding, "existing_account", slow_state)
    else:
        profile = f.b._profile

        def slow_profile():
            value = profile()
            clock.at += timedelta(seconds=10)
            clock.checked = True
            return value

        f.b._profile = slow_profile
    run = f.b.run

    def process(args):
        if clock.checked and refresh != "stale":
            current = dict(f.control, at=clock.at.isoformat())
            if refresh == "drift":
                current["run_id"] = "b" * 32
            write(f.folder / "continuous.json", current)
        return run(args)

    f.b.run = process
    if refresh == "fresh":
        value = proof(f)
        assert value["source_process"]["run_id"] == RUN
        assert (
            value["failure"]["sha256"]
            == hashlib.sha256(f.failure.read_bytes()).hexdigest()
        )
    else:
        with pytest.raises(m.SwitchError, match="HOST_UNPROVEN"):
            proof(f)


@pytest.mark.parametrize("field", ["CurrMargin", "FrozenMargin", "FrozenCommission"])
def test_empty_native_rows_cannot_hide_frozen_financial_obligations(
    held_failure, field
):
    from dataclasses import replace
    from guiyi_quant.simnow_execution.inventory import native_hash

    f = held_failure
    evidence = Evidence(f.folder / "native-evidence.sqlite", wire.ACCOUNT)
    previous = evidence.latest()
    data = previous.data
    data["funds"][0][field] = "1"
    stamp = previous.at + timedelta(seconds=2)
    snapshot = replace(
        previous,
        started_at=previous.at + timedelta(seconds=1),
        at=stamp,
        payload_json=json.dumps(data),
        source_id="ctp-inventory:"
        + previous.trading_day
        + ":"
        + native_hash(
            (previous.account_id, previous.trading_day, data, stamp.isoformat())
        ),
    )
    evidence.append(snapshot)
    evidence.close()
    f.account = f.b._account()
    f.preimage["account"] = f.account
    with pytest.raises(m.SwitchError, match="PENDING_OBLIGATIONS"):
        proof(f)
