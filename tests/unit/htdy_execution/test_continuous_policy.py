"""Offline replay safety for managed commands; no Broker or production ledger."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
import json

import pytest

from guiyi_quant import htdy_account_execution as a
from guiyi_quant import htdy_execution as h
from guiyi_quant.htdy_account_execution import codec


T = datetime(2026, 10, 27, 1, tzinfo=UTC)


def readback(at=T, *, positions=(), orders=(), trades=(), used="0"):
    return a.Readback(
        h.AccountSnapshot("account", at, D("100000"), D("100000"), positions, orders),
        D(used),
        D(0),
        D(0),
        (),
        trades,
        "native:" + at.isoformat(),
        at + timedelta(days=1),
        True,
    )


def step(state, cmd):
    return a.apply(state, f"cmd-{len(state.receipts)}", cmd)


def initial():
    state = a.start("account", ("RB", "JM"), T, readback())
    for product in ("RB", "JM"):
        state = step(
            state, h.Owner(product, product + "2701", T, "owner:" + product)
        ).state
    return state


def signal(product, direction="buy", minute=60, previous=None):
    end = T + timedelta(minutes=minute)
    return h.Signal(
        f"signal:{product}:{minute}",
        product,
        product + "2701",
        end,
        end + timedelta(seconds=2),
        previous,
        (direction,),
        "a" * 64,
    )


def fact(product, at):
    contract = product + "2701"
    return a.ExecutionInput(
        a.Instrument(
            product,
            contract,
            T,
            T + timedelta(days=1),
            "instrument:" + product,
            D(1),
            D(10),
            D("0.1"),
            D("0.1"),
            D(3),
        ),
        a.Session(
            contract,
            T,
            T + timedelta(days=1),
            "session:" + product,
            T + timedelta(hours=6),
            True,
            True,
        ),
        a.Quote(
            contract,
            at,
            at + timedelta(seconds=10),
            "quote:" + product,
            D(999),
            D(1000),
            1,
            1,
            D(1),
            D(100000),
        ),
    )


def opened_two():
    state = initial()
    for product in ("RB", "JM"):
        state = step(state, signal(product)).state
    at = T + timedelta(minutes=61)
    tx = step(state, a.Tick(at, (fact("RB", at), fact("JM", at))))
    assert len(tx.effects) == 2  # Legacy Tick remains capable of both OPENs.
    state = tx.state
    fills = []
    for effect in tx.effects:
        order = effect.order
        state = step(
            state,
            a.OrderUpdate(
                "account",
                order.order_id,
                at + timedelta(seconds=1),
                "accepted:" + order.product,
                "WORKING",
                at + timedelta(seconds=1),
            ),
        ).state
        fill = h.Fill(
            "fill:" + order.product,
            order.order_id,
            "account",
            order.contract,
            at + timedelta(seconds=2),
            at + timedelta(seconds=3),
            order.price,
            D(3),
            1,
        )
        state = step(state, fill).state
        fills.append(fill)
    native_orders = tuple(
        h.OrderReport(effect.order.order_id, "FILLED") for effect in tx.effects
    )
    state = step(
        state,
        readback(
            T + timedelta(minutes=62),
            positions=state.positions,
            orders=native_orders,
            trades=tuple(fill.trade_id for fill in fills),
            used="2000",
        ),
    ).state
    return state


def test_managed_tick_never_opens_or_reserves_and_rejects_true_flag():
    state = step(initial(), signal("RB")).state
    at = T + timedelta(minutes=61)
    command = a.ManagedTickV1(at, (fact("RB", at),))
    assert command.opening_allowed is False
    with pytest.raises(ValueError, match="MANAGED_TICK_POLICY_INVALID"):
        a.ManagedTickV1(at, (fact("RB", at),), opening_allowed=True)
    tx = step(state, command)
    assert tx.effects == ()
    assert tx.state.orders == tx.state.reservations == tx.state.risk_decisions == ()
    assert tx.state.products[0].desired == 1
    assert tx.state.products[0].opening_consumed is False


def test_managed_tick_cancels_existing_accepted_open_obligation():
    state = step(initial(), signal("RB")).state
    at = T + timedelta(minutes=61)
    opened = step(state, a.Tick(at, (fact("RB", at),)))
    order = opened.effects[0].order
    accepted_at = at + timedelta(seconds=1)
    state = step(
        opened.state,
        a.OrderUpdate(
            "account",
            order.order_id,
            accepted_at,
            "accepted:rb",
            "WORKING",
            accepted_at,
        ),
    ).state
    later = at + timedelta(seconds=2)
    tx = step(state, a.ManagedTickV1(later, (fact("RB", later),)))
    assert [effect.kind for effect in tx.effects] == ["CANCEL"]
    assert len(tx.state.reservations) == 1
    assert len(tx.state.orders) == 1


def test_managed_tick_serializes_close_submissions_without_blocking_close():
    state = opened_two()
    for product in ("RB", "JM"):
        state = step(
            state, signal(product, "sell", 120, T + timedelta(minutes=60))
        ).state
    at = T + timedelta(minutes=121)
    tx = step(state, a.ManagedTickV1(at, (fact("RB", at), fact("JM", at))))
    assert len(tx.effects) == 1
    assert tx.effects[0].kind == "SUBMIT"
    assert tx.effects[0].order.offset == "CLOSE"
    assert tx.state.reservations == state.reservations
    assert len(tx.state.orders) == len(state.orders) + 1
    later = at + timedelta(seconds=2)
    tx2 = step(tx.state, a.ManagedTickV1(later, (fact("RB", later), fact("JM", later))))
    assert not any(effect.kind == "SUBMIT" for effect in tx2.effects)
    order = tx.effects[0].order
    fill = h.Fill(
        "close:" + order.product,
        order.order_id,
        "account",
        order.contract,
        at + timedelta(seconds=3),
        at + timedelta(seconds=4),
        order.price,
        D(3),
        1,
    )
    filled = step(tx2.state, fill).state
    later = at + timedelta(seconds=5)
    assert not any(
        effect.kind == "SUBMIT"
        for effect in step(
            filled, a.ManagedTickV1(later, (fact("RB", later), fact("JM", later)))
        ).effects
    )


def test_product_recovery_only_unblocks_named_product_and_keeps_healthy_target():
    state = initial()
    state = step(state, signal("RB")).state
    state = step(state, signal("JM")).state
    state = step(state, signal("RB", minute=120, previous=None)).state
    assert state.blocked_products == ("RB",)
    healthy = next(p for p in state.products if p.product == "JM")
    at = T + timedelta(minutes=121)
    cmd = a.ProductRecoveryV1(
        readback(at),
        (h.RecoveryInput("RB", "RB2701", 1, T + timedelta(minutes=120), "proof-rb"),),
        ("RB",),
    )
    tx = step(state, cmd)
    assert tx.state.blocked_products == ()
    assert next(p for p in tx.state.products if p.product == "JM") == healthy
    recovered = next(p for p in tx.state.products if p.product == "RB")
    assert recovered.desired == 0 and recovered.opening_consumed
    assert recovered.wait_after == at
    assert recovered.last_bar == T + timedelta(minutes=120)
    assert tx.state.reservations == () and tx.effects == ()
    assert a.apply(tx.state, f"cmd-{len(state.receipts)}", cmd).state == tx.state


def test_product_recovery_rejects_healthy_scope_and_invalid_proof():
    state = initial()
    at = T + timedelta(minutes=1)
    cmd = a.ProductRecoveryV1(readback(at), (), ("JM",))
    with pytest.raises(ValueError, match="PRODUCT_NOT_BLOCKED"):
        step(state, cmd)
    with pytest.raises(ValueError, match="PRODUCT_RECOVERY_INVALID"):
        a.ProductRecoveryV1(
            readback(at), (h.RecoveryInput("RB", "RB2701", 0, T, "rb"),), ("JM",)
        )


def test_restart_requires_full_account_recover_before_product_recovery(tmp_path):
    path = tmp_path / "journal.sqlite"
    store = a.LocalStore(path, initial())
    store.execute("rb-first", signal("RB"))
    store.execute("rb-gap", signal("RB", minute=120, previous=None))
    assert store.current().blocked_products == ("RB",)
    store.close()
    reopened = a.LocalStore(path)
    at = T + timedelta(minutes=121)
    rb_proof = h.RecoveryInput("RB", "RB2701", 1, T + timedelta(minutes=120), "rb")
    with pytest.raises(a.StoreError, match="NATIVE_RECOVERY_REQUIRED"):
        reopened.execute(
            "local-only", a.ProductRecoveryV1(readback(at), (rb_proof,), ("RB",))
        )
    full = a.Recover(
        readback(at), (rb_proof, h.RecoveryInput("JM", "JM2701", 0, T, "jm"))
    )
    assert reopened.execute("full-recover", full).state.phase == "READY"
    assert reopened.replay() == reopened.current()
    reopened.close()


def test_v2_checkpoint_and_old_tick_replay_remain_stable_with_new_codec_classes():
    state = step(initial(), signal("RB")).state
    at = T + timedelta(minutes=61)
    old = a.Tick(at, (fact("RB", at),))
    before_hash = codec.digest(old)
    tx = step(state, old)
    packet = json.loads(a.checkpoint(tx.state))
    assert packet["body"]["policy"] == "htdy_60m_account_execution_v2"
    assert codec.digest(old) == before_hash
    assert codec.load(json.dumps(packet)) == tx.state
    assert codec.decode(
        codec.encode(a.ManagedTickV1(at, (fact("RB", at),)))
    ) == a.ManagedTickV1(at, (fact("RB", at),))
