from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.data_core.bar_schema import CanonicalBar
from app.data_core.aggregation import AggregationSession
from app.data_core.canonical_store import (
    CANONICAL_MANIFEST_FORMAT_V2,
    CanonicalStore,
    PublishExpectation,
)
from app.data_core.catalog import GapWindow, HistoricalCatalog
from app.data_core.contracts import (
    BarFrequency,
    BarQuery,
    DataGapError,
    DatasetAmbiguousError,
    DatasetOrigin,
    DatasetKey,
    DatasetKind,
    ManifestLineage,
)
from app.data_core.historical_reader import CanonicalHistoricalReader
from app.data_core.rqdata_adapter import (
    ProviderBarBatch,
    ProviderBarRequest,
    TradingSessionCoverage,
)
from app.db.base import Base
from app.models.data_center import MainContractMap


START = datetime(2026, 7, 1, 1, 0, tzinfo=UTC)
FIRST = datetime(2026, 7, 1, 1, 1, tzinfo=UTC)
SECOND = datetime(2026, 7, 1, 1, 2, tzinfo=UTC)
FIFTH = datetime(2026, 7, 1, 1, 5, tzinfo=UTC)


def _dataset(
    contract: str = "JM2609",
    frequency: BarFrequency = BarFrequency.M1,
) -> DatasetKey:
    return DatasetKey(
        provider="rqdata",
        dataset_kind=DatasetKind.ACTUAL_DOMINANT,
        symbol="jm",
        contract_or_series=contract,
        frequency=frequency,
        adjustment="none",
        schema_version="canonical-bar-v1",
    )


def _bar(
    bar_end: datetime,
    close: str,
    *,
    contract: str = "JM2609",
    trading_day: date = date(2026, 7, 1),
    frequency: BarFrequency = BarFrequency.M1,
) -> CanonicalBar:
    return CanonicalBar(
        provider="rqdata",
        dataset_kind=DatasetKind.ACTUAL_DOMINANT,
        symbol="jm",
        contract_or_series=contract,
        frequency=frequency,
        bar_end=bar_end,
        trading_day=trading_day,
        open=Decimal("100"),
        high=Decimal("102"),
        low=Decimal("99"),
        close=Decimal(close),
        volume=Decimal("12"),
        turnover=Decimal("1213.5"),
        open_interest=Decimal("99"),
        adjustment="none",
        schema_version="canonical-bar-v1",
    )


def _weekly_dataset() -> DatasetKey:
    return DatasetKey(
        provider="rqdata",
        dataset_kind=DatasetKind.CONTINUOUS,
        symbol="jm",
        contract_or_series="JM.MAIN",
        frequency=BarFrequency.W1,
        adjustment="none",
        schema_version="canonical-bar-v1",
    )


def _weekly_bar(bar_end: datetime, trading_day: date) -> CanonicalBar:
    return CanonicalBar(
        provider="rqdata",
        dataset_kind=DatasetKind.CONTINUOUS,
        symbol="jm",
        contract_or_series="JM.MAIN",
        frequency=BarFrequency.W1,
        bar_end=bar_end,
        trading_day=trading_day,
        open=Decimal("100"),
        high=Decimal("102"),
        low=Decimal("99"),
        close=Decimal("101"),
        volume=Decimal("12"),
        turnover=Decimal("1213.5"),
        open_interest=Decimal("99"),
        adjustment="none",
        schema_version="canonical-bar-v1",
    )


def _publish_sample(
    *,
    root: Path,
    session: Session,
    bars: tuple[CanonicalBar, ...] = (_bar(FIRST, "101"), _bar(SECOND, "101.25")),
    dataset: DatasetKey | None = None,
    data_version: str = "provider-final-20260701",
    manifest_version: str = "canonical-manifest-v1",
    overlap_reason: str | None = None,
) -> None:
    store = CanonicalStore(
        staging_root=root / "staging",
        canonical_root=root / "canonical",
        metadata_session_factory=lambda: sessionmaker(
            bind=session.get_bind(),
            expire_on_commit=False,
        )(),
    )
    source_minutes = {
        BarFrequency.M1: 1,
        BarFrequency.M5: 5,
        BarFrequency.M15: 15,
        BarFrequency.M30: 30,
        BarFrequency.H1: 60,
    }.get((dataset or _dataset()).frequency, 1)
    request = ProviderBarRequest(
        dataset=dataset or _dataset(),
        start=bars[0].bar_end - timedelta(minutes=source_minutes),
        end=bars[-1].bar_end,
        sessions=(
            TradingSessionCoverage(
                trading_day=bars[0].trading_day,
                start=bars[0].bar_end - timedelta(minutes=source_minutes),
                end=bars[-1].bar_end,
                expected_bar_ends=tuple(bar.bar_end for bar in bars),
            ),
        ),
    )
    staged = store.stage(
        ProviderBarBatch(
            request=request,
            bars=bars,
            data_version=data_version,
        )
    )
    source = staged.source
    aggregate = source.dataset.frequency in {
        BarFrequency.M5,
        BarFrequency.M15,
        BarFrequency.M30,
        BarFrequency.H1,
    }
    store.publish(
        staged,
        PublishExpectation(
            dataset=source.dataset,
            coverage_start=source.coverage_start,
            coverage_end=source.coverage_end,
            row_count=source.row_count,
            data_version=source.data_version,
            manifest_version=manifest_version,
            file_checksum=staged.file_checksum,
            canonical_logical_fingerprint=staged.canonical_logical_fingerprint,
            overlap_reason=overlap_reason,
            manifest_format=(
                CANONICAL_MANIFEST_FORMAT_V2 if aggregate else "canonical-manifest-v1"
            ),
            lineage=(
                ManifestLineage(
                    origin=DatasetOrigin.PREAGGREGATED_FROM_1M,
                    source_frequency=BarFrequency.M1,
                    legacy_source_checksum="a" * 64,
                    quality_evidence_digest="b" * 64,
                )
                if aggregate
                else None
            ),
        ),
    )


def test_reader_returns_verified_direct_bars_with_catalog_lineage(tmp_path: Path) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE VIEW data_core_main_contract_map AS
                SELECT id, instrument_symbol AS symbol, trade_date AS trading_day,
                       contract_code AS actual_contract, provider, rank, rule,
                       data_version, created_at
                FROM main_contract_map
                WHERE provider = 'rqdata' AND rank = 1
                  AND rule = 'volume_open_interest'
                """
            )
        )
    with sessionmaker(bind=engine, expire_on_commit=False)() as session:
        _publish_sample(root=tmp_path, session=session)
        result = CanonicalHistoricalReader(
            catalog=HistoricalCatalog(session),
            canonical_root=tmp_path / "canonical",
        ).get_bars(
            BarQuery(
                dataset_kind=DatasetKind.ACTUAL_DOMINANT,
                symbol="jm",
                contract_or_series="JM2609",
                frequency=BarFrequency.M1,
                start=START,
                end=SECOND,
            )
        )

    assert [bar.close for bar in result.bars] == [Decimal("101"), Decimal("101.25")]
    assert result.source_datasets == (_dataset(),)
    assert result.requested_window == (START, SECOND)
    assert result.data_type is DatasetKind.ACTUAL_DOMINANT
    assert result.derived_frequency is None
    assert len(result.manifest_digests) == 1
    assert result.source_data_versions == ("provider-final-20260701",)


def test_reader_selects_replacement_partition_without_reading_original(
    tmp_path: Path,
) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as session:
        _publish_sample(root=tmp_path, session=session)
        _publish_sample(
            root=tmp_path,
            session=session,
            bars=(_bar(FIRST, "100.5"), _bar(SECOND, "100.75")),
            data_version="provider-final-20260701-jm-session-v1",
            manifest_version="canonical-manifest-v2-jm-session",
            overlap_reason="version_replacement",
        )

        result = CanonicalHistoricalReader(
            catalog=HistoricalCatalog(session),
            canonical_root=tmp_path / "canonical",
        ).get_bars(
            BarQuery(
                dataset_kind=DatasetKind.ACTUAL_DOMINANT,
                symbol="jm",
                contract_or_series="JM2609",
                frequency=BarFrequency.M1,
                start=START,
                end=SECOND,
            )
        )

    assert [bar.close for bar in result.bars] == [
        Decimal("100.5"),
        Decimal("100.75"),
    ]
    assert result.source_data_versions == (
        "provider-final-20260701-jm-session-v1",
    )
    assert len(result.manifest_digests) == 1


def test_reader_rejects_identical_duplicate_primary_keys(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with Session(engine) as session:
        reader = CanonicalHistoricalReader(
            catalog=HistoricalCatalog(session),
            canonical_root=(tmp_path / "canonical").resolve(),
        )
        duplicate = _bar(FIRST, "101")
        monkeypatch.setattr(
            reader,
            "_read_direct_dataset",
            lambda *_args, **_kwargs: (
                (duplicate, duplicate),
                ("a" * 64,),
                ("provider-final-20260701",),
            ),
        )
        monkeypatch.setattr(reader, "_require_direct_coverage", lambda *_args, **_kwargs: None)

        with pytest.raises(
            DatasetAmbiguousError,
            match="DATASET_AMBIGUOUS",
        ):
            reader.get_bars(
                BarQuery(
                    dataset_kind=DatasetKind.ACTUAL_DOMINANT,
                    symbol="jm",
                    contract_or_series="JM2609",
                    frequency=BarFrequency.M1,
                    start=START,
                    end=SECOND,
                )
            )


def test_weekly_reader_uses_padded_calendar_without_partial_month_end_week(
    tmp_path: Path,
) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    weekly_end = datetime(2026, 6, 26, tzinfo=UTC)
    session_days = (
        date(2026, 6, 26),
        date(2026, 6, 29),
        date(2026, 6, 30),
        date(2026, 7, 1),
        date(2026, 7, 2),
        date(2026, 7, 3),
    )
    sessions = tuple(
        AggregationSession(
            name=f"day-{trading_day.isoformat()}",
            trading_day=trading_day,
            start=datetime.combine(
                trading_day,
                datetime.min.time(),
                tzinfo=UTC,
            ),
            end=datetime.combine(
                trading_day,
                datetime.min.time(),
                tzinfo=UTC,
            )
            + timedelta(hours=1),
        )
        for trading_day in session_days
    )
    with sessionmaker(bind=engine, expire_on_commit=False)() as session:
        _publish_sample(
            root=tmp_path,
            session=session,
            dataset=_weekly_dataset(),
            bars=(_weekly_bar(weekly_end, weekly_end.date()),),
        )
        result = CanonicalHistoricalReader(
            catalog=HistoricalCatalog(session),
            canonical_root=tmp_path / "canonical",
            session_provider=lambda _symbol, _start, _end: sessions,
        ).get_bars(
            BarQuery(
                dataset_kind=DatasetKind.CONTINUOUS,
                symbol="jm",
                contract_or_series="JM.MAIN",
                frequency=BarFrequency.W1,
                start=datetime(2026, 6, 1, tzinfo=UTC),
                end=datetime(2026, 7, 1, tzinfo=UTC),
            )
        )

    assert [bar.bar_end for bar in result.bars] == [weekly_end]


def test_reader_rejects_partially_covered_window_instead_of_shortening_it(
    tmp_path: Path,
) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as session:
        _publish_sample(root=tmp_path, session=session)
        reader = CanonicalHistoricalReader(
            catalog=HistoricalCatalog(session),
            canonical_root=tmp_path / "canonical",
        )

        with pytest.raises(DataGapError) as raised:
            reader.get_bars(
                BarQuery(
                    dataset_kind=DatasetKind.ACTUAL_DOMINANT,
                    symbol="jm",
                    contract_or_series="JM2609",
                    frequency=BarFrequency.M1,
                    start=START,
                    end=FIFTH,
                )
            )

    assert raised.value.facts["reason"] == "catalog_coverage_missing"


def test_reader_resolves_actual_dominant_from_rank_one_mapping(tmp_path: Path) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE VIEW data_core_main_contract_map AS
                SELECT id, instrument_symbol AS symbol, trade_date AS trading_day,
                       contract_code AS actual_contract, provider, rank, rule,
                       data_version, created_at
                FROM main_contract_map
                WHERE provider = 'rqdata' AND rank = 1
                  AND rule = 'volume_open_interest'
                """
            )
        )
    with sessionmaker(bind=engine, expire_on_commit=False)() as session:
        _publish_sample(root=tmp_path, session=session)
        session.add(
            MainContractMap(
                instrument_symbol="jm",
                trade_date=date(2026, 7, 1),
                rank=1,
                contract_code="JM2609",
                rule="volume_open_interest",
                provider="rqdata",
                data_version="rqdata-rank1-20260701",
            )
        )
        session.commit()
        reader = CanonicalHistoricalReader(
            catalog=HistoricalCatalog(session),
            canonical_root=tmp_path / "canonical",
            session_provider=lambda _symbol, _start, _end: (
                AggregationSession(
                    name="night",
                    trading_day=date(2026, 7, 1),
                    start=START,
                    end=SECOND,
                ),
            ),
        )
        result = reader.get_bars(
            BarQuery(
                dataset_kind=DatasetKind.ACTUAL_DOMINANT,
                symbol="jm",
                contract_or_series=None,
                frequency=BarFrequency.M1,
                start=START,
                end=SECOND,
            )
        )

    assert [bar.contract_or_series for bar in result.bars] == ["JM2609", "JM2609"]
    assert result.source_datasets == (_dataset(),)


def test_actual_dominant_reads_only_mapping_valid_segments_and_ignores_other_contract_days(
    tmp_path: Path,
) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE VIEW data_core_main_contract_map AS
                SELECT id, instrument_symbol AS symbol, trade_date AS trading_day,
                       contract_code AS actual_contract, provider, rank, rule,
                       data_version, created_at
                FROM main_contract_map
                WHERE provider = 'rqdata' AND rank = 1
                  AND rule = 'volume_open_interest'
                """
            )
        )
    day2_start = datetime(2026, 7, 2, 1, 0, tzinfo=UTC)
    day2_end = datetime(2026, 7, 2, 1, 1, tzinfo=UTC)
    with sessionmaker(bind=engine, expire_on_commit=False)() as session:
        _publish_sample(
            root=tmp_path,
            session=session,
            bars=(_bar(FIRST, "101"),),
        )
        _publish_sample(
            root=tmp_path,
            session=session,
            dataset=_dataset("JM2610"),
            bars=(
                _bar(
                    day2_end,
                    "102",
                    contract="JM2610",
                    trading_day=date(2026, 7, 2),
                ),
            ),
        )
        session.add_all(
            [
                MainContractMap(
                    instrument_symbol="jm",
                    trade_date=date(2026, 7, day),
                    rank=1,
                    contract_code=contract,
                    rule="volume_open_interest",
                    provider="rqdata",
                    data_version="rqdata-rank1-test",
                )
                for day, contract in ((1, "JM2609"), (2, "JM2610"))
            ]
        )
        catalog = HistoricalCatalog(session)
        catalog.record_gap(
            _dataset("JM2609"),
            GapWindow(
                gap_start=day2_start,
                gap_end=day2_end,
                reason_code="outside_mapping_segment",
                details={},
            ),
        )
        session.commit()
        sessions = (
            AggregationSession(
                name="night",
                trading_day=date(2026, 7, 1),
                start=START,
                end=FIRST,
            ),
            AggregationSession(
                name="night",
                trading_day=date(2026, 7, 2),
                start=day2_start,
                end=day2_end,
            ),
        )
        result = CanonicalHistoricalReader(
            catalog=catalog,
            canonical_root=tmp_path / "canonical",
            session_provider=lambda _symbol, _start, _end: sessions,
        ).get_bars(
            BarQuery(
                dataset_kind=DatasetKind.ACTUAL_DOMINANT,
                symbol="jm",
                contract_or_series=None,
                frequency=BarFrequency.M1,
                start=START,
                end=day2_end,
            )
        )

    assert [bar.contract_or_series for bar in result.bars] == ["JM2609", "JM2610"]


def test_reader_does_not_fallback_from_missing_five_minute_to_one_minute(
    tmp_path: Path,
) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE VIEW data_core_main_contract_map AS
                SELECT id, instrument_symbol AS symbol, trade_date AS trading_day,
                       contract_code AS actual_contract, provider, rank, rule,
                       data_version, created_at
                FROM main_contract_map
                WHERE provider = 'rqdata' AND rank = 1
                  AND rule = 'volume_open_interest'
                """
            )
        )
    bars = tuple(
        _bar(
            datetime(2026, 7, 1, 1, minute, tzinfo=UTC),
            f"101.{minute}",
        )
        for minute in range(1, 6)
    )
    with sessionmaker(bind=engine, expire_on_commit=False)() as session:
        _publish_sample(root=tmp_path, session=session, bars=bars)
        session.add(
            MainContractMap(
                instrument_symbol="jm",
                trade_date=date(2026, 7, 1),
                rank=1,
                contract_code="JM2609",
                rule="volume_open_interest",
                provider="rqdata",
                data_version="rqdata-rank1-test",
            )
        )
        session.commit()
        reader = CanonicalHistoricalReader(
            catalog=HistoricalCatalog(session),
            canonical_root=tmp_path / "canonical",
            session_provider=lambda _symbol, _start, _end: (
                AggregationSession(
                    name="night",
                    trading_day=date(2026, 7, 1),
                    start=START,
                    end=FIFTH,
                ),
            ),
        )
        with pytest.raises(DataGapError) as raised:
            reader.get_bars(
                BarQuery(
                    dataset_kind=DatasetKind.ACTUAL_DOMINANT,
                    symbol="jm",
                    contract_or_series="JM2609",
                    frequency=BarFrequency.M5,
                    start=START,
                    end=FIFTH,
                )
            )

    assert raised.value.facts["reason"] == "catalog_coverage_missing"


def test_reader_reads_persisted_five_minute_partition_at_same_frequency(
    tmp_path: Path,
) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    bar = _bar(FIFTH, "101.5", frequency=BarFrequency.M5)
    with sessionmaker(bind=engine, expire_on_commit=False)() as session:
        _publish_sample(
            root=tmp_path,
            session=session,
            bars=(bar,),
            dataset=_dataset(frequency=BarFrequency.M5),
        )
        result = CanonicalHistoricalReader(
            catalog=HistoricalCatalog(session),
            canonical_root=tmp_path / "canonical",
        ).get_bars(
            BarQuery(
                dataset_kind=DatasetKind.ACTUAL_DOMINANT,
                symbol="jm",
                contract_or_series="JM2609",
                frequency=BarFrequency.M5,
                start=START,
                end=FIFTH,
            )
        )

    assert result.bars == (bar,)
    assert result.source_datasets == (_dataset(frequency=BarFrequency.M5),)
    assert result.derived_frequency is None


@pytest.mark.parametrize("frequency", tuple(BarFrequency))
def test_reader_reads_each_legal_frequency_only_from_same_frequency_catalog(
    tmp_path: Path,
    frequency: BarFrequency,
) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    bar_end = datetime(2026, 7, 3, 0, 0, tzinfo=UTC)
    bar = _bar(bar_end, "101.5", frequency=frequency)
    dataset = _dataset(frequency=frequency)
    root = tmp_path / frequency.value
    root.mkdir()
    with sessionmaker(bind=engine, expire_on_commit=False)() as session:
        _publish_sample(
            root=root,
            session=session,
            bars=(bar,),
            dataset=dataset,
        )
        result = CanonicalHistoricalReader(
            catalog=HistoricalCatalog(session),
            canonical_root=root / "canonical",
        ).get_bars(
            BarQuery(
                dataset_kind=DatasetKind.ACTUAL_DOMINANT,
                symbol="jm",
                contract_or_series="JM2609",
                frequency=frequency,
                start=bar_end - timedelta(minutes=1),
                end=bar_end,
            )
        )

    assert result.bars == (bar,)
    assert result.source_datasets == (dataset,)
    assert result.derived_frequency is None


def test_actual_dominant_weekly_uses_last_trading_day_rank_one_mapping(
    tmp_path: Path,
) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE VIEW data_core_main_contract_map AS
                SELECT id, instrument_symbol AS symbol, trade_date AS trading_day,
                       contract_code AS actual_contract, provider, rank, rule,
                       data_version, created_at
                FROM main_contract_map
                WHERE provider = 'rqdata' AND rank = 1
                  AND rule = 'volume_open_interest'
                """
            )
        )
    monday = date(2026, 6, 29)
    friday = date(2026, 7, 3)
    start = datetime(2026, 6, 28, 0, 0, tzinfo=UTC)
    end = datetime(2026, 7, 3, 0, 0, tzinfo=UTC)
    weekly_bar = _bar(
        end,
        "101.5",
        trading_day=friday,
        frequency=BarFrequency.W1,
    )
    with sessionmaker(bind=engine, expire_on_commit=False)() as session:
        _publish_sample(
            root=tmp_path,
            session=session,
            bars=(weekly_bar,),
            dataset=_dataset(frequency=BarFrequency.W1),
        )
        session.add_all(
            [
                MainContractMap(
                    instrument_symbol="jm",
                    trade_date=monday,
                    rank=1,
                    contract_code="JM2605",
                    rule="volume_open_interest",
                    provider="rqdata",
                    data_version="monday",
                ),
                MainContractMap(
                    instrument_symbol="jm",
                    trade_date=friday,
                    rank=1,
                    contract_code="JM2609",
                    rule="volume_open_interest",
                    provider="rqdata",
                    data_version="friday",
                ),
            ]
        )
        session.commit()
        sessions = (
            AggregationSession(
                name="monday",
                trading_day=monday,
                start=datetime(2026, 6, 29, 0, 0, tzinfo=UTC),
                end=datetime(2026, 6, 29, 1, 0, tzinfo=UTC),
            ),
            AggregationSession(
                name="friday",
                trading_day=friday,
                start=end - timedelta(hours=1),
                end=end,
            ),
        )
        result = CanonicalHistoricalReader(
            catalog=HistoricalCatalog(session),
            canonical_root=tmp_path / "canonical",
            session_provider=lambda _symbol, _start, _end: sessions,
        ).get_bars(
            BarQuery(
                dataset_kind=DatasetKind.ACTUAL_DOMINANT,
                symbol="jm",
                contract_or_series=None,
                frequency=BarFrequency.W1,
                start=start,
                end=end,
            )
        )

    assert result.bars == (weekly_bar,)
    assert result.source_datasets == (_dataset(frequency=BarFrequency.W1),)
