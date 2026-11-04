"""Offline fixtures prove policy/transport safety, never remote trading success."""

from datetime import datetime, UTC, timedelta
from decimal import Decimal as D
from dataclasses import replace
import pytest
from guiyi_quant.htdy_account_execution import model as m, codec
from guiyi_quant.htdy_account_execution.reducer import start, apply
from guiyi_quant.htdy_account_execution.store import LocalStore, StoreError
from guiyi_quant.tq_simulation.controller import Controller
from guiyi_quant.tq_simulation.journal import Journal
from guiyi_quant.tq_simulation.gateway import decimal, order_status
from guiyi_quant.tq_simulation.credentials import Credentials

A = "a" * 64
T = datetime(2026, 11, 4, 13, tzinfo=UTC)


def rb(at=T, balance="1000000", positions=(), orders=(), trades=(), used="0"):
    return m.Readback(
        m.AccountSnapshot(A, at, D(balance), D(balance), positions, orders),
        D(used),
        D(0),
        D(0),
        (),
        trades,
        "snapshot:" + at.isoformat(),
        at + timedelta(hours=5),
        True,
    )


def initial():
    s = start(A, ("RB",), T, rb())
    s = apply(s, "owner", m.Owner("RB", "RB2701", T, "owner")).state
    return s


def signal(at=T + timedelta(hours=1)):
    return m.Signal(
        "s:" + at.isoformat(),
        "RB",
        "RB2701",
        at - timedelta(seconds=1),
        at,
        None,
        ("buy",),
        "b" * 64,
    )


def fact(at, margin=D("1000"), fee=D("3")):
    return m.TqKqExecutionInput(
        m.TqKqInstrument(
            "RB",
            "RB2701",
            at - timedelta(seconds=1),
            at + timedelta(seconds=10),
            "instrument",
            D(1),
            D(10),
            margin,
            fee,
        ),
        m.Session(
            "RB2701",
            at - timedelta(seconds=1),
            at + timedelta(seconds=10),
            "session",
            at + timedelta(hours=3),
            True,
            True,
        ),
        m.Quote(
            "RB2701",
            at - timedelta(seconds=1),
            at + timedelta(seconds=10),
            "quote",
            D(999),
            D(1000),
            1,
            1,
            D(1),
            D(2000),
        ),
    )


@pytest.mark.parametrize("margin,allowed", [("700000", True), ("700001", False)])
def test_actual_equity_seventy_percent_boundary_and_one_lot(margin, allowed):
    s = apply(initial(), "signal", signal()).state
    at = signal().observed_at + timedelta(seconds=1)
    tx = apply(s, "tick", m.TqKqTick(at, (fact(at, D(margin)),), True))
    assert bool(tx.effects) is allowed
    if allowed:
        assert tx.effects[0].order.quantity == 1
        assert tx.state.reservations[0].margin == D(margin)
    else:
        assert tx.state.risk_decisions[-1].reason == "MARGIN_CAP"


@pytest.mark.parametrize("margin,fee", [(None, D(3)), (D(1000), None)])
def test_unknown_account_margin_or_fee_never_falls_back(margin, fee):
    s = apply(initial(), "signal", signal()).state
    at = signal().observed_at + timedelta(seconds=1)
    assert not apply(s, "tick", m.TqKqTick(at, (fact(at, margin, fee),), True)).effects


def test_pause_consumes_target_resume_does_not_replay():
    s = apply(initial(), "signal", signal()).state
    at = signal().observed_at + timedelta(seconds=1)
    s = apply(s, "paused", m.TqKqTick(at, (), False)).state
    assert s.products[0].opening_consumed
    assert not apply(
        s, "resume", m.TqKqTick(at + timedelta(seconds=1), (fact(at),), True)
    ).effects


def test_stop_never_submits_new_position():
    s = apply(initial(), "signal", signal()).state
    at = signal().observed_at + timedelta(seconds=1)
    assert not apply(
        s, "stop", m.TqKqTick(at, (fact(at),), False, stopping=True)
    ).effects


def test_tq_store_identity_and_unknown_fee_replay(tmp_path):
    s = apply(initial(), "signal", signal()).state
    at = signal().observed_at + timedelta(seconds=1)
    path = tmp_path / "account.sqlite"
    identity = "TQKQ:" + A + ":htdy_tqkq_v1"
    # Initial states may have observations but never prior orders.
    store = LocalStore(path, s, execution_identity=identity)
    tx = store.execute("tick", m.TqKqTick(at, (fact(at),), True))
    o = tx.effects[0].order
    f = m.TqKqFill(
        "tq-trade:x",
        o.order_id,
        A,
        o.contract,
        at + timedelta(seconds=1),
        at + timedelta(seconds=2),
        D(1000),
        None,
        1,
        "x",
        "native",
        "f" * 64,
    )
    store.execute("fill", f)
    assert store.current().fills[0].fee is None
    assert codec.load(codec.checkpoint(store.current())) == store.current()
    store.close()
    with pytest.raises(StoreError):
        LocalStore(path)
    read = LocalStore.inspect(path)
    assert read.fills[0].fee is None
    reopened = LocalStore(path, execution_identity=identity)
    assert reopened.current().phase == "RECOVERY_REQUIRED"
    reopened.close()


def test_legacy_store_cannot_accept_tq_execution(tmp_path):
    store = LocalStore(tmp_path / "old.sqlite", initial())
    with pytest.raises(StoreError, match="TQ_ACCOUNT_IDENTITY_REQUIRED"):
        store.execute("tq", m.TqKqTick(T, (), True))
    store.close()


def test_claim_before_send_is_durable_and_cannot_retry(tmp_path):
    p = tmp_path / "dispatch.sqlite"
    j = Journal(p, A)
    native = j.claim("SUBMIT", "order", {"price": "1000"}, T)
    assert native and len(native) == 32
    j.close()
    j = Journal(p, A)
    assert (
        j.claim("SUBMIT", "order", {"price": "1000"}, T + timedelta(seconds=1)) is None
    )
    with pytest.raises(ValueError, match="CLAIM_DRIFT"):
        j.claim("SUBMIT", "order", {"price": "1001"}, T)
    with pytest.raises(Exception):
        j.db.execute("DELETE FROM claims")
    j.close()


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True])
def test_nonfinite_numbers_rejected(value):
    with pytest.raises((ValueError, ArithmeticError)):
        decimal(value)


@pytest.mark.parametrize(
    "row,want",
    [
        ({"volume_orign": 1, "volume_left": 0, "status": "FINISHED"}, "FILLED"),
        (
            {
                "volume_orign": 1,
                "volume_left": 1,
                "status": "FINISHED",
                "is_error": True,
            },
            "REJECTED",
        ),
        (
            {
                "volume_orign": 1,
                "volume_left": 1,
                "status": "FINISHED",
                "is_dead": True,
            },
            "CANCELLED",
        ),
        (
            {"volume_orign": 1, "volume_left": 1, "status": "ALIVE", "is_online": True},
            "WORKING",
        ),
        (
            {
                "volume_orign": 1,
                "volume_left": 1,
                "status": "ALIVE",
                "is_online": False,
            },
            "UNKNOWN",
        ),
    ],
)
def test_finished_is_not_automatically_a_fill(row, want):
    assert order_status(row) == want


def test_credentials_are_redacted_and_provider_scoped():
    c = Credentials("fixture@example.test", "fixture-password")
    assert "fixture" not in repr(c)
    assert c.account_id != A


class Transport:
    def assert_continuity(self):
        pass

    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def submit(self, *args):
        self.calls.append(("submit", args))
        if self.fail:
            raise OSError("fixture transport disconnect")

    def cancel(self, *args):
        self.calls.append(("cancel", args))


def snapshot(at, *, orders=(), trades=(), positions=()):
    payload = {
        "account_id": A,
        "account": {
            k: "0"
            for k in [
                "margin",
                "frozen_margin",
                "frozen_commission",
                "commission",
                "position_profit",
                "close_profit",
                "deposit",
                "withdraw",
            ]
        },
        "positions": list(positions),
        "orders": list(orders),
        "trades": list(trades),
        "trading_day": "20261104",
        "snapshot_id": "c" * 64,
        "observed_at": at.isoformat(),
    }
    payload["account"].update(
        balance="1000000", available="1000000", static_balance="1000000"
    )
    return payload


def live_controller(tmp_path, transport=None):
    now = datetime.now(UTC)
    c = Controller(tmp_path, A, ("RB",), transport or Transport())
    c.bind_symbol("SHFE.rb2701", "RB", "RB2701")
    c.bootstrap(snapshot(now - timedelta(hours=2)), now - timedelta(hours=2))
    c.owner("RB", "RB2701", now - timedelta(seconds=20), "owner")
    s = signal(now - timedelta(seconds=10))
    c.signal(s)
    c.synchronize(snapshot(now - timedelta(seconds=2)), now - timedelta(seconds=2))
    return c, now


def test_transport_exception_never_retries_claim(tmp_path):
    transport = Transport(fail=True)
    c, now = live_controller(tmp_path, transport)
    with pytest.raises(OSError):
        c.tick((fact(now),), now, opening_allowed=True)
    assert len(transport.calls) == 1
    state = c.store.current()
    order = state.orders[0]
    effect = m.Effect("SUBMIT", order)
    assert (
        c.dispatch(effect, fact(now), datetime.now(UTC), opening_allowed=True)
        == "ALREADY_CLAIMED_NO_SEND"
    )
    assert len(transport.calls) == 1
    with pytest.raises(ValueError, match="AWAITING_ORDER_FACTS"):
        c.synchronize(snapshot(datetime.now(UTC)), datetime.now(UTC))
    c.close()


def test_initial_nonflat_is_readonly_and_never_initializes_account(tmp_path):
    c = Controller(tmp_path, A, ("RB",), Transport())
    with pytest.raises(ValueError, match="INITIAL_ACCOUNT_NOT_FLAT"):
        c.bootstrap(
            snapshot(
                T,
                positions=[
                    {
                        "symbol": "SHFE.rb2701",
                        "pos_long_today": 1,
                        "pos_long_his": 0,
                        "pos_short_today": 0,
                        "pos_short_his": 0,
                    }
                ],
            ),
            T,
        )
    assert not (tmp_path / "account.sqlite").exists()
    assert c.gateway.calls == []
    c.close()


def native_order(c, order, *, state="WORKING", left=1):
    native = next(n for n, o in c.journal.mappings().items() if o == order.order_id)
    return dict(
        order_id=native,
        exchange_order_id="exchange",
        exchange_id="SHFE",
        instrument_id="rb2701",
        direction=order.side,
        offset=order.offset,
        volume_orign=1,
        volume_left=left,
        status="ALIVE" if left else "FINISHED",
        is_error=False,
        is_dead=not left,
        is_online=bool(left),
        insert_date_time=0,
        limit_price=str(order.price),
        price_type="LIMIT",
        state=state,
    )


def full_fill(c, now):
    tx = c.tick((fact(now),), now, opening_allowed=True)
    order = tx.effects[0].order
    row = native_order(c, order)
    c.synchronize(
        snapshot(now + timedelta(seconds=1), orders=[row]), now + timedelta(seconds=1)
    )
    row = {
        **row,
        "state": "FILLED",
        "volume_left": 0,
        "status": "FINISHED",
        "is_dead": True,
        "is_online": False,
    }
    with pytest.raises(ValueError, match="AWAITING_TRADE_FACTS"):
        c.synchronize(
            snapshot(now + timedelta(seconds=2), orders=[row]),
            now + timedelta(seconds=2),
        )
    fill_at = now + timedelta(seconds=2)
    ns = int(fill_at.timestamp()) * 1000000000 + fill_at.microsecond * 1000
    trade = dict(
        order_id=row["order_id"],
        trade_id="native-fill",
        exchange_id="SHFE",
        instrument_id="rb2701",
        direction="BUY",
        offset="OPEN",
        volume=1,
        trade_date_time=ns,
        price="1000",
    )
    with pytest.raises(ValueError, match="AWAITING_ACCOUNT_FACTS"):
        c.synchronize(
            snapshot(now + timedelta(seconds=3), orders=[row], trades=[trade]),
            now + timedelta(seconds=3),
        )
    position = dict(
        symbol="SHFE.rb2701",
        pos_long_today=1,
        pos_long_his=0,
        pos_short_today=0,
        pos_short_his=0,
    )
    s = snapshot(
        now + timedelta(seconds=4), orders=[row], trades=[trade], positions=[position]
    )
    s["account"]["margin"] = "1000"
    rb = c.synchronize(s, now + timedelta(seconds=4))
    assert c.store.current().positions[0].quantity == 1
    assert len(c.store.current().fills) == 1 and c.store.current().fills[0].fee is None
    assert c.store.current().orders[0].reconciled
    assert c.store.current().reservations[0].released
    return s, rb


def test_out_of_order_native_updates_preserve_fill_and_reconcile_once(tmp_path):
    c, now = live_controller(tmp_path)
    s, rb = full_fill(c, now)
    c.synchronize(
        {**s, "observed_at": (now + timedelta(seconds=5)).isoformat()},
        now + timedelta(seconds=5),
    )
    assert len(c.store.current().fills) == 1 and len(c.gateway.calls) == 1
    c.close()
    c = Controller(tmp_path, A, ("RB",), Transport())
    rb = c.synchronize(s, now + timedelta(seconds=6))
    proof = m.RecoveryInput(
        "RB",
        "RB2701",
        1,
        signal(now - timedelta(seconds=10)).bar_end,
        "fixture-recovery",
    )
    c.recover(rb, (proof,))
    assert c.store.current().phase == "READY" and len(c.store.current().fills) == 1
    assert c.store.current().products[0].opening_consumed
    assert c.gateway.calls == []
    c.close()


@pytest.mark.parametrize("today,expected", [(1, "CLOSETODAY"), (0, "CLOSE")])
def test_shfe_close_uses_actual_today_historical_inventory(tmp_path, today, expected):
    c, now = live_controller(tmp_path)
    s, _ = full_fill(c, now)
    s["positions"][0].update(pos_long_today=today, pos_long_his=1 - today)
    at = now + timedelta(minutes=2)
    old = c.store.current().products[0].last_bar
    reverse = m.Signal(
        "reverse",
        "RB",
        "RB2701",
        at - timedelta(seconds=1),
        at,
        old,
        ("sell",),
        "c" * 64,
    )
    c.signal(reverse)
    c.synchronize(s, at + timedelta(seconds=1))
    at += timedelta(seconds=2)
    f = fact(at)
    tx = c.store.execute("close-tick", m.TqKqTick(at, (f,), True))
    assert tx.effects[0].order.offset == "CLOSE"
    c.dispatch(tx.effects[0], f, at, opening_allowed=True)
    assert c.gateway.calls[-1][1][2] == expected
    c.close()


def test_native_ack_wait_is_bounded_and_cannot_be_reset_on_restart(tmp_path):
    c, now = live_controller(tmp_path)
    c.tick((fact(now),), now, opening_allowed=True)
    c.close()
    c = Controller(tmp_path, A, ("RB",), Transport())
    with pytest.raises(ValueError, match="SEND_OUTCOME_UNKNOWN"):
        c.synchronize(
            snapshot(now + timedelta(seconds=30)), now + timedelta(seconds=30)
        )
    assert c.gateway.calls == []
    c.close()


def test_dispatch_rejects_fact_identity_drift(tmp_path):
    c, now = live_controller(tmp_path)
    f = fact(now)
    tx = c.store.execute("fixture-tick", m.TqKqTick(now, (f,), True))
    drift = replace(
        f, instrument=replace(f.instrument, source_id="unapproved-margin-source")
    )
    with pytest.raises(ValueError, match="DISPATCH_FACT_DRIFT"):
        c.dispatch(tx.effects[0], drift, now, opening_allowed=True)
    assert not c.journal.mappings() and c.gateway.calls == []
    c.close()


def test_sdk_margin_fallback_is_never_account_specific_proof():
    from types import SimpleNamespace
    from guiyi_quant.tq_simulation.gateway import Gateway

    g = Gateway.__new__(Gateway)
    g.notifications, g.connections, g.reconnection_required = set(), {}, False
    g.account = object()
    g.account_key = "fixture-key"
    g.quote = lambda _: {"commission": 3}
    g.api = SimpleNamespace(
        _requests={"margin_rates": {}},
        _get_margin_rate=lambda *a: 0.12,
        _account=SimpleNamespace(_get_account_id=lambda _: "fixture-user"),
        _data={"trade": {}},
    )
    with pytest.raises(ValueError, match="ACCOUNT_MARGIN_UNAVAILABLE"):
        g.margin("SHFE.rb2701", "BUY")
    response = {
        "trade": {
            "fixture-key": {
                "pre_insert_orders": {
                    "fixture-key_fixture-user": {
                        "exchange_id": "SHFE",
                        "instrument_id": "rb2701",
                        "direction": "BUY",
                        "pre_margin": 2101.4123,
                        "pre_commission": 0.3002,
                    }
                }
            }
        }
    }

    def respond(*_):
        import copy

        g.api._data = copy.deepcopy(response)
        return 0.12

    g.api._get_margin_rate = respond
    margin, fee, source = g.margin("SHFE.rb2701", "BUY")
    assert (
        margin == D("2101.4123")
        and fee == D("0.3002")
        and source["source"] == "TQKQ_PRE_INSERT"
    )


def test_observe_gateway_cannot_submit_or_cancel():
    from guiyi_quant.tq_simulation.gateway import Gateway

    g = Gateway.__new__(Gateway)
    g.execution_allowed = False
    with pytest.raises(ValueError, match="OBSERVE_ONLY"):
        g.submit("SHFE.rb2701", None, "OPEN", "native")
    with pytest.raises(ValueError, match="OBSERVE_ONLY"):
        g.cancel("native")


def test_pending_order_reversal_and_pause_trigger_tick_without_waiting_180(tmp_path):
    from guiyi_quant.tq_simulation.worker import should_tick

    c, now = live_controller(tmp_path)
    tx = c.tick((fact(now),), now, opening_allowed=True)
    row = native_order(c, tx.effects[0].order)
    c.synchronize(
        snapshot(now + timedelta(seconds=1), orders=[row]), now + timedelta(seconds=1)
    )
    state = c.store.current()
    assert not should_tick(state, now + timedelta(seconds=2))
    assert should_tick(state, now + timedelta(seconds=2), opening_allowed=False)
    assert should_tick(state, now + timedelta(seconds=2), stopping=True)
    assert should_tick(state, now + timedelta(seconds=182))
    p = state.products[0]
    reversed_state = replace(state, products=(replace(p, desired=-1),))
    assert should_tick(reversed_state, now + timedelta(seconds=2))
    c.close()


def test_margin_queries_refresh_shared_slot_and_rounded_cache_for_a_b_a():
    from types import SimpleNamespace
    from guiyi_quant.tq_simulation.gateway import Gateway

    g = Gateway.__new__(Gateway)
    g.notifications, g.connections, g.reconnection_required = set(), {}, False
    g.account, g.account_key = object(), "key"
    g.quote = lambda symbol: {"instrument_id": symbol, "commission": 3}
    slots = {"key_user": {"pre_margin": 99}}
    cache = {("key", "SHFE.rb2701", "BUY"): 0.12}
    g.api = SimpleNamespace(
        _requests={"margin_rates": cache},
        _data={"trade": {"key": {"pre_insert_orders": slots}}},
        _account=SimpleNamespace(_get_account_id=lambda _: "user"),
    )
    calls = []

    def respond(q, side, account):
        symbol = q["instrument_id"]
        assert ("key", symbol, side) not in cache and "key_user" not in slots
        calls.append(symbol)
        exchange, instrument = symbol.split(".")
        slots["key_user"] = dict(
            exchange_id=exchange,
            instrument_id=instrument,
            direction=side,
            pre_margin=1000 + len(calls),
            pre_commission=3,
        )
        cache[("key", symbol, side)] = 0.12
        return 0.12

    g.api._get_margin_rate = respond
    assert [
        g.margin(s, "BUY")[0] for s in ("SHFE.rb2701", "DCE.i2701", "SHFE.rb2701")
    ] == [D(1001), D(1002), D(1003)]


@pytest.mark.parametrize(
    "mutation,code",
    [
        (dict(offset="CLOSETODAY"), "OFFSET_INVALID"),
        (dict(limit_price="1001"), "PRICE_DRIFT"),
        (dict(price_type="ANY"), "PRICE_DRIFT"),
    ],
)
def test_remote_order_must_match_exact_persisted_submission(tmp_path, mutation, code):
    c, now = live_controller(tmp_path)
    tx = c.tick((fact(now),), now, opening_allowed=True)
    row = {**native_order(c, tx.effects[0].order), **mutation}
    with pytest.raises(ValueError, match=code):
        c.synchronize(
            snapshot(now + timedelta(seconds=1), orders=[row]),
            now + timedelta(seconds=1),
        )
    assert len(c.gateway.calls) == 1
    c.close()


def test_projection_does_not_claim_expired_readback_or_zero_frozen(tmp_path):
    from guiyi_quant.tq_simulation.monitor import projection

    c, now = live_controller(tmp_path)
    s = snapshot(now)
    payload = projection(
        c,
        s,
        now + timedelta(minutes=1),
        mode="trade",
        opening=False,
        source_issues={"RB": "TQ_QUOTE_STALE"},
    )
    assert payload["overview"]["readback_status"] == "unverified"
    assert payload["overview"]["issues"][0]["product"] == "RB"
    c.close()


def test_pending_open_cancel_cutoff_fires_before_180_second_timeout(tmp_path):
    from guiyi_quant.tq_simulation.worker import should_tick

    c, now = live_controller(tmp_path)
    tx = c.tick((fact(now),), now, opening_allowed=True)
    row = native_order(c, tx.effects[0].order)
    c.synchronize(
        snapshot(now + timedelta(seconds=1), orders=[row]), now + timedelta(seconds=1)
    )
    at = now + timedelta(seconds=90)
    c.synchronize(snapshot(at, orders=[row]), at)
    session = replace(fact(at).session, final_close_at=at + timedelta(seconds=60))
    facts = {("RB", "RB2701"): dict(contract="RB2701", session=codec.encode(session))}
    assert should_tick(c.store.current(), at, facts=facts)
    f = replace(
        fact(at),
        session=replace(session, source_id="fresh-cancel-session"),
        instrument=replace(fact(at).instrument, source_id="fresh-cancel-metadata"),
        quote=None,
    )
    tx = c.store.execute("cutoff", m.TqKqTick(at, (f,), True))
    assert [e.kind for e in tx.effects] == ["CANCEL"]
    c.dispatch(tx.effects[0], f, at, opening_allowed=True)
    assert len(c.gateway.calls) == 2
    c.close()


def test_managed_position_can_pass_preflight_after_complete_recovery(tmp_path):
    from guiyi_quant.tq_simulation.worker import preflight_ready

    c, now = live_controller(tmp_path)
    s, _ = full_fill(c, now)
    assert preflight_ready(c, s, {}, {"RB"}, ("RB",), now + timedelta(seconds=5))
    assert not preflight_ready(c, s, {}, {"RB"}, ("RB",), now + timedelta(seconds=40))
    assert not preflight_ready(
        c, s, {"RB": "UNKNOWN"}, {"RB"}, ("RB",), now + timedelta(seconds=5)
    )
    c.close()


def test_market_timeout_discards_channel_and_never_reads_late_response(monkeypatch):
    from types import SimpleNamespace
    from io import BytesIO
    from guiyi_quant.tq_simulation.market import Market

    mkt = Market.__new__(Market)
    mkt.failed, mkt.buffer = False, b""
    stdin = BytesIO()
    mkt.process = SimpleNamespace(stdin=stdin, stdout=object())

    class Timeout:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def register(self, *_):
            pass

        def select(self, *_):
            return []

    monkeypatch.setattr(
        "guiyi_quant.tq_simulation.market.selectors.DefaultSelector", Timeout
    )
    with pytest.raises(ValueError, match="MARKET_TIMEOUT"):
        mkt.request(dict(mode="poll"))
    size = len(stdin.getvalue())
    with pytest.raises(ValueError, match="CHANNEL_FAILED"):
        mkt.request(dict(mode="poll"))
    assert len(stdin.getvalue()) == size


def test_sdk_internal_margin_wait_records_reconnect():
    from types import SimpleNamespace
    from guiyi_quant.tq_simulation.gateway import Gateway
    g = Gateway.__new__(Gateway)
    g.notifications, g.connections, g.reconnection_required = set(), {}, False
    g.account, g.account_key = object(), "fixture"
    g.quote = lambda _: {}
    def respond(*_):
        g.api._data.update(notify={"new": {"code": 2019112902, "conn_id": "trade"}})
        g.api._data["trade"] = {"fixture": {"pre_insert_orders": {"fixture_user": {
            "exchange_id": "SHFE", "instrument_id": "rb2701", "direction": "BUY",
            "pre_margin": 1000, "pre_commission": 3}}}}
    g.api = SimpleNamespace(_requests={"margin_rates": {}}, _data={},
        _get_margin_rate=respond, _account=SimpleNamespace(_get_account_id=lambda _: "user"))
    assert g.margin("SHFE.rb2701", "BUY")[0] == D(1000)
    assert g.reconnection_required


def test_continuity_guard_prevents_claim_before_native_send(tmp_path):
    c, now = live_controller(tmp_path)
    def reconnect():
        raise ValueError("TQ_RECOVERY_REQUIRED")
    c.gateway.assert_continuity = reconnect
    with pytest.raises(ValueError, match="TQ_RECOVERY_REQUIRED"):
        c.tick((fact(now),), now, opening_allowed=True)
    assert c.gateway.calls == []
    assert c.journal.db.execute("SELECT COUNT(*) FROM claims").fetchone()[0] == 0
    assert len(c.store.current().orders) == 1  # persisted proposal, never erased/retried
    c.close()


def test_gateway_final_guard_blocks_submit_and_cancel():
    from guiyi_quant.tq_simulation.gateway import Gateway
    g = Gateway.__new__(Gateway)
    g.execution_allowed, g.reconnection_required = True, True
    g.snapshot = lambda _: {}
    for invoke in (lambda: g.submit("SHFE.rb2701", None, "OPEN", "native"),
                   lambda: g.cancel("native")):
        with pytest.raises(ValueError, match="TQ_RECOVERY_REQUIRED"):
            invoke()


def test_never_active_restart_keeps_baseline_and_accepts_only_new_signal(tmp_path):
    c = Controller(tmp_path, A, ("RB",), Transport())
    initial_at = datetime.now(UTC) - timedelta(hours=1)
    c.bootstrap(snapshot(initial_at), initial_at)
    original = c.store.current()
    c.close()
    c = Controller(tmp_path, A, ("RB",), Transport())
    now = datetime.now(UTC) - timedelta(seconds=5)
    readback = c.synchronize(snapshot(now), now)
    assert c.resume_never_active(readback, now)
    resumed = c.store.current()
    assert resumed.activated_at == original.activated_at
    assert resumed.products[0].wait_after == now
    assert resumed.phase == "READY" and not resumed.blocked_products
    c.close()
    c = Controller(tmp_path, A, ("RB",), Transport())
    assert c.store.replay() == resumed
    second = now + timedelta(microseconds=1)
    second_rb = c.synchronize(snapshot(second), second)
    assert c.resume_never_active(second_rb, second)
    assert c.store.current().activated_at == original.activated_at
    c.bind_symbol("SHFE.rb2701", "RB", "RB2701")
    c.owner("RB", "RB2701", second, "new-owner")
    c.signal(signal(second))  # bar precedes resume; cannot create a target
    assert c.store.current().products[0].desired == 0
    fresh = now + timedelta(seconds=2)
    c.signal(signal(fresh))
    assert not c.resume_never_active(readback, now)
    c.synchronize(snapshot(fresh), fresh)
    tick_at = fresh + timedelta(seconds=1)
    tx = c.tick((fact(tick_at),), tick_at, opening_allowed=True)
    assert len(tx.effects) == 1 and len(c.gateway.calls) == 1
    assert c.store.replay() == c.store.current()
    c.close()


@pytest.mark.parametrize("change", ["orders", "trades", "used"])
def test_empty_resume_rejects_remote_activity(change):
    from guiyi_quant.htdy_execution import OrderReport
    at = T + timedelta(seconds=1)
    state = apply(start(A, ("RB",), T, rb()), "disconnect", m.Disconnect(at)).state
    readback = replace(rb(at), source_id="tq-readback:fixture")
    if change == "orders":
        readback = replace(readback, snapshot=replace(readback.snapshot,
            orders=(OrderReport("external:one", "CANCELLED"),)))
    elif change == "trades":
        readback = replace(readback, confirmed_trade_ids=("external:trade",))
    else:
        readback = replace(readback, used_margin=D(1))
    cmd = m.TqKqResumeEmptyV1(readback, codec.digest({"account_id": A, "claims": []}))
    with pytest.raises(ValueError, match="REQUIRES_NATIVE_FLAT"):
        apply(state, "resume", cmd)
