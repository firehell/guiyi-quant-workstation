import contextlib
import copy
import importlib.util
import json
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[3] / "scripts/ops/macos/simnow-trade-switch.py"
spec = importlib.util.spec_from_file_location("trade_switch_test", PATH)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class Clock:
    value = 1000

    def __call__(self):
        return self.value

    def sleep(self, seconds):
        self.value += seconds


class Backend:
    def __init__(self):
        self.calls = []
        self.stop_ok = True
        self.start_ok = True
        self.window = True
        self.value = dict(
            candidate=dict(
                tag="v1.16.35",
                commit="82a8031470009249acccb83b9911a374af70ca00",
                annotated_exact=True,
                clean=True,
                sdk_check=True,
                preflight_valid=True,
                identities={
                    k: "identity"
                    for k in (
                        "code",
                        "sdk",
                        "config",
                        "plist",
                        "old_config",
                        "old_plist",
                        "monitor",
                    )
                },
            ),
            account=dict(
                existing=True,
                same_account_anchor=True,
                scope_count=60,
                databases=[1, 2, 3, 4],
                scope_hash="s",
                budget_day="20261030",
                today_attempts=2,
                remaining_attempts=1,
                day_blocked=False,
                attempts_hash="a",
                blocks_hash="b",
                dispatch_hash="d",
                account_id="id",
                unknown_positions=False,
                unknown_orders=False,
                unknown_trades=False,
                reservations=False,
            ),
            host=dict(
                label=m.LABEL,
                mode="observe",
                unique=True,
                pid=100,
                run_id="old",
                dual_locks_held_by_pid=True,
                command_identity="c",
            ),
            window=dict(
                policy=m.POLICY,
                trading_day="20261030",
                authoritative=True,
                night_count=45,
                excluded_no_night_count=15,
                all_closed=True,
                current_session_absent=True,
                next_session_gap_seconds=10000,
            ),
            preimage="immutable",
        )

    def snapshot(self):
        return copy.deepcopy(self.value)

    def stop(self, pid):
        self.calls.append("stop")

    def stopped(self, s):
        return self.stop_ok

    @contextlib.contextmanager
    def offline_guard(self, s):
        self.calls.append("guard")
        yield
        self.calls.append("unguard")

    def offline_preflight(self, s):
        return dict(
            writer_idle=True, protected_state_unchanged=True, preimage=s["preimage"]
        )

    def window_open(self):
        return self.window

    def install(self, s):
        self.calls.append("install")
        return True

    def start(self, s):
        self.calls.append("start")
        return self.start_ok

    def readback(self, s):
        self.calls.append("readback")
        return dict(
            verified=True,
            mode="trade",
            pid=200,
            run_id="new",
            dual_locks_held_by_pid=True,
            config_bound=True,
            monitor_bound=True,
            host_status="WAITING_SESSION",
            opening_enabled=False,
        )


@pytest.fixture
def setup(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    monkeypatch.setenv("HOME", str(tmp_path))
    b, clock = Backend(), Clock()
    c = m.Coordinator(b, tmp_path, clock=clock, sleep=clock.sleep)
    return b, c, clock


def test_success_two_rounds_and_idempotence(setup):
    b, c, _ = setup
    plan = c.plan()
    assert b.calls == []
    assert c.apply(plan)["stage"] == "COMPLETE"
    assert b.calls == [
        "stop",
        "guard",
        "install",
        "unguard",
        "start",
        "readback",
        "readback",
    ]
    with pytest.raises(m.SwitchError, match="ATTEMPT_CONSUMED"):
        c.apply(plan)
    assert c.readback()["native_recovery_complete"] is False


@pytest.mark.parametrize(
    "field", ["unknown_positions", "unknown_orders", "unknown_trades", "reservations"]
)
def test_pending_obligation_blocks_before_stop(setup, field):
    b, c, _ = setup
    b.value["account"][field] = True
    with pytest.raises(m.SwitchError, match="PENDING_OBLIGATIONS"):
        c.plan()
    assert b.calls == []


def test_preimage_change(setup):
    b, c, _ = setup
    p = c.plan()
    b.value["preimage"] = "changed"
    with pytest.raises(m.SwitchError, match="PREIMAGE_CHANGED"):
        c.apply(p)
    assert not c.intent.exists()


def test_not_closed(setup):
    b, c, _ = setup
    b.value["window"]["all_closed"] = False
    with pytest.raises(m.SwitchError, match="WINDOW_UNPROVEN"):
        c.plan()


def test_expired(setup):
    b, c, clock = setup
    p = c.plan()
    clock.value += 61
    with pytest.raises(m.SwitchError, match="PLAN_EXPIRED"):
        c.apply(p)
    assert b.calls == []


def test_stop_timeout_preserves_phase(setup):
    b, c, _ = setup
    p = c.plan()
    b.stop_ok = False
    with pytest.raises(m.SwitchError, match="STOP_TIMEOUT"):
        c.apply(p)
    assert c.readback()["stage"] == "STOP_REQUESTED"
    assert b.calls == ["stop"]


def test_failed_start_recovery_is_read_only(setup):
    b, c, _ = setup
    p = c.plan()
    b.start_ok = False
    with pytest.raises(m.SwitchError, match="START_UNPROVEN"):
        c.apply(p)
    before = list(b.calls)
    assert c.readback()["recovery_required"]
    assert c.readback()["stage"] == "START_REQUESTED"
    assert b.calls == before
    with pytest.raises(m.SwitchError, match="ATTEMPT_CONSUMED"):
        c.apply(p)


def test_unknown_phase_blocks(setup):
    b, c, _ = setup
    m.write_private(c.intent, dict(stage="MYSTERY"), exclusive=True)
    with pytest.raises(m.SwitchError, match="UNKNOWN_STAGE"):
        c.apply(c.plan())
    assert b.calls == []


def test_concurrent_switch_lock(setup):
    b, c, _ = setup
    p = c.plan()
    with c._guard():
        with pytest.raises(m.SwitchError, match="SWITCH_BUSY"):
            c.apply(p)
    assert b.calls == []


def test_unknown_backend_result_is_sanitized_and_never_retried(setup):
    b, c, _ = setup

    def stop(pid):
        raise RuntimeError("SECRET-NATIVE-ERROR")

    b.stop = stop
    with pytest.raises(m.SwitchError, match="RESULT_UNKNOWN"):
        c.apply(c.plan())
    assert "SECRET" not in c.intent.read_text()
    assert c.readback()["stage"] == "STOP_REQUESTED"


def test_offline_writer_failure_prevents_install(setup):
    b, c, _ = setup
    b.offline_preflight = lambda s: dict(writer_idle=False)
    with pytest.raises(m.SwitchError, match="WRITER_NOT_IDLE"):
        c.apply(c.plan())
    assert "install" not in b.calls


@pytest.mark.parametrize(
    "change", ["tag", "sdk", "scope", "night_count", "label", "dual_lock"]
)
def test_identity_drift_is_rejected(setup, change):
    b, c, _ = setup
    if change == "tag":
        b.value["candidate"]["tag"] = "develop"
    if change == "sdk":
        b.value["candidate"]["sdk_check"] = False
    if change == "scope":
        b.value["account"]["scope_count"] = 59
    if change == "night_count":
        b.value["window"]["night_count"] = 60
    if change == "label":
        b.value["host"]["label"] = "other.service"
    if change == "dual_lock":
        b.value["host"]["dual_locks_held_by_pid"] = False
    with pytest.raises(m.SwitchError):
        c.plan()
    assert b.calls == []


def test_window_closes_after_stop_preserves_stopped_stage(setup):
    b, c, _ = setup
    p = c.plan()
    b.window = False
    with pytest.raises(m.SwitchError, match="WINDOW_UNPROVEN"):
        c.apply(p)
    assert c.readback()["stage"] == "STOPPED"
    assert "install" not in b.calls


def test_restart_between_proof_rounds_is_rejected(setup):
    b, c, _ = setup
    original = b.readback

    def unstable(s):
        p = original(s)
        if b.calls.count("readback") == 2:
            p["pid"] = 201
        return p

    b.readback = unstable
    with pytest.raises(m.SwitchError, match="READBACK_UNPROVEN"):
        c.apply(c.plan())
    assert c.readback()["stage"] == "VERIFYING"


def test_preflight_crossing_ttl_cannot_consume_attempt(setup):
    b, c, clock = setup
    p = c.plan()
    original = b.snapshot

    def slow():
        value = original()
        clock.value += 61
        return value

    b.snapshot = slow
    with pytest.raises(m.SwitchError, match="PLAN_EXPIRED"):
        c.apply(p)
    assert b.calls == []
    assert not c.intent.exists()


def test_native_prefix_append_allowed_but_edit_or_delete_rejected():
    old = dict(
        account=dict(
            databases={
                "native-evidence.sqlite": dict(
                    device=1, inode=2, rows=[[1, "s", "hash"]]
                )
            }
        ),
        sdk="s",
    )
    fresh = copy.deepcopy(old)
    fresh["account"]["databases"]["native-evidence.sqlite"]["rows"].append(
        [2, "s2", "hash2"]
    )
    assert m.same_preimage(old, fresh)
    changed = copy.deepcopy(fresh)
    changed["account"]["databases"]["native-evidence.sqlite"]["rows"][0][2] = "changed"
    assert not m.same_preimage(old, changed)
    deleted = copy.deepcopy(fresh)
    deleted["account"]["databases"]["native-evidence.sqlite"]["rows"].pop(0)
    assert not m.same_preimage(old, deleted)


@pytest.mark.parametrize("stage", ["STOPPED", "INSTALLING", "INSTALLED"])
def test_explicit_prestart_restore_and_unknown_start_denied(setup, stage):
    b, c, _ = setup
    p = c.plan()
    snapshot = p["snapshot"]
    b.recovery_preflight = lambda s: b.calls.append("recovery_preflight")
    b.recover = lambda s: dict(verified=True, mode="observe")
    m.write_private(c.intent, dict(stage=stage, snapshot=snapshot), exclusive=True)
    assert c.recover()["stage"] == "RECOVERED"
    assert b.calls == ["recovery_preflight"]


def test_restore_after_start_request_is_forbidden(setup):
    b, c, _ = setup
    m.write_private(c.intent, dict(stage="START_REQUESTED"), exclusive=True)
    with pytest.raises(m.SwitchError, match="UNKNOWN_STAGE"):
        c.recover()
    assert b.calls == []


def test_mac_backend_install_keeps_private_preimages_and_uses_exact_commands(tmp_path):
    from types import SimpleNamespace

    b = m.MacBackend.__new__(m.MacBackend)
    tmp_path.chmod(0o700)
    b.plist = tmp_path / "live.plist"
    b.monitor = tmp_path / "monitor.json"
    b.old_config = tmp_path / "observe.json"
    b.candidate_plist = tmp_path / "candidate.plist"
    b.config = tmp_path / "trade.json"
    b.label = "gui/1/" + m.LABEL
    for p, raw in (
        (b.plist, b"old-plist"),
        (b.monitor, b"old-monitor"),
        (b.old_config, b"old-config"),
        (b.candidate_plist, b"new-plist"),
        (b.config, b"new-config"),
    ):
        p.write_bytes(raw)
        p.chmod(0o600)
    calls = []

    def run(args):
        calls.append(args)
        return SimpleNamespace(
            returncode=113 if args[1] == "print" else 0,
            stdout="",
            stderr="Could not find service " + m.LABEL,
        )

    b.run = run
    b.settings = SimpleNamespace(account_takeover_pending=False)
    assert b.install({})
    assert calls == [
        ["/bin/launchctl", "bootout", b.label],
        ["/bin/launchctl", "print", b.label],
    ]
    assert (
        b.plist.read_bytes() == b"new-plist"
        and b.monitor.read_bytes() == b"old-monitor"
    )
    assert (
        b.plist.with_name("live.plist.trade-switch-preimage").read_bytes()
        == b"old-plist"
    )
    assert (
        b.monitor.with_name("monitor.json.trade-switch-preimage").read_bytes()
        == b"old-monitor"
    )
    assert b.old_config.read_bytes() == b"old-config"


def test_mac_snapshot_uses_pinned_sdk_no_broker_check(tmp_path):
    from types import SimpleNamespace

    b = m.MacBackend.__new__(m.MacBackend)
    b.code = tmp_path
    b.config = tmp_path / "trade.json"
    b.candidate_plist = tmp_path / "trade.plist"
    b.old_config = tmp_path / "observe.json"
    b.candidate_plist.write_bytes(b"plist")
    b.home = tmp_path
    b.folder = tmp_path / "account"
    b.folder.mkdir()
    status = b.folder / "continuous.json"
    status.write_text(
        json.dumps(dict(mode="observe", opening_enabled=False, run_id="run"))
    )
    status.chmod(0o600)
    b.settings = SimpleNamespace(sdk_python=tmp_path / "sdk-python")
    b.locks = []
    b.tag = "v1.16.35"
    b.exact = "82a8031470009249acccb83b9911a374af70ca00"
    b.service = SimpleNamespace(
        render_trade_launch_agent=lambda *a, **k: b"plist",
        preflight_trade=lambda *a: dict(candidate_valid=True),
    )
    b._preimage = lambda: dict(
        config="c", plist="p", old_config="o", old_plist="p", monitor="m", sdk="s"
    )
    b._account = lambda: dict(databases={})
    b.last_observe_index = {}
    b._pid = lambda: 123
    b._prove = lambda *args: ["fixed-command"]
    b._window = lambda: dict(policy=m.POLICY)
    calls = []

    def run(args):
        calls.append(args)
        out = ""
        if args[-2:] == ["-t", "v1.16.35"]:
            out = "tag"
        elif "rev-parse" in args:
            out = "82a8031470009249acccb83b9911a374af70ca00"
        elif "--check" in args:
            out = "CONTINUOUS_CONFIG_SDK_COMPATIBLE_NO_BROKER_IO"
        return SimpleNamespace(returncode=0, stdout=out)

    b.run = run
    snapshot = b.snapshot()
    assert snapshot["host"]["run_id"] == "run"
    assert calls[-1] == [
        b.settings.sdk_python,
        "-I",
        "-B",
        b.code / "scripts/broker/simnow_supervisor.py",
        "--config",
        b.config,
        "--trade",
        "--check",
    ]


@pytest.fixture
def real_account(tmp_path, monkeypatch):
    from dataclasses import replace
    from datetime import datetime, UTC, timedelta
    from types import SimpleNamespace
    from test_supervisor import setup as existing_fixture, ACCOUNT
    from guiyi_quant import htdy_account_execution as a
    from guiyi_quant.simnow_execution.journal import Journal
    from guiyi_quant.simnow_execution.inbox import SignalInbox
    from guiyi_quant.simnow_execution.evidence import Evidence
    from guiyi_quant.simnow_execution.inventory import project_readback, native_hash
    from guiyi_quant.simnow_execution.observe_reconciliation import build_proof
    from guiyi_quant.htdy_account_execution.codec import digest as state_digest

    settings, original = existing_fixture(tmp_path)
    folder = settings.state_root / ACCOUNT
    products = tuple(
        p.upper()
        for p in (PATH.parents[3] / "data/universe/operational_products.txt")
        .read_text()
        .split()
    )
    initial = a.LocalStore.inspect(folder / "account.sqlite")
    (folder / "account.sqlite").unlink()
    store = a.LocalStore(
        folder / "account.sqlite",
        a.start(ACCOUNT, products, initial.activated_at, initial.initial_readback),
    )
    store.close()
    Journal(folder / "dispatch.sqlite", ACCOUNT).close()
    inbox = SignalInbox(folder / "signals.sqlite", ACCOUNT, products)
    inbox.close()
    payload = original.data
    for rows in payload.values():
        for row in rows:
            row["TradingDay"] = "20261030"
    at = datetime(2026, 10, 30, 3, 30, tzinfo=UTC)
    native = replace(
        original,
        trading_day="20261030",
        started_at=at - timedelta(seconds=2),
        at=at,
        payload_json=json.dumps(payload, sort_keys=True, separators=(",", ":")),
        source_id="ctp-inventory:20261030:"
        + native_hash((ACCOUNT, "20261030", payload, at.isoformat())),
    )
    evidence = Evidence(folder / "native-evidence.sqlite", ACCOUNT)
    evidence.append(native)
    evidence.close()
    state = a.LocalStore.inspect(folder / "account.sqlite")
    journal = Journal(folder / "dispatch.sqlite", ACCOUNT)
    rb, _ = project_readback(
        native, (), journal, state, native.at + timedelta(seconds=30)
    )
    journal.close()
    recovered = a.apply(
        replace(state, phase="RECOVERY_REQUIRED", readback_valid=False),
        "fixture-recover",
        a.Recover(rb, ()),
    ).state
    clock = [native.at + timedelta(seconds=1)]
    proof = build_proof(state, native, recovered, "run-fixture", clock[0])
    assert proof is not None
    index = dict(
        run_id="run-fixture",
        account_id=ACCOUNT,
        mode="observe",
        native_source_id=native.source_id,
        ledger_hash=state_digest(state),
        published_at=clock[0].isoformat(),
        observe_reconciliation=proof,
    )
    control = dict(
        run_id="run-fixture", mode="observe", opening_enabled=False, auto_order=False
    )
    for p, v in (
        (settings.state_root / "monitor.json", index),
        (folder / "continuous.json", control),
    ):
        p.write_text(json.dumps(v))
        p.chmod(0o600)

    class FakeDatetime(datetime):
        @staticmethod
        def now(tz):
            return clock[0]

    monkeypatch.setattr(m, "datetime", FakeDatetime)
    b = m.MacBackend.__new__(m.MacBackend)
    b.settings, b.folder = settings, folder
    before = {
        name: (folder / name).read_bytes()
        for name in (
            "account.sqlite",
            "dispatch.sqlite",
            "signals.sqlite",
            "native-evidence.sqlite",
        )
    }
    result = b._account()
    assert result["scope_count"] == 60
    assert before == {name: (folder / name).read_bytes() for name in before}
    b.code_check = lambda: None
    b._preimage = lambda: {}
    b.locks = (tmp_path / "global.lock", folder / "host.lock")
    for path in b.locks:
        path.write_bytes(b"")
        path.chmod(0o600)
    snapshot = Backend().value
    snapshot["host"]["run_id"] = "run-fixture"
    snapshot.update(
        account=result,
        observe_index=copy.deepcopy(b.last_observe_index),
        preimage=dict(
            account=result,
            locks=[
                dict(path=str(p), device=p.stat().st_dev, inode=p.stat().st_ino)
                for p in b.locks
            ],
        ),
    )
    b.snapshot = lambda: copy.deepcopy(snapshot)
    tmp_path.chmod(0o700)
    coordinator = m.Coordinator(b, tmp_path, clock=lambda: clock[0].timestamp())
    plan = coordinator.plan()

    def stop(latest=native):
        stopped_index = {
            k: v for k, v in index.items() if k != "observe_reconciliation"
        }
        stopped_index.update(
            status="STOPPED",
            host_status="STOPPED",
            native_source_id=latest.source_id,
            published_at=clock[0].isoformat(),
        )
        (settings.state_root / "monitor.json").write_text(json.dumps(stopped_index))
        (folder / "continuous.json").write_text(
            json.dumps(dict(control, status="STOPPED", at=clock[0].isoformat()))
        )

    def offline():
        with b.offline_guard(plan["snapshot"]):
            return b.offline_preflight(plan["snapshot"])

    # Only this isolated fixture's non-existent former host PID is simulated.
    def gone(pid, sig):
        raise ProcessLookupError

    monkeypatch.setattr(m.os, "kill", gone)
    return SimpleNamespace(
        b=b,
        settings=settings,
        folder=folder,
        native=native,
        state=state,
        clock=clock,
        plan=plan,
        index=index,
        stop=stop,
        offline=offline,
        before=before,
        proof=proof,
    )


def appended(env, *, seconds=2):
    from dataclasses import replace
    from datetime import timedelta
    from guiyi_quant.simnow_execution.inventory import native_hash

    original = env.native
    at = original.at + timedelta(seconds=seconds)
    return replace(
        original,
        started_at=original.at,
        at=at,
        source_id="ctp-inventory:"
        + original.trading_day
        + ":"
        + native_hash(
            (original.account_id, original.trading_day, original.data, at.isoformat())
        ),
    )


def insert_native(env, snapshot):
    """Malformed rows are deliberately inserted only into isolated test SQLite."""
    import sqlite3

    fields = dict(
        account_id=snapshot.account_id,
        trading_day=snapshot.trading_day,
        started_at=snapshot.started_at.isoformat(),
        at=snapshot.at.isoformat(),
        source_id=snapshot.source_id,
        payload_json=snapshot.payload_json,
    )
    db = sqlite3.connect(env.folder / "native-evidence.sqlite")
    try:
        db.execute(
            "INSERT INTO snapshots(source,payload) VALUES (?,?)",
            (
                snapshot.source_id,
                json.dumps(fields, sort_keys=True, separators=(",", ":")),
            ),
        )
        db.commit()
    finally:
        db.close()


def test_mac_account_reads_real_four_journals_and_bound_monitor_proof(real_account):
    from datetime import timedelta

    e = real_account
    assert e.plan["snapshot"]["observe_index"]["observe_reconciliation"] == e.proof
    e.stop()
    assert e.offline()["writer_idle"] is True
    e.clock[0] += timedelta(seconds=60)
    with pytest.raises(m.SwitchError, match="ACCOUNT_UNPROVEN"):
        e.offline()
    assert (
        e.b._account(restoring=True, frozen_index=e.plan["snapshot"]["observe_index"])[
            "account_id"
        ]
        == e.settings.account_id
    )


def test_stop_boundary_valid_native_append_is_accepted(real_account):
    from datetime import timedelta

    e = real_account
    latest = appended(e)
    insert_native(e, latest)
    e.clock[0] = latest.at + timedelta(seconds=1)
    e.stop(latest)
    assert e.offline()["protected_state_unchanged"] is True
    assert all(
        (e.folder / name).read_bytes() == e.before[name]
        for name in ("account.sqlite", "dispatch.sqlite", "signals.sqlite")
    )


@pytest.mark.parametrize("changed", ["runner", "sdk"])
def test_recovery_rechecks_frozen_observe_executables(tmp_path, monkeypatch, changed):
    old_config = tmp_path / "observe.json"
    old_config.write_text(
        json.dumps(dict(project_root=str(tmp_path), sdk_python=str(tmp_path / "sdk")))
    )
    old_config.chmod(0o600)
    b = m.MacBackend.__new__(m.MacBackend)
    b.code_check = lambda: None
    b.identity = (
        lambda path, **kwargs: "changed"
        if (
            (changed == "runner" and path.name == "simnow_supervisor.py")
            or (changed == "sdk" and path.name == "sdk")
        )
        else "frozen"
    )
    b.run = lambda args: pytest.fail(
        "launchctl must not be reached after executable drift"
    )
    snapshot = dict(
        old_config_path=str(old_config),
        observe_index={},
        preimage=dict(old_runner="frozen", old_sdk="frozen"),
    )
    with pytest.raises(m.SwitchError, match="PREIMAGE_CHANGED"):
        b.recovery_preflight(snapshot)


def rehash(snapshot):
    from dataclasses import replace
    from guiyi_quant.simnow_execution.inventory import native_hash

    return replace(
        snapshot,
        source_id="ctp-inventory:"
        + snapshot.trading_day
        + ":"
        + native_hash(
            (
                snapshot.account_id,
                snapshot.trading_day,
                snapshot.data,
                snapshot.at.isoformat(),
            )
        ),
    )


@pytest.mark.parametrize(
    "case",
    [
        "foreign_account",
        "trading_day",
        "time_reversal",
        "source_hash",
        "nonempty_position",
        "nonempty_order",
        "nonempty_trade",
        "fund_delta",
        "stale",
        "future",
        "future_started",
        "malformed_payload",
    ],
)
def test_stop_boundary_rejects_invalid_appended_native(real_account, case):
    from dataclasses import replace
    from datetime import timedelta

    e = real_account
    latest = appended(e)
    payload = latest.data
    if case == "foreign_account":
        latest = replace(latest, account_id="b" * 64)
    if case == "trading_day":
        latest = replace(latest, trading_day="20261102")
        for rows in payload.values():
            for row in rows:
                row["TradingDay"] = latest.trading_day
    if case == "time_reversal":
        latest = replace(latest, started_at=e.native.at - timedelta(seconds=1))
    if case.startswith("nonempty_"):
        payload[
            {
                "nonempty_position": "positions",
                "nonempty_order": "orders",
                "nonempty_trade": "trades",
            }[case]
        ] = [{"TradingDay": latest.trading_day}]
    if case == "fund_delta":
        payload["funds"][0]["Balance"] = str(int(payload["funds"][0]["Balance"]) + 1)
        payload["funds"][0]["Available"] = str(
            int(payload["funds"][0]["Available"]) + 1
        )
    if case == "malformed_payload":
        payload["extra"] = []
    if case == "future":
        latest = replace(latest, at=e.native.at + timedelta(seconds=10))
    if case == "future_started":
        latest = replace(latest, started_at=latest.at + timedelta(seconds=1))
    latest = rehash(
        replace(
            latest,
            payload_json=json.dumps(payload, sort_keys=True, separators=(",", ":")),
        )
    )
    if case == "source_hash":
        latest = replace(latest, source_id="ctp-inventory:20261030:" + "c" * 64)
    insert_native(e, latest)
    e.clock[0] = e.native.at + timedelta(seconds=3)
    if case == "stale":
        e.clock[0] = latest.at + timedelta(seconds=31)
    e.stop(latest)
    with pytest.raises(m.SwitchError, match="ACCOUNT_UNPROVEN|PENDING_OBLIGATIONS"):
        e.offline()


@pytest.mark.parametrize("case", ["tamper", "deletion"])
def test_stop_boundary_rejects_prefix_rewrite_or_deletion(real_account, case):
    import sqlite3
    from datetime import timedelta

    e = real_account
    latest = appended(e)
    insert_native(e, latest)
    db = sqlite3.connect(e.folder / "native-evidence.sqlite")
    try:
        db.execute("DROP TRIGGER no_update")
        db.execute("DROP TRIGGER no_delete")
        if case == "tamper":
            db.execute("UPDATE snapshots SET payload=payload || ' ' WHERE rowid=1")
        else:
            db.execute("DELETE FROM snapshots WHERE rowid=1")
        db.commit()
    finally:
        db.close()
    e.clock[0] = latest.at + timedelta(seconds=1)
    e.stop(latest)
    with pytest.raises(m.SwitchError, match="PREIMAGE_CHANGED"):
        e.offline()


@pytest.mark.parametrize(
    "key,value",
    [
        ("run_id", "other-run"),
        ("account_id", "b" * 64),
        ("ledger_hash", "b" * 64),
        ("native_source_id", "missing"),
        ("status", "ACTIVE"),
    ],
)
def test_stop_boundary_requires_latest_stopped_monitor_binding(
    real_account, key, value
):
    from datetime import timedelta

    e = real_account
    latest = appended(e)
    insert_native(e, latest)
    e.clock[0] = latest.at + timedelta(seconds=1)
    e.stop(latest)
    path = e.settings.state_root / "monitor.json"
    index = json.loads(path.read_bytes())
    index[key] = value
    path.write_text(json.dumps(index))
    with pytest.raises(m.SwitchError, match="ACCOUNT_UNPROVEN"):
        e.offline()


def test_stop_boundary_rejects_unbound_extra_latest_snapshot(real_account):
    from datetime import timedelta

    e = real_account
    latest = appended(e)
    insert_native(e, latest)
    e.clock[0] = latest.at + timedelta(seconds=1)
    e.stop(e.native)
    with pytest.raises(m.SwitchError, match="ACCOUNT_UNPROVEN"):
        e.offline()


def test_stop_boundary_valid_later_snapshot_cannot_hide_invalid_middle(real_account):
    from dataclasses import replace
    from datetime import timedelta

    e = real_account
    bad = appended(e)
    payload = bad.data
    payload["orders"] = [{"TradingDay": "20261030"}]
    bad = rehash(replace(bad, payload_json=json.dumps(payload)))
    insert_native(e, bad)
    latest = appended(e, seconds=5)
    latest = replace(latest, started_at=bad.at)
    insert_native(e, latest)
    e.clock[0] = latest.at + timedelta(seconds=1)
    e.stop(latest)
    with pytest.raises(m.SwitchError, match="PENDING_OBLIGATIONS"):
        e.offline()


def test_offline_requires_real_dual_guard_and_unchanged_lock_identity(real_account):
    e = real_account
    e.stop()
    with pytest.raises(m.SwitchError, match="STOP_UNPROVEN"):
        e.b.offline_preflight(e.plan["snapshot"])
    lock = e.b.locks[0]
    renamed = lock.with_name("old-global.lock")
    lock.rename(renamed)
    lock.write_bytes(b"")
    lock.chmod(0o600)
    with pytest.raises(m.SwitchError, match="PREIMAGE_CHANGED"):
        e.offline()


@pytest.mark.parametrize("attempts,blocked", [(3, False), (2, True)])
def test_connection_capacity_rejected_before_sigterm(setup, attempts, blocked):
    b, c, _ = setup
    b.value["account"].update(
        today_attempts=attempts, remaining_attempts=3 - attempts, day_blocked=blocked
    )
    with pytest.raises(m.SwitchError, match="ACCOUNT_UNPROVEN"):
        c.plan()
    assert not b.calls


def session_rows(
    local_now, *, phase_override=None, afternoon_hour=13, afternoon_minute=30
):
    from datetime import datetime, date
    from zoneinfo import ZoneInfo
    from types import SimpleNamespace as NS

    zone = ZoneInfo("Asia/Shanghai")

    def at(h, m=0):
        return datetime(2026, 10, 30, h, m, tzinfo=zone)

    windows = [
        NS(is_night=False, window=NS(start=at(9), end=at(10, 15))),
        NS(is_night=False, window=NS(start=at(10, 30), end=at(11, 30))),
        NS(
            is_night=False,
            window=NS(start=at(afternoon_hour, afternoon_minute), end=at(15)),
        ),
    ]
    next_open = next(
        (w.window.start for w in windows if w.window.start > local_now), None
    )
    current = next(
        (w.window for w in windows if w.window.start <= local_now < w.window.end), None
    )
    phase = (
        "TRADING" if current else "BREAK" if at(9) <= local_now < at(15) else "CLOSED"
    )
    if phase_override:
        phase = phase_override
    return [
        (
            "p" + str(i),
            NS(
                is_trading_day=True,
                has_night_session=i < 45,
                trade_date=date(2026, 10, 30),
            ),
            copy.deepcopy(windows),
            NS(
                phase=phase,
                current_session=current,
                next_session_start=next_open,
                trading_day=date(2026, 10, 30),
            ),
        )
        for i in range(60)
    ]


@pytest.mark.parametrize(
    "hour,minute,opened",
    [
        (9, 0, False),
        (10, 20, False),
        (11, 29, False),
        (11, 30, True),
        (11, 35, True),
        (13, 0, True),
        (13, 19, True),
        (13, 20, False),
        (13, 30, False),
        (14, 0, False),
    ],
)
def test_midday_uses_authoritative_afternoon_not_a_fixed_1300(hour, minute, opened):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    now = datetime(2026, 10, 30, hour, minute, tzinfo=ZoneInfo("Asia/Shanghai"))
    result = m.window_facts(session_rows(now), now, "midday")
    assert result["window_open"] is opened
    assert result["policy"] == m.MIDDAY_POLICY
    assert result["eligible_from"].startswith("2026-10-30T11:30")
    assert result["eligible_until"].startswith("2026-10-30T13:19")
    if opened:
        m.validate_window(result)
        assert set(result["phases"].values()) == {"BREAK"}
    else:
        with pytest.raises(m.SwitchError, match="WINDOW_UNPROVEN"):
            m.validate_window(result)


@pytest.mark.parametrize(
    "case",
    [
        "unknown",
        "missing_calendar",
        "wrong_day",
        "missing_afternoon",
        "active_one",
        "missing_current",
        "different_next",
        "scope",
    ],
)
def test_midday_rejects_unknown_or_inconsistent_authoritative_fact(case):
    from datetime import datetime, date, timedelta
    from zoneinfo import ZoneInfo

    now = datetime(2026, 10, 30, 11, 35, tzinfo=ZoneInfo("Asia/Shanghai"))
    rows = session_rows(now)
    product, calendar, windows, phase = rows[0]
    if case == "unknown":
        phase.phase = "UNKNOWN"
    if case == "missing_calendar":
        calendar.is_trading_day = False
    if case == "wrong_day":
        phase.trading_day = date(2026, 11, 2)
    if case == "missing_afternoon":
        windows.pop()
    if case == "active_one":
        phase.phase = "TRADING"
    if case == "missing_current":
        phase.current_session = windows[0].window
    if case == "different_next":
        phase.next_session_start += timedelta(minutes=1)
    if case == "scope":
        rows.pop()
    try:
        result = m.window_facts(rows, now, "midday")
        m.validate_window(result)
    except m.SwitchError as exc:
        assert str(exc) == "WINDOW_UNPROVEN"
    else:
        pytest.fail("invalid session facts accepted")


def test_plan_v2_policy_cannot_be_switched_between_plan_and_apply(setup):
    b, c, _ = setup
    plan = c.plan()
    assert plan["schema"] == "simnow_trade_switch_plan_v4"
    b.value["window"] = dict(
        policy=m.MIDDAY_POLICY,
        trading_day="20261030",
        authoritative=True,
        current_session_absent=True,
        next_session_gap_seconds=7000,
        product_count=60,
        window_open=True,
        morning_completed=True,
        next_is_afternoon=True,
    )
    with pytest.raises(m.SwitchError, match="PLAN_INVALID"):
        c.apply(plan)
    assert not b.calls
    assert not c.intent.exists()


@pytest.mark.parametrize(
    "old_schema",
    [
        "simnow_trade_switch_plan_v1",
        "simnow_trade_switch_plan_v2",
        "simnow_trade_switch_plan_v3",
    ],
)
def test_v1_plan_is_not_accepted_for_new_execution(setup, old_schema):
    b, c, _ = setup
    plan = c.plan()
    plan["schema"] = old_schema
    plan["plan_hash"] = m.digest({k: v for k, v in plan.items() if k != "plan_hash"})
    with pytest.raises(m.SwitchError, match="PLAN_INVALID"):
        c.apply(plan)
    assert not b.calls


@pytest.mark.parametrize(
    "field,value",
    [
        ("Commission", "NaN"),
        ("Deposit", "-1"),
        ("Withdraw", None),
        ("CloseProfit", "Infinity"),
        ("PositionProfit", "changed"),
        ("Deposit", "1"),
        ("CloseProfit", "-1"),
        ("Commission", 1),
    ],
)
@pytest.mark.parametrize("bad_middle", [False, True])
def test_appended_native_preserves_all_original_money_contracts(
    real_account, field, value, bad_middle
):
    from dataclasses import replace
    from datetime import timedelta

    e = real_account
    bad = appended(e)
    payload = bad.data
    if value is None:
        payload["funds"][0].pop(field)
    else:
        payload["funds"][0][field] = value
    bad = rehash(replace(bad, payload_json=json.dumps(payload)))
    insert_native(e, bad)
    latest = bad
    if bad_middle:
        latest = replace(appended(e, seconds=5), started_at=bad.at)
        insert_native(e, latest)
    e.clock[0] = latest.at + timedelta(seconds=1)
    e.stop(latest)
    with pytest.raises(m.SwitchError, match="ACCOUNT_UNPROVEN"):
        e.offline()


def test_actual_budget_and_block_are_read_without_reset(real_account):
    import sqlite3

    e = real_account
    db = sqlite3.connect(e.folder / "signals.sqlite")
    try:
        db.execute("INSERT INTO attempts(day,count) VALUES (?,?)", ("20261030", 2))
        db.commit()
        result = e.b._account()
        assert (
            result["today_attempts"],
            result["remaining_attempts"],
            result["day_blocked"],
        ) == (2, 1, False)
        db.execute("UPDATE attempts SET count=3 WHERE day=?", ("20261030",))
        db.commit()
        result = e.b._account()
        assert result["remaining_attempts"] == 0
        candidate = copy.deepcopy(e.plan["snapshot"])
        candidate["account"] = result
        with pytest.raises(m.SwitchError, match="ACCOUNT_UNPROVEN"):
            m.validate_snapshot(candidate)
        db.execute("UPDATE attempts SET count=2 WHERE day=?", ("20261030",))
        db.execute(
            "INSERT INTO blocks(day,code) VALUES (?,?)", ("20261030", "RETAINED")
        )
        db.commit()
        result = e.b._account()
        assert result["day_blocked"] is True
        candidate["account"] = result
        with pytest.raises(m.SwitchError, match="ACCOUNT_UNPROVEN"):
            m.validate_snapshot(candidate)
        assert db.execute(
            "SELECT count FROM attempts WHERE day=?", ("20261030",)
        ).fetchone() == (2,)
        assert db.execute(
            "SELECT code FROM blocks WHERE day=?", ("20261030",)
        ).fetchone() == ("RETAINED",)
    finally:
        db.close()


def test_last_budget_change_is_rejected_before_os_sigterm(real_account, monkeypatch):
    import sqlite3

    e = real_account
    e.b._stop_signals = e.b.identity(e.folder / "signals.sqlite")
    e.b.old_config = e.folder / "not-read-by-mocked-process-proof"
    e.b._prove = lambda *args: None
    db = sqlite3.connect(e.folder / "signals.sqlite")
    db.execute("INSERT INTO attempts(day,count) VALUES (?,?)", ("20261030", 3))
    db.commit()
    db.close()
    monkeypatch.setattr(
        m.os, "kill", lambda *args: pytest.fail("SIGTERM before budget readback")
    )
    with pytest.raises(m.SwitchError, match="PREIMAGE_CHANGED"):
        e.b.stop(e.plan["snapshot"]["host"]["pid"])


def test_night_policy_excludes_fifteen_no_night_phase_checks():
    from datetime import datetime, timedelta
    from types import SimpleNamespace as NS
    from zoneinfo import ZoneInfo

    zone = ZoneInfo("Asia/Shanghai")
    now = datetime(2026, 10, 30, 2, 35, tzinfo=zone)
    rows = session_rows(now)
    for i, (_, calendar, windows, phase) in enumerate(rows):
        phase.phase = "CLOSED" if i < 45 else "UNKNOWN"
        phase.current_session = None
        phase.next_session_start = datetime(2026, 10, 30, 9, tzinfo=zone)
        if i < 45:
            windows.append(
                NS(
                    is_night=True,
                    window=NS(
                        start=now - timedelta(hours=5), end=now - timedelta(minutes=5)
                    ),
                )
            )
    result = m.window_facts(rows, now, "night")
    m.validate_window(result)
    assert result["night_count"] == 45 and result["excluded_no_night_count"] == 15


def test_stop_boundary_only_accepts_normal_append_rowid_sequence(real_account):
    import sqlite3
    from datetime import timedelta

    e = real_account
    latest = appended(e)
    fields = dict(
        account_id=latest.account_id,
        trading_day=latest.trading_day,
        started_at=latest.started_at.isoformat(),
        at=latest.at.isoformat(),
        source_id=latest.source_id,
        payload_json=latest.payload_json,
    )
    db = sqlite3.connect(e.folder / "native-evidence.sqlite")
    db.execute(
        "INSERT INTO snapshots(rowid,source,payload) VALUES (?,?,?)",
        (3, latest.source_id, json.dumps(fields)),
    )
    db.commit()
    db.close()
    e.clock[0] = latest.at + timedelta(seconds=1)
    e.stop(latest)
    with pytest.raises(m.SwitchError, match="PREIMAGE_CHANGED"):
        e.offline()


def test_expired_frozen_proof_is_only_history_when_real_latest_append_is_fresh(
    real_account,
):
    from datetime import timedelta

    e = real_account
    latest = appended(e, seconds=35)
    insert_native(e, latest)
    e.clock[0] = latest.at + timedelta(seconds=1)
    assert e.clock[0] > e.native.at + timedelta(seconds=30)
    e.stop(latest)
    result = e.offline()
    assert result["protected_state_unchanged"] is True
    assert result["native_appended_count"] == 1


def test_window_rows_materialize_calendar_before_real_readonly_rollback(
    tmp_path, monkeypatch
):
    sqlalchemy = pytest.importorskip("sqlalchemy")
    from datetime import date, datetime, time, UTC
    from sqlalchemy.orm import Session, sessionmaker
    from sqlalchemy.orm.exc import DetachedInstanceError

    monkeypatch.syspath_prepend(str(PATH.parents[3] / "services/quant-api"))
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    from app.db import session as db_session
    from app.models import Exchange, Instrument, TradingCalendar, TradingSession
    from app.db.base import Base
    from app.market_data.operational_universe import load_operational_products

    engine = sqlalchemy.create_engine(
        "sqlite+pysqlite:///" + str(tmp_path / "window-authority.sqlite")
    )
    Base.metadata.create_all(
        engine,
        tables=[
            Exchange.__table__,
            Instrument.__table__,
            TradingCalendar.__table__,
            TradingSession.__table__,
        ],
    )
    products = load_operational_products()
    assert len(products) == 60
    with Session(engine) as db:
        db.add(Exchange(code="SHFE", name="Isolated fixture exchange"))
        for day, active in [
            (date(2026, 10, 30), True),
            (date(2026, 10, 31), False),
            (date(2026, 11, 1), False),
            (date(2026, 11, 2), True),
        ]:
            db.add(
                TradingCalendar(
                    exchange_code="SHFE",
                    trade_date=day,
                    is_trading_day=active,
                    has_night_session=False,
                )
            )
        for product in products:
            db.add(
                Instrument(
                    symbol=product, name=product, exchange_code="SHFE", is_active=True
                )
            )
            for name, start, end in [
                ("morning1", time(9), time(10, 15)),
                ("morning2", time(10, 30), time(11, 30)),
                ("afternoon", time(13, 30), time(15)),
            ]:
                db.add(
                    TradingSession(
                        exchange_code="SHFE",
                        instrument_symbol=product,
                        session_name=name,
                        start_time=start,
                        end_time=end,
                        effective_from=date(2026, 10, 1),
                        is_active=True,
                    )
                )
        db.commit()

    class AuthoritySession(Session):
        pass

    captured = []

    @sqlalchemy.event.listens_for(AuthoritySession, "loaded_as_persistent")
    def capture_calendar(session, instance):
        if isinstance(instance, TradingCalendar):
            captured.append(instance)

    monkeypatch.setattr(
        db_session,
        "SessionLocal",
        sessionmaker(bind=engine, class_=AuthoritySession, expire_on_commit=True),
    )
    b = m.MacBackend.__new__(m.MacBackend)
    b.window = "midday"
    now = datetime(2026, 10, 30, 2, 0, tzinfo=UTC)
    try:
        facts = b._window_rows(now)
        assert captured and all(
            sqlalchemy.inspect(row).detached and sqlalchemy.inspect(row).expired
            for row in captured
        )
        # This is the actual former failure mechanism, not a stand-in object.
        with pytest.raises(DetachedInstanceError):
            _ = captured[0].is_trading_day
        result = m.window_facts(facts, now, "midday")
        assert result["window_open"] is False
        assert set(result["phases"].values()) == {"TRADING"}
        with pytest.raises(m.SwitchError, match="WINDOW_UNPROVEN"):
            m.validate_window(result)
        from zoneinfo import ZoneInfo

        assert (
            datetime.fromisoformat(result["eligible_from"])
            .astimezone(ZoneInfo("Asia/Shanghai"))
            .strftime("%H:%M")
            == "11:30"
        )
        with pytest.raises(AttributeError):
            facts[0][1].is_trading_day = False
    finally:
        engine.dispose()
