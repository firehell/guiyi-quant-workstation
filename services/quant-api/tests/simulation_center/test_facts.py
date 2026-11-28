from datetime import UTC, datetime

import pytest

from app.simulation_center.facts import normalize
from app.simulation_center.readback import Readback, ReadbackError


def sample():
    return {
        "account": [{"AccountID": "INV", "BrokerID": "9999", "TradingDay": "20261130",
                     "Balance": 100.01, "Available": 80, "CurrMargin": 20,
                     "Deposit": 0, "Withdraw": 0, "CurrencyID": "CNY"}],
        "positions": [],
        "orders": [{"InvestorID": "INV", "BrokerID": "9999", "TradingDay": "20261130",
                    "ExchangeID": "SHFE", "InstrumentID": "rb2701", "Direction": "0",
                    "CombOffsetFlag": "0", "OrderSysID": "  100", "OrderStatus": "0",
                    "VolumeTotalOriginal": 1, "VolumeTraded": 1, "LimitPrice": 3201.5,
                    "FrontID": 1, "SessionID": 2, "OrderRef": "1"}],
        "fills": [{"InvestorID": "INV", "BrokerID": "9999", "TradingDay": "20261130",
                   "ExchangeID": "SHFE", "InstrumentID": "rb2701", "Direction": "0",
                   "OffsetFlag": "0", "OrderSysID": "100", "TradeID": "123",
                   "Volume": 1, "Price": 3201.5, "TradeDate": "20261127", "TradeTime": "21:00:04"}],
    }


def test_cabinet_origin_preserves_decimal_and_trading_day():
    result = normalize(sample(), "INV", "20261130")
    assert result["account"]["equity"] == "100.01"
    assert result["positions"] == []
    assert result["fills"][0]["id"] == "2026-11-30:SHFE:123"
    assert result["fills"][0]["order_id"] == result["orders"][0]["id"]
    assert result["fills"][0]["occurred_at"] == "2026-11-27T21:00:04+08:00"
    assert result["fills"][0]["fee"] is None
    assert "INV" not in str(result)


@pytest.mark.parametrize("change", ["day", "unknown_order", "account", "quantity", "duplicate"])
def test_conflicting_readbacks_cannot_be_published(change):
    rows = sample()
    fill = rows["fills"][0]
    if change == "duplicate":
        rows["fills"].append(fill)
    else:
        field, value = {
            "day": ("TradingDay", "20261127"), "unknown_order": ("OrderSysID", "101"),
            "account": ("InvestorID", "OTHER"), "quantity": ("Volume", 2),
        }[change]
        fill[field] = value
    with pytest.raises(ReadbackError):
        normalize(rows, "INV", "20261130")


def now():
    return datetime(2026, 11, 27, 13, 1, tzinfo=UTC)


def test_terminal_and_identity_fences():
    state = Readback()
    state.login(1, "20261130")
    state.begin(now())
    state.request("account", 11)
    assert not state.reply("account", 10, {}, 0, True)
    assert not state.reply("account", 11, sample()["account"][0], 0, False)
    assert state.reply("account", 11, {}, 0, True)
    for request, kind in enumerate(("positions", "orders", "fills"), 12):
        state.request(kind, request)
        assert state.reply(kind, request, {}, 0, True)
    assert state.complete("INV", now())["positions"] == []
    state.begin(now())
    state.request("account", 15)
    state.changed()
    with pytest.raises(ReadbackError, match="READBACK_CHANGED"):
        state.reply("account", 15, {}, 0, True)


def test_failure_and_relogin_discard_partial_readback():
    state = Readback()
    state.login(1, "20261130")
    state.begin(now())
    state.request("account", 11)
    with pytest.raises(ReadbackError, match="NATIVE_QUERY_FAILED"):
        state.reply("account", 11, {}, 13, False)
    state.disconnect()
    assert not state.reply("account", 11, {}, 0, True)
    with pytest.raises(ReadbackError, match="NOT_LOGGED_IN"):
        state.begin(now())
    state.login(2, "20261201")
    state.begin(now())
    with pytest.raises(ReadbackError, match="READBACK_INCOMPLETE"):
        state.complete("INV", now())


def test_full_order_cannot_have_zero_fills():
    rows = sample()
    rows["orders"][0]["VolumeTraded"] = 0
    rows["fills"] = []
    with pytest.raises(ReadbackError):
        normalize(rows, "INV", "20261130")


def test_order_without_exchange_id_and_without_fills_can_be_retained():
    rows = sample()
    rows["orders"][0].update(OrderSysID="", OrderStatus="4", VolumeTraded=0)
    rows["fills"] = []
    assert normalize(rows, "INV", "20261130")["orders"][0]["system_id"] is None
