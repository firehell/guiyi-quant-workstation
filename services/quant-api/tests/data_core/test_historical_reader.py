from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.data_core.bar_schema import CanonicalBar
from app.data_core.aggregation import AggregationSession
from app.data_core.canonical_store import CanonicalStore, PublishExpectation
from app.data_core.catalog import HistoricalCatalog
from app.data_core.contracts import (
    BarFrequency,
    BarQuery,
    DataGapError,
    DatasetKey,
    DatasetKind,
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


def _dataset() -> DatasetKey:
    return DatasetKey(
        provider="rqdata",
        dataset_kind=DatasetKind.ACTUAL_DOMINANT,
        symbol="jm",
        contract_or_series="JM2609",
        frequency=BarFrequency.M1,
        adjustment="none",
        schema_version="canonical-bar-v1",
    )


def _bar(bar_end: datetime, close: str) -> CanonicalBar:
    return CanonicalBar(
        provider="rqdata",
        dataset_kind=DatasetKind.ACTUAL_DOMINANT,
        symbol="jm",
        contract_or_series="JM2609",
        frequency=BarFrequency.M1,
        bar_end=bar_end,
        trading_day=date(2026, 7, 1),
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


def _publish_sample(
    *,
    root: Path,
    session: Session,
    bars: tuple[CanonicalBar, ...] = (_bar(FIRST, "101"), _bar(SECOND, "101.25")),
) -> None:
    store = CanonicalStore(
        staging_root=root / "staging",
        canonical_root=root / "canonical",
        metadata_session_factory=lambda: sessionmaker(
            bind=session.get_bind(),
            expire_on_commit=False,
        )(),
    )
    request = ProviderBarRequest(
        dataset=_dataset(),
        start=START,
        end=bars[-1].bar_end,
        sessions=(
            TradingSessionCoverage(
                trading_day=date(2026, 7, 1),
                start=START,
                end=bars[-1].bar_end,
                expected_bar_ends=tuple(bar.bar_end for bar in bars),
            ),
        ),
    )
    staged = store.stage(
        ProviderBarBatch(
            request=request,
        bars=bars,
            data_version="provider-final-20260701",
        )
    )
    source = staged.source
    store.publish(
        staged,
        PublishExpectation(
            dataset=source.dataset,
            coverage_start=source.coverage_start,
            coverage_end=source.coverage_end,
            row_count=source.row_count,
            data_version=source.data_version,
            manifest_version="canonical-manifest-v1",
            file_checksum=staged.file_checksum,
            canonical_logical_fingerprint=staged.canonical_logical_fingerprint,
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


def test_reader_derives_five_minute_bars_from_verified_one_minute_source(
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
        result = reader.get_bars(
            BarQuery(
                dataset_kind=DatasetKind.ACTUAL_DOMINANT,
                symbol="jm",
                contract_or_series="JM2609",
                frequency=BarFrequency.M5,
                start=START,
                end=FIFTH,
            )
        )

    assert len(result.bars) == 1
    assert result.bars[0].close == Decimal("101.5")
    assert result.bars[0].frequency is BarFrequency.M5
    assert result.source_datasets == (_dataset(),)
    assert result.derived_frequency is BarFrequency.M5
