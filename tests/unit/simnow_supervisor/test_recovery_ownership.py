"""Claimed offline fill ownership must precede real Host fee reconciliation."""

from datetime import timedelta
from decimal import Decimal
from pathlib import Path
import importlib.util
import sys

import pytest

from guiyi_quant.simnow_execution.inventory import read_snapshot
from guiyi_quant.simnow_execution.supervisor import verify_recovery_ownership


HOST_DIR = Path(__file__).parents[1] / "simnow_host"
sys.path.insert(0, str(HOST_DIR))
try:
    SPEC = importlib.util.spec_from_file_location(
        "isolated_simnow_host_fixture", HOST_DIR / "test_host.py"
    )
    assert SPEC and SPEC.loader
    host_fixture = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(host_fixture)
finally:
    sys.path.pop(0)


def test_claimed_offline_fill_passes_ownership_then_real_fee_reconciliation(tmp_path):
    host, adapter, effect, _, binding, at, api = host_fixture.host_setup(tmp_path)
    report = host_fixture.filled_report(adapter, effect, at)
    snapshot = read_snapshot(report)
    state_before = adapter.store.current()
    assert state_before.fills == ()
    verify_recovery_ownership(snapshot, (binding,), adapter.journal, state_before)

    accepted, state = host.reconcile(report, (binding,), at + timedelta(seconds=20))
    assert state is not None and state.readback_valid and state.phase == "READY"
    assert state.fills[0].fee == Decimal("3.12")
    assert state.positions[0].quantity == 1
    assert state.orders[0].reconciled and state.reservations[0].released
    assert host.summary(accepted)["performance"]["net_profit"] == "-3.12"
    assert len(api.calls) == 1


def test_unknown_native_order_fails_ownership_before_recovery(tmp_path):
    host, adapter, effect, _, binding, at, _ = host_fixture.host_setup(tmp_path)
    report = host_fixture.filled_report(adapter, effect, at)
    row = dict(report["rounds"][0]["queries"]["orders"]["rows"][0])
    row["OrderRef"] = "unknown-ref"
    altered = host_fixture.changed(report, "orders", [row])
    snapshot = read_snapshot(altered)
    with pytest.raises(ValueError):
        verify_recovery_ownership(
            snapshot, (binding,), adapter.journal, adapter.store.current()
        )
    assert adapter.store.current().fills == ()


def test_unlinked_native_trade_fails_ownership_before_recovery(tmp_path):
    host, adapter, effect, _, binding, at, _ = host_fixture.host_setup(tmp_path)
    report = host_fixture.filled_report(adapter, effect, at)
    row = dict(report["rounds"][0]["queries"]["trades"]["rows"][0])
    row["OrderSysID"] = "unknown-system"
    altered = host_fixture.changed(report, "trades", [row])
    snapshot = read_snapshot(altered)
    with pytest.raises(ValueError):
        verify_recovery_ownership(
            snapshot, (binding,), adapter.journal, adapter.store.current()
        )
    assert adapter.store.current().fills == ()
