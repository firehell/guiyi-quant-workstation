"""Synthetic cabinet evidence with real reducer, VeighNa conversion and PostgreSQL."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
import os
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from app.simulation_center.store import connect
from app.simulation_center.execution_store import ExecutionStore
from guiyi_quant import htdy_account_execution as account, htdy_execution as htdy
from guiyi_quant.simnow_execution.model import Contract
from simulation_execution import CabinetProof, ExecutionSession, FeeEvidence, OfflineExecution, RehearsalError, SOURCE

T = datetime(2026, 11, 30, 1, tzinfo=UTC)
BAR = T + timedelta(hours=1)
OWNER = "RB2701"
DAY = "20261130"
SESSION = ExecutionSession(T.date(), 1, -2, 30)
CHINA = ZoneInfo("Asia/Shanghai")


def book(equity="100000", available=None, margin="0", *, positions=(), orders=(), fills=()):
    return {
        "account": [{"BrokerID": "9999", "AccountID": "OFFLINE", "TradingDay": DAY, "CurrencyID": "CNY",
                     "Balance": equity, "Available": available or equity, "CurrMargin": margin,
                     "FrozenMargin": "0", "FrozenCommission": "0", "Deposit": "0", "Withdraw": "0"}],
        "positions": list(positions), "orders": list(orders), "fills": list(fills),
    }


def checked(at, rows=None, *, session=SESSION):
    rows = rows or book()
    return CabinetProof.compare(session, rows, rows, at - timedelta(seconds=2), at)


def signal(bar=BAR, *, side="buy", previous=None):
    return htdy.Signal("fixture:" + bar.isoformat(), "RB", OWNER, bar, bar + timedelta(seconds=2),
                       previous, (side,), "ab" * 32)


def market(at):
    until = at + timedelta(seconds=30)
    return account.ExecutionInput(
        account.Instrument("RB", OWNER, at, until, "fixture-instrument", D("1"), D("10"), D(".10"), D(".10"), D("2")),
        account.Session(OWNER, at, until, "fixture-session", at + timedelta(minutes=20), True, True),
        account.Quote(OWNER, at, until, "fixture-quote:" + at.isoformat(), D("3200"), D("3201"), 2, 2, D("3000"), D("3400")),
    )


@pytest.fixture
def exercise():
    dsn = os.environ.get("GUIYI_SIMULATION_ISOLATED_TEST_DSN")
    if not dsn:
        pytest.skip("requires separate offline exercise PostgreSQL")
    with connect(dsn) as database:
        store = ExecutionStore(database, uuid4().hex)
        binding = Contract(OWNER, "rb2701", "SHFE", "fixture-physical-binding", T, T + timedelta(hours=5))
        yield OfflineExecution(store, (binding,)), store


def open_order(execution, *, balance="100000"):
    execution.create(("RB",), checked(T, book(balance)))
    execution.owner(htdy.Owner("RB", OWNER, T, "fixture-rank1"))
    execution.signal(signal())
    at = BAR + timedelta(seconds=5)
    proof = checked(at, book(balance))
    execution.reconcile(proof)
    return execution.tick("open", at, (market(at),)), proof, at


def native_order(action, *, status="3", traded=0):
    data = action.request
    _, _, front, session, ref = action.cabinet_id.split(":")
    return {"BrokerID": "9999", "InvestorID": "OFFLINE", "TradingDay": DAY, "ExchangeID": "SHFE",
            "InstrumentID": "rb2701", "Direction": "0" if data.direction.name == "LONG" else "1",
            "CombOffsetFlag": {"OPEN": "0", "CLOSE": "1", "CLOSETODAY": "3", "CLOSEYESTERDAY": "4"}[data.offset.name],
            "OrderSysID": "SYS" + ref, "OrderStatus": status, "VolumeTraded": traded,
            "VolumeTotalOriginal": 1, "LimitPrice": data.price, "FrontID": int(front),
            "SessionID": int(session), "OrderRef": ref}


def native_fill(order, at, name):
    calendar = at.astimezone(CHINA)
    return {"BrokerID": "9999", "InvestorID": "OFFLINE", "TradingDay": DAY, "ExchangeID": "SHFE",
            "InstrumentID": "rb2701", "Direction": order["Direction"], "OffsetFlag": order["CombOffsetFlag"],
            "OrderSysID": order["OrderSysID"], "TradeID": name, "Volume": 1, "Price": order["LimitPrice"],
            "TradeDate": calendar.strftime("%Y%m%d"), "TradeTime": calendar.strftime("%H:%M:%S")}


def position(today=1):
    return {"BrokerID": "9999", "InvestorID": "OFFLINE", "TradingDay": DAY, "ExchangeID": "SHFE",
            "InstrumentID": "rb2701", "PosiDirection": "2", "Position": 1, "TodayPosition": today,
            "PositionDate": "1" if today else "2", "ShortFrozen": 0, "LongFrozen": 0, "HedgeFlag": "1",
            "PositionProfit": "0"}


def test_readback_requires_stable_funds_and_four_sections():
    with pytest.raises(RehearsalError, match="OFFLINE_ROUNDS_DIFFER"):
        CabinetProof.compare(SESSION, book(), book("99999"), T, T + timedelta(seconds=2))
    with pytest.raises(RehearsalError, match="OFFLINE_SECTIONS_INCOMPLETE"):
        CabinetProof.compare(SESSION, book(), {"account": book()["account"]}, T, T + timedelta(seconds=2))


def test_margin_rejection_is_replayed_with_no_native_request(exercise):
    execution, store = exercise
    effects, _, _ = open_order(execution, balance="100")
    assert not effects and not store.claims()
    risk = store.replay().risk_decisions
    assert len(risk) == 1 and risk[0].approved is False
    assert risk[0].margin == D("3201")


@pytest.mark.parametrize("today, expected", [(1, "CLOSETODAY"), (0, "CLOSEYESTERDAY")])
def test_fixed_one_lot_reverse_and_explicit_fill_proof(exercise, today, expected):
    execution, store = exercise
    (effect,), proof, at = open_order(execution)
    first = execution.prepare(effect, proof, at)
    assert first.request.volume == 1 and first.request.offset.name == "OPEN"
    assert first.cabinet_id == "2026-11-30:SHFE:1:-2:31"
    assert execution.prepare(effect, proof, at) is None
    assert not store.current().positions
    original = market(at)
    spoofed = replace(original, instrument=replace(original.instrument, multiplier=D("999")))
    assert not execution.tick("reused-source-label", at, (spoofed,))

    opened = native_order(first, status="0", traded=1)
    fill = native_fill(opened, at + timedelta(seconds=2), "F1")
    after = book(available="96500", margin="3201", positions=(position(today),), orders=(opened,), fills=(fill,))
    first_fee = "2026-11-30:SHFE:F1"
    execution.reconcile(checked(at + timedelta(seconds=5), after), fees={first_fee: FeeEvidence(D("2"), "fixture:open-fee")})
    assert store.current().positions == (htdy.Position("RB", OWNER, 1),)
    assert store.current().reservations[0].released

    next_bar = BAR + timedelta(hours=1)
    execution.signal(signal(next_bar, side="sell", previous=BAR))
    close_at = next_bar + timedelta(seconds=6)
    close_proof = checked(close_at, after)
    execution.reconcile(close_proof)
    (close,) = execution.tick("reverse-close", close_at, (market(close_at),))
    closing = execution.prepare(close, close_proof, close_at)
    assert closing.request.offset.name == expected and closing.request.direction.name == "SHORT"
    assert closing.request.volume == 1 and closing.request.price == 3200

    closed = native_order(closing, status="0", traded=1)
    fill_close = native_fill(closed, close_at + timedelta(seconds=2), "F2")
    finish = book("99986", orders=(opened, closed), fills=(fill, fill_close))
    execution.reconcile(checked(close_at + timedelta(seconds=5), finish), fees={"2026-11-30:SHFE:F2": FeeEvidence(D("2"), "fixture:close-fee")})
    state = store.replay()
    assert not state.positions and len(state.fills) == 2
    assert all(item.reconciled for item in state.orders)
    assert len(store.claims()) == 2
    (realized,) = execution.realized_trades()
    assert (realized.gross, realized.fees, realized.net, realized.source) == (D("-10"), D("4"), D("-14"), SOURCE)
    with pytest.raises(ValueError, match="RETAINED_ORDER_REGRESSION"):
        execution.reconcile(checked(close_at + timedelta(seconds=8), book("99986")))
    assert len(store.replay().fills) == 2


def test_unproved_outcome_survives_restart_and_cannot_send_again(exercise):
    execution, store = exercise
    (effect,), proof, at = open_order(execution)
    prepared = execution.prepare(effect, proof, at)
    with pytest.raises(RehearsalError, match="ORDER_OUTCOME_MISSING"):
        execution.reconcile(checked(at + timedelta(seconds=4)))
    assert store.replay().phase == "RECOVERY_REQUIRED"
    assert not store.current().reservations[0].released
    assert store.claims()[(effect.order.order_id, "SUBMIT")]["native_id"] == prepared.cabinet_id
    assert not execution.tick("after-uncertain", at + timedelta(seconds=5), (market(at + timedelta(seconds=5)),))


def test_unknown_fees_leave_prior_fill_and_positions_unchanged(exercise):
    execution, store = exercise
    (effect,), proof, at = open_order(execution)
    action = execution.prepare(effect, proof, at)
    order = native_order(action, status="0", traded=1)
    fill = native_fill(order, at + timedelta(seconds=2), "F1")
    with pytest.raises(RehearsalError, match="OFFLINE_FILL_FEE_UNPROVEN"):
        execution.reconcile(checked(at + timedelta(seconds=5), book(
            available="96500", margin="3201", positions=(position(),), orders=(order,), fills=(fill,))))
    assert not store.replay().fills and not store.current().positions


def test_cancel_uses_confirmed_oms_identity_and_only_claims_once(exercise):
    execution, store = exercise
    (effect,), proof, at = open_order(execution)
    request = execution.prepare(effect, proof, at)
    working = native_order(request)
    view = book(orders=(working,))
    execution.reconcile(checked(at + timedelta(seconds=3), view))
    cancel_at = at + timedelta(seconds=185)
    cancel_proof = checked(cancel_at, view)
    execution.reconcile(cancel_proof)
    (cancel,) = execution.tick("aged-out", cancel_at, (market(cancel_at),))
    assert cancel.kind == "CANCEL"
    action = execution.prepare(cancel, cancel_proof, cancel_at)
    assert action.request.orderid == "1_-2_31" and action.cabinet_id == request.cabinet_id
    assert execution.prepare(cancel, cancel_proof, cancel_at) is None
    execution.reconcile(checked(cancel_at + timedelta(seconds=3), book(orders=({**working, "OrderStatus": "5"},))))
    assert store.current().reservations[0].released and store.replay().orders[0].status == "CANCELLED"
    assert all(claim["source"] == SOURCE for claim in store.claims().values())


def test_restart_cannot_replace_frozen_native_contract(exercise):
    execution, store = exercise
    execution.create(("RB",), checked(T))
    wrong = Contract(OWNER, "rb2701", "DCE", "fixture-other-native", T, T + timedelta(hours=5))
    reopened = OfflineExecution(store, (wrong,))
    with pytest.raises(ValueError, match="OFFLINE_BINDING_HASH_MISMATCH"):
        reopened.owner(htdy.Owner("RB", OWNER, T, "fixture-rank1"))
    assert store.replay().products[0].owner is None


def test_recovery_waits_for_new_completed_signal(exercise):
    execution, store = exercise
    execution.create(("RB",), checked(T))
    execution.owner(htdy.Owner("RB", OWNER, T, "fixture-rank1"))
    execution.signal(signal())
    at = BAR + timedelta(seconds=5)
    execution.disconnect("fixture-restart", at)
    next_proof = checked(at + timedelta(seconds=3), session=ExecutionSession(T.date(), 1, -3, 30))
    execution.reconcile(next_proof, recovery=(htdy.RecoveryInput("RB", OWNER, 1, BAR, "fixture:recovery"),))
    assert store.replay().phase == "READY"
    at = next_proof.observed_at + timedelta(seconds=1)
    assert not execution.tick("no-replay", at, (market(at),))


def test_fee_evidence_cannot_change_on_same_readback_retry(exercise):
    execution, store = exercise
    (effect,), proof, at = open_order(execution)
    action = execution.prepare(effect, proof, at)
    order = native_order(action, status="0", traded=1)
    fill = native_fill(order, at + timedelta(seconds=2), "F1")
    after = checked(at + timedelta(seconds=5), book(
        available="96500", margin="3201", positions=(position(),), orders=(order,), fills=(fill,)))
    trade_id = "2026-11-30:SHFE:F1"
    claimed = {trade_id: FeeEvidence(D("2"), "fixture:open-fee")}
    execution.reconcile(after, fees=claimed)
    execution.reconcile(after, fees=claimed)
    with pytest.raises(RehearsalError, match="OFFLINE_EVIDENCE_RETRY_CONFLICT"):
        execution.reconcile(after, fees={trade_id: FeeEvidence(D("5"), "fixture:correction")})
    assert store.replay().fills[0].fee == D("2")
