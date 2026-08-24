from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.market_data.domain import BarFrequency
from app.market_data.subing_daily_watch import (
    SubingDailyWatchBuilder,
    SubingDailyWatchCurrentResult,
    SubingDailyWatchCurrentService,
    SubingDailyWatchDecision,
    SubingDailyWatchError,
    SubingDailyWatchGenerator,
    SubingDailyWatchItem,
    SubingDailyWatchProduct,
    SubingDailyWatchSnapshot,
)
from app.market_data.subing_daily_watch_calendar import (
    SubingDailyWatchCalendarError,
)
from app.market_data.subing_daily_watch_store import (
    SubingDailyWatchPublishResult,
    SubingDailyWatchStoreError,
)
from app.market_data.subing_ema_trend import PriceSide, SubingEmaTrendSnapshot
from app.market_data.operational_universe import (
    ActiveUniverseError,
    OperationalUniverseError,
)


_SOURCE_DAY = date(2026, 8, 24)
_TARGET_DAY = date(2026, 8, 25)
_NOW = datetime(2026, 8, 24, 18, 25, tzinfo=UTC)
_GENERATED_AT = datetime(2026, 8, 24, 10, 24, 13, tzinfo=UTC)
_SYMBOLS = tuple(
    f"{first}{second}"
    for first in "abc"
    for second in "abcdefghijklmnopqrstuvwxyz"
)[:60]


def _trend(
    timeframe: BarFrequency,
    *,
    price_side: PriceSide = PriceSide.ABOVE,
    close: Decimal = Decimal("3512"),
    ema21: Decimal = Decimal("3478.2468"),
    slope: Decimal = Decimal("8.6214"),
) -> SubingEmaTrendSnapshot:
    return SubingEmaTrendSnapshot(
        timeframe=timeframe,
        bar_end=datetime(2026, 8, 24, 7, tzinfo=UTC),
        trading_day=_SOURCE_DAY,
        contract="RB2610",
        segment_start_trading_day=date(2026, 7, 20),
        close=close,
        ema21=ema21,
        price_side=price_side,
        slope_5_raw=Decimal("3.0001"),
        slope_10_raw=Decimal("2.0001"),
        slope_5_bps_per_bar=slope,
        slope_10_bps_per_bar=Decimal("5.9173") if slope > 0 else slope,
    )


def _snapshot() -> SubingDailyWatchSnapshot:
    items: list[SubingDailyWatchItem] = []
    for index, symbol in enumerate(_SYMBOLS):
        if index == 0:
            decision = SubingDailyWatchDecision.LONG_WATCH
            reason_codes = ("D1_H1_LONG_ALIGNED",)
            unavailable_reasons: tuple[str, ...] = ()
            daily = _trend(BarFrequency.D1)
            hourly = _trend(BarFrequency.H1)
        elif index == 1:
            decision = SubingDailyWatchDecision.SHORT_WATCH
            reason_codes = ("D1_H1_SHORT_ALIGNED",)
            unavailable_reasons = ()
            daily = _trend(
                BarFrequency.D1,
                price_side=PriceSide.BELOW,
                close=Decimal("3400"),
                ema21=Decimal("3478.2468"),
                slope=Decimal("-8.6214"),
            )
            hourly = _trend(
                BarFrequency.H1,
                price_side=PriceSide.BELOW,
                close=Decimal("3400"),
                ema21=Decimal("3478.2468"),
                slope=Decimal("-8.6214"),
            )
        elif index == 2:
            decision = SubingDailyWatchDecision.EXCLUDED
            reason_codes = ("D1_TREND_NEUTRAL",)
            unavailable_reasons = ()
            daily = _trend(
                BarFrequency.D1,
                price_side=PriceSide.EQUAL,
                close=Decimal("3478.2468"),
            )
            hourly = _trend(BarFrequency.H1)
        else:
            decision = SubingDailyWatchDecision.UNAVAILABLE
            reason_codes = ()
            unavailable_reasons = ("D1_HISTORY_INSUFFICIENT",)
            daily = None
            hourly = None
        items.append(
            SubingDailyWatchItem(
                symbol=symbol,
                product_name=f"Product {symbol}",
                sector="black",
                decision=decision,
                reason_codes=reason_codes,
                daily=daily,
                hourly=hourly,
                unavailable_reasons=unavailable_reasons,
            )
        )
    return SubingDailyWatchSnapshot(
        source_trading_day=_SOURCE_DAY,
        target_trading_day=_TARGET_DAY,
        generated_at=_GENERATED_AT,
        items=tuple(items),
    )


class _Store:
    def __init__(
        self,
        current: SubingDailyWatchSnapshot | None = None,
        *,
        read_error: SubingDailyWatchStoreError | None = None,
    ) -> None:
        self.current = current
        self.read_error = read_error
        self.published: list[tuple[SubingDailyWatchSnapshot, datetime]] = []
        self.failures: list[dict[str, object]] = []

    def read_current(self) -> SubingDailyWatchSnapshot | None:
        if self.read_error is not None:
            raise self.read_error
        return self.current

    def publish(
        self,
        snapshot: SubingDailyWatchSnapshot,
        *,
        started_at: datetime,
    ) -> SubingDailyWatchPublishResult:
        self.published.append((snapshot, started_at))
        return SubingDailyWatchPublishResult("published", snapshot.target_trading_day)

    def record_failure(self, **kwargs: object) -> None:
        self.failures.append(kwargs)


def _current_service(
    store_factory,
    *,
    expected_day=lambda _now: _TARGET_DAY,
    products: tuple[str, ...] = _SYMBOLS,
    operational_products: tuple[str, ...] = _SYMBOLS,
) -> SubingDailyWatchCurrentService:
    return SubingDailyWatchCurrentService(
        products=products,
        operational_products=operational_products,
        store_factory=store_factory,
        expected_day=expected_day,
    )


def test_current_service_projects_ready_snapshot_without_excluded_details() -> None:
    """Catches the browser receiving the immutable excluded ledger."""
    result = _current_service(lambda: _Store(_snapshot())).current(_NOW)

    assert result.status == "ready"
    assert result.expected_target_trading_day == _TARGET_DAY
    assert result.latest_target_trading_day == _TARGET_DAY
    assert result.error_code is None
    assert result.snapshot is not None
    assert result.snapshot.counts == {
        "universe": 60,
        "long_watch": 1,
        "short_watch": 1,
        "excluded": 1,
        "unavailable": 57,
    }
    assert tuple(item.symbol for item in result.snapshot.long_watch) == ("aa",)
    assert tuple(item.symbol for item in result.snapshot.short_watch) == ("ab",)
    assert len(result.snapshot.unavailable) == 57
    assert not hasattr(result.snapshot, "excluded_items")
    assert result.snapshot.long_watch[0].daily is not None
    assert result.snapshot.long_watch[0].daily.close == Decimal("3512")


def test_current_service_accepts_matching_non_alphabetical_active_order() -> None:
    """Catches current validation replacing exact active order with sorting."""
    products = tuple(reversed(_SYMBOLS))
    snapshot = replace(_snapshot(), items=tuple(reversed(_snapshot().items)))

    result = _current_service(
        lambda: _Store(snapshot),
        products=products,
        operational_products=_SYMBOLS,
    ).current(_NOW)

    assert result.status == "ready"
    assert result.snapshot is not None
    assert result.snapshot.long_watch[0].symbol == "aa"


def test_current_service_rejects_matching_but_incomplete_universe() -> None:
    """Catches a partial configured ledger being accepted as current active60."""
    partial = replace(_snapshot(), items=_snapshot().items[:1])

    result = _current_service(lambda: _Store(partial)).current(_NOW)

    assert result == SubingDailyWatchCurrentResult(
        status="unavailable",
        expected_target_trading_day=_TARGET_DAY,
        latest_target_trading_day=_TARGET_DAY,
        error_code="SUBING_DAILY_WATCH_INVALID",
        snapshot=None,
    )


def test_current_service_rejects_invalid_configuration_before_missing_current() -> None:
    """Catches invalid scope identity being mislabeled as not generated."""
    result = _current_service(
        lambda: _Store(None),
        products=("aa",),
    ).current(_NOW)

    assert result.error_code == "SUBING_DAILY_WATCH_INVALID"
    assert result.snapshot is None


def test_current_service_validates_ledger_before_reporting_stale() -> None:
    """Catches a malformed old/current file being mislabeled as merely stale."""
    partial = replace(
        _snapshot(),
        target_trading_day=date(2026, 8, 26),
        items=_snapshot().items[:1],
    )

    result = _current_service(lambda: _Store(partial)).current(_NOW)

    assert result.error_code == "SUBING_DAILY_WATCH_INVALID"
    assert result.latest_target_trading_day == date(2026, 8, 26)
    assert result.snapshot is None


@pytest.mark.parametrize(
    ("store_factory", "expected_day", "error_code", "expected", "latest"),
    [
        (
            lambda: _Store(None),
            lambda _now: _TARGET_DAY,
            "SUBING_DAILY_WATCH_NOT_GENERATED",
            _TARGET_DAY,
            None,
        ),
        (
            lambda: _Store(
                replace(_snapshot(), target_trading_day=date(2026, 8, 26))
            ),
            lambda _now: _TARGET_DAY,
            "SUBING_DAILY_WATCH_STALE",
            _TARGET_DAY,
            date(2026, 8, 26),
        ),
        (
            lambda: _Store(
                read_error=SubingDailyWatchStoreError("SNAPSHOT_INVALID")
            ),
            lambda _now: _TARGET_DAY,
            "SUBING_DAILY_WATCH_INVALID",
            _TARGET_DAY,
            None,
        ),
        (
            lambda: (_ for _ in ()).throw(
                SubingDailyWatchStoreError("OBSERVATION_ROOT_UNAVAILABLE")
            ),
            lambda _now: _TARGET_DAY,
            "SUBING_OBSERVATION_ROOT_UNAVAILABLE",
            _TARGET_DAY,
            None,
        ),
        (
            lambda: pytest.fail("store must not be read without expected day"),
            lambda _now: (_ for _ in ()).throw(
                SubingDailyWatchCalendarError("EXPECTED_TRADING_DAY_UNAVAILABLE")
            ),
            "SUBING_DAILY_WATCH_EXPECTED_DAY_UNAVAILABLE",
            None,
            None,
        ),
    ],
)
def test_current_service_returns_exact_typed_unavailable_without_stale_snapshot(
    store_factory,
    expected_day,
    error_code: str,
    expected: date | None,
    latest: date | None,
) -> None:
    """Catches unavailable branches leaking a stale or unvalidated candidate."""
    result = _current_service(
        store_factory,
        expected_day=expected_day,
    ).current(_NOW)

    assert result == SubingDailyWatchCurrentResult(
        status="unavailable",
        expected_target_trading_day=expected,
        latest_target_trading_day=latest,
        error_code=error_code,
        snapshot=None,
    )


def test_current_service_propagates_unknown_calendar_domain_code() -> None:
    """Catches a new Calendar failure being silently relabeled as expected-day unavailable."""
    error = SubingDailyWatchCalendarError("NEW_CALENDAR_FAILURE")
    service = _current_service(
        lambda: pytest.fail("store must not be read after Calendar failure"),
        expected_day=lambda _now: (_ for _ in ()).throw(error),
    )

    with pytest.raises(SubingDailyWatchCalendarError) as raised:
        service.current(_NOW)

    assert raised.value is error


def test_current_service_propagates_unknown_store_domain_code() -> None:
    """Catches a new Store failure being silently relabeled as snapshot invalid."""
    error = SubingDailyWatchStoreError("NEW_STORE_FAILURE")
    service = _current_service(
        lambda: (_ for _ in ()).throw(error),
    )

    with pytest.raises(SubingDailyWatchStoreError) as raised:
        service.current(_NOW)

    assert raised.value is error


def test_builder_takes_generated_at_only_after_product_work() -> None:
    """Catches generated_at being sampled before the 60-product build finishes."""
    events: list[str] = []

    class _UnavailableLoader:
        def load(self, **_kwargs):
            events.append("load")
            from app.market_data.market_data_service import MarketDataError

            raise MarketDataError("MAPPED_CONTRACT_DATASET_MISSING")

    builder = SubingDailyWatchBuilder(
        segment_loader=_UnavailableLoader(),
        products=("aa",),
        product_metadata={
            "aa": SubingDailyWatchProduct("aa", "Product aa", "black")
        },
        expected_universe_size=1,
    )

    snapshot = builder.build_at_completion(
        source_trading_day=_SOURCE_DAY,
        target_trading_day=_TARGET_DAY,
        generated_at=lambda: events.append("clock") or _GENERATED_AT,
    )

    assert events == ["load", "clock"]
    assert snapshot.generated_at == _GENERATED_AT


def test_generator_persists_real_run_start_and_truthful_completion_time() -> None:
    """Catches publish receiving a fabricated start or pre-work finish time."""
    events: list[str] = []
    store = _Store()
    clock_values = iter(
        [
            datetime(2026, 8, 24, 10, 24, tzinfo=UTC),
            _GENERATED_AT,
        ]
    )

    class _Builder:
        def build_at_completion(self, **kwargs) -> SubingDailyWatchSnapshot:
            events.append("build")
            return replace(_snapshot(), generated_at=kwargs["generated_at"]())

    generator = SubingDailyWatchGenerator(
        builder=_Builder(),
        store=store,
        target_day=lambda source: events.append(f"target:{source}") or _TARGET_DAY,
        clock=lambda: events.append("clock") or next(clock_values),
    )

    result = generator.run(_SOURCE_DAY)

    assert result.status == "published"
    assert events == ["clock", f"target:{_SOURCE_DAY}", "build", "clock"]
    assert store.published == [
        (
            replace(_snapshot(), generated_at=_GENERATED_AT),
            datetime(2026, 8, 24, 10, 24, tzinfo=UTC),
        )
    ]


def test_generator_records_only_stable_failure_with_real_timing() -> None:
    """Catches a known failed run omitting truthful sanitized status timing."""
    store = _Store()
    start = datetime(2026, 8, 24, 10, 24, tzinfo=UTC)
    finish = datetime(2026, 8, 24, 10, 24, 13, tzinfo=UTC)
    clock_values = iter([start, finish])
    generator = SubingDailyWatchGenerator(
        builder=pytest.fail,
        store=store,
        target_day=lambda _source: (_ for _ in ()).throw(
            SubingDailyWatchCalendarError("NEXT_TRADING_DAY_UNAVAILABLE")
        ),
        clock=lambda: next(clock_values),
    )

    with pytest.raises(SubingDailyWatchCalendarError) as raised:
        generator.run(_SOURCE_DAY)

    assert raised.value.code == "NEXT_TRADING_DAY_UNAVAILABLE"
    assert store.failures == [
        {
            "source_trading_day": _SOURCE_DAY,
            "target_trading_day": None,
            "started_at": start,
            "finished_at": finish,
            "error_code": "NEXT_TRADING_DAY_UNAVAILABLE",
        }
    ]


def test_generator_composition_is_complete_and_creates_no_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches composition widening scope or eagerly creating observation files."""
    from app.market_data.composition import build_subing_daily_watch_generator

    root = tmp_path / "observation-root"
    loader = object()
    store = object()
    captured_store: dict[str, object] = {}
    root_resolutions: list[Path] = []
    products = _SYMBOLS
    dominants = tuple(
        SimpleNamespace(
            symbol=symbol,
            product_name=f"Product {symbol}",
            sector="black",
        )
        for symbol in products
    )
    market_data = SimpleNamespace(list_latest_dominants=lambda: dominants)
    monkeypatch.setattr(
        "app.market_data.composition.load_active_products", lambda: products
    )
    monkeypatch.setattr(
        "app.market_data.composition.load_operational_products", lambda: products[::-1]
    )
    monkeypatch.setattr(
        "app.market_data.composition.build_market_data_service",
        lambda _session: market_data,
    )
    monkeypatch.setattr(
        "app.market_data.composition.ActualDominantResearchSegmentLoader",
        lambda value: loader if value is market_data else pytest.fail("wrong MDS"),
    )
    def resolve_root(**_kwargs: object) -> Path:
        root_resolutions.append(root)
        return root

    def build_store(
        value: Path,
        *,
        root_validator: object,
    ) -> object:
        captured_store.update(root=value, root_validator=root_validator)
        return store

    monkeypatch.setattr(
        "app.market_data.composition.resolve_subing_observation_root",
        resolve_root,
    )
    monkeypatch.setattr(
        "app.market_data.composition.SubingDailyWatchStore",
        build_store,
    )

    generator = build_subing_daily_watch_generator(object())

    assert isinstance(generator, SubingDailyWatchGenerator)
    assert generator.builder._segment_loader is loader
    assert generator.builder._products == products
    assert captured_store["root"] == root
    root_validator = captured_store["root_validator"]
    assert callable(root_validator)
    assert root_validator() == root
    assert root_resolutions == [root, root]
    assert not root.exists()


def test_generator_composition_requires_exact_active_operational_60(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches generation silently running a partial operational universe."""
    from app.market_data.composition import build_subing_daily_watch_generator

    monkeypatch.setattr(
        "app.market_data.composition.load_active_products", lambda: _SYMBOLS
    )
    monkeypatch.setattr(
        "app.market_data.composition.load_operational_products",
        lambda: _SYMBOLS[:-1],
    )

    with pytest.raises(SubingDailyWatchError) as raised:
        build_subing_daily_watch_generator(object())

    assert raised.value.code == "ACTIVE_OPERATIONAL_SCOPE_MISMATCH"


def test_generator_composition_rejects_unavailable_root_before_market_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches an unusable output root failing only after expensive composition."""
    from app.market_data.composition import build_subing_daily_watch_generator

    monkeypatch.setattr(
        "app.market_data.composition.load_active_products", lambda: _SYMBOLS
    )
    monkeypatch.setattr(
        "app.market_data.composition.load_operational_products", lambda: _SYMBOLS
    )
    root_error = SubingDailyWatchStoreError("OBSERVATION_ROOT_UNAVAILABLE")
    monkeypatch.setattr(
        "app.market_data.composition.resolve_subing_observation_root",
        lambda **_kwargs: (_ for _ in ()).throw(root_error),
    )
    monkeypatch.setattr(
        "app.market_data.composition.build_market_data_service",
        lambda _session: pytest.fail("unavailable root initialized market data"),
    )

    with pytest.raises(SubingDailyWatchStoreError) as raised:
        build_subing_daily_watch_generator(object())

    assert raised.value is root_error


def test_current_composition_reads_only_calendar_and_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches the current HTTP read path initializing provider, Redis, or writes."""
    from app.market_data.composition import build_subing_daily_watch_current_service

    root = tmp_path / "missing-observation-root"
    monkeypatch.setattr(
        "app.market_data.composition.load_active_products", lambda: _SYMBOLS
    )
    monkeypatch.setattr(
        "app.market_data.composition.load_operational_products", lambda: _SYMBOLS
    )
    monkeypatch.setattr(
        "app.market_data.composition.resolve_expected_daily_watch_day",
        lambda _session, *, products, now: (
            _TARGET_DAY
            if products == _SYMBOLS and now == _NOW
            else pytest.fail("wrong calendar input")
        ),
    )
    monkeypatch.setattr(
        "app.market_data.composition.resolve_subing_observation_root",
        lambda **_kwargs: root,
    )
    monkeypatch.setattr(
        "app.market_data.composition.build_market_data_service",
        lambda _session: pytest.fail("current read initialized MarketDataService"),
    )
    monkeypatch.setattr(
        "app.market_data.composition.get_redis_connection",
        lambda: pytest.fail("current read initialized Redis"),
    )

    result = build_subing_daily_watch_current_service(object()).current(_NOW)

    assert result.status == "unavailable"
    assert result.error_code == "SUBING_DAILY_WATCH_NOT_GENERATED"
    assert not root.exists()


def test_current_composition_maps_unsearchable_root_before_not_generated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches a write-only root being reported as not generated."""
    from app.market_data.composition import build_subing_daily_watch_current_service

    root = Path("/Volumes/Fake/observations/subing-daily-v1")
    monkeypatch.setenv("GUIYI_SUBING_OBSERVATION_ROOT", str(root))
    monkeypatch.setattr(
        "app.market_data.composition.load_active_products", lambda: _SYMBOLS
    )
    monkeypatch.setattr(
        "app.market_data.composition.load_operational_products", lambda: _SYMBOLS
    )
    monkeypatch.setattr(
        "app.market_data.composition.resolve_expected_daily_watch_day",
        lambda _session, *, products, now: _TARGET_DAY,
    )
    monkeypatch.setattr(
        "app.market_data.composition.PathMountInspector",
        lambda: SimpleNamespace(
            is_mount=lambda _path: True,
            is_symlink=lambda _path: False,
            exists=lambda _path: True,
            is_dir=lambda _path: True,
            is_writable=lambda path: path != root,
        ),
    )

    result = build_subing_daily_watch_current_service(object()).current(_NOW)

    assert result.status == "unavailable"
    assert result.error_code == "SUBING_OBSERVATION_ROOT_UNAVAILABLE"
    assert result.snapshot is None


def test_current_composition_uses_active_order_when_operational_order_differs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches set-equal operational order invalidating an active-ordered ledger."""
    from app.market_data.composition import build_subing_daily_watch_current_service

    monkeypatch.setattr(
        "app.market_data.composition.load_active_products", lambda: _SYMBOLS
    )
    monkeypatch.setattr(
        "app.market_data.composition.load_operational_products",
        lambda: _SYMBOLS[::-1],
    )
    monkeypatch.setattr(
        "app.market_data.composition.resolve_expected_daily_watch_day",
        lambda _session, *, products, now: (
            _TARGET_DAY
            if products == _SYMBOLS and now == _NOW
            else pytest.fail("Calendar must use active order")
        ),
    )
    root = Path("/Volumes/Fake/subing-daily-watch")
    store = _Store(_snapshot())
    monkeypatch.setattr(
        "app.market_data.composition.resolve_subing_observation_root",
        lambda **_kwargs: root,
    )
    monkeypatch.setattr(
        "app.market_data.composition.SubingDailyWatchStore",
        lambda value: store if value == root else pytest.fail("wrong store root"),
    )
    monkeypatch.setattr(
        "app.market_data.composition.build_market_data_service",
        lambda _session: pytest.fail("current read initialized MarketDataService"),
    )
    monkeypatch.setattr(
        "app.market_data.composition.get_redis_connection",
        lambda: pytest.fail("current read initialized Redis"),
    )

    result = build_subing_daily_watch_current_service(object()).current(_NOW)

    assert result.status == "ready"
    assert result.snapshot is not None
    assert result.snapshot.long_watch[0].symbol == "aa"


def test_current_composition_rejects_scope_mismatch_before_calendar_or_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches active/operational mismatch becoming not-generated after store read."""
    from app.market_data.composition import build_subing_daily_watch_current_service

    monkeypatch.setattr(
        "app.market_data.composition.load_active_products", lambda: _SYMBOLS
    )
    monkeypatch.setattr(
        "app.market_data.composition.load_operational_products",
        lambda: _SYMBOLS[:-1],
    )
    monkeypatch.setattr(
        "app.market_data.composition.resolve_expected_daily_watch_day",
        lambda *_args, **_kwargs: pytest.fail("invalid config reached Calendar"),
    )
    monkeypatch.setattr(
        "app.market_data.composition.resolve_subing_observation_root",
        lambda **_kwargs: pytest.fail("invalid config reached store"),
    )
    monkeypatch.setattr(
        "app.market_data.composition.build_market_data_service",
        lambda _session: pytest.fail("invalid config initialized MarketDataService"),
    )
    monkeypatch.setattr(
        "app.market_data.composition.get_redis_connection",
        lambda: pytest.fail("invalid config initialized Redis"),
    )

    result = build_subing_daily_watch_current_service(object()).current(_NOW)

    assert result.error_code == "SUBING_DAILY_WATCH_INVALID"
    assert result.expected_target_trading_day is None
    assert result.latest_target_trading_day is None
    assert result.snapshot is None


@pytest.mark.parametrize(
    ("loader_name", "error"),
    [
        ("load_active_products", ActiveUniverseError()),
        ("load_operational_products", OperationalUniverseError()),
    ],
)
def test_current_composition_maps_universe_loader_error_before_read_dependencies(
    loader_name: str,
    error: Exception,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches invalid universe files escaping before typed current response."""
    from app.market_data.composition import build_subing_daily_watch_current_service

    monkeypatch.setattr(
        f"app.market_data.composition.{loader_name}",
        lambda: (_ for _ in ()).throw(error),
    )
    monkeypatch.setattr(
        "app.market_data.composition.resolve_expected_daily_watch_day",
        lambda *_args, **_kwargs: pytest.fail("invalid config reached Calendar"),
    )
    monkeypatch.setattr(
        "app.market_data.composition.resolve_subing_observation_root",
        lambda **_kwargs: pytest.fail("invalid config reached store"),
    )
    monkeypatch.setattr(
        "app.market_data.composition.build_market_data_service",
        lambda _session: pytest.fail("invalid config initialized MarketDataService"),
    )
    monkeypatch.setattr(
        "app.market_data.composition.get_redis_connection",
        lambda: pytest.fail("invalid config initialized Redis"),
    )

    result = build_subing_daily_watch_current_service(object()).current(_NOW)

    assert result.error_code == "SUBING_DAILY_WATCH_INVALID"
    assert result.snapshot is None


def test_current_api_returns_ready_decimal_projection_and_omits_excluded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches a missing route/DTO or lossy/over-broad browser projection."""
    result = _current_service(lambda: _Store(_snapshot())).current(_NOW)
    monkeypatch.setattr(
        "app.api.market.build_subing_daily_watch_current_service",
        lambda _session: SimpleNamespace(current=lambda _now: result),
    )

    response = TestClient(app).get(
        "/api/v1/market/research/subing-daily-watch/current"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["snapshot"]["counts"]["universe"] == 60
    assert payload["snapshot"]["long_watch"][0]["daily"]["close"] == "3512"
    assert "excluded_items" not in payload["snapshot"]
    assert "excluded" not in payload["snapshot"]


@pytest.mark.parametrize(
    "error_code",
    [
        "SUBING_DAILY_WATCH_NOT_GENERATED",
        "SUBING_DAILY_WATCH_STALE",
        "SUBING_DAILY_WATCH_INVALID",
        "SUBING_OBSERVATION_ROOT_UNAVAILABLE",
        "SUBING_DAILY_WATCH_EXPECTED_DAY_UNAVAILABLE",
    ],
)
def test_current_api_returns_each_unavailable_as_sanitized_http_200(
    error_code: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches typed unavailability becoming an error or leaking internals."""
    result = SubingDailyWatchCurrentResult(
        status="unavailable",
        expected_target_trading_day=(
            None
            if error_code == "SUBING_DAILY_WATCH_EXPECTED_DAY_UNAVAILABLE"
            else _TARGET_DAY
        ),
        latest_target_trading_day=None,
        error_code=error_code,
        snapshot=None,
    )
    monkeypatch.setattr(
        "app.api.market.build_subing_daily_watch_current_service",
        lambda _session: SimpleNamespace(current=lambda _now: result),
    )

    response = TestClient(app).get(
        "/api/v1/market/research/subing-daily-watch/current"
    )

    assert response.status_code == 200
    assert response.json()["error_code"] == error_code
    assert response.json()["snapshot"] is None
    serialized = response.text
    assert "/Volumes/" not in serialized
    assert "Traceback" not in serialized
    assert "RuntimeError" not in serialized


def test_current_api_unexpected_exception_uses_fastapi_safe_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches unexpected exception text or a physical path entering HTTP."""
    monkeypatch.setattr(
        "app.api.market.build_subing_daily_watch_current_service",
        lambda _session: (_ for _ in ()).throw(
            RuntimeError("secret failure at /Volumes/private/current.json")
        ),
    )

    response = TestClient(app, raise_server_exceptions=False).get(
        "/api/v1/market/research/subing-daily-watch/current"
    )

    assert response.status_code == 500
    assert "/Volumes/" not in response.text
    assert "secret failure" not in response.text


@pytest.mark.parametrize(
    "configuration_error",
    [ActiveUniverseError(), OperationalUniverseError()],
)
def test_current_api_maps_universe_configuration_error_to_sanitized_http_200(
    configuration_error: Exception,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches composition config errors escaping as HTTP 500."""
    monkeypatch.setattr(
        "app.api.market.build_subing_daily_watch_current_service",
        lambda _session: (_ for _ in ()).throw(configuration_error),
    )

    response = TestClient(app, raise_server_exceptions=False).get(
        "/api/v1/market/research/subing-daily-watch/current"
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "unavailable",
        "expected_target_trading_day": None,
        "latest_target_trading_day": None,
        "error_code": "SUBING_DAILY_WATCH_INVALID",
        "snapshot": None,
    }


def test_current_api_unknown_store_code_uses_safe_500_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches a new Store code or physical path leaking through HTTP."""
    error = SubingDailyWatchStoreError(
        "NEW_STORE_FAILURE at /Volumes/private/current.json"
    )
    service = _current_service(
        lambda: (_ for _ in ()).throw(error),
    )
    monkeypatch.setattr(
        "app.api.market.build_subing_daily_watch_current_service",
        lambda _session: service,
    )

    response = TestClient(app, raise_server_exceptions=False).get(
        "/api/v1/market/research/subing-daily-watch/current"
    )

    assert response.status_code == 500
    assert "/Volumes/" not in response.text
    assert "NEW_STORE_FAILURE" not in response.text
