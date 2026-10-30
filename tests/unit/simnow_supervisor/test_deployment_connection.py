"""One deployment connection: real private files/journals, no native transport."""

from datetime import datetime, UTC, timedelta
import json
from pathlib import Path
import sqlite3
import subprocess

import pytest

from guiyi_quant.simnow_execution import deployment_connection as permit
from guiyi_quant.simnow_execution.settings import load_settings
from guiyi_quant.simnow_execution.inbox import SignalInbox
from test_settings import existing_v2, write


@pytest.fixture
def granted(tmp_path):
    yield from grant_state(tmp_path)


def grant_state(tmp_path, *, pending=False, issue=True):
    config, value, folder = existing_v2(tmp_path)
    root = tmp_path / "release-v1.16.37"
    Path(value["project_root"]).rename(root)
    value.update(project_root=str(root), enabled=True)
    for args in (
        ["init", "-q"],
        ["add", "."],
        [
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        [
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "tag",
            "-a",
            "v1.16.37",
            "-m",
            "fixture",
        ],
    ):
        subprocess.run(
            ["/usr/bin/git", "-C", str(root), *args], check=True, capture_output=True
        )
    out = tmp_path / "one-intent"
    out.mkdir(mode=0o700)
    path = out / "deployment-connection-permit.private.json"
    value["deployment_connection_permit"] = str(path)
    if pending:
        value["account_takeover_pending"] = True
    write(config, value)
    settings = load_settings(config)
    from guiyi_quant.simnow_execution.supervisor import global_account_lock_directory

    private_global = global_account_lock_directory()
    assert private_global.is_relative_to(tmp_path), (
        "fixture must never touch production AppSupport"
    )
    private_global.mkdir(mode=0o700, parents=True, exist_ok=True)
    db = sqlite3.connect(folder / "signals.sqlite")
    db.execute("INSERT INTO attempts VALUES (?,?)", ("20261030", 3))
    if pending:
        db.execute(
            "INSERT INTO blocks VALUES (?,?)",
            ("20261030", "CONNECTION_BUDGET_EXHAUSTED"),
        )
    db.commit()
    db.close()
    now = datetime(2026, 10, 30, 3, 35, tzinfo=UTC)
    pm = datetime(2026, 10, 30, 5, 30, tzinfo=UTC)
    binding = permit.binding(settings, config, pm, now)
    intent = out / "switch-intent.private.json"
    record = dict(
        schema="simnow_trade_switch_plan_v4",
        stage="INSTALLED",
        plan_hash="a" * 64,
        window_policy="simnow_midday_deployment_window_v1",
        snapshot=dict(
            connection_permit=binding,
            connection_anchor=permit.account_anchor(settings) if pending else None,
        ),
    )
    if issue:
        intent.write_text(json.dumps(record))
        intent.chmod(0o600)
        grant_sha = permit.issue(
            settings, binding, "a" * 64, intent, now, clock=lambda: now
        )
        record["connection_grant_sha256"] = grant_sha
        record["stage"] = "START_REQUESTED"
        intent.write_text(json.dumps(record))
    inbox = SignalInbox(folder / "signals.sqlite", settings.account_id, ("RB",))
    yield settings, inbox, now, pm, intent, record, binding
    inbox.close()


@pytest.fixture(params=[False, True], ids=["ordinary-grant", "pending-budget-block"])
def unissued_state(tmp_path, request):
    yield from grant_state(tmp_path, pending=request.param, issue=False)


def test_settings_optional_permit_and_single_run_attempt(granted):
    settings, inbox, now, pm, intent, record, binding = granted
    assert settings.deployment_connection_permit.is_absolute()
    permit.activate(settings, inbox, "1" * 32, now, clock=lambda: now)
    record["stage"] = "COMPLETE"
    intent.write_text(json.dumps(record))
    permit.consume(
        settings,
        inbox,
        "1" * 32,
        "20261030",
        pm - timedelta(minutes=2),
        clock=lambda: pm - timedelta(minutes=2),
    )
    assert inbox.conn.execute(
        "SELECT count FROM attempts WHERE day=?", ("20261030",)
    ).fetchone() == (3,)
    with pytest.raises(ValueError, match="DEPLOYMENT_CONNECTION_EXHAUSTED"):
        permit.consume(settings, inbox, "1" * 32, "20261030", pm, clock=lambda: pm)
    with pytest.raises(ValueError, match="DEPLOYMENT_CONNECTION_EXHAUSTED"):
        permit.activate(settings, inbox, "2" * 32, now, clock=lambda: now)


def test_grant_cannot_activate_before_start_requested(granted):
    settings, inbox, now, pm, intent, record, binding = granted
    record["stage"] = "INSTALLED"
    intent.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="DEPLOYMENT_CONNECTION_INVALID"):
        permit.activate(settings, inbox, "1" * 32, now, clock=lambda: now)


@pytest.mark.parametrize(
    "stage", ["INTENT", "INSTALLED", "RESTORE_REQUESTED", "RECOVERED", "UNKNOWN"]
)
def test_unknown_or_prestart_intent_never_activates(granted, stage):
    s, i, n, pm, path, r, b = granted
    r["stage"] = stage
    path.write_text(json.dumps(r))
    with pytest.raises(ValueError, match="DEPLOYMENT_CONNECTION_INVALID"):
        permit.activate(s, i, "1" * 32, n, clock=lambda: n)
    assert not Path(str(s.deployment_connection_permit) + ".run-claim").exists()


@pytest.mark.parametrize(
    "case",
    [
        "config",
        "account",
        "day",
        "release",
        "sdk",
        "grant_hash",
        "expired",
        "early",
        "block",
        "base_remaining",
    ],
)
def test_exact_permit_drift_rejected_before_factory(granted, case):
    from dataclasses import replace

    s, i, n, pm, path, r, b = granted
    when = n
    if case == "config":
        s.source_config_path.write_text(s.source_config_path.read_text() + " ")
    if case == "account":
        s = replace(s, account_id="b" * 64)
    if case == "day":
        when = n + timedelta(days=1)
    if case == "release":
        (s.project_root / "dirty").write_text("fixture")
    if case == "sdk":
        s.sdk_python.resolve().write_text("changed")
    if case == "grant_hash":
        s.deployment_connection_permit.write_text(
            s.deployment_connection_permit.read_text() + " "
        )
    if case == "expired":
        when = pm + timedelta(seconds=120)
    if case == "early":
        when = n - timedelta(seconds=1)
    if case == "block":
        i.block("20261030", "RETAINED")
    if case == "base_remaining":
        i.conn.execute("UPDATE attempts SET count=2 WHERE day=?", ("20261030",))
    with pytest.raises(ValueError, match="DEPLOYMENT_CONNECTION_INVALID"):
        permit.activate(s, i, "1" * 32, when, clock=lambda: when)
    assert not Path(str(s.deployment_connection_permit) + ".run-claim").exists()


def test_consumption_is_not_allowed_during_midday_wait(granted):
    s, i, n, pm, path, r, b = granted
    permit.activate(s, i, "1" * 32, n, clock=lambda: n)
    with pytest.raises(ValueError, match="DEPLOYMENT_CONNECTION_INVALID"):
        permit.consume(s, i, "1" * 32, "20261030", n, clock=lambda: n)
    assert not Path(str(s.deployment_connection_permit) + ".attempt-claim").exists()


@pytest.mark.parametrize("operation", ["activate", "consume", "issue"])
def test_slow_binding_cannot_cross_deadline(granted, monkeypatch, operation):
    s, i, n, pm, path, r, b = granted
    if operation == "consume":
        permit.activate(s, i, "1" * 32, n, clock=lambda: n)
    clock = [pm + timedelta(seconds=119)]
    if operation == "issue":
        s.deployment_connection_permit.unlink()
        r["stage"] = "INSTALLED"
        path.write_text(json.dumps(r))
        clock[0] = pm - timedelta(seconds=661)
    original = permit.binding

    def slow(*args, **kwargs):
        result = original(*args, **kwargs)
        clock[0] += timedelta(seconds=2)
        return result

    monkeypatch.setattr(permit, "binding", slow)
    with pytest.raises(ValueError, match="DEPLOYMENT_CONNECTION_INVALID"):
        if operation == "activate":
            permit.activate(s, i, "1" * 32, clock[0], clock=lambda: clock[0])
        elif operation == "consume":
            permit.consume(s, i, "1" * 32, "20261030", clock[0], clock=lambda: clock[0])
        else:
            permit.issue(s, b, "a" * 64, path, clock[0], clock=lambda: clock[0])
    suffix = ".run-claim" if operation == "activate" else ".attempt-claim"
    assert not (
        s.deployment_connection_permit
        if operation == "issue"
        else Path(str(s.deployment_connection_permit) + suffix)
    ).exists()


def test_claim_fsync_failure_is_spent_and_no_factory(granted, monkeypatch):
    s, i, n, pm, path, r, b = granted
    permit.activate(s, i, "1" * 32, n, clock=lambda: n)
    original = permit.os.fsync

    def fail(fd):
        raise OSError("private fixture IO failure")

    monkeypatch.setattr(permit.os, "fsync", fail)
    with pytest.raises(ValueError, match="DEPLOYMENT_CONNECTION_INVALID"):
        permit.consume(s, i, "1" * 32, "20261030", pm, clock=lambda: pm)
    monkeypatch.setattr(permit.os, "fsync", original)
    with pytest.raises(ValueError, match="DEPLOYMENT_CONNECTION_EXHAUSTED"):
        permit.consume(s, i, "1" * 32, "20261030", pm, clock=lambda: pm)
    assert i.conn.execute(
        "SELECT count FROM attempts WHERE day=?", ("20261030",)
    ).fetchone() == (3,)


def test_historical_v38_settings_midday_run_and_pm_once(unissued_state, monkeypatch):
    import threading
    from types import SimpleNamespace as NS
    from datetime import date
    from test_trade_switch import Backend, m
    from guiyi_quant.simnow_execution.supervisor import Supervisor

    s, inbox, now, pm, intent, record, binding = unissued_state
    clock = [now]
    waiting = threading.Event()
    advance = threading.Event()
    errors = []
    factory_calls = []

    class Market:
        issues = {}

        def plan(self, at):
            return NS(
                trading_day=date(2026, 10, 30),
                active=at >= pm,
                connect_allowed=at >= pm - timedelta(seconds=120),
            )

        def activate(self, at):
            pass

        def close(self):
            pass

    class Driver:
        transport_failed = True

        def connect(self):
            raise ValueError("NATIVE_GATEWAY_FAILED")

        def close(self):
            pass

    def factory(*args):
        assert Path(str(s.deployment_connection_permit) + ".attempt-claim").exists()
        assert json.loads(intent.read_bytes())["stage"] == "COMPLETE"
        factory_calls.append(True)
        return Driver()

    def sleep(seconds):
        waiting.set()
        if not advance.wait(10):
            raise RuntimeError("fixture synchronization timeout")
        clock[0] = pm - timedelta(seconds=120)

    host = Supervisor(
        load_settings(s.source_config_path),
        ("RB",),
        Market(),
        factory,
        clock=lambda: clock[0],
        sleep=sleep,
    )

    before = (
        inbox.conn.execute("SELECT * FROM attempts").fetchall(),
        inbox.conn.execute("SELECT * FROM blocks").fetchall(),
    )
    # v5 cannot mint an old extra permit, even through a generic Backend.
    backend = Backend()
    backend.value["connection_permit"] = binding
    backend.value["account"].update(
        today_attempts=3, remaining_attempts=0, account_id=s.account_id
    )
    backend.value["window"] = dict(
        policy=m.MIDDAY_POLICY,
        trading_day="20261030",
        authoritative=True,
        product_count=60,
        current_session_absent=True,
        next_session_gap_seconds=6900,
        window_open=True,
        morning_completed=True,
        next_is_afternoon=True,
    )
    if s.account_takeover_pending:
        backend.value["account"].update(
            account_takeover_pending=True,
            native_account_verified=False,
            local_obligations_clear=True,
            unknown_positions=None,
            unknown_orders=None,
            unknown_trades=None,
            day_blocked=True,
            day_block_code="CONNECTION_BUDGET_EXHAUSTED",
        )
    coordinator = m.Coordinator(backend, intent.parent, clock=lambda: now.timestamp())
    with pytest.raises(m.SwitchError):
        coordinator.plan()
    assert backend.calls == [] and not intent.exists()
    assert not s.deployment_connection_permit.exists()
    assert not permit.global_marker(s).exists()
    assert before == (
        inbox.conn.execute("SELECT * FROM attempts").fetchall(),
        inbox.conn.execute("SELECT * FROM blocks").fetchall(),
    )

    # Preserve the historical v38 consumer contract independently of the retired
    # issuing Coordinator. The exact v4 persisted intent is its input evidence.
    intent.write_text(json.dumps(record))
    intent.chmod(0o600)
    record["connection_grant_sha256"] = permit.issue(
        s, binding, record["plan_hash"], intent, now, clock=lambda: now
    )
    record["stage"] = "START_REQUESTED"
    intent.write_text(json.dumps(record))

    def run():
        try:
            host.run(max_cycles=3)
        except Exception as exc:
            errors.append(type(exc).__name__)

    thread = threading.Thread(target=run)
    thread.start()
    try:
        assert waiting.wait(10)
        assert not factory_calls
        assert Path(str(s.deployment_connection_permit) + ".run-claim").exists()
        assert not Path(str(s.deployment_connection_permit) + ".attempt-claim").exists()
        record["stage"] = "COMPLETE"
        intent.write_text(json.dumps(record))
    finally:
        advance.set()
        thread.join(10)
    assert not errors and factory_calls == [True]
    if s.account_takeover_pending:
        assert host.account_takeover_pending is True
    assert before == (
        inbox.conn.execute("SELECT * FROM attempts").fetchall(),
        inbox.conn.execute("SELECT * FROM blocks").fetchall(),
    )
    for _ in range(2):
        restart = Supervisor(
            s,
            ("RB",),
            Market(),
            lambda *args: pytest.fail("restart factory"),
            clock=lambda: clock[0],
        )
        with pytest.raises(ValueError, match="DEPLOYMENT_CONNECTION_EXHAUSTED"):
            restart.run(max_cycles=1)


def test_factory_failure_spends_grant_without_resetting_budget(granted):
    from types import SimpleNamespace as NS
    from guiyi_quant.simnow_execution.supervisor import Supervisor

    s, i, n, pm, path, r, b = granted
    permit.activate(s, i, "1" * 32, n, clock=lambda: n)
    calls = []

    def factory(*args):
        assert Path(str(s.deployment_connection_permit) + ".attempt-claim").exists()
        calls.append(True)
        raise RuntimeError("fixture unknown factory result")

    host = Supervisor(s, ("RB",), NS(issues={}), factory, clock=lambda: pm)
    host.inbox = i
    host.folder = s.state_root / s.account_id
    host.run_id = "1" * 32
    host.status = lambda *args, **kwargs: None
    with pytest.raises(RuntimeError):
        host.connect("20261030")
    with pytest.raises(ValueError, match="DEPLOYMENT_CONNECTION_EXHAUSTED"):
        host.connect("20261030")
    assert calls == [True] and i.conn.execute(
        "SELECT count FROM attempts WHERE day=?", ("20261030",)
    ).fetchone() == (3,)
    assert i.conn.execute("SELECT * FROM blocks").fetchall() == []


def test_next_day_uses_ordinary_budget_and_no_permit_is_still_capped(granted):
    from dataclasses import replace
    from types import SimpleNamespace as NS
    from guiyi_quant.simnow_execution.supervisor import Supervisor

    s, i, n, pm, path, r, b = granted
    calls = []

    def factory(*args):
        calls.append(True)
        raise RuntimeError("fixture stop")

    host = Supervisor(
        s, ("RB",), NS(issues={}), factory, clock=lambda: pm + timedelta(days=1)
    )
    host.inbox = i
    host.folder = s.state_root / s.account_id
    host.status = lambda *args, **kwargs: None
    for _ in range(3):
        with pytest.raises(RuntimeError):
            host.connect("20261031")
    with pytest.raises(ValueError, match="CONNECTION_BUDGET_EXHAUSTED"):
        host.connect("20261031")
    assert i.conn.execute(
        "SELECT count FROM attempts WHERE day=?", ("20261031",)
    ).fetchone() == (3,)
    host.settings = replace(s, deployment_connection_permit=None)
    with pytest.raises(ValueError, match="CONNECTION_BUDGET_EXHAUSTED"):
        host.connect("20261030")
    assert calls == [True, True, True]


@pytest.mark.parametrize("mode", ["observe", "manage"])
def test_settings_refuses_nontrade_permit(granted, mode):
    s, i, n, pm, path, r, b = granted
    value = json.loads(s.source_config_path.read_bytes())
    value["mode"] = mode
    write(s.source_config_path, value)
    with pytest.raises(ValueError, match="DEPLOYMENT_CONNECTION_INVALID"):
        load_settings(s.source_config_path)


def test_duplicate_issue_never_replaces_grant(granted):
    s, i, n, pm, path, r, b = granted
    r["stage"] = "INSTALLED"
    path.write_text(json.dumps(r))
    raw = s.deployment_connection_permit.read_bytes()
    with pytest.raises(ValueError, match="DEPLOYMENT_CONNECTION_EXHAUSTED"):
        permit.issue(s, b, "a" * 64, path, n, clock=lambda: n)
    assert s.deployment_connection_permit.read_bytes() == raw


@pytest.mark.parametrize("step", ["activation", "attempt"])
def test_slow_claim_fsync_cannot_reach_native_after_deadline(
    granted, monkeypatch, step
):
    s, i, n, pm, path, r, b = granted
    clock = [pm + timedelta(seconds=119)]
    if step == "attempt":
        permit.activate(s, i, "1" * 32, n, clock=lambda: n)
    original = permit.os.fsync

    def slow(fd):
        original(fd)
        clock[0] += timedelta(seconds=2)

    monkeypatch.setattr(permit.os, "fsync", slow)
    with pytest.raises(ValueError, match="DEPLOYMENT_CONNECTION_INVALID"):
        if step == "activation":
            permit.activate(s, i, "1" * 32, clock[0], clock=lambda: clock[0])
        else:
            permit.consume(s, i, "1" * 32, "20261030", clock[0], clock=lambda: clock[0])
    suffix = ".run-claim" if step == "activation" else ".attempt-claim"
    assert Path(str(s.deployment_connection_permit) + suffix).exists()


def test_slow_factory_cannot_call_sdk_after_deadline(granted):
    from types import SimpleNamespace as NS
    from guiyi_quant.simnow_execution.supervisor import Supervisor

    s, i, n, pm, path, r, b = granted
    permit.activate(s, i, "1" * 32, n, clock=lambda: n)
    clock = [pm + timedelta(seconds=119)]

    class Driver:
        def connect(self):
            pytest.fail("expired grant reached SDK login")

    def factory(*args):
        clock[0] += timedelta(seconds=2)
        return Driver()

    host = Supervisor(s, ("RB",), NS(issues={}), factory, clock=lambda: clock[0])
    host.inbox = i
    host.folder = s.state_root / s.account_id
    host.run_id = "1" * 32
    host.status = lambda *args, **kwargs: None
    with pytest.raises(ValueError, match="DEPLOYMENT_CONNECTION_INVALID"):
        host.connect("20261030")
    assert Path(str(s.deployment_connection_permit) + ".attempt-claim").exists()


def test_new_block_after_activation_still_forbids_consume(granted):
    s, i, n, pm, path, r, b = granted
    permit.activate(s, i, "1" * 32, n, clock=lambda: n)
    i.block("20261030", "RETAINED_AFTER_START")
    with pytest.raises(ValueError, match="DEPLOYMENT_CONNECTION_INVALID"):
        permit.consume(s, i, "1" * 32, "20261030", pm, clock=lambda: pm)
    assert not Path(str(s.deployment_connection_permit) + ".attempt-claim").exists()
    assert i.conn.execute(
        "SELECT code FROM blocks WHERE day=?", ("20261030",)
    ).fetchone() == ("RETAINED_AFTER_START",)


def test_parent_directory_fsync_failure_is_fail_closed(granted, monkeypatch):
    import os
    import stat

    s, i, n, pm, path, r, b = granted
    permit.activate(s, i, "1" * 32, n, clock=lambda: n)
    original = permit.os.fsync

    def fail_directory(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("fixture directory durability failure")
        original(fd)

    monkeypatch.setattr(permit.os, "fsync", fail_directory)
    with pytest.raises(ValueError, match="DEPLOYMENT_CONNECTION_INVALID"):
        permit.consume(s, i, "1" * 32, "20261030", pm, clock=lambda: pm)
    assert Path(str(s.deployment_connection_permit) + ".attempt-claim").exists()
    monkeypatch.setattr(permit.os, "fsync", original)
    with pytest.raises(ValueError, match="DEPLOYMENT_CONNECTION_EXHAUSTED"):
        permit.consume(s, i, "1" * 32, "20261030", pm, clock=lambda: pm)


def test_permit_config_does_not_add_exception_to_initially_available_budget(granted):
    from types import SimpleNamespace as NS
    from guiyi_quant.simnow_execution.supervisor import Supervisor

    s, i, n, pm, path, r, b = granted
    i.conn.execute("UPDATE attempts SET count=2 WHERE day=?", ("20261030",))
    calls = []

    def factory(*args):
        calls.append(True)
        raise RuntimeError("fixture")

    host = Supervisor(s, ("RB",), NS(issues={}), factory, clock=lambda: pm)
    host.inbox = i
    host.folder = s.state_root / s.account_id
    host.status = lambda *args, **kwargs: None
    with pytest.raises(RuntimeError):
        host.connect("20261030")
    with pytest.raises(ValueError, match="DEPLOYMENT_CONNECTION_INVALID"):
        host.connect("20261030")
    assert calls == [True] and i.conn.execute(
        "SELECT count FROM attempts WHERE day=?", ("20261030",)
    ).fetchone() == (3,)
    assert not Path(str(s.deployment_connection_permit) + ".attempt-claim").exists()


def test_civil_oct30_night_startup_uses_authoritative_nov2_regular_budget(granted):
    from datetime import date
    from types import SimpleNamespace as NS
    from guiyi_quant.simnow_execution.supervisor import Supervisor

    s, i, n, pm, path, r, b = granted
    permit.activate(s, i, "1" * 32, n, clock=lambda: n)
    activation = Path(str(s.deployment_connection_permit) + ".run-claim").read_bytes()
    at = datetime(
        2026, 10, 30, 13, 0, tzinfo=UTC
    )  # 21:00 civil Oct30, next trading day Nov2.
    calls = []

    class Market:
        issues = {}

        def plan(self, now):
            return NS(trading_day=date(2026, 11, 2), active=True, connect_allowed=True)

        def activate(self, now):
            pass

        def close(self):
            pass

    class Driver:
        transport_failed = True

        def connect(self):
            raise ValueError("NATIVE_GATEWAY_FAILED")

        def close(self):
            pass

    def factory(*args):
        calls.append(True)
        return Driver()

    host = Supervisor(s, ("RB",), Market(), factory, clock=lambda: at)
    host.run(max_cycles=1)
    assert calls == [True]
    assert i.conn.execute(
        "SELECT count FROM attempts WHERE day=?", ("20261030",)
    ).fetchone() == (3,)
    assert i.conn.execute(
        "SELECT count FROM attempts WHERE day=?", ("20261102",)
    ).fetchone() == (1,)
    assert (
        Path(str(s.deployment_connection_permit) + ".run-claim").read_bytes()
        == activation
    )
    assert not Path(str(s.deployment_connection_permit) + ".attempt-claim").exists()


@pytest.mark.parametrize("failed_fsync", [1, 2, 3, 4])
def test_global_stamp_partial_failure_is_never_refunded(
    unissued_state, monkeypatch, failed_fsync
):
    s, inbox, now, pm, intent, record, binding = unissued_state
    intent.write_text(json.dumps(record))
    intent.chmod(0o600)
    count = [0]
    original = permit.os.fsync

    def failure(fd):
        count[0] += 1
        if count[0] == failed_fsync:
            raise OSError("fixture interrupted durability")
        original(fd)

    monkeypatch.setattr(permit.os, "fsync", failure)
    with pytest.raises(ValueError, match="DEPLOYMENT_CONNECTION_INVALID"):
        permit.issue(s, binding, "a" * 64, intent, now, clock=lambda: now)
    marker = permit.global_marker(s)
    assert marker.exists()
    before = marker.read_bytes()
    monkeypatch.setattr(permit.os, "fsync", original)
    with pytest.raises(ValueError, match="DEPLOYMENT_CONNECTION_EXHAUSTED"):
        permit.issue(s, binding, "a" * 64, intent, now, clock=lambda: now)
    assert marker.read_bytes() == before


def test_global_stamp_blocks_second_config_and_state_directory(granted, tmp_path):
    s, inbox, now, pm, intent, record, binding = granted
    marker = permit.global_marker(s)
    original = marker.read_bytes()
    other = tmp_path / "other-intent"
    other.mkdir(mode=0o700)
    cfg = json.loads(s.source_config_path.read_bytes())
    cfg["deployment_connection_permit"] = str(other / permit.NAME)
    config = tmp_path / "other-config.private.json"
    write(config, cfg)
    second = load_settings(config)
    frozen = permit.binding(second, config, pm, now)
    new_intent = other / "switch-intent.private.json"
    new_intent.write_text(
        json.dumps(
            dict(
                record,
                stage="INSTALLED",
                plan_hash="b" * 64,
                snapshot=dict(connection_permit=frozen),
            )
        )
    )
    new_intent.chmod(0o600)
    with pytest.raises(ValueError, match="DEPLOYMENT_CONNECTION_EXHAUSTED"):
        permit.issue(second, frozen, "b" * 64, new_intent, now, clock=lambda: now)
    assert (
        marker.read_bytes() == original
        and not second.deployment_connection_permit.exists()
    )


def test_missing_or_modified_global_stamp_forbids_activation(granted):
    s, inbox, now, pm, *_ = granted
    marker = permit.global_marker(s)
    original = marker.read_bytes()
    marker.write_bytes(original + b" ")
    with pytest.raises(ValueError, match="DEPLOYMENT_CONNECTION_INVALID"):
        permit.activate(s, inbox, "1" * 32, now, clock=lambda: now)
    marker.unlink()
    with pytest.raises(ValueError, match="DEPLOYMENT_CONNECTION_INVALID"):
        permit.activate(s, inbox, "1" * 32, now, clock=lambda: now)
