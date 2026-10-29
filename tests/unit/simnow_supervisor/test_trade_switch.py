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
        return dict(writer_idle=True, journals_unchanged=True, preimage=s["preimage"])

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
    assert b.install({})
    assert calls == [
        ["/bin/launchctl", "bootout", b.label],
        ["/bin/launchctl", "print", b.label],
    ]
    assert (
        b.plist.read_bytes() == b"new-plist" and b.monitor.read_bytes() == b"new-config"
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


def test_mac_account_reads_real_four_journals_and_bound_monitor_proof(
    tmp_path, monkeypatch
):
    from dataclasses import replace
    from datetime import timedelta
    from test_supervisor import setup as existing_fixture, ACCOUNT
    from guiyi_quant import htdy_account_execution as a
    from guiyi_quant.simnow_execution.journal import Journal
    from guiyi_quant.simnow_execution.inbox import SignalInbox
    from guiyi_quant.simnow_execution.evidence import Evidence
    from guiyi_quant.simnow_execution.inventory import project_readback
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
    native = replace(
        original, trading_day="20261030", source_id="ctp-inventory:20261030:" + "c" * 64
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
    now = native.at + timedelta(seconds=1)
    proof = build_proof(state, native, recovered, "run-fixture", now)
    assert proof is not None
    index = dict(
        run_id="run-fixture",
        account_id=ACCOUNT,
        mode="observe",
        native_source_id=native.source_id,
        ledger_hash=state_digest(state),
        published_at=now.isoformat(),
        observe_reconciliation=proof,
    )
    for p, v in (
        (settings.state_root / "monitor.json", index),
        (folder / "continuous.json", dict(run_id="run-fixture")),
    ):
        p.write_text(json.dumps(v))
        p.chmod(0o600)

    class FakeDatetime:
        @staticmethod
        def now(tz):
            return now

    monkeypatch.setattr(m, "datetime", FakeDatetime)
    b = m.MacBackend.__new__(m.MacBackend)
    b.settings = settings
    b.folder = folder
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
    assert not any(
        result[k]
        for k in (
            "unknown_positions",
            "unknown_orders",
            "unknown_trades",
            "reservations",
        )
    )
    assert b.last_observe_index["observe_reconciliation"] == proof
    assert before == {name: (folder / name).read_bytes() for name in before}
    # Freeze a real account/proof plan before STOPPED publication clears proof.
    b.code_check = lambda: None
    b._preimage = lambda: {}
    snapshot = Backend().value
    snapshot.update(
        account=result,
        observe_index=copy.deepcopy(b.last_observe_index),
        preimage=dict(account=result),
    )
    b.snapshot = lambda: copy.deepcopy(snapshot)
    tmp_path.chmod(0o700)
    coordinator = m.Coordinator(b, tmp_path, clock=lambda: now.timestamp())
    plan = coordinator.plan()
    assert plan["snapshot"]["observe_index"]["observe_reconciliation"] == proof
    # STOPPED may clear proof; offline validation still requires the frozen proof fresh.
    index.pop("observe_reconciliation")
    (settings.state_root / "monitor.json").write_text(json.dumps(index))
    (folder / "continuous.json").write_text(
        json.dumps(dict(run_id="run-fixture", status="STOPPED"))
    )
    assert b.offline_preflight(plan["snapshot"])["writer_idle"] is True
    now += timedelta(seconds=60)
    with pytest.raises(m.SwitchError, match="ACCOUNT_UNPROVEN"):
        b.offline_preflight(plan["snapshot"])
    assert (
        b._account(restoring=True, frozen_index=plan["snapshot"]["observe_index"])[
            "account_id"
        ]
        == ACCOUNT
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
