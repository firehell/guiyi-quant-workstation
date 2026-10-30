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
        now = T + timedelta(seconds=9)
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


def rb_book():
    return dict(InstrumentID="rb2701", ExchangeID="SHFE", TradingDay="20261027",
                ActionDay="20261027", UpdateTime="09:00:00", UpdateMillisec=0,
                BidPrice1=999, AskPrice1=1000, BidVolume1=1, AskVolume1=2,
                LowerLimitPrice=900, UpperLimitPrice=1100)


def rb_binding():
    from guiyi_quant.simnow_execution.model import Contract
    return Contract("RB2701", "rb2701", "SHFE", "fixture-binding", T, T+timedelta(minutes=5))


def test_complete_batch_selects_exact_book_not_first_record():
    from guiyi_quant.simnow_execution.facts import quote_from_native_batch
    rows = [dict(rb_book(), InstrumentID=f"other{i}") for i in range(32)]
    rows.insert(17, rb_book())
    q = quote_from_native_batch(rb_binding(), rows, "20261027", T)
    assert q.contract == "RB2701" and q.bid == 999 and q.ask == 1000


@pytest.mark.parametrize("rows,code", [
    ([], "NATIVE_BOOK_TARGET_MISSING"),
    ([dict(rb_book(), InstrumentID="rb2705")], "NATIVE_BOOK_TARGET_MISSING"),
    ([dict(rb_book(), ExchangeID="DCE")], "NATIVE_BOOK_TARGET_MISSING"),
    ([rb_book(), rb_book()], "NATIVE_BOOK_TARGET_AMBIGUOUS"),
])
def test_batch_book_missing_or_duplicate_never_falls_back(rows, code):
    from guiyi_quant.simnow_execution.facts import quote_from_native_batch
    with pytest.raises(ValueError, match=code):
        quote_from_native_batch(rb_binding(), rows, "20261027", T)


@pytest.mark.parametrize("change,now", [
    ({"TradingDay":"20261026"}, T),
    ({}, T+timedelta(seconds=9)),
    ({}, T-timedelta(seconds=1)),
    ({"AskPrice1":1.7976931348623157e308}, T),
    ({"AskPrice1":998}, T),
])
def test_selected_batch_quote_retains_identity_price_and_time_checks(change, now):
    from guiyi_quant.simnow_execution.facts import quote_from_native_batch
    with pytest.raises(ValueError):
        quote_from_native_batch(rb_binding(), [dict(rb_book(), **change)], "20261027", now)


@pytest.mark.parametrize("age,accepted", [(5.922269, True), (8, True), (8.000001, False), (-0.000001, False)])
def test_owner_eight_second_source_age_limit(age, accepted):
    from guiyi_quant.simnow_execution.facts import quote_from_native_batch
    now = T + timedelta(seconds=age)
    if accepted:
        quote = quote_from_native_batch(rb_binding(), [rb_book()], "20261027", now)
        assert quote.valid_until == now + timedelta(seconds=3)
    else:
        with pytest.raises(ValueError, match="NATIVE_BOOK_STALE"):
            quote_from_native_batch(rb_binding(), [rb_book()], "20261027", now)


def test_shared_quote_keeps_absolute_source_deadline_after_batch_receive():
    from guiyi_quant.simnow_execution.facts import execution_quote_from_native_batch
    received = T + timedelta(seconds=7, milliseconds=500)
    quote = execution_quote_from_native_batch(rb_binding(), [rb_book()], '20261027', received)
    assert quote.valid_until == T + timedelta(seconds=8)
    raw = quote_from_native(rb_binding(), rb_book(), '20261027', received)
    assert quote.source_id == raw.source_id  # Existing source identity bytes stay intact.


def test_exact_eight_second_raw_receipt_has_no_remaining_execution_lifetime():
    from guiyi_quant.simnow_execution.facts import (
        quote_from_native_batch, execution_quote_from_native_batch,
    )
    received = T + timedelta(seconds=8)
    raw = quote_from_native_batch(rb_binding(), [rb_book()], '20261027', received)
    assert raw.at == received
    with pytest.raises(ValueError, match='NATIVE_BOOK_STALE'):
        execution_quote_from_native_batch(rb_binding(), [rb_book()], '20261027', received)
