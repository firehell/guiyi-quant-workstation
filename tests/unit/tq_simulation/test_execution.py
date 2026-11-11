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
    c.signal(s, processed_at=s.observed_at)
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
    c.signal(reverse, processed_at=reverse.observed_at)
    c.synchronize(s, at + timedelta(seconds=1))
    at += timedelta(seconds=2)
    f = fact(at)
    tx = c.store.execute("close-tick", m.TqKqTick(at, (f,), True))
    assert tx.effects[0].order.offset == "CLOSE"
    c.clock = lambda: at
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
    c.clock = lambda: at
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
    stdin.fileno = lambda: 123
    monkeypatch.setattr("guiyi_quant.tq_simulation.market.os.set_blocking", lambda *_: None)
    clock = iter((0, 21))
    monkeypatch.setattr("time.monotonic", lambda: next(clock))
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
        g.api._data["trade"] = {
            "fixture": {
                "pre_insert_orders": {
                    "fixture_user": {
                        "exchange_id": "SHFE",
                        "instrument_id": "rb2701",
                        "direction": "BUY",
                        "pre_margin": 1000,
                        "pre_commission": 3,
                    }
                }
            }
        }

    g.api = SimpleNamespace(
        _requests={"margin_rates": {}},
        _data={},
        _get_margin_rate=respond,
        _account=SimpleNamespace(_get_account_id=lambda _: "user"),
    )
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
    assert (
        len(c.store.current().orders) == 1
    )  # persisted proposal, never erased/retried
    c.close()


def test_gateway_final_guard_blocks_submit_and_cancel():
    from guiyi_quant.tq_simulation.gateway import Gateway

    g = Gateway.__new__(Gateway)
    g.execution_allowed, g.reconnection_required = True, True
    g.snapshot = lambda _: {}
    for invoke in (
        lambda: g.submit("SHFE.rb2701", None, "OPEN", "native"),
        lambda: g.cancel("native"),
    ):
        with pytest.raises(ValueError, match="TQ_RECOVERY_REQUIRED"):
            invoke()


def test_never_active_restart_keeps_baseline_and_accepts_only_new_signal(tmp_path):
    c = Controller(tmp_path, A, ("RB",), Transport())
    initial_at = datetime.now(UTC) - timedelta(hours=1)
    c.bootstrap(snapshot(initial_at), initial_at)
    original = c.store.current()
    # Prior ordinary recovery may stamp signal_at without any strategy input.
    c.recover(c.readback(snapshot(initial_at), initial_at), ())
    assert len(c.store.current().blocked_products) == 1
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
    c.signal(
        signal(second), processed_at=second
    )  # bar precedes resume; cannot create a target
    assert c.store.current().products[0].desired == 0
    fresh = now + timedelta(seconds=2)
    c.signal(signal(fresh), processed_at=fresh)
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
        readback = replace(
            readback,
            snapshot=replace(
                readback.snapshot, orders=(OrderReport("external:one", "CANCELLED"),)
            ),
        )
    elif change == "trades":
        readback = replace(readback, confirmed_trade_ids=("external:trade",))
    else:
        readback = replace(readback, used_margin=D(1))
    cmd = m.TqKqResumeEmptyV1(readback, codec.digest({"account_id": A, "claims": []}))
    with pytest.raises(ValueError, match="REQUIRES_NATIVE_FLAT"):
        apply(state, "resume", cmd)


def test_batched_receipts_keep_original_time_after_account_clock_advances(
    tmp_path, monkeypatch
):
    from dataclasses import replace
    from guiyi_quant.htdy_account_execution.store import LocalStore

    now = datetime.now(UTC)
    base = now - timedelta(minutes=5)
    c = Controller(tmp_path, A, ("RB", "AG"), Transport())
    c.bootstrap(snapshot(base), base)
    c.owner("RB", "RB2701", base, "rb-owner")
    first = m.Signal(
        "batch-rb",
        "RB",
        "RB2701",
        now - timedelta(minutes=1),
        now - timedelta(seconds=2),
        None,
        (),
        "a" * 64,
    )
    c.signal(first, processed_at=now)
    advanced = now + timedelta(seconds=5)
    c.synchronize(snapshot(advanced), advanced)
    processed = now + timedelta(seconds=6)
    c.owner("AG", "AG2612", processed, "ag-owner")
    second = m.Signal(
        "batch-ag",
        "AG",
        "AG2612",
        now - timedelta(minutes=1),
        now - timedelta(seconds=1),
        None,
        (),
        "b" * 64,
    )
    c.signal(second, processed_at=processed)
    s = c.store.current()
    assert s.signals == (first, second) and s.clock == processed
    assert type(s.audit[-1].command) is m.TqKqObservedSignalV1
    count = len(s.audit)
    processed += timedelta(seconds=1)
    c.signal(second, processed_at=processed)
    assert len(c.store.current().audit) == count
    with pytest.raises(ValueError, match="TQ_SIGNAL_IDENTITY_DRIFT"):
        c.signal(replace(second, input_hash="c" * 64))
    with pytest.raises(ValueError, match="COMMAND_TIME_REGRESSION"):
        c.store.execute(
            "unversioned-regression",
            replace(
                second,
                source_id="generic-late",
                bar_end=second.bar_end + timedelta(seconds=1),
            ),
        )
    c.close()
    replay = LocalStore.inspect(tmp_path / "account.sqlite")
    assert replay.signals == (first, second) and replay.clock == s.clock


def test_versioned_signal_rejects_processing_before_receipt():
    now = datetime.now(UTC)
    sig = m.Signal(
        "future", "RB", "RB2701", now - timedelta(minutes=1), now, None, (), "d" * 64
    )
    with pytest.raises(ValueError, match="TQ_SIGNAL_PROCESSING_TIME_INVALID"):
        m.TqKqObservedSignalV1(sig, now - timedelta(seconds=1))


@pytest.mark.parametrize("directions", [("buy",), ("sell",), ("buy", "sell"), ()])
def test_closed_signal_records_fact_and_continuity_without_target_or_order_effects(directions):
    before = initial()
    end = T + timedelta(hours=1)
    sig = m.Signal("tail", "RB", "RB2701", end, end + timedelta(seconds=2),
                   None, directions, "f" * 64)
    cmd = m.TqKqClosedSignalV1(sig, end + timedelta(seconds=5), end)
    result = apply(before, "tail", cmd)
    after = result.state
    assert after.signals == (sig,)
    assert after.products[0] == replace(before.products[0], last_bar=end)
    assert after.orders == before.orders and after.reservations == before.reservations
    assert after.abandoned == before.abandoned and not result.effects
    assert after.audit[-1].reason == "CLOSED_SIGNAL_RECORDED"
    from guiyi_quant.htdy_account_execution.codec import encode, decode
    assert decode(encode(cmd)) == cmd
    # Next-session continuity uses the terminal Bar; the tail created no target.
    fresh = replace(sig, source_id="fresh", bar_end=end+timedelta(hours=12),
                    observed_at=end+timedelta(hours=12,seconds=2), previous_bar_end=end)
    nxt = apply(after, "fresh", m.TqKqObservedSignalV1(fresh, fresh.observed_at)).state
    assert nxt.blocked_products == () and nxt.products[0].last_bar == fresh.bar_end


@pytest.mark.parametrize("offset", [61, -1])
def test_closed_signal_rejects_expired_or_wrong_terminal_receipt(offset):
    end = T+timedelta(hours=1)
    sig = m.Signal("tail", "RB", "RB2701", end, end+timedelta(seconds=61 if offset==61 else 1), None, (), "a"*64)
    with pytest.raises(ValueError, match="TQ_CLOSED_SIGNAL_INVALID"):
        m.TqKqClosedSignalV1(sig, end+timedelta(seconds=100), end+timedelta(seconds=2) if offset==-1 else end)


def test_closed_signal_wrong_owner_blocks_without_replacing_owner_or_other_product():
    before = initial()
    end = T+timedelta(hours=1)
    sig = m.Signal("tail", "RB", "RB2705", end, end+timedelta(seconds=2), None, ("buy",), "a"*64)
    after = apply(before, "tail", m.TqKqClosedSignalV1(sig, end+timedelta(seconds=5), end)).state
    assert after.products == before.products and after.orders == before.orders
    assert after.blocked_products == ("RB",)


def test_closed_signal_real_sqlite_replay_and_restart_preserve_targets(tmp_path):
    from guiyi_quant.htdy_account_execution.store import LocalStore
    end = T+timedelta(hours=1)
    c = Controller(tmp_path,A,("RB",),Transport())
    c.bootstrap(snapshot(T),T)
    c.owner("RB","RB2701",T,"owner")
    before = c.store.current()
    sig=m.Signal("tail-db","RB","RB2701",end,end+timedelta(seconds=2),None,("buy",),"a"*64)
    c.signal(sig,processed_at=end+timedelta(seconds=3),closed_at=end)
    accepted=c.store.current()
    assert accepted.products[0] == replace(before.products[0],last_bar=end)
    assert accepted.positions==before.positions and accepted.orders==before.orders
    assert accepted.reservations==before.reservations and not c.journal.mappings()
    c.signal(sig,processed_at=end+timedelta(seconds=5),closed_at=end)
    assert c.store.current()==accepted==c.store.replay()
    c.close()
    assert LocalStore.inspect(tmp_path/"account.sqlite")==accepted
    reopened=Controller(tmp_path,A,("RB",),Transport())
    assert reopened.store.current().phase=="RECOVERY_REQUIRED"
    assert reopened.store.current().products==accepted.products
    reopened.close()


def test_projection_cache_reuses_state_and_detects_external_projection_corruption(tmp_path, monkeypatch):
    import sqlite3
    store = LocalStore(tmp_path / 'account.sqlite', initial())
    first = store.current()
    def forbidden(*_args, **_kwargs):
        raise AssertionError('unchanged committed state was decoded again')
    with monkeypatch.context() as patch:
        patch.setattr(codec, 'load', forbidden)
        assert store.current() is first
    other = sqlite3.connect(store.path)
    other.execute('UPDATE projection SET sequence=sequence+1')
    other.commit()
    other.close()
    with pytest.raises(StoreError, match='PROJECTION_JOURNAL_MISMATCH'):
        store.current()
    store.close()


def test_market_packet_is_independent_of_history_size():
    from guiyi_quant.tq_simulation.market import market_state, load_market_state
    from types import SimpleNamespace as NS
    import json
    s = initial()
    packet = market_state(s)
    restored = load_market_state(packet)
    assert restored.products[0].owner == s.products[0].owner
    assert restored.activated_at == s.activated_at
    expanded = NS(**{**s.__dict__, 'audit': ('x' * 1000000,) * 30})
    assert market_state(expanded) == packet
    assert len(json.dumps(packet)) < 2000
    with pytest.raises(ValueError, match='TQ_MARKET_STATE_INVALID'):
        load_market_state({**packet, 'audit': []})


def test_closed_session_does_not_tick_rollover_obligation():
    from guiyi_quant.tq_simulation.worker import should_tick
    s = initial()
    s = replace(s, positions=(m.Position('RB', 'RB2701', -1),),
                products=(replace(s.products[0], owner='RB2705', rolling=True, must_close=True,
                                  signal_id='verified-rollover'),))
    session = replace(fact(T).session, can_trade=False, can_cancel=False)
    facts = {('RB', 'RB2701'): dict(contract='RB2701', session=codec.encode(session))}
    assert not should_tick(s, T, facts=facts)
    facts[('RB', 'RB2701')]['session'] = codec.encode(replace(session, can_trade=True))
    assert should_tick(s, T, facts=facts)


def test_pipe_backpressure_has_deadline_and_pumps_sdk(monkeypatch):
    import os
    from types import SimpleNamespace as NS
    from guiyi_quant.tq_simulation.market import Market
    import time
    read_fd, write_fd = os.pipe()
    os.set_blocking(write_fd, False)
    while True:
        try:
            os.write(write_fd, b'x' * 65536)
        except BlockingIOError:
            break
    mkt = Market.__new__(Market)
    mkt.failed, mkt.buffer = False, b''
    pumped = []
    elapsed = [0.0]
    mkt.pump = lambda: (pumped.append(True), elapsed.__setitem__(0, elapsed[0] + 21))
    monkeypatch.setattr(time, 'monotonic', lambda: elapsed[0])
    stream = os.fdopen(write_fd, 'wb', buffering=0)
    mkt.process = NS(stdin=stream)
    try:
        with pytest.raises(ValueError, match='TQ_MARKET_TIMEOUT'):
            mkt.request(dict(mode='poll'))
        assert pumped and mkt.failed
    finally:
        stream.close()
        os.close(read_fd)


def test_external_change_immediately_after_commit_invalidates_cache(tmp_path, monkeypatch):
    import sqlite3
    store = LocalStore(tmp_path / 'account.sqlite', initial())
    commit = store._commit
    def raced_commit():
        commit()
        with sqlite3.connect(store.path) as external:
            external.execute('UPDATE projection SET sequence=999')
    monkeypatch.setattr(store, '_commit', raced_commit)
    store.execute('disconnect-cache-race', m.Disconnect(T))
    with pytest.raises(StoreError, match='PROJECTION_JOURNAL_MISMATCH'):
        store.current()
    store.close()


def test_market_drains_response_before_reporting_pump_disconnect():
    import os
    import json
    import threading
    from types import SimpleNamespace as NS
    from guiyi_quant.tq_simulation.market import Market
    request_read, request_write = os.pipe()
    response_read, response_write = os.pipe()
    mkt = Market.__new__(Market)
    mkt.failed, mkt.buffer = False, b''
    mkt.process = NS(stdin=os.fdopen(request_write, 'wb', buffering=0),
                     stdout=os.fdopen(response_read, 'rb', buffering=0))
    def respond():
        with os.fdopen(request_read, 'rb') as incoming, os.fdopen(response_write, 'wb', buffering=0) as outgoing:
            for _ in range(2):
                packet = json.loads(incoming.readline())
                outgoing.write((json.dumps(dict(status='ok', request_id=packet['request_id']))+'\n').encode())
    thread = threading.Thread(target=respond)
    thread.start()
    def disconnect():
        raise ValueError('TQ_DISCONNECTED')
    mkt.pump = disconnect
    try:
        with pytest.raises(ValueError, match='TQ_DISCONNECTED'):
            mkt.request(dict(mode='poll'))
        mkt.pump = lambda: None
        assert mkt.request(dict(mode='poll'))['status'] == 'ok'
        assert not mkt.failed
    finally:
        mkt.process.stdin.close()
        mkt.process.stdout.close()
        thread.join(timeout=2)
    assert not thread.is_alive()


def test_flat_rollover_gets_cleanup_tick():
    from guiyi_quant.tq_simulation.worker import should_tick
    s = initial()
    s = replace(s, products=(replace(s.products[0], rolling=True),))
    assert should_tick(s, T, facts={})
    tx = apply(s, 'flat-rollover-cleanup', m.TqKqTick(T, (), True))
    assert not tx.state.products[0].rolling
    assert not tx.effects


def test_checked_sdk_submit_rechecks_deadline_after_continuity():
    from types import SimpleNamespace as NS
    from guiyi_quant.tq_simulation.gateway import Gateway
    from decimal import Decimal
    g = Gateway.__new__(Gateway)
    g.execution_allowed = True
    calls = []
    g.assert_continuity = lambda: calls.append('continuity')
    g.quote = lambda _: dict(ask_price1=1000, bid_price1=999, price_tick=1)
    g.account = object()
    g.api = NS(insert_order=lambda **_: calls.append('sent'))
    order = NS(price=Decimal(1000), side='BUY')
    with pytest.raises(ValueError, match='TQ_SUBMIT_EXPIRED_NO_SEND'):
        g.submit_checked('SHFE.rb2701', order, 'OPEN', 'unique', datetime.now(UTC)-timedelta(seconds=1))
    assert calls == ['continuity', 'continuity']


def test_final_submit_deadline_includes_opening_cutoff(tmp_path):
    c, now = live_controller(tmp_path)
    f = fact(now)
    f = replace(f, session=replace(f.session, final_close_at=now+timedelta(seconds=62)))
    captured = []
    c.gateway.submit_checked = lambda _symbol, _order, _offset, _native, deadline: captured.append(deadline)
    c.clock = lambda: now
    c.tick((f,), now, opening_allowed=True)
    assert captured == [now+timedelta(seconds=2)]
    c.close()


@pytest.mark.parametrize("after_claim", [False, True])
def test_local_quote_rejection_aborts_proposal_without_sending(tmp_path, after_claim):
    from guiyi_quant.tq_simulation.gateway import SubmissionNotSent

    c, now = live_controller(tmp_path)
    f = fact(now)
    if after_claim:
        def reject(_symbol, _order, _offset, native, _deadline):
            raise SubmissionNotSent("TQ_OPPONENT_PRICE_DRIFT", native_id=native)
        c.gateway.submit_checked = reject
        c.clock = lambda: now
    else:
        f = replace(f, quote=replace(f.quote, valid_until=now + timedelta(seconds=1)))
        c.clock = lambda: f.quote.valid_until
    tx = c.tick((f,), now, opening_allowed=True)
    order = c.store.current().orders[-1]
    assert order.order_id == tx.effects[0].order.order_id
    assert order.status == "LOCAL_ABORTED" and order.reconciled
    assert c.store.current().phase == "READY"
    assert len(c.journal.mappings()) == int(after_claim)
    assert len(c.journal.events("local_not_sent")) == 1
    assert not c.journal.events("queued")
    c.close()


def test_restart_finishes_recorded_unsent_before_missing_claim_check(tmp_path):
    from guiyi_quant.tq_simulation.gateway import SubmissionNotSent

    c, now = live_controller(tmp_path)
    def reject(_symbol, _order, _offset, native, _deadline):
        raise SubmissionNotSent("TQ_OPPONENT_PRICE_DRIFT", native_id=native)
    c.gateway.submit_checked = reject
    c.clock = lambda: now
    execute = c.store.execute
    def interrupted(key, command, **options):
        if isinstance(command, m.AbortUnsent):
            raise OSError("interrupted after writing no-send evidence")
        return execute(key, command, **options)
    c.store.execute = interrupted
    with pytest.raises(OSError):
        c.tick((fact(now),), now, opening_allowed=True)
    assert c.store.current().orders[-1].status == "PROPOSED"
    c.close()

    c = Controller(tmp_path, A, ("RB",), Transport())
    observed = now + timedelta(seconds=30)
    c.clock = lambda: observed + timedelta(seconds=1)
    rb = c.synchronize(snapshot(observed), observed)
    c.recover(rb, ())
    assert c.store.current().orders[-1].status == "LOCAL_ABORTED"
    assert len(c.journal.mappings()) == 1
    assert not c.gateway.calls
    c.close()
