"""Manual acceptance records are identified from the durable audit, not a name pattern."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from guiyi_quant import htdy_account_execution as a, htdy_execution as h
from guiyi_quant.simnow_execution.monitor_projection import all_records


T = datetime(2026, 10, 27, 1, tzinfo=UTC)
TEST_ID = "manual:00000000-0000-4000-8000-000000000001"


def _step(state, command):
    return a.apply(state, f"monitor:{len(state.receipts)}", command)


def _state():
    snapshot = h.AccountSnapshot(
        "account", T, Decimal("100000"), Decimal("100000"), (), (), ()
    )
    readback = a.Readback(
        snapshot,
        Decimal(0),
        Decimal(0),
        Decimal(0),
        (),
        (),
        "native:initial",
        T + timedelta(hours=4),
        True,
    )
    state = a.start("account", ("RB",), T, readback)
    return _step(state, h.Owner("RB", "RB2701", T, "owner:RB")).state


def _facts(at):
    return a.ExecutionInput(
        a.Instrument(
            "RB",
            "RB2701",
            T,
            T + timedelta(hours=3),
            "instrument",
            Decimal(1),
            Decimal(10),
            Decimal("0.1"),
            Decimal("0.1"),
            Decimal(3),
        ),
        a.Session(
            "RB2701",
            T,
            T + timedelta(hours=3),
            "session",
            T + timedelta(hours=3),
            True,
            True,
        ),
        a.Quote(
            "RB2701",
            at,
            at + timedelta(seconds=10),
            "quote",
            Decimal(999),
            Decimal(1000),
            1,
            1,
            Decimal(1),
            Decimal(100000),
        ),
    )


def _records(state):
    return all_records({"state": state, "actions": []})


def test_manual_origin_requires_audited_begin_and_keeps_strategy_records_plain():
    state = _state()
    state = _step(
        state,
        a.ManualBeginV1(
            TEST_ID, "RB", "RB2701", T + timedelta(seconds=1), T + timedelta(minutes=2)
        ),
    ).state
    opened = _step(
        state,
        a.ManualTickV1(
            T + timedelta(seconds=2), (_facts(T + timedelta(seconds=2)),), TEST_ID
        ),
    )
    order = opened.effects[0].order
    fill = a.NativeFill(
        "native-fill",
        order.order_id,
        "account",
        "RB2701",
        T + timedelta(seconds=3),
        T + timedelta(seconds=4),
        order.price,
        Decimal(3),
        1,
        order.created_at + timedelta(seconds=1),
        "dispatch:open",
        "system:fill",
    )
    manual = _step(opened.state, fill).state
    manual_rows = _records(manual)
    assert {r["kind"] for r in manual_rows} == {"risk", "order", "fill"}
    assert all(r["signal_id"] == TEST_ID for r in manual_rows)
    assert all(r["label"].startswith("人工验收·") for r in manual_rows)
    assert all(r["facts"]["origin"] == "人工验收交易" for r in manual_rows)
    assert manual.signals == ()

    signal_at = T + timedelta(minutes=60)
    signal = h.Signal(
        "strategy:RB",
        "RB",
        "RB2701",
        signal_at,
        signal_at + timedelta(seconds=2),
        None,
        ("buy",),
        "a" * 64,
    )
    strategy = _step(_state(), signal).state
    strategy = _step(
        strategy,
        a.Tick(
            signal_at + timedelta(minutes=1),
            (_facts(signal_at + timedelta(minutes=1)),),
        ),
    ).state
    strategy_rows = _records(strategy)
    assert {r["kind"] for r in strategy_rows} == {"signal", "risk", "order"}
    assert all(not r["label"].startswith("人工验收·") for r in strategy_rows)
    assert all("origin" not in r["facts"] for r in strategy_rows)


def test_manual_looking_signal_id_without_begin_is_not_labelled():
    from dataclasses import replace

    state = _state()
    order = a.Order(
        "test-order",
        "RB",
        "RB2701",
        "BUY",
        "OPEN",
        TEST_ID,
        T + timedelta(seconds=1),
        Decimal(1000),
        "instrument",
        "quote",
        "session",
    )
    rows = _records(replace(state, orders=(order,)))
    assert len(rows) == 1 and rows[0]["kind"] == "order"
    assert rows[0]["label"] == "待提交"
    assert "origin" not in rows[0]["facts"]
