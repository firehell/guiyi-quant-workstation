from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.market_data.catalog import CatalogPartition, MarketCatalog
from app.market_data.domain import (
    BarFrequency,
    DatasetKey,
    DatasetKind,
    ResolvedContractSegment,
)
from app.market_data.market_data_service import MarketDataService
from app.market_data.subing_strategy.contracts import SUBING_STRATEGY_ID
from app.market_data.subing_strategy.performance_lineage import (
    FULL_REBUILD_REQUIRED,
    REPLAY_FROM_SEGMENT,
    UNCHANGED,
    CatalogSubingStrategyPerformanceLineageResolver,
    SubingStrategyPerformanceLineage,
    SubingStrategyPerformanceLineageError,
    SubingStrategyPerformanceSemanticIdentity,
    SubingStrategyPerformanceSourceSegment,
    decide_subing_strategy_performance_tail,
)
from app.models import Exchange, Instrument, MarketPartition, TradingCalendar


ENGINE_A = "a" * 64
ENGINE_B = "b" * 64
FORMULA = "subing_strategy_15m_v1"
_FREQUENCIES = (BarFrequency.M1, BarFrequency.M5, BarFrequency.M15)


class SpyCanonicalStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.bar_reads: list[tuple[str, object]] = []

    def read_month(self, dataset: DatasetKey, year: int, month: int) -> tuple[object, ...]:
        self.bar_reads.append(("read_month", (dataset, year, month)))
        raise AssertionError("Canonical Bar read")

    def read_catalog_partition(self, partition: CatalogPartition) -> tuple[object, ...]:
        self.bar_reads.append(("read_catalog_partition", partition))
        raise AssertionError("Canonical Bar read")


class ForbiddenBarMarketDataService(MarketDataService):
    def query(self, request):  # type: ignore[no-untyped-def]
        raise AssertionError("Canonical query invoked")

    def query_actual_dominant_trading_days(self, request):  # type: ignore[no-untyped-def]
        raise AssertionError("Canonical actual-dominant trading-day read invoked")

    def query_actual_dominant_recent_bars(self, request):  # type: ignore[no-untyped-def]
        raise AssertionError("Canonical actual-dominant recent-bar read invoked")

    def contract_bars_for_trading_day(self, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("Canonical contract Bar read invoked")


class FakeCoverage:
    def __init__(self, *, start: date, through: date) -> None:
        self.start = start
        self.through = through

    def product_start(self, symbol: str) -> date:
        assert symbol == "jm"
        return self.start

    def latest_complete_day(self, products: tuple[str, ...]) -> date:
        assert products == ("jm",)
        return self.through


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.add_all(
        (
            Exchange(code="DCE", name="DCE"),
            Instrument(symbol="jm", name="JM", exchange_code="DCE", is_active=True),
        )
    )
    session.commit()
    return session


def _add_calendar(session: Session, days: dict[int, bool]) -> None:
    for day, is_trading_day in days.items():
        session.add(
            TradingCalendar(
                exchange_code="DCE",
                trade_date=date(2025, 1, day),
                is_trading_day=is_trading_day,
            )
        )


def _register_partitions(
    catalog: MarketCatalog,
    *,
    contract: str,
    row_count: int,
    file_suffix: str = "part.parquet",
) -> None:
    for frequency in _FREQUENCIES:
        key = DatasetKey(DatasetKind.CONTRACT, "jm", contract, frequency)
        dataset = catalog.dataset_row(key, create=True)
        assert dataset is not None
        relative = (
            f"{key.relative_root.as_posix()}/year=2025/month=01/{file_suffix}"
        )
        catalog.session.add(
            MarketPartition(
                dataset_id=dataset.id,
                year=2025,
                month=1,
                coverage_start=datetime(2025, 1, 1, tzinfo=UTC),
                coverage_end=datetime(2025, 1, 31, tzinfo=UTC),
                file_uri=relative,
                row_count=row_count,
            )
        )


def _seed_two_segments(
    session: Session,
    catalog: MarketCatalog,
    *,
    last_day: int = 8,
    tail_row_count: int = 20,
    prefix_row_count: int = 10,
) -> None:
    trading = {day: day not in {4, 5} for day in range(1, last_day + 1)}
    _add_calendar(session, trading)
    mappings = []
    for day, is_trading_day in trading.items():
        if not is_trading_day or day < 2:
            continue
        contract = "JM2505" if day <= 3 else "JM2509"
        mappings.append(("jm", date(2025, 1, day), contract))
    catalog.upsert_main_contracts(tuple(mappings))
    _register_partitions(catalog, contract="JM2505", row_count=prefix_row_count)
    _register_partitions(catalog, contract="JM2509", row_count=tail_row_count)
    session.commit()


def _resolver(
    session: Session,
    catalog: MarketCatalog,
    store: SpyCanonicalStore,
    *,
    start: date = date(2025, 1, 2),
    through: date = date(2025, 1, 8),
) -> CatalogSubingStrategyPerformanceLineageResolver:
    return CatalogSubingStrategyPerformanceLineageResolver(
        market_data=ForbiddenBarMarketDataService(catalog, store),
        coverage=FakeCoverage(start=start, through=through),
    )


def _identity(engine: str = ENGINE_A) -> SubingStrategyPerformanceSemanticIdentity:
    return SubingStrategyPerformanceSemanticIdentity(
        strategy_id=SUBING_STRATEGY_ID,
        formula_version=FORMULA,
        engine_identity_sha256=engine,
    )


def _segment(
    *,
    contract: str,
    start: date,
    end: date,
    source_identity: str,
) -> SubingStrategyPerformanceSourceSegment:
    return SubingStrategyPerformanceSourceSegment(
        contract=contract,
        effective_start=start,
        effective_end=end,
        source_identity=source_identity,
    )


def _lineage(
    *,
    through: date,
    segments: tuple[SubingStrategyPerformanceSourceSegment, ...],
    since: date = date(2025, 1, 2),
    manifest: str | None = None,
) -> SubingStrategyPerformanceLineage:
    return SubingStrategyPerformanceLineage(
        symbol="jm",
        coverage_since=since,
        coverage_through=through,
        ordered_segments=segments,
        source_manifest_sha256=manifest or ENGINE_A,
    )


def test_resolver_uses_rank1_mapping_and_catalog_partitions_without_bar_reads(
    tmp_path: Path,
) -> None:
    session = _session()
    catalog = MarketCatalog(session, tmp_path)
    store = SpyCanonicalStore(tmp_path)
    _seed_two_segments(session, catalog)
    glob_calls: list[str] = []
    original_glob = Path.glob

    def tracked_glob(self: Path, pattern: str, **kwargs: object):
        glob_calls.append(pattern)
        return original_glob(self, pattern, **kwargs)

    Path.glob = tracked_glob  # type: ignore[method-assign]
    try:
        lineage = _resolver(session, catalog, store).resolve("jm")
    finally:
        Path.glob = original_glob  # type: ignore[method-assign]
        session.close()

    assert store.bar_reads == []
    assert glob_calls == []
    assert lineage.symbol == "jm"
    assert lineage.coverage_since == date(2025, 1, 2)
    assert lineage.coverage_through == date(2025, 1, 8)
    assert tuple(
        (item.contract, item.effective_start, item.effective_end)
        for item in lineage.ordered_segments
    ) == (
        ("JM2505", date(2025, 1, 2), date(2025, 1, 3)),
        ("JM2509", date(2025, 1, 6), date(2025, 1, 8)),
    )
    assert all(len(item.source_identity) == 64 for item in lineage.ordered_segments)
    assert lineage.ordered_segments[0].source_identity != lineage.ordered_segments[1].source_identity
    assert len(lineage.source_manifest_sha256) == 64


def test_expected_complete_through_is_min_of_coverage_and_last_rank1_day(
    tmp_path: Path,
) -> None:
    session = _session()
    catalog = MarketCatalog(session, tmp_path)
    store = SpyCanonicalStore(tmp_path)
    _seed_two_segments(session, catalog, last_day=8)
    resolver = _resolver(
        session,
        catalog,
        store,
        through=date(2025, 1, 10),
    )

    assert resolver.expected_complete_through("jm") == date(2025, 1, 8)
    session.close()


def test_canonical_partition_lineage_changes_segment_source_identity(
    tmp_path: Path,
) -> None:
    session = _session()
    catalog = MarketCatalog(session, tmp_path)
    store = SpyCanonicalStore(tmp_path)
    _seed_two_segments(session, catalog, tail_row_count=20)
    first = _resolver(session, catalog, store).resolve("jm")

    tail_key = DatasetKey(DatasetKind.CONTRACT, "jm", "JM2509", BarFrequency.M15)
    dataset = catalog.dataset_row(tail_key)
    assert dataset is not None
    partition = session.query(MarketPartition).filter_by(dataset_id=dataset.id).one()
    partition.row_count = 99
    session.commit()
    second = _resolver(session, catalog, store).resolve("jm")
    session.close()

    assert first.ordered_segments[0].source_identity == second.ordered_segments[0].source_identity
    assert first.ordered_segments[1].source_identity != second.ordered_segments[1].source_identity
    assert first.source_manifest_sha256 != second.source_manifest_sha256
    assert store.bar_reads == []


def test_mapping_gap_fails_closed_without_leaking_sql_or_paths(tmp_path: Path) -> None:
    session = _session()
    catalog = MarketCatalog(session, tmp_path)
    store = SpyCanonicalStore(tmp_path)
    _add_calendar(session, {2: True, 3: True, 6: True})
    catalog.upsert_main_contracts(
        (
            ("jm", date(2025, 1, 2), "JM2505"),
            ("jm", date(2025, 1, 6), "JM2509"),
        )
    )
    _register_partitions(catalog, contract="JM2505", row_count=1)
    _register_partitions(catalog, contract="JM2509", row_count=1)
    session.commit()

    with pytest.raises(SubingStrategyPerformanceLineageError) as raised:
        _resolver(session, catalog, store, through=date(2025, 1, 6)).resolve("jm")

    assert raised.value.code == "SUBING_STRATEGY_PERFORMANCE_LINEAGE_UNAVAILABLE"
    assert str(raised.value) == "SUBING_STRATEGY_PERFORMANCE_LINEAGE_UNAVAILABLE"
    assert "SELECT" not in str(raised.value)
    assert str(tmp_path) not in str(raised.value)
    assert store.bar_reads == []
    session.close()


def test_missing_partition_metadata_fails_closed(tmp_path: Path) -> None:
    session = _session()
    catalog = MarketCatalog(session, tmp_path)
    store = SpyCanonicalStore(tmp_path)
    _add_calendar(session, {2: True, 3: True})
    catalog.upsert_main_contracts(
        (
            ("jm", date(2025, 1, 2), "JM2505"),
            ("jm", date(2025, 1, 3), "JM2505"),
        )
    )
    session.commit()

    with pytest.raises(SubingStrategyPerformanceLineageError) as raised:
        _resolver(session, catalog, store, through=date(2025, 1, 3)).resolve("jm")

    assert raised.value.code == "SUBING_STRATEGY_PERFORMANCE_LINEAGE_UNAVAILABLE"
    assert store.bar_reads == []
    session.close()


def test_promoted_metadata_method_returns_merged_rank1_segments_without_bars(
    tmp_path: Path,
) -> None:
    session = _session()
    catalog = MarketCatalog(session, tmp_path)
    store = SpyCanonicalStore(tmp_path)
    _seed_two_segments(session, catalog)
    service = ForbiddenBarMarketDataService(catalog, store)

    segments = service.actual_dominant_segments(
        "jm",
        date(2025, 1, 2),
        date(2025, 1, 8),
    )

    assert segments == (
        ResolvedContractSegment("JM2505", date(2025, 1, 2), date(2025, 1, 3)),
        ResolvedContractSegment("JM2509", date(2025, 1, 6), date(2025, 1, 8)),
    )
    assert store.bar_reads == []
    session.close()


def test_decide_unchanged_same_day_is_a_hit() -> None:
    prefix = _segment(
        contract="JM2505",
        start=date(2025, 1, 2),
        end=date(2025, 1, 3),
        source_identity=ENGINE_A,
    )
    tail = _segment(
        contract="JM2509",
        start=date(2025, 1, 6),
        end=date(2025, 1, 8),
        source_identity=ENGINE_B,
    )
    lineage = _lineage(through=date(2025, 1, 8), segments=(prefix, tail), manifest=ENGINE_A)

    assert decide_subing_strategy_performance_tail(
        previous=lineage,
        current=lineage,
        previous_identity=_identity(),
        current_identity=_identity(),
    ) == UNCHANGED


def test_decide_normal_append_replays_current_mutable_segment() -> None:
    prefix = _segment(
        contract="JM2505",
        start=date(2025, 1, 2),
        end=date(2025, 1, 3),
        source_identity=ENGINE_A,
    )
    previous = _lineage(
        through=date(2025, 1, 7),
        segments=(
            prefix,
            _segment(
                contract="JM2509",
                start=date(2025, 1, 6),
                end=date(2025, 1, 7),
                source_identity=ENGINE_B,
            ),
        ),
        manifest="1" * 64,
    )
    current = _lineage(
        through=date(2025, 1, 8),
        segments=(
            prefix,
            _segment(
                contract="JM2509",
                start=date(2025, 1, 6),
                end=date(2025, 1, 8),
                source_identity=ENGINE_B,
            ),
        ),
        manifest="2" * 64,
    )

    assert decide_subing_strategy_performance_tail(
        previous=previous,
        current=current,
        previous_identity=_identity(),
        current_identity=_identity(),
    ) == REPLAY_FROM_SEGMENT(1)


def test_decide_rollover_replays_previous_mutable_segment() -> None:
    prefix = _segment(
        contract="JM2505",
        start=date(2025, 1, 2),
        end=date(2025, 1, 3),
        source_identity=ENGINE_A,
    )
    previous_tail = _segment(
        contract="JM2509",
        start=date(2025, 1, 6),
        end=date(2025, 1, 8),
        source_identity=ENGINE_B,
    )
    previous = _lineage(
        through=date(2025, 1, 8),
        segments=(prefix, previous_tail),
        manifest="1" * 64,
    )
    current = _lineage(
        through=date(2025, 1, 9),
        segments=(
            prefix,
            previous_tail,
            _segment(
                contract="JM2513",
                start=date(2025, 1, 9),
                end=date(2025, 1, 9),
                source_identity="c" * 64,
            ),
        ),
        manifest="2" * 64,
    )

    assert decide_subing_strategy_performance_tail(
        previous=previous,
        current=current,
        previous_identity=_identity(),
        current_identity=_identity(),
    ) == REPLAY_FROM_SEGMENT(1)


def test_decide_immutable_prefix_mapping_drift_requires_full_rebuild() -> None:
    previous = _lineage(
        through=date(2025, 1, 8),
        segments=(
            _segment(
                contract="JM2505",
                start=date(2025, 1, 2),
                end=date(2025, 1, 3),
                source_identity=ENGINE_A,
            ),
            _segment(
                contract="JM2509",
                start=date(2025, 1, 6),
                end=date(2025, 1, 8),
                source_identity=ENGINE_B,
            ),
        ),
    )
    current = _lineage(
        through=date(2025, 1, 8),
        segments=(
            _segment(
                contract="JM2501",
                start=date(2025, 1, 2),
                end=date(2025, 1, 3),
                source_identity=ENGINE_A,
            ),
            previous.ordered_segments[1],
        ),
        manifest="2" * 64,
    )

    assert decide_subing_strategy_performance_tail(
        previous=previous,
        current=current,
        previous_identity=_identity(),
        current_identity=_identity(),
    ) == FULL_REBUILD_REQUIRED


def test_decide_immutable_prefix_canonical_lineage_drift_requires_full_rebuild() -> None:
    tail = _segment(
        contract="JM2509",
        start=date(2025, 1, 6),
        end=date(2025, 1, 8),
        source_identity=ENGINE_B,
    )
    previous = _lineage(
        through=date(2025, 1, 8),
        segments=(
            _segment(
                contract="JM2505",
                start=date(2025, 1, 2),
                end=date(2025, 1, 3),
                source_identity=ENGINE_A,
            ),
            tail,
        ),
    )
    current = _lineage(
        through=date(2025, 1, 8),
        segments=(
            _segment(
                contract="JM2505",
                start=date(2025, 1, 2),
                end=date(2025, 1, 3),
                source_identity="d" * 64,
            ),
            tail,
        ),
        manifest="2" * 64,
    )

    assert decide_subing_strategy_performance_tail(
        previous=previous,
        current=current,
        previous_identity=_identity(),
        current_identity=_identity(),
    ) == FULL_REBUILD_REQUIRED


def test_decide_coverage_regression_requires_full_rebuild() -> None:
    segments = (
        _segment(
            contract="JM2505",
            start=date(2025, 1, 2),
            end=date(2025, 1, 8),
            source_identity=ENGINE_A,
        ),
    )
    previous = _lineage(through=date(2025, 1, 8), segments=segments)
    current = _lineage(through=date(2025, 1, 7), segments=segments, manifest="2" * 64)

    assert decide_subing_strategy_performance_tail(
        previous=previous,
        current=current,
        previous_identity=_identity(),
        current_identity=_identity(),
    ) == FULL_REBUILD_REQUIRED


def test_decide_reordered_overlapping_or_gapped_segments_require_full_rebuild() -> None:
    first = _segment(
        contract="JM2505",
        start=date(2025, 1, 2),
        end=date(2025, 1, 3),
        source_identity=ENGINE_A,
    )
    second = _segment(
        contract="JM2509",
        start=date(2025, 1, 6),
        end=date(2025, 1, 8),
        source_identity=ENGINE_B,
    )
    previous = _lineage(through=date(2025, 1, 8), segments=(first, second))

    reordered = _lineage(
        through=date(2025, 1, 8),
        segments=(second, first),
        manifest="2" * 64,
    )
    overlapping = _lineage(
        through=date(2025, 1, 8),
        segments=(
            first,
            _segment(
                contract="JM2509",
                start=date(2025, 1, 3),
                end=date(2025, 1, 8),
                source_identity=ENGINE_B,
            ),
        ),
        manifest="3" * 64,
    )
    gapped = _lineage(
        through=date(2025, 1, 10),
        segments=(
            first,
            _segment(
                contract="JM2513",
                start=date(2025, 1, 10),
                end=date(2025, 1, 10),
                source_identity="c" * 64,
            ),
        ),
        manifest="4" * 64,
    )

    for current in (reordered, overlapping, gapped):
        assert decide_subing_strategy_performance_tail(
            previous=previous,
            current=current,
            previous_identity=_identity(),
            current_identity=_identity(),
        ) == FULL_REBUILD_REQUIRED


def test_decide_strategy_or_engine_identity_drift_requires_full_rebuild() -> None:
    segments = (
        _segment(
            contract="JM2505",
            start=date(2025, 1, 2),
            end=date(2025, 1, 8),
            source_identity=ENGINE_A,
        ),
    )
    lineage = _lineage(through=date(2025, 1, 8), segments=segments)

    assert decide_subing_strategy_performance_tail(
        previous=lineage,
        current=lineage,
        previous_identity=_identity(ENGINE_A),
        current_identity=_identity(ENGINE_B),
    ) == FULL_REBUILD_REQUIRED
    assert decide_subing_strategy_performance_tail(
        previous=lineage,
        current=lineage,
        previous_identity=_identity(),
        current_identity=SubingStrategyPerformanceSemanticIdentity(
            strategy_id="other_strategy",
            formula_version=FORMULA,
            engine_identity_sha256=ENGINE_A,
        ),
    ) == FULL_REBUILD_REQUIRED


def test_lineage_error_does_not_include_stack_or_sql() -> None:
    exc = SubingStrategyPerformanceLineageError()
    assert exc.code == "SUBING_STRATEGY_PERFORMANCE_LINEAGE_UNAVAILABLE"
    assert str(exc) == "SUBING_STRATEGY_PERFORMANCE_LINEAGE_UNAVAILABLE"
    assert "Traceback" not in str(exc)
