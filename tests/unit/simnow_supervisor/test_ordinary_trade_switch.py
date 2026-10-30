"""v5 lifecycle uses ordinary budget and never restarts a spent old host."""

from test_trade_switch import m, Backend
import pytest


def anchor(value):
    historical = dict(
        policy="simnow_completed_contract_anchor_v1",
        trading_day="20261030",
        product_count=60,
        sha256="a" * 64,
    )
    value["historical_contract_anchor"] = historical
    value["preimage"] = {"historical_contract_anchor": historical}
    return value


def test_ordinary_v5_target_day_not_old_civil_day():
    b = Backend()
    value = anchor(b.value)
    value["ordinary_permit"] = dict(
        schema="simnow_ordinary_takeover_v2",
        account_id="id",
        profile={"profile_id": "original_anchor_v1"},
        window={"trading_day": "20261102"},
    )
    value["account"].update(
        budget_day="20261102",
        account_takeover_pending=True,
        native_account_verified=False,
        local_obligations_clear=True,
        unknown_positions=None,
        unknown_orders=None,
        unknown_trades=None,
        account_profile={"profile_id": "original_anchor_v1"},
    )
    value["host"]["mode"] = "trade"
    value["window"] = dict(
        policy="simnow_ordinary_next_session_v2",
        trading_day="20261102",
        authoritative=True,
        product_count=60,
        current_session_absent=True,
        window_open=True,
        next_session_gap_seconds=3600,
    )
    assert m.SCHEMA == "simnow_trade_switch_plan_v6"
    m.validate_snapshot(value)


@pytest.mark.parametrize(
    "field,value",
    [("today_attempts", 3), ("day_blocked", True), ("budget_day", "20261030")],
)
def test_ordinary_v5_never_borrows_other_day_or_block(field, value):
    b = Backend()
    b.value["ordinary_permit"] = {
        "schema": "simnow_ordinary_takeover_v2",
        "account_id": "id",
        "window": {"trading_day": "20261102"},
    }
    b.value["account"][field] = value
    with pytest.raises(m.SwitchError):
        m.validate_snapshot(b.value)


@pytest.mark.parametrize(
    "schema", ["simnow_trade_switch_plan_v4", "simnow_trade_switch_plan_v5"]
)
def test_old_plan_is_historical_only(tmp_path, schema):
    tmp_path.chmod(0o700)
    b = Backend()
    c = m.Coordinator(b, tmp_path, clock=lambda: 1000)
    p = c.plan()
    p["schema"] = schema
    p["plan_hash"] = m.digest({k: v for k, v in p.items() if k != "plan_hash"})
    with pytest.raises(m.SwitchError, match="PLAN_INVALID"):
        c.apply(p)
    assert not b.calls


def ordinary_snapshot(m):
    value = anchor(Backend().value)
    profile = {"profile_id": "original_anchor_v1"}
    value["ordinary_permit"] = dict(
        schema="simnow_ordinary_takeover_v2",
        account_id="id",
        profile=profile,
        state_dir="",
        window={"trading_day": "20261102"},
    )
    value["account"].update(
        budget_day="20261102",
        account_takeover_pending=True,
        native_account_verified=False,
        local_obligations_clear=True,
        unknown_positions=None,
        unknown_orders=None,
        unknown_trades=None,
        account_profile=profile,
    )
    value["host"]["mode"] = "trade"
    value["window"] = dict(
        policy="simnow_ordinary_next_session_v2",
        trading_day="20261102",
        authoritative=True,
        product_count=60,
        current_session_absent=True,
        window_open=True,
        next_session_gap_seconds=3600,
    )
    return value


def test_explicit_stopped_recovery_never_restarts_old_host_and_is_one_shot(tmp_path):
    import json

    old = tmp_path / "old"
    old.mkdir(mode=0o700)
    source = old / "switch-intent.private.json"
    source.write_text(
        json.dumps(
            dict(schema=m.SCHEMA, stage="STOPPED", snapshot=ordinary_snapshot(m))
        )
    )
    source.chmod(0o600)
    (old / "switch.lock").touch(mode=0o600)
    fresh = tmp_path / "new"
    fresh.mkdir(mode=0o700)

    class RecoveryBackend(Backend):
        def recovery_snapshot(self, original):
            value = ordinary_snapshot(m)
            value["ordinary_permit"]["state_dir"] = str(fresh)
            return value

        def offline_preflight(self, s):
            value = super().offline_preflight(s)
            value["connection_anchor"] = {"frozen": "anchor"}
            return value

        def issue_ordinary_permit(self, *args):
            self.calls.append("ordinary-grant")
            return "f" * 64

        def readback(self, s):
            v = super().readback(s)
            v.update(account_takeover_pending=True, opening_enabled=False)
            return v

    b = RecoveryBackend()
    c = m.Coordinator(b, fresh, clock=lambda: 1000, sleep=lambda _: None)
    p = c.plan_recovery(source)
    # A distinct process holding the original coordinator lock forbids takeover.
    import subprocess
    import sys

    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            'import fcntl,sys; f=open(sys.argv[1],"r+"); fcntl.flock(f,fcntl.LOCK_EX); print("locked",flush=True); sys.stdin.read()',
            str(old / "switch.lock"),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout.readline().strip() == "locked"
        with pytest.raises(m.SwitchError, match="SWITCH_BUSY"):
            c.recover_pending_trade(p)
        assert not (old / "pending-trade-recovery-claim.private.json").exists()
        assert not (fresh / "ordinary-recovery-intent.private.json").exists()
        assert not b.calls
    finally:
        holder.communicate("", timeout=5)
    assert c.recover_pending_trade(p)["stage"] == "COMPLETE"
    assert "stop" not in b.calls and b.calls.count("start") == 1
    assert json.loads(source.read_text())["stage"] == "STOPPED"
    with pytest.raises(m.SwitchError):
        c.recover_pending_trade(p)


@pytest.mark.parametrize(
    "stage", ["START_REQUESTED", "VERIFYING", "COMPLETE", "RESTORE_REQUESTED"]
)
def test_recovery_after_unknown_start_is_never_admitted(tmp_path, stage):
    import json

    tmp_path.chmod(0o700)
    p = tmp_path / "source.json"
    p.write_text(
        json.dumps(dict(schema=m.SCHEMA, stage=stage, snapshot=ordinary_snapshot(m)))
    )
    p.chmod(0o600)
    c = m.Coordinator(Backend(), tmp_path, clock=lambda: 1000)
    with pytest.raises(m.SwitchError):
        c.plan_recovery(p)


@pytest.mark.parametrize(
    "changed", ["sdk", "old_config", "target_config", "old_pid", "loaded_pid"]
)
def test_real_recovery_backend_rejects_drift_before_candidate_or_install(
    tmp_path, changed
):
    """Run the actual MacBackend admission method without launchctl/native IO."""
    import hashlib
    import json
    from types import SimpleNamespace

    tmp_path.chmod(0o700)
    original = tmp_path / "original.json"
    old = tmp_path / "old.json"
    cfg = {"mode": "trade", "ordinary_takeover_permit": "old-path"}
    for path, value in ((original, cfg), (old, {})):
        path.write_text(json.dumps(value))
        path.chmod(0o600)
    b = m.MacBackend.__new__(m.MacBackend)
    b.ordinary = True
    b.settings = SimpleNamespace(sdk_python=tmp_path / "sdk")
    b.code = tmp_path
    b.exact = "e" * 40
    b.tag = "v1.2.3"
    b.cfg = dict(cfg, ordinary_takeover_permit="new-path")
    b.identity = lambda path, **kw: {
        "sha256": "changed"
        if (changed == "sdk" and path.name == "sdk")
        or (changed == "old_config" and path == old)
        else "frozen"
    }
    b.stopped = lambda source: changed != "old_pid"
    b._label_loaded = lambda: (
        SimpleNamespace(stdout="pid = 42") if changed == "loaded_pid" else None
    )
    b._candidate = lambda: pytest.fail("must reject before candidate SDK check")
    source = dict(
        candidate=dict(commit=b.exact, tag=b.tag),
        old_config_path=str(old),
        ordinary_permit=dict(config_path=str(original)),
        preimage=dict(
            sdk={"sha256": "frozen"},
            old_config={"sha256": "frozen"},
            release={"root": str(tmp_path)},
            config={"sha256": hashlib.sha256(original.read_bytes()).hexdigest()},
        ),
    )
    b._historical_anchor = lambda: None
    if changed == "target_config":
        b.cfg["mode"] = "observe"
    with pytest.raises(m.SwitchError):
        b.recovery_snapshot(source)


def test_historical_anchor_drift_refuses_real_backend_before_stop():
    b = m.MacBackend.__new__(m.MacBackend)
    b._historical_anchor = lambda: {"sha256": "changed"}
    with pytest.raises(m.SwitchError, match="PREIMAGE_CHANGED"):
        b._verify_historical_anchor(
            {"historical_contract_anchor": {"sha256": "frozen"}}
        )


def test_ordinary_snapshot_requires_frozen_historical_anchor():
    value = ordinary_snapshot(m)
    value["historical_contract_anchor"] = dict(
        value["historical_contract_anchor"], sha256="b" * 64
    )
    with pytest.raises(m.SwitchError, match="ACCOUNT_UNPROVEN"):
        m.validate_snapshot(value)


@pytest.mark.parametrize("phase", ["STOPPED", "START_REQUESTED", "COMPLETE"])
def test_v5_intent_remains_readable_without_mutation(tmp_path, phase):
    import json

    tmp_path.chmod(0o700)
    intent = tmp_path / "switch-intent.private.json"
    intent.write_text(
        json.dumps(dict(schema="simnow_trade_switch_plan_v5", stage=phase, snapshot={}))
    )
    intent.chmod(0o600)
    before = intent.read_bytes()
    value = m.Coordinator(None, tmp_path).readback()
    assert value["schema"] == "simnow_trade_switch_plan_v5"
    assert value["mutation_performed"] is False and not value["retry_permitted"]
    assert intent.read_bytes() == before
