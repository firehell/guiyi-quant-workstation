from types import SimpleNamespace as NS
from app.tq_simulation_market import recovery_batch, BATCH_PRODUCTS


def state(phase="READY", blocked=None):
    products = tuple(
        NS(product="P" + str(i), owner="contract" + str(i)) for i in range(60)
    )
    return NS(
        phase=phase,
        products=products,
        blocked_products=tuple(p.product for p in products)
        if blocked is None
        else blocked,
        positions=tuple(NS(product="P" + str(i)) for i in (11, 22, 33, 44)),
    )


def test_recovery_batches_cover_all_without_starving_unavailable_held():
    s = state()
    cursor = 0
    seen = set()
    for _ in range(15):
        batch, cursor = recovery_batch(s, cursor)
        assert len(batch) == BATCH_PRODUCTS
        seen.update(batch)
    assert seen == {p.product for p in s.products}


def test_full_recovery_prioritizes_held_and_does_not_invent_unknown_owner():
    s = state("RECOVERY_REQUIRED")
    s.products += (NS(product="UNKNOWN", owner=None),)
    batch, _ = recovery_batch(s, 37)
    assert set(batch) == {p.product for p in s.positions}


def test_ready_recovery_only_selects_known_blocked_and_rotates_shrinking_set():
    s = state(blocked=("P2", "P3"))
    s.products += (NS(product="UNOWNED", owner=None),)
    s.blocked_products += ("UNOWNED",)
    assert recovery_batch(s, 0)[0] == ("P2", "P3")
    s.blocked_products = ()
    assert recovery_batch(s, 99) == ((), 0)


def test_bridge_bounds_signal_and_recovery_work_in_same_request(monkeypatch):
    import io
    import json
    from datetime import datetime, UTC
    from app import tq_simulation_market as bridge

    products = tuple(chr(65 + i) for i in range(20))
    s = NS(
        phase="READY",
        products=tuple(
            NS(product=p, owner=p + "2701", last_bar=None) for p in products
        ),
        blocked_products=products,
        positions=(),
        activated_at=datetime.now(UTC),
    )

    class Market:
        started = s.activated_at

        def __init__(self, chosen, *, record_closed_tails=False):
            assert chosen == products and record_closed_tails
            self.closed_tails = {}

        def activate(self, now):
            pass

        def poll(self, now, after, *, max_products):
            assert max_products == 4
            return tuple(
                NS(product=p, contract=p + "2701", source_id=p) for p in products[:max_products]
            )

        def recovery(self, state, now, *, products):
            assert len(products) <= 4
            return products

        def close(self):
            pass

        issues = {}

    request = {
        "mode": "poll",
        "request_id": "a" * 32,
        "state": "checkpoint",
        "contracts": [],
    }
    monkeypatch.setattr(
        bridge, "load_operational_products", lambda: tuple(p.lower() for p in products)
    )
    monkeypatch.setattr(bridge, "PortfolioMarket", Market)
    monkeypatch.setattr(bridge, "load_market_state", lambda _: s)
    monkeypatch.setattr(
        bridge.codec, "encode", lambda p: p if isinstance(p, str) else p.product
    )
    monkeypatch.setattr(
        bridge,
        "authority",
        lambda market, product, now, contract, trading_day=None: {
            "product": product,
            "contract": contract,
        },
    )
    monkeypatch.setattr(
        bridge.sys,
        "stdin",
        NS(buffer=io.BytesIO((json.dumps(request) + "\n").encode())),
    )
    output = io.StringIO()
    monkeypatch.setattr(bridge.sys, "stdout", output)
    assert bridge.main() == 0
    response = json.loads(output.getvalue())
    assert (
        response["status"] == "ok" and response["request_id"] == request["request_id"]
    )
    assert (
        len(response["signals"])
        == len(response["facts"])
        == len(response["recovery"])
        == 4
    )
