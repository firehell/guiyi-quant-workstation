"""Simulated CTP wire E2E; never native account evidence."""

import hashlib
import json
from datetime import datetime, UTC, timedelta
from decimal import Decimal as D
from types import SimpleNamespace
import pytest
from guiyi_quant import htdy_execution as h, htdy_account_execution as a
from guiyi_quant import simnow_execution as b

T = datetime(2026, 10, 27, 1, tzinfo=UTC)


def test_close_offset_does_not_infer_czce_month_or_net_inventory():
    binding = b.Contract(
        "RB2701", "rb2701", "SHFE", "instrument-native", T, T + timedelta(hours=1)
    )
    assert (
        b.close_offset(
            binding,
            b.Inventory("RB2701", 1, 1, 0, "positions", T, T + timedelta(minutes=1)),
            "SELL",
            T,
        )
        == "3"
    )
    assert (
        b.close_offset(
            binding,
            b.Inventory("RB2701", 1, 0, 1, "positions", T, T + timedelta(minutes=1)),
            "SELL",
            T,
        )
        == "4"
    )
    with pytest.raises(ValueError):
        b.close_offset(
            binding,
            b.Inventory("RB2701", -1, 1, 0, "positions", T, T + timedelta(minutes=1)),
            "SELL",
            T,
        )


USER = "123456"

ACCOUNT = hashlib.sha256(
    json.dumps(["SIMNOW_FIRST", "9999", USER], separators=(",", ":")).encode()
).hexdigest()


def setup(tmp_path, api=None):
    rb = a.Readback(
        h.AccountSnapshot(ACCOUNT, T, D("100000"), D("100000")),
        D(0),
        D(0),
        D(0),
        (),
        (),
        "funds-real-fixture",
        T + timedelta(hours=3),
        True,
    )
    state = a.start(ACCOUNT, ("RB",), T, rb)
    state = a.apply(state, "owner", h.Owner("RB", "RB2701", T, "owner")).state
    store = a.LocalStore(tmp_path / "account.db", state)
    at = T + timedelta(minutes=61)
    store.execute(
        "signal",
        h.Signal(
            "signal",
            "RB",
            "RB2701",
            T + timedelta(minutes=60),
            T + timedelta(minutes=60, seconds=2),
            None,
            ("buy",),
            "a" * 64,
        ),
    )
    facts = a.ExecutionInput(
        a.Instrument(
            "RB",
            "RB2701",
            T,
            T + timedelta(hours=3),
            "instrument",
            D(1),
            D(10),
            D(".1"),
            D(".1"),
            D(3),
        ),
        a.Session(
            "RB2701",
            T,
            T + timedelta(hours=3),
            "session",
            T + timedelta(hours=6),
            True,
            True,
        ),
        a.Quote(
            "RB2701",
            at,
            at + timedelta(seconds=10),
            "quote",
            D(999),
            D(1000),
            3,
            3,
            D(900),
            D(1100),
        ),
    )
    effect = store.execute("tick", a.Tick(at, (facts,))).effects[0]
    session = b.Session(
        ACCOUNT,
        "SIMNOW_FIRST",
        "tcp://182.254.243.31:30001",
        "20261027",
        1,
        2,
        10,
        "native-login",
        "native-settlement-confirm",
        T,
        T + timedelta(hours=3),
    )
    binding = b.Contract(
        "RB2701", "rb2701", "SHFE", "native-instrument", T, T + timedelta(hours=3)
    )
    journal = b.Journal(tmp_path / "dispatch.db", ACCOUNT)
    api = api or FakeApi()
    sdk = SimpleNamespace(
        CThostFtdcInputOrderField=SimpleNamespace,
        CThostFtdcInputOrderActionField=SimpleNamespace,
    )
    adapter = b.Adapter(store, journal, sdk, api, USER, session)
    permit = b.Permit(
        "owner-intent",
        ACCOUNT,
        "20261027",
        b.action_hash(store.current(), effect, session, binding, None, facts),
        at,
        at + timedelta(seconds=5),
    )
    return adapter, effect, facts, binding, permit, at, api


class FakeApi:
    def __init__(self):
        self.calls = []
        self.error = False
        self.callback = None

    def ReqOrderInsert(self, req, rid):
        self.calls.append(("insert", req, rid))
        if self.callback:
            self.callback(req)
        if self.error:
            raise RuntimeError("hidden-raw-error-never-logged")
        return 0

    def ReqOrderAction(self, req, rid):
        self.calls.append(("cancel", req, rid))
        return 0


def row(adapter, effect, at, status="3", submit="3"):
    binding = adapter.journal.find(effect.order.order_id)
    native = at.astimezone(__import__("zoneinfo").ZoneInfo("Asia/Shanghai"))
    return SimpleNamespace(
        BrokerID="9999",
        InvestorID=USER,
        TradingDay="20261027",
        OrderRef=binding["order_ref"],
        FrontID=1,
        SessionID=2,
        InstrumentID="rb2701",
        ExchangeID="SHFE",
        Direction="0",
        CombOffsetFlag="0",
        CombHedgeFlag="1",
        LimitPrice=1000.0,
        VolumeTotalOriginal=1,
        VolumeTraded=int(status == "0"),
        VolumeTotal=int(status not in ("0", "5")),
        OrderStatus=status,
        OrderSubmitStatus=submit,
        OrderSysID="sys-1",
        InsertDate=native.strftime("%Y%m%d"),
        InsertTime=native.strftime("%H:%M:%S"),
    )


def test_submit_is_durable_once_and_sdk_zero_does_not_mean_working(tmp_path):
    ad, effect, facts, binding, permit, at, api = setup(tmp_path)
    assert (
        ad.dispatch(effect, binding, None, facts, permit, at)
        == "REQUEST_ACCEPTED_AWAIT_NATIVE"
    )
    assert ad.store.current().orders[0].status == "PROPOSED"
    assert (
        ad.dispatch(effect, binding, None, facts, permit, at)
        == "ALREADY_CLAIMED_NO_SEND"
    )
    assert len(api.calls) == 1
    req = api.calls[0][1]
    assert (
        req.OrderRef,
        req.CombOffsetFlag,
        req.Direction,
        req.TimeCondition,
        req.VolumeTotalOriginal,
    ) == ("11", "0", "0", "3", 1)
    assert ad.journal.find(effect.order.order_id)["order_ref"] == "11"


def test_native_acceptance_stages_then_drains_and_duplicates_are_safe(tmp_path):
    ad, effect, facts, binding, permit, at, api = setup(tmp_path)
    ad.dispatch(effect, binding, None, facts, permit, at)
    accepted = at + timedelta(seconds=1)
    callback = row(ad, effect, at)
    ad.order_callback(callback, accepted)
    assert ad.store.current().orders[0].status == "PROPOSED"
    assert not ad.drain()
    assert ad.store.current().orders[0].accepted_at == accepted
    ad.order_callback(callback, accepted + timedelta(seconds=1))
    ad.drain()
    assert ad.store.current().orders[0].accepted_at == accepted
    assert ad.store.replay() == ad.store.current()


def test_exception_after_claim_never_resends(tmp_path):
    api = FakeApi()
    api.error = True
    ad, e, f, c, p, at, _ = setup(tmp_path, api)
    assert ad.dispatch(e, c, None, f, p, at) == "SEND_OUTCOME_UNKNOWN"
    with pytest.raises(ValueError):
        ad.dispatch(e, c, None, f, p, at)
    assert len(api.calls) == 1


@pytest.mark.parametrize(
    "problem", ["expired", "wrong_hash", "wrong_account", "stale_quote"]
)
def test_preflight_zero_calls(tmp_path, problem):
    from dataclasses import replace

    ad, e, f, c, p, at, api = setup(tmp_path)
    if problem == "expired":
        at += timedelta(seconds=6)
    elif problem == "wrong_hash":
        p = replace(p, action_hash="0" * 64)
    elif problem == "wrong_account":
        p = replace(p, account_id="other")
    else:
        at += timedelta(seconds=11)
        p = replace(p, expires_at=at + timedelta(seconds=1))
    with pytest.raises(ValueError):
        ad.dispatch(e, c, None, f, p, at)
    assert api.calls == []


def test_trade_waits_for_actual_fee_and_preserves_identity(tmp_path):
    ad, e, f, c, p, at, api = setup(tmp_path)
    ad.dispatch(e, c, None, f, p, at)
    ad.order_callback(row(ad, e, at, "0"), at + timedelta(seconds=2))
    ad.drain()
    trade = SimpleNamespace(
        BrokerID="9999",
        InvestorID=USER,
        TradingDay="20261027",
        OrderRef="11",
        InstrumentID="rb2701",
        ExchangeID="SHFE",
        Direction="0",
        OffsetFlag="0",
        HedgeFlag="1",
        Volume=1,
        Price=999.0,
        TradeDate="20261027",
        TradeTime="10:01:01",
        TradeID="trade-1",
        OrderSysID="sys-1",
    )
    identity = ad.trade_callback(trade, at + timedelta(seconds=3))
    assert ad.drain() == (identity,)
    assert ad.store.current().fills == ()
    ad.fee(
        b.Fee(identity, D("3.12"), "native-commission-proof"), at + timedelta(seconds=4)
    )
    assert not ad.drain()
    assert ad.store.current().fills[0].fee == D("3.12")
    assert ad.store.current().positions[0].quantity == 1
    ad.drain()
    assert len(ad.store.current().fills) == 1


def test_cancel_requires_persisted_deadline_and_uses_original_native_identity(tmp_path):
    ad, e, f, c, p, at, api = setup(tmp_path)
    ad.dispatch(e, c, None, f, p, at)
    ad.order_callback(row(ad, e, at), at + timedelta(seconds=1))
    ad.drain()
    now = at + timedelta(seconds=182)
    effects = ad.store.execute("deadline", a.Tick(now, (f,))).effects
    assert len(effects) == 1 and effects[0].kind == "CANCEL"
    cancel = effects[0]
    permit = b.Permit(
        "cancel-intent",
        ACCOUNT,
        "20261027",
        b.action_hash(ad.store.current(), cancel, ad.session, c, None, f),
        now,
        now + timedelta(seconds=5),
    )
    ad.dispatch(cancel, c, None, f, permit, now)
    req = api.calls[-1][1]
    assert (req.OrderRef, req.FrontID, req.SessionID, req.ActionFlag) == (
        "11",
        1,
        2,
        "0",
    )
    ad.order_callback(row(ad, e, at, "5"), now + timedelta(seconds=1))
    ad.drain()
    assert not ad.store.current().orders[0].reconciled
    assert not ad.store.current().reservations[0].released


def test_rejection_response_and_cancel_error_require_reconciliation(tmp_path):
    ad, e, f, c, p, at, api = setup(tmp_path)
    ad.dispatch(e, c, None, f, p, at)
    req = api.calls[0][1]
    ad.response("SUBMIT", req, 31, api.calls[0][2], at + timedelta(seconds=1))
    ad.drain()
    assert ad.store.current().orders[0].status == "REJECTED"
    assert not ad.store.current().reservations[0].released
    assert ad.store.current().phase == "RECOVERY_REQUIRED"


def test_no_ack_timeout_never_resends_and_disconnect_is_durable(tmp_path):
    ad, e, f, c, p, at, api = setup(tmp_path)
    ad.dispatch(e, c, None, f, p, at)
    ad.expire_unacknowledged(at + timedelta(seconds=26))
    ad.drain()
    assert ad.store.current().orders[0].status == "UNKNOWN"
    assert not ad.store.current().reservations[0].released
    ad.disconnected(at + timedelta(seconds=27))
    ad.drain()
    assert not ad.store.current().readback_valid
    assert len(api.calls) == 1


def test_callback_during_sdk_send_only_stages_facts(tmp_path):
    ad, e, f, c, p, at, api = setup(tmp_path)
    api.callback = lambda _: ad.order_callback(
        row(ad, e, at), at + timedelta(seconds=1)
    )
    ad.dispatch(e, c, None, f, p, at)
    ad.drain()
    assert ad.store.current().orders[0].status == "WORKING"


@pytest.mark.parametrize(
    "field,value",
    [
        ("InvestorID", "other"),
        ("TradingDay", "20261026"),
        ("InstrumentID", "rb2705"),
        ("VolumeTotalOriginal", 2),
        ("CombOffsetFlag", "3"),
        ("Direction", "1"),
        ("LimitPrice", 1001),
    ],
)
def test_bad_native_report_is_rejected_without_projecting(tmp_path, field, value):
    ad, e, f, c, p, at, api = setup(tmp_path)
    ad.dispatch(e, c, None, f, p, at)
    callback = row(ad, e, at)
    setattr(callback, field, value)
    with pytest.raises(ValueError):
        ad.order_callback(callback, at + timedelta(seconds=1))
    assert ad.store.current().orders[0].status == "PROPOSED"


def test_journal_reopen_keeps_native_ref_and_duplicate_send_claim(tmp_path):
    ad, e, f, c, p, at, api = setup(tmp_path)
    ad.dispatch(e, c, None, f, p, at)
    ad.journal.close()
    ad.journal = b.Journal(tmp_path / "dispatch.db", ACCOUNT)
    assert ad.dispatch(e, c, None, f, p, at) == "ALREADY_CLAIMED_NO_SEND"
    assert ad.journal.find(e.order.order_id)["order_ref"] == "11"
    ad.order_callback(row(ad, e, at), at + timedelta(seconds=1))
    ad.drain()
    assert ad.store.current().orders[0].status == "WORKING"


def test_sdk_nonzero_does_not_release_reserve(tmp_path):
    ad, e, f, c, p, at, api = setup(tmp_path)
    api.ReqOrderInsert = lambda *_: -2
    assert ad.dispatch(e, c, None, f, p, at) == "NOT_ACCEPTED_RECONCILE_REQUIRED"
    ad.drain()
    assert ad.store.current().orders[0].status == "UNKNOWN"
    assert not ad.store.current().reservations[0].released


def native_trade(ref="11", system="sys-1", clock="10:01:01", day="20261027"):
    return SimpleNamespace(
        BrokerID="9999",
        InvestorID=USER,
        TradingDay=day,
        OrderRef=ref,
        InstrumentID="rb2701",
        ExchangeID="SHFE",
        Direction="0",
        OffsetFlag="0",
        HedgeFlag="1",
        Volume=1,
        Price=999.0,
        TradeDate=day,
        TradeTime=clock,
        TradeID="trade-review",
        OrderSysID=system,
    )


def test_same_second_fill_retains_precision_without_invented_timestamp(tmp_path):
    ad, e, f, c, p, at, api = setup(tmp_path)
    ad.dispatch(e, c, None, f, p, at)
    ad.order_callback(row(ad, e, at), at + timedelta(milliseconds=100))
    identity = ad.trade_callback(
        native_trade(clock="10:01:00"), at + timedelta(milliseconds=200)
    )
    ad.fee(b.Fee(identity, D(3), "actual-fee"), at + timedelta(seconds=1))
    ad.drain()
    fill = ad.store.current().fills[0]
    assert fill.filled_at == at and fill.native_precision_seconds == 1
    assert fill.request_started_at == at and fill.dispatch_source_id
    assert ad.store.replay() == ad.store.current()


def test_restart_disconnect_does_not_prevent_offline_fill_journaling(tmp_path):
    ad, e, f, c, p, at, api = setup(tmp_path)
    ad.dispatch(e, c, None, f, p, at)
    ad.order_callback(row(ad, e, at), at + timedelta(seconds=1))
    ad.drain()
    ad.disconnected(at + timedelta(seconds=2))
    identity = ad.trade_callback(native_trade(), at + timedelta(seconds=3))
    ad.fee(b.Fee(identity, D(3), "actual-fee"), at + timedelta(seconds=4))
    ad.store.close()
    ad.store = a.LocalStore(tmp_path / "account.db")
    ad.drain()
    assert len(ad.store.current().fills) == 1
    assert not ad.store.current().readback_valid


def test_trade_system_id_conflict_is_retained_but_never_projected(tmp_path):
    ad, e, f, c, p, at, api = setup(tmp_path)
    ad.dispatch(e, c, None, f, p, at)
    ad.order_callback(row(ad, e, at), at + timedelta(seconds=1))
    ad.drain()
    identity = ad.trade_callback(
        native_trade(system="another-order"), at + timedelta(seconds=3)
    )
    ad.fee(b.Fee(identity, D(3), "actual-fee"), at + timedelta(seconds=4))
    assert ad.drain() == (identity,)
    assert ad.store.current().fills == ()
    assert any(
        payload.get("system_id") == "another-order"
        for _, payload, _ in ad.journal.events()
    )


def test_previous_day_known_order_fill_is_retained_after_new_login(tmp_path):
    from dataclasses import replace

    ad, e, f, c, p, at, api = setup(tmp_path)
    ad.dispatch(e, c, None, f, p, at)
    ad.order_callback(row(ad, e, at), at + timedelta(seconds=1))
    ad.drain()
    ad.session = replace(ad.session, trading_day="20261028", front_id=2, session_id=3)
    identity = ad.trade_callback(native_trade(), at + timedelta(days=1))
    ad.fee(b.Fee(identity, D(3), "actual-fee"), at + timedelta(days=1, seconds=1))
    ad.drain()
    assert ad.store.current().fills[0].trade_id == identity


def test_subsecond_proposal_accepts_native_insert_second_interval(
    tmp_path, monkeypatch
):
    monkeypatch.setitem(globals(), "T", T + timedelta(milliseconds=250))
    ad, e, f, c, p, at, api = setup(tmp_path)
    ad.dispatch(e, c, None, f, p, at)
    ad.order_callback(row(ad, e, at), at + timedelta(milliseconds=100))
    identity = ad.trade_callback(
        native_trade(clock="10:01:00"), at + timedelta(milliseconds=200)
    )
    ad.fee(b.Fee(identity, D(3), "actual-fee"), at + timedelta(seconds=1))
    ad.drain()
    assert len(ad.store.current().fills) == 1
    assert ad.store.current().fills[0].filled_at.microsecond == 0
    assert ad.store.current().fills[0].request_started_at.microsecond == 250000


def test_unbound_trade_keeps_whitelisted_native_fact_and_blocks_dispatch(tmp_path):
    ad, e, f, c, p, at, api = setup(tmp_path)
    trade = native_trade(ref="external")
    with pytest.raises(ValueError):
        ad.trade_callback(trade, at)
    assert any(
        payload["kind"] == "quarantine" and payload["fields"]["OrderRef"] == "external"
        for _, payload, _ in ad.journal.events()
    )
    with pytest.raises(ValueError):
        ad.dispatch(e, c, None, f, p, at)
    assert api.calls == []


def test_two_dispatch_handles_claim_only_once(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    ad, e, f, c, p, at, api = setup(tmp_path)
    otherjournal = b.Journal(tmp_path / "dispatch.db", ACCOUNT)
    # This test pins journal atomicity independently from recovery business semantics.
    payload = {"contract": "RB2701"}

    def claim(j):
        return j.claim(
            "SUBMIT:one", "one", "SUBMIT", payload, ad.session, "same-intent"
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(claim, j) for j in (ad.journal, otherjournal)]
        results = [f.result() for f in futures]
    assert sum(value is not None for value in results) == 1
    otherjournal.close()


@pytest.mark.parametrize("native_report", [False, True])
def test_unresolved_external_fill_then_disconnect_still_records_known_fill(
    tmp_path, native_report
):
    ad, e, f, c, p, at, api = setup(tmp_path)
    ad.dispatch(e, c, None, f, p, at)
    ad.order_callback(row(ad, e, at), at + timedelta(seconds=1))
    ad.drain()
    external = h.Fill(
        "external-trade",
        "external-order",
        ACCOUNT,
        "RB2701",
        at + timedelta(seconds=2),
        at + timedelta(seconds=2),
        D(1000),
        D(3),
        1,
    )
    ad.store.execute("external-unknown", external)
    if native_report:
        ad.order_callback(row(ad, e, at, "0"), at + timedelta(seconds=3))
    ad.disconnected(at + timedelta(seconds=3))
    identity = ad.trade_callback(native_trade(), at + timedelta(seconds=4))
    ad.fee(b.Fee(identity, D(3), "actual-fee"), at + timedelta(seconds=5))
    ad.store.close()
    ad.store = a.LocalStore(tmp_path / "account.db")
    ad.drain()
    assert len(ad.store.current().fills) == 2
    assert ad.store.current().phase == "BLOCKED"
    assert ad.store.replay().phase == "BLOCKED"
