"""Explicit simulated-account promotion; native side effects use local fixtures."""

import json
import pytest
from test_trade_switch import m, setup as setup
from test_held_migration import held_preimage as held_preimage
from test_ordinary_trade_switch import ordinary_snapshot


def enable_candidate(b):
    b.enable_auto_order = True
    b.settings.account_recovery_hold = False
    b.settings.account_profile = {"profile_id": "original_anchor_v1"}
    b.cfg.update(account_recovery_hold=False, account_profile=b.settings.account_profile)
    old = json.loads(b.old_config.read_bytes())
    old["account_profile"] = b.settings.account_profile
    b.old_config.write_text(json.dumps(old))
    b.config.write_text(json.dumps(b.cfg))


def source_control(**changes):
    return dict(account_recovery_hold=True, auto_order=False,
                opening_enabled=False, account_takeover_pending=False,
                status="ACCOUNT_RECOVERED_HELD", run_id="1" * 32, **changes)


def test_explicit_simnow_enable_is_bound_to_preimage_and_actual_held_source(held_preimage):
    b = held_preimage
    enable_candidate(b)
    preimage = b._preimage()
    assert preimage["auto_order_transition"] == dict(
        policy="simnow_owner_auto_order_enable_v1", source_hold=True, target_hold=False)
    assert b._source_hold(source_control()) is True
    control = source_control()
    control["status"] = "WAITING_SESSION"
    control["account_takeover_pending"] = True
    assert b._source_hold(control) is True
    (b.folder / ("failure-" + control["run_id"] + "-0.json")).write_text("{}")
    with pytest.raises(m.SwitchError, match="HOST_UNPROVEN"):
        b._source_hold(control)
    b.enable_auto_order = False
    with pytest.raises(m.SwitchError, match="CANDIDATE_UNPROVEN"):
        b._preimage()


@pytest.mark.parametrize("change", ["ordinary", "pending", "schema", "mode", "enabled", "profile", "sdk", "source_hold", "target_hold"])
def test_enable_cannot_change_account_policy_or_bypass_normal_takeover(held_preimage, change):
    b = held_preimage
    enable_candidate(b)
    if change == "ordinary":
        b.ordinary = False
    elif change == "pending":
        b.settings.account_takeover_pending = False
    elif change == "schema":
        b.settings.schema = 1
    elif change == "mode":
        b.settings.mode = "observe"
    elif change == "enabled":
        b.settings.enabled = False
    elif change == "profile":
        b.cfg["account_profile"] = {"profile_id": "different"}
    elif change == "sdk":
        b.cfg["sdk_python"] = "different"
    elif change == "source_hold":
        old = json.loads(b.old_config.read_bytes())
        old["account_recovery_hold"] = False
        b.old_config.write_text(json.dumps(old))
    else:
        b.cfg["account_recovery_hold"] = True
    with pytest.raises(m.SwitchError, match="CANDIDATE_UNPROVEN"):
        b._preimage()


@pytest.mark.parametrize("key,value", [
    ("account_takeover_pending", True), ("account_recovery_hold", False),
    ("auto_order", True), ("opening_enabled", True),
    ("status", "RECOVERY_BLOCKED"), ("status", "ACCOUNT_RECONCILIATION_REQUIRED"),
])
def test_unknown_or_active_source_never_authorizes_auto_enable(held_preimage, key, value):
    b = held_preimage
    enable_candidate(b)
    b._preimage()
    control = source_control()
    control[key] = value
    with pytest.raises(m.SwitchError, match="HOST_UNPROVEN"):
        b._source_hold(control)


def enabled_snapshot():
    value = ordinary_snapshot(m)
    value["host"]["account_recovery_hold"] = True
    value["account"]["account_recovery_hold"] = False
    value["preimage"]["auto_order_transition"] = dict(
        policy=m.AUTO_ORDER_ENABLE_POLICY, source_hold=True, target_hold=False)
    return value


@pytest.mark.parametrize("change", ["missing", "policy", "source", "host_mode", "budget", "block", "scope"])
def test_forged_transition_does_not_bypass_snapshot_admission(change):
    v = enabled_snapshot()
    if change == "missing":
        del v["preimage"]["auto_order_transition"]
    elif change == "policy":
        v["preimage"]["auto_order_transition"]["policy"] = "other"
    elif change == "source":
        v["host"]["account_recovery_hold"] = False
    elif change == "host_mode":
        v["host"]["mode"] = "observe"
    elif change == "budget":
        v["account"]["today_attempts"] = 3
    elif change == "block":
        v["account"]["day_blocked"] = True
    else:
        v["account"]["scope_count"] = 59
    with pytest.raises(m.SwitchError):
        m.validate_snapshot(v)


def auto_backend(b, c):
    b.value = enabled_snapshot()
    b.value["ordinary_permit"]["state_dir"] = str(c.root)
    b.issue_ordinary_permit = lambda *args: "f" * 64
    old_preflight = b.offline_preflight
    b.offline_preflight = lambda snapshot: {**old_preflight(snapshot), "connection_anchor": {"anchor": "same"}}
    readback = b.readback
    b.readback = lambda snapshot: {**readback(snapshot),
        "account_recovery_hold": False, "auto_order": True,
        "account_takeover_pending": True, "opening_enabled": False}


def test_auto_host_switch_still_waits_for_native_takeover_and_never_claims_fill(setup):
    b, c, clock = setup
    auto_backend(b, c)
    result = c.apply(c.plan())
    assert result["stage"] == "COMPLETE"
    assert result["result"] == "HOST_SWITCH_VERIFIED"
    assert result["native_recovery_complete"] is False
    assert b.calls.count("start") == 1 and b.calls.count("readback") == 2
    with pytest.raises(m.SwitchError, match="ATTEMPT_CONSUMED"):
        c.apply(c.plan())


@pytest.mark.parametrize("key,value", [
    ("account_recovery_hold", True), ("auto_order", False),
    ("account_takeover_pending", False), ("opening_enabled", True),
])
def test_destination_auto_or_pending_mismatch_never_becomes_success(setup, key, value):
    b, c, clock = setup
    auto_backend(b, c)
    original = b.readback
    b.readback = lambda snapshot: {**original(snapshot), key: value}
    with pytest.raises(m.SwitchError, match="READBACK_UNPROVEN"):
        c.apply(c.plan())
    assert json.loads(c.intent.read_bytes())["result"] == "UNKNOWN"


def test_approval_transition_drift_after_plan_stops_before_sigterm(setup):
    b, c, clock = setup
    auto_backend(b, c)
    plan = c.plan()
    b.value["preimage"]["auto_order_transition"]["target_hold"] = True
    with pytest.raises(m.SwitchError):
        c.apply(plan)
    assert b.calls == [] and not c.intent.exists()


def test_real_supervisor_close_rollover_can_transfer_waiting_pending_source(
    tmp_path, held_preimage, monkeypatch
):
    from datetime import date
    from types import SimpleNamespace as NS
    from test_trade_end_to_end import seeded_account, Driver
    from guiyi_quant.simnow_execution.supervisor import Supervisor
    from guiyi_quant.simnow_execution.credentials import CredentialStore
    from guiyi_quant import htdy_account_execution as a

    monkeypatch.setattr(CredentialStore, "load", lambda *_: pytest.fail("Keychain accessed"))
    settings, folder, clock, market = seeded_account(tmp_path)
    settings.account_recovery_hold = True
    settings.account_takeover_pending = True
    captured = []
    drivers = []

    def factory(settings, folder):
        driver = Driver(settings, folder, clock)
        drivers.append(driver)
        return driver

    def sleep(seconds):
        value = json.loads((folder / "continuous.json").read_bytes())
        captured.append(value)
        if len(captured) == 1:
            assert value["status"] == "ACCOUNT_RECOVERED_HELD", value["status"]
            assert value["account_takeover_pending"] is False
            market.plan = lambda now: NS(trading_day=date(2026, 10, 28),
                                         active=False, connect_allowed=False)
        clock.sleep(seconds)

    supervisor = Supervisor(settings, ("RB", "JM"), market, factory,
                            clock=clock.now, sleep=sleep)
    supervisor.stopped = lambda: len(captured) >= 2
    supervisor.run(max_cycles=5)
    waiting = captured[1]
    assert waiting["status"] == "WAITING_SESSION"
    assert waiting["account_takeover_pending"] is True
    assert waiting["account_recovery_hold"] is True
    assert waiting["auto_order"] is waiting["opening_enabled"] is False
    assert len(drivers) == 1
    state = a.LocalStore.inspect(folder / "account.sqlite")
    assert not state.orders and not state.fills and not state.positions
    b = held_preimage
    enable_candidate(b)
    b._preimage()
    b.folder = folder
    assert b._source_hold(waiting) is True
    (folder / ("failure-" + waiting["run_id"] + "-0.json")).write_text("{}")
    with pytest.raises(m.SwitchError, match="HOST_UNPROVEN"):
        b._source_hold(waiting)


def test_source_failure_scan_unreadable_is_not_treated_as_empty(held_preimage, monkeypatch):
    b = held_preimage
    enable_candidate(b)
    b._preimage()
    def unreadable(path):
        raise OSError("fixture directory unavailable")
    monkeypatch.setattr(m.os, "scandir", unreadable)
    with pytest.raises(m.SwitchError, match="HOST_UNPROVEN"):
        b._source_hold(source_control())


def test_actual_unreadable_source_directory_never_authorizes_transition(held_preimage):
    b = held_preimage
    enable_candidate(b)
    b._preimage()
    (b.folder / ("failure-" + "1" * 32 + "-1.json")).write_text("{}")
    b.folder.chmod(0)
    try:
        with pytest.raises(m.SwitchError, match="HOST_UNPROVEN"):
            b._source_hold(source_control())
    finally:
        b.folder.chmod(0o700)
