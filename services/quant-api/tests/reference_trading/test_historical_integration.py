from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from guiyi_quant.newow.product_adapters import build_product_identity
from guiyi_quant.newow.product_contracts import ProductFrequency, ProductStrategy
from guiyi_quant.newow.product_identity import (
    REFERENCE_MODEL_VERSION as NEWOW_REFERENCE_MODEL_VERSION,
    futures_adaptation_version,
)
from guiyi_quant.reference_trading import StreamIdentity
from guiyi_quant.subing_reference import (
    FORMULA_VERSIONS,
    REFERENCE_MODEL_VERSION,
    REFERENCE_MODEL_VERSION_V2,
)

from app.db.base import Base
from app.market_data.catalog import MarketCatalog
from app.market_data.domain import CanonicalBar, DatasetKey
from app.market_data.market_data_service import MarketDataService
from app.market_data.newow.product_reader import NewowProductReader
from app.market_data.rqdata_adapter import _aggregate_daily_rows
from app.market_data.storage import CanonicalMonthlyStore, PublishRequest
from app.market_data.subing_reference import SubingReferenceService
from app.models import Contract, Exchange, Instrument, TradingCalendar, TradingSession
from app.reference_trading.inputs import MarketDataHistoricalInputReader
from app.reference_trading.planning import (
    HistoricalReferencePlanner,
    HistoricalReferenceRequest,
    HistoricalStreamRequest,
    WorkBudget,
)
from app.reference_trading.repository import ReferenceRepository
from app.reference_trading.service import HistoricalReferenceService


class _Coverage:
    def __init__(self, first: date, last: date) -> None:
        self.first = first
        self.last = last

    def product_start(self, _symbol: str) -> date:
        return self.first

    def latest_complete_day(self, _products: tuple[str, ...]) -> date:
        return self.last


def _bar(end: datetime, trading_day: date, close: int) -> CanonicalBar:
    value = Decimal(close)
    return CanonicalBar(
        end, trading_day, value - 1, value + 2, value - 2, value,
        Decimal(10), Decimal(1000), Decimal(500),
    )


def _publish_all(catalog, store, frequency: str, bars: tuple[CanonicalBar, ...]) -> None:
    grouped: dict[tuple[int, int], list[CanonicalBar]] = defaultdict(list)
    for bar in bars:
        grouped[(bar.trading_day.year, bar.trading_day.month)].append(bar)
    for (year, month), values in sorted(grouped.items()):
        ordered = tuple(values)
        partition = store.publish(PublishRequest(
            DatasetKey("contract", "rb", "RB2701", frequency),
            year,
            month,
            ordered,
            tuple(item.bar_end for item in ordered),
        ))
        catalog.register_partition(partition)


def _newow_stream(strategy: ProductStrategy, frequency: ProductFrequency) -> StreamIdentity:
    identity = build_product_identity("rb", strategy, frequency)
    return StreamIdentity(
        strategy_code=f"newow_{strategy.value}",
        formula_versions=identity.formula_versions,
        profile_id=identity.profile_id,
        reference_model_version=NEWOW_REFERENCE_MODEL_VERSION,
        futures_adaptation_version=futures_adaptation_version(frequency.value),
        product="rb",
        frequency=frequency.value,
        series_kind="actual_dominant",
        recording_mode="historical_replay",
        observation_policy_version=None,
    )


def _subing_stream(frequency: str) -> StreamIdentity:
    return StreamIdentity(
        strategy_code="subing_reference",
        formula_versions=(FORMULA_VERSIONS[frequency],),
        profile_id=f"subing_reference_{frequency}_v1",
        reference_model_version=(
            REFERENCE_MODEL_VERSION_V2 if frequency == "1d" else REFERENCE_MODEL_VERSION
        ),
        futures_adaptation_version="subing_actual_dominant_v1",
        product="RB",
        frequency=frequency,
        series_kind="actual_dominant",
        recording_mode="historical_replay",
        observation_policy_version=None,
    )


def test_real_canonical_catalog_mds_builds_all_p4_strategy_frequency_streams(tmp_path) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    first = date(2026, 1, 5)
    days = tuple(first + timedelta(days=offset) for offset in range(84))
    trading_days = tuple(day for day in days if day.weekday() < 5)
    last = trading_days[-1]
    as_of = datetime.combine(last, time(13), tzinfo=UTC) - timedelta(hours=8) + timedelta(seconds=1)

    with Session(engine) as session:
        session.add_all((
            Exchange(code="SHFE", name="SHFE"),
            Instrument(symbol="rb", name="RB", exchange_code="SHFE", is_active=True),
            Contract(
                contract_code="RB2701", instrument_symbol="rb", exchange_code="SHFE",
                listed_date=first,
                expired_date=last + timedelta(days=30), provider="rqdata",
            ),
        ))
        session.add_all(
            TradingSession(
                exchange_code="SHFE", instrument_symbol="rb", session_name="day",
                start_time=time(9), end_time=time(13), effective_from=day,
                effective_to=day, is_active=True, provider="rqdata",
            )
            for day in trading_days
        )
        session.add_all(
            TradingCalendar(
                exchange_code="SHFE", trade_date=day,
                is_trading_day=day.weekday() < 5, provider="rqdata",
            )
            for day in days
        )
        session.commit()
        catalog = MarketCatalog(session, tmp_path)
        store = CanonicalMonthlyStore(tmp_path)
        catalog.upsert_main_contracts(
            tuple(("rb", day, "RB2701") for day in trading_days)
        )
        session.commit()

        by_frequency: dict[str, tuple[CanonicalBar, ...]] = {}
        for frequency, minutes in (("15m", 15), ("30m", 30), ("60m", 60)):
            count = 240 // minutes
            by_frequency[frequency] = tuple(
                _bar(
                    datetime.combine(day, time(9), tzinfo=UTC)
                    - timedelta(hours=8)
                    + timedelta(minutes=minutes * index),
                    day,
                    3500,
                )
                for day in trading_days
                for index in range(1, count + 1)
            )
        by_frequency["1d"] = tuple(
            _bar(
                datetime.combine(day, time(13), tzinfo=UTC) - timedelta(hours=8),
                day,
                3500,
            )
            for day in trading_days
        )
        daily_by_week: dict[tuple[int, int], list[CanonicalBar]] = defaultdict(list)
        for bar in by_frequency["1d"]:
            daily_by_week[bar.trading_day.isocalendar()[:2]].append(bar)
        by_frequency["1w"] = tuple(
            _aggregate_daily_rows(
                tuple((bar.trading_day, bar.as_record()) for bar in week_bars),
                bar_end=week_bars[-1].bar_end,
            )
            for week_bars in daily_by_week.values()
            if week_bars[-1].trading_day.weekday() == 4
        )
        for frequency, bars in by_frequency.items():
            _publish_all(catalog, store, frequency, bars)
        session.commit()

        market_data = MarketDataService(catalog, store)
        coverage = _Coverage(first, last)
        reader = MarketDataHistoricalInputReader(
            newow_reader=NewowProductReader(
                market_data, coverage=coverage, active_products=("rb",), now=lambda: as_of,
            ),
            subing_service=SubingReferenceService(
                market_data, coverage=coverage, active_products=("rb",), now=lambda: as_of,
            ),
        )
        streams = tuple(
            HistoricalStreamRequest(stream, first, last, as_of)
            for stream in (
                *(
                    _newow_stream(strategy, frequency)
                    for strategy in ProductStrategy
                    for frequency in (
                        ProductFrequency.DAILY,
                        ProductFrequency.WEEKLY,
                        ProductFrequency.HOURLY,
                    )
                ),
                *(_subing_stream(frequency) for frequency in ("15m", "30m", "60m", "1d")),
            )
        )
        prior_day = trading_days[-2]
        prior_as_of = (
            datetime.combine(prior_day, time(13), tzinfo=UTC)
            - timedelta(hours=8)
            + timedelta(seconds=1)
        )
        initial_streams = tuple(
            replace(item, through=prior_day, as_of=prior_as_of) for item in streams
        )
        request = HistoricalReferenceRequest(
            "build", initial_streams,
            WorkBudget(13, 100_000, 120, 100_000_000),
            batch_size=256,
        )
        planner = HistoricalReferencePlanner(reader, now=lambda: as_of)
        repository = ReferenceRepository(factory)
        plan = planner.plan(request)
        built = HistoricalReferenceService(repository, reader).execute(
            plan, plan.plan_hash,
        )
        advance_request = HistoricalReferenceRequest(
            "advance", streams, request.budget, batch_size=256,
        )
        advance_plan = planner.plan(advance_request)
        stepped = 0

        def count(value: int) -> None:
            nonlocal stepped
            stepped += value

        report = HistoricalReferenceService(
            repository, reader, step_counter=count,
        ).advance(advance_plan, advance_plan.plan_hash)

        metadata_probe = streams[-1]
        token_before_session_change = reader.plan_stream(metadata_probe).source_token
        first_session = session.scalar(
            select(TradingSession)
            .where(
                TradingSession.instrument_symbol == "rb",
                TradingSession.effective_from == first,
            )
            .limit(1)
        )
        assert first_session is not None
        first_session.start_time = time(8, 59)
        session.commit()
        token_after_session_change = reader.plan_stream(metadata_probe).source_token

    assert len(plan.streams) == 13
    assert built.status == "completed"
    assert report.status == "completed", [
        (
            stream.request.identity.strategy_code,
            stream.request.identity.frequency,
            item.status,
            item.reason,
            item.completed_bars,
        )
        for stream, item in zip(advance_plan.streams, report.streams, strict=True)
        if item.status != "completed"
    ]
    assert {item.status for item in report.streams} == {"completed"}
    assert all(item.snapshot is not None for item in report.streams)
    assert stepped == 47
    assert token_after_session_change != token_before_session_change
