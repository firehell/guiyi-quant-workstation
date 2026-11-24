"""Offline P1-B tests. Use the sandbox invocation in gateway_smoke.py."""

import pytest

from gateway_smoke import (
    capture_gateway_callbacks,
    import_ctp,
    import_portfolio_strategy,
    require_offline,
)


@pytest.fixture(scope="module")
def callbacks():
    require_offline()
    try:
        import_ctp()
    except ModuleNotFoundError as exc:
        if exc.name == "vnpy_ctp":
            pytest.skip("locked vnpy_ctp absent; native install must pass first")
        raise
    return capture_gateway_callbacks()


def test_requires_isolated_home_before_import(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    with pytest.raises(RuntimeError, match="private temporary HOME"):
        require_offline()


def test_portfolio_strategy_loads_independently_under_network_denial():
    require_offline()
    app = import_portfolio_strategy()
    assert app.app_name == "PortfolioStrategy"


def test_contract_and_tick_are_emitted_before_execution_events(callbacks):
    assert [kind for kind, _ in callbacks] == [
        "contract", "tick", "order", "trade", "trade", "trade", "order",
        "account", "position",
    ]

    contract = callbacks[0][1]
    assert contract.vt_symbol == "rb9911.SHFE"
    assert contract.gateway_name == "CTP_FIXTURE"
    assert contract.product.name == "FUTURES"
    assert (contract.size, contract.pricetick, contract.min_volume) == (10, 0.5, 1)

    tick = callbacks[1][1]
    assert tick.vt_symbol == "rb9911.SHFE"
    assert tick.gateway_name == "CTP_FIXTURE"
    assert tick.datetime.isoformat() == "2026-11-24T09:30:01.125000+08:00"
    assert (tick.last_price, tick.volume, tick.open_interest) == (103.5, 154, 220)
    assert (tick.bid_price_1, tick.ask_price_1) == (103, 104)


def test_order_status_and_trade_ids_preserve_duplicate_and_distinct_fills(callbacks):
    partial, cancelled = [data for kind, data in callbacks if kind == "order"]
    assert partial.vt_orderid == cancelled.vt_orderid == "CTP_FIXTURE.7_13_000042"
    assert partial.orderid == cancelled.orderid == "7_13_000042"
    assert (partial.status.name, cancelled.status.name) == ("PARTTRADED", "CANCELLED")
    for order in (partial, cancelled):
        assert (order.vt_symbol, order.type.name) == ("rb9911.SHFE", "LIMIT")
        assert (order.direction.name, order.offset.name) == ("SHORT", "CLOSETODAY")
        assert (order.price, order.volume, order.traded) == (103.5, 3, 2)

    trades = [data for kind, data in callbacks if kind == "trade"]
    assert [trade.tradeid for trade in trades] == ["000101", "000101", "000102"]
    assert [trade.vt_tradeid for trade in trades] == [
        "CTP_FIXTURE.000101", "CTP_FIXTURE.000101", "CTP_FIXTURE.000102",
    ]
    for trade in trades:
        assert trade.vt_orderid == "CTP_FIXTURE.7_13_000042"
        assert (trade.vt_symbol, trade.gateway_name) == ("rb9911.SHFE", "CTP_FIXTURE")
        assert (trade.direction.name, trade.offset.name) == ("SHORT", "CLOSETODAY")
        assert (trade.price, trade.volume) == (103.5, 1)
        assert trade.datetime.isoformat() == "2026-11-24T09:30:03+08:00"


def test_account_and_remaining_long_position_fields_are_delivered(callbacks):
    account, position = [data for kind, data in callbacks if kind in {"account", "position"}]
    assert (account.accountid, account.vt_accountid) == ("FIXTURE", "CTP_FIXTURE.FIXTURE")
    assert (account.balance, account.frozen, account.available) == (1000, 0, 900)
    assert position.vt_symbol == "rb9911.SHFE"
    assert position.gateway_name == "CTP_FIXTURE"
    assert position.direction.name == "LONG"
    assert (position.volume, position.yd_volume, position.frozen) == (1, 0, 0)
    assert (position.price, position.pnl) == (99, 45)
