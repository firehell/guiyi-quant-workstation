"""Idle audits use the existing serial connection, yielding at every query stage."""

from datetime import timedelta
import pytest
from test_native_portfolio import Market as BaseMarket, T, portfolio as base_portfolio
from guiyi_quant.simnow_execution.input_evidence import input_check_view


class Market(BaseMarket):
    def authority(self, *args, **kwargs):
        result = super().authority(*args, **kwargs)
        if args[0] == "J":
            result.exchange = "DCE"
        result.owner = result.contract
        return result


def portfolio(tmp_path):
    native = base_portfolio(tmp_path)
    original = native.gateway.query

    def query(kind, *args, **kwargs):
        rows = original(kind, *args, **kwargs)
        product = (
            (args[0] if args else kwargs.get("product", ""))
            .upper()
            .removesuffix("2701")
        )
        if product == "J" and kind in {"instrument", "book"}:
            for row in rows:
                row["ExchangeID"] = "DCE"
        return rows

    native.gateway.query = query
    return native


def turn(native, products=("JM",), **kwargs):
    return native.audit_next(
        products,
        Market(),
        "20261027",
        idle=True,
        obligations_pending=False,
        next_boundary=T + timedelta(minutes=30),
        **kwargs,
    )


def test_one_query_per_turn_and_audit_never_populates_execution_cache(tmp_path):
    native = portfolio(tmp_path)
    for expected in ("instrument", "margin", "commission", "book"):
        before = len(native.gateway.queries)
        result = turn(native)
        assert len(native.gateway.queries) == before + 1
        assert native.gateway.queries[-1][0] == expected
    assert result["status"] == "CHECKED"
    assert native.input_checks["JM"]["purpose"] == "audit"
    assert (
        native.input_checks["JM"]["valid_until"]
        == (T + timedelta(seconds=3)).isoformat()
    )
    assert not native.last_facts
    assert not input_check_view(native.input_checks, T, connected=True)["JM"][
        "execution_permitted"
    ]


@pytest.mark.parametrize(
    "reason", ["execution", "obligation", "boundary", "unknown", "disconnected"]
)
def test_priority_and_unknown_window_never_query(tmp_path, reason):
    native = portfolio(tmp_path)
    args = dict(
        idle=True, obligations_pending=False, next_boundary=T + timedelta(minutes=30)
    )
    if reason == "execution":
        args["idle"] = False
    if reason == "obligation":
        args["obligations_pending"] = True
    if reason == "boundary":
        args["next_boundary"] = T + timedelta(seconds=20)
    if reason == "unknown":
        args["next_boundary"] = None
    if reason == "disconnected":
        native.gateway.login_done.clear()
    result = native.audit_next(("JM",), Market(), "20261027", **args)
    assert result["status"] == "DEFERRED"
    assert native.gateway.queries == []


def test_interrupted_partial_restarts_without_old_rates(tmp_path):
    native = portfolio(tmp_path)
    turn(native)
    turn(native)
    native.audit_next(
        ("JM",),
        Market(),
        "20261027",
        idle=False,
        obligations_pending=False,
        next_boundary=T + timedelta(minutes=30),
    )
    turn(native)  # Cached instrument; no new native query.
    turn(native)
    assert [k for k, _ in native.gateway.queries] == ["instrument", "margin", "margin"]


def test_all_60_products_without_signals_get_a_turn(tmp_path):
    from pathlib import Path

    products = tuple(
        (Path(__file__).parents[3] / "data/universe/operational_products.txt")
        .read_text()
        .upper()
        .split()
    )
    assert len(products) == 60
    native = portfolio(tmp_path)
    complete = []
    for _ in range(240):
        before = len(native.gateway.queries)
        result = turn(native, products)
        assert len(native.gateway.queries) - before <= 1
        if result["status"] == "CHECKED":
            complete.append(result["product"])
    assert complete == list(products)
    assert set(native.input_checks) == set(products)
    assert all(v["purpose"] == "audit" for v in native.input_checks.values())
    assert not native.last_facts


@pytest.mark.parametrize("product", ["AG", "J", "PB", "ZN"])
@pytest.mark.parametrize(
    "offset,delay,reason",
    [
        (-9, 0, "SOURCE_OLD_BEFORE_QUERY"),
        (1, 0, "SOURCE_TIME_IN_FUTURE"),
        (-7, 2, "QUERY_CROSSED_SOURCE_AGE_LIMIT"),
    ],
)
def test_required_products_retain_timing_failure_evidence(
    tmp_path, product, offset, delay, reason
):
    from zoneinfo import ZoneInfo

    native = portfolio(tmp_path)
    clock = [T]
    native.now = lambda: clock[0]
    original = native.gateway.query

    def query(kind, *args, **kwargs):
        rows = original(kind, *args, **kwargs)
        if kind == "book":
            event = T + timedelta(seconds=offset)
            rows[0].update(
                ActionDay=event.strftime("%Y%m%d"),
                UpdateTime=event.astimezone(ZoneInfo("Asia/Shanghai")).strftime(
                    "%H:%M:%S"
                ),
            )
            clock[0] += timedelta(seconds=delay)
        return rows

    native.gateway.query = query
    for _ in range(4):
        result = turn(native, (product,))
    assert result["status"] == "FAILED"
    check = native.input_checks[product]
    assert check["purpose"] == "audit" and check["code"] == "NATIVE_BOOK_STALE"
    assert check["timing_classification"] == reason
    assert not input_check_view(native.input_checks, clock[0], connected=True)[product][
        "fresh"
    ]


def test_failed_product_does_not_starve_following_products(tmp_path):
    native = portfolio(tmp_path)
    native.gateway.fail_product = "AG"
    assert turn(native, ("AG", "PB"))["status"] == "FAILED"
    for _ in range(4):
        result = turn(native, ("AG", "PB"))
    assert result["status"] == "CHECKED" and result["product"] == "PB"


def test_audit_success_expires_or_disconnects_without_becoming_permission(tmp_path):
    native = portfolio(tmp_path)
    for _ in range(4):
        turn(native)
    for now, connected in ((T + timedelta(seconds=3), True), (T, False)):
        check = input_check_view(native.input_checks, now, connected=connected)["JM"]
        assert not check["fresh"] and not check["execution_permitted"]


def test_slow_query_crossing_boundary_invalidates_partial_check(tmp_path):
    native = portfolio(tmp_path)
    clock = [T]
    native.now = lambda: clock[0]
    original = native.gateway.query

    def slow(*args, **kwargs):
        result = original(*args, **kwargs)
        clock[0] += timedelta(seconds=25)
        return result

    native.gateway.query = slow
    result = native.audit_next(
        ("JM",),
        Market(),
        "20261027",
        idle=True,
        obligations_pending=False,
        next_boundary=T + timedelta(seconds=22),
    )
    assert result["status"] == "FAILED"
    assert native.input_checks["JM"]["code"] == "AUDIT_WINDOW_ELAPSED"
    assert len(native.gateway.queries) == 1
    assert not input_check_view(native.input_checks, clock[0], connected=True)["JM"][
        "fresh"
    ]


def test_expired_partial_binding_stops_before_book(tmp_path):
    native = portfolio(tmp_path)
    for _ in range(3):
        turn(native)
    native.now = lambda: T + timedelta(minutes=6)
    before = len(native.gateway.queries)
    assert turn(native)["status"] == "FAILED"
    assert native.input_checks["JM"]["code"] == "AUDIT_BINDING_EXPIRED"
    assert len(native.gateway.queries) == before


class ScopedMarket(Market):
    active = ("AG",)
    boundary = T + timedelta(minutes=30)
    trading_day = T.date()

    def audit_window(self, now):
        from types import SimpleNamespace as NS
        if self.active is None:
            return None
        return NS(products=self.active, boundary=self.boundary, trading_day=self.trading_day)


def scoped_turn(native, market, products=("AG", "AP", "PB"), **overrides):
    args = dict(idle=True, obligations_pending=False,
        next_boundary=T + timedelta(minutes=30))
    args.update(overrides)
    return native.audit_next(products, market, "20261027", **args)


def test_night_audit_only_queries_authoritative_active_products(tmp_path):
    native = portfolio(tmp_path)
    market = ScopedMarket()
    market.active = ("AG", "PB")
    completed = []
    for _ in range(8):
        result = scoped_turn(native, market)
        if result["status"] == "CHECKED":
            completed.append(result["product"])
    assert completed == ["AG", "PB"]
    assert set(native.input_checks) == {"AG", "PB"}
    assert not native.last_facts


@pytest.mark.parametrize("reason", ["unknown", "empty", "boundary", "wrong_day", "foreign"])
def test_scoped_audit_defers_without_query_when_authority_unproven(tmp_path, reason):
    native = portfolio(tmp_path)
    market = ScopedMarket()
    if reason == "unknown":
        market.active = None
    if reason == "empty":
        market.active = ()
    if reason == "boundary":
        market.boundary = T + timedelta(seconds=20)
    if reason == "wrong_day":
        market.trading_day = T.date() + timedelta(days=1)
    if reason == "foreign":
        market.active = ("CU",)
    assert scoped_turn(native, market)["status"] == "DEFERRED"
    assert native.gateway.queries == []


def test_scope_change_drops_closed_partial_and_retains_rotation_until_day_resumes(tmp_path):
    native = portfolio(tmp_path)
    market = ScopedMarket()
    market.active = ("AG", "AP", "PB")
    assert scoped_turn(native, market)["product"] == "AG"
    # This product's Session ends while its staged audit is pending. No more
    # rates/book queries may be sent for it, and the next active cursor wins.
    market.active = ("PB",)
    for _ in range(4):
        result = scoped_turn(native, market)
    assert result["status"] == "CHECKED" and result["product"] == "PB"
    assert [kind for kind, _ in native.gateway.queries] == [
        "instrument", "instrument", "margin", "commission", "book"]
    # Session resumes in day trading. Rotation is against the stable full scope.
    market.active = ("AG", "AP", "PB")
    assert scoped_turn(native, market)["product"] == "AG"
    assert "AP" not in native.input_checks


def test_45_night_products_audited_without_querying_15_closed_products(tmp_path):
    from pathlib import Path

    products = tuple((Path(__file__).parents[3] / "data/universe/operational_products.txt")
        .read_text().upper().split())
    native = portfolio(tmp_path)
    market = ScopedMarket()
    market.active = products[15:]
    complete = []
    for _ in range(4 * 45):
        result = scoped_turn(native, market, products)
        if result["status"] == "CHECKED":
            complete.append(result["product"])
    assert complete == list(market.active)
    assert set(native.input_checks) == set(market.active)
    assert {p for _, p in native.gateway.queries} == set(market.active)


def test_other_product_closing_does_not_restart_pending_active_audit(tmp_path):
    native = portfolio(tmp_path)
    market = ScopedMarket()
    market.active = ("AG", "AP", "PB")
    assert scoped_turn(native, market)["stage"] == "margin"
    market.active = ("AG", "PB")
    assert scoped_turn(native, market)["stage"] == "commission"
    assert scoped_turn(native, market)["stage"] == "book"
    assert scoped_turn(native, market)["status"] == "CHECKED"
    assert scoped_turn(native, market)["product"] == "PB"


def test_slow_authority_read_consumes_reserve_before_any_native_query(tmp_path):
    native = portfolio(tmp_path)
    clock = [T]
    native.now = lambda: clock[0]
    market = ScopedMarket()

    def delayed(now):
        clock[0] = T + timedelta(minutes=30, seconds=-19)
        return ScopedMarket.audit_window(market, now)

    market.audit_window = delayed
    assert scoped_turn(native, market)["status"] == "DEFERRED"
    assert native.gateway.queries == []
