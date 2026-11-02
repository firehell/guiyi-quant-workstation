"""Exercise the real inherited offline account reader, not a fake backend."""

import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace as NS
import pytest
from test_trade_switch import real_account as account_fixture, m

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "preparation_native_test", ROOT / "scripts/ops/macos/simnow-preparation-recovery.py"
)
controller = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(controller)


def test_terminal_history_is_preserved_but_open_obligations_are_rejected():
    state = NS(
        orders=(NS(reconciled=True, status="LOCAL_ABORTED"),),
        fills=(),
        positions=(),
        reservations=(NS(released=True),),
        unresolved_fill_ids=(),
    )
    assert controller.obligations_clear(state)
    state.orders[0].reconciled = False
    assert not controller.obligations_clear(state)
    state.orders[0].reconciled = True
    state.reservations[0].released = False
    assert not controller.obligations_clear(state)


def test_real_inherited_stopped_account_contract_receives_trade_mode(
    tmp_path, monkeypatch
):
    e = account_fixture.__wrapped__(tmp_path, monkeypatch)
    e.settings.account_takeover_pending = True
    b = controller.backend_type(m).__new__(controller.backend_type(m))
    b.__dict__.update(e.b.__dict__)
    # This reader-only fixture uses the inherited historical-day branch; no PG/Broker.
    b.ordinary = False
    account = b._account()
    snapshot = copy.deepcopy(e.plan["snapshot"])
    snapshot["host"] = controller.host_fact(
        snapshot["host"]["pid"], "run-fixture", "fixture-command"
    )
    snapshot["account"] = account
    snapshot["preimage"]["account"] = account
    e.stop()
    for path in (e.folder / "continuous.json", e.settings.state_root / "monitor.json"):
        value = json.loads(path.read_text())
        value["mode"] = "trade"
        path.write_text(json.dumps(value))
    with b.offline_guard(snapshot):
        proof = b.offline_preflight(snapshot)
    assert proof["protected_state_unchanged"] and proof["native_appended_count"] == 0
    assert snapshot["host"]["mode"] == "trade"


@pytest.mark.parametrize("field", ["CurrMargin", "FrozenMargin", "FrozenCommission"])
def test_empty_position_with_encumbered_funds_is_not_recovery_permission(field):
    data = {
        "positions": [],
        "orders": [],
        "trades": [],
        "funds": [dict(CurrMargin="0", FrozenMargin="0", FrozenCommission="0")],
    }
    inventory = NS(account_id="a" * 64, trading_day=controller.DAY, data=data)
    assert controller.diagnostic_inventory_clear(inventory, "a" * 64)
    data["funds"][0][field] = "1"
    assert not controller.diagnostic_inventory_clear(inventory, "a" * 64)
