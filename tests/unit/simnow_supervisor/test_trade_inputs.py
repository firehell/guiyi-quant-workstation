"""Trade input selection refreshes account after rates and quotes exactly one target."""

from datetime import timedelta
from zoneinfo import ZoneInfo
import pytest
from guiyi_quant import htdy_account_execution as a
from test_native_portfolio import portfolio, Gateway, Market, T
from guiyi_quant import htdy_execution as h
from decimal import Decimal as D


def pending_state():
    rb = a.Readback(
        h.AccountSnapshot("fixture", T, D(100000), D(100000)),
        D(0),
        D(0),
        D(0),
        (),
        (),
        "initial",
        T + timedelta(hours=3),
        True,
    )
    state = a.start("fixture", ("JM", "RB"), T, rb)
    for product in ("RB", "JM"):
        state = a.apply(
            state,
            "owner-" + product,
            h.Owner(product, product + "2701", T, "owner-" + product),
        ).state
    for product, minute in (("RB", 60), ("JM", 61)):
        end = T + timedelta(minutes=minute)
        state = a.apply(
            state,
            "signal-" + product,
            h.Signal(
                "signal-" + product,
                product,
                product + "2701",
                end,
                end + timedelta(seconds=2),
                None,
                ("buy",),
                "a" * 64,
            ),
        ).state
    return state


def setup(tmp_path, stale=None):
    at = T + timedelta(minutes=62)
    gateway = Gateway()
    query = gateway.query

    def fetch(kind, instrument_id=None, **scope):
        rows = query(kind, instrument_id, **scope)
        if kind == "book" and instrument_id.upper().removesuffix("2701") != stale:
            rows[0]["UpdateTime"] = at.astimezone(ZoneInfo("Asia/Shanghai")).strftime(
                "%H:%M:%S"
            )
        return rows

    gateway.query = fetch
    native = portfolio(tmp_path, gateway=gateway, at=at)
    market = Market()
    authority = market.authority

    def auth(product, day, now, contract=None):
        value = authority(product, day, now, contract)
        value.owner = product + "2701"
        return value

    market.authority = auth
    return native, gateway, market, at


def test_trade_uses_signal_order_and_refreshes_after_rates_before_book(tmp_path):
    native, gateway, market, at = setup(tmp_path)
    state = pending_state()

    def refresh():
        gateway.queries.append(("refresh", "RB"))
        return state

    facts, bindings = native.execution_for(
        state, market, at, "20261027", {}, opening_allowed=True, refresh=refresh
    )
    assert [f.instrument.product for f in facts] == ["RB"]
    assert [b.canonical for b in bindings] == ["RB2701"]
    kinds = [kind for kind, _ in gateway.queries]
    assert kinds.index("commission") < kinds.index("refresh") < kinds.index("book")
    assert {p for _, p in gateway.queries} == {"RB"}


def test_stale_earlier_product_does_not_starve_next_qualified_product(tmp_path):
    native, gateway, market, at = setup(tmp_path, stale="RB")
    issues = {}
    state = pending_state()
    facts, _ = native.execution_for(
        state,
        market,
        at,
        "20261027",
        issues,
        opening_allowed=True,
        refresh=lambda: state,
    )
    assert [f.instrument.product for f in facts] == ["JM"]
    assert issues == {"RB": "EXECUTION_INPUT_UNPROVEN"}


def test_account_change_during_refresh_stops_before_book(tmp_path):
    native, gateway, market, at = setup(tmp_path)
    facts, _ = native.execution_for(
        pending_state(),
        market,
        at,
        "20261027",
        {},
        opening_allowed=True,
        refresh=lambda: None,
    )
    assert facts == () and not any(k == "book" for k, _ in gateway.queries)


def test_no_trade_acquisition_without_refresh_capability(tmp_path):
    native, gateway, market, at = setup(tmp_path)
    with pytest.raises(ValueError, match="TRADE_ACCOUNT_REFRESH_REQUIRED"):
        native.execution_for(
            pending_state(), market, at, "20261027", {}, opening_allowed=True
        )
    assert gateway.queries == []


@pytest.mark.parametrize("blocked", ["zero-volume", "closed", "off-tick"])
def test_temporary_first_candidate_ineligibility_never_starves_later_product(
    tmp_path, blocked
):
    from dataclasses import replace

    native, gateway, market, at = setup(tmp_path)
    query = gateway.query

    def fetch(kind, instrument_id=None, **scope):
        rows = query(kind, instrument_id, **scope)
        if kind == "book" and instrument_id.startswith("rb"):
            if blocked == "zero-volume":
                rows[0]["AskVolume1"] = 0
            if blocked == "off-tick":
                rows[0]["AskPrice1"] = "1000.5"
        return rows

    gateway.query = fetch
    authority = market.authority

    def auth(product, *args, **kwargs):
        result = authority(product, *args, **kwargs)
        if product == "RB" and blocked == "closed":
            result.session = replace(result.session, can_trade=False)
        return result

    market.authority = auth
    state = pending_state()
    for _ in range(3):
        facts, _ = native.execution_for(
            state,
            market,
            at,
            "20261027",
            {},
            opening_allowed=True,
            refresh=lambda: state,
        )
        assert [f.instrument.product for f in facts] == ["JM"]
    assert not state.abandoned


@pytest.mark.parametrize("failure", ["book", "margin"])
def test_cold_restart_cancels_without_new_book_or_rates(tmp_path, failure):
    from dataclasses import replace

    native, gateway, market, at = setup(tmp_path)
    state = pending_state()
    fact = native.facts("RB", "RB2701", market, "20261027")[1]
    state = a.apply(state, "create", a.ContinuousTradeTickV1(at, (fact,))).state
    order = state.orders[0]
    state = a.apply(
        state,
        "accept",
        a.OrderUpdate(
            "fixture",
            order.order_id,
            at + timedelta(seconds=1),
            "accepted",
            "WORKING",
            at + timedelta(seconds=1),
        ),
    ).state
    # Actual restart Recover contributes RecoveryInput after the original Tick.
    proof = h.RecoveryInput("RB", "RB2701", 0, at, "restart-proof")
    rb = replace(
        state.readback,
        snapshot=replace(
            state.readback.snapshot,
            at=at + timedelta(seconds=2),
            orders=(h.OrderReport(order.order_id, "WORKING"),),
        ),
        source_id="restart-readback",
    )
    state = a.apply(
        state,
        "restart",
        a.Recover(rb, (proof, h.RecoveryInput("JM", "JM2701", 0, at, "restart-jm"))),
    ).state
    assert state.readback_valid
    native.last_facts.clear()
    native.now = lambda: at + timedelta(seconds=181)
    query = gateway.query

    def failed(kind, *args, **kwargs):
        if kind == failure:
            raise ValueError("FIXTURE_TEMPORARY_INPUT_FAILURE")
        return query(kind, *args, **kwargs)

    gateway.query = failed
    facts, _ = native.execution_for(
        state,
        market,
        native.now(),
        "20261027",
        {},
        opening_allowed=True,
        refresh=lambda: state,
    )
    assert len(facts) == 1 and facts[0].quote is None
    tx = a.apply(state, "cancel", a.ContinuousTradeTickV1(native.now(), facts))
    assert [e.kind for e in tx.effects] == ["CANCEL"]
    assert not tx.state.reservations[0].released
