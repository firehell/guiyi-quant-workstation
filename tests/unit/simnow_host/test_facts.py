from datetime import timedelta
import pytest
from test_inventory import T
from guiyi_quant.simnow_execution.facts import bind_contract, quote_from_native


def native():
    return dict(
        InstrumentID="SR701",
        ExchangeID="CZCE",
        ProductID="SR",
        ProductClass="1",
        DeliveryYear=2027,
        DeliveryMonth=1,
        OpenDate="20260101",
        ExpireDate="20270110",
        StartDelivDate="20270115",
        IsTrading=1,
        MinLimitOrderVolume=1,
        MaxLimitOrderVolume=100,
    )


def test_czce_native_month_is_bound_by_explicit_delivery_year():
    binding, _ = bind_contract(
        "SR2701", "CZCE", (native(),), T, T + timedelta(hours=1), "20261027"
    )
    assert binding.native == "SR701"
    wrong = native()
    wrong["DeliveryYear"] = 2037
    with pytest.raises(ValueError):
        bind_contract("SR2701", "CZCE", (wrong,), T, T + timedelta(hours=1), "20261027")


@pytest.mark.parametrize(
    "field,value",
    [
        ("IsTrading", 0),
        ("MinLimitOrderVolume", 2),
        ("ProductClass", "2"),
        ("StartDelivDate", "20261026"),
    ],
)
def test_unqualified_instrument_is_not_a_one_lot_future(field, value):
    row = native()
    row[field] = value
    with pytest.raises(ValueError):
        bind_contract("SR2701", "CZCE", (row,), T, T + timedelta(hours=1), "20261027")


@pytest.mark.parametrize(
    "issue", ["stale", "wrong_day", "missing_action_day", "sentinel", "zero_volume"]
)
def test_native_book_is_not_promoted_to_fresh_execution_input(issue):
    binding, _ = bind_contract(
        "SR2701", "CZCE", (native(),), T, T + timedelta(hours=1), "20261027"
    )
    row = dict(
        InstrumentID="SR701",
        ExchangeID="CZCE",
        TradingDay="20261027",
        ActionDay="20261027",
        UpdateTime="09:00:00",
        UpdateMillisec=0,
        BidPrice1=1000,
        AskPrice1=1001,
        BidVolume1=1,
        AskVolume1=1,
        LowerLimitPrice=900,
        UpperLimitPrice=1100,
    )
    now = T
    if issue == "stale":
        now = T + timedelta(seconds=6)
    elif issue == "wrong_day":
        row["TradingDay"] = "20261026"
    elif issue == "missing_action_day":
        row["ActionDay"] = ""
    elif issue == "sentinel":
        row["AskPrice1"] = 1.7976931348623157e308
    else:
        row["AskVolume1"] = -1
    with pytest.raises(ValueError):
        quote_from_native(binding, row, "20261027", now)


@pytest.mark.parametrize("product,exchange,expected", [
    ("RB", "SHFE", "rb"), ("SR", "CZCE", "SR"), ("IF", "CFFEX", "IF"),
    ("I", "DCE", "i"), ("SC", "INE", "sc"), ("SI", "GFEX", "si"),
])
def test_native_product_query_scope(product, exchange, expected):
    from guiyi_quant.simnow_execution.facts import native_product_id
    assert native_product_id(product, exchange) == expected


@pytest.mark.parametrize("product,exchange", [("rb", "SHFE"), ("RB", "UNKNOWN"), ("RB2701", "SHFE")])
def test_native_product_scope_invalid_fails_closed(product, exchange):
    from guiyi_quant.simnow_execution.facts import native_product_id
    with pytest.raises(ValueError):
        native_product_id(product, exchange)
