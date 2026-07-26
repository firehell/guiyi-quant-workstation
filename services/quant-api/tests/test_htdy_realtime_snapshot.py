from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.data_center import (
    DataProfile,
    LiveMinuteBar,
    MainContractMap,
    MarketDataFile,
    ProfileActiveBinding,
    TradingCalendar,
    TradingSession,
)
from app.services.htdy_realtime_models import (
    HistoricalWarmupIdentity,
    HtDy15mBarSnapshot,
)
from app.services.jm_session_contract import (
    JM_SESSION_PROVIDER,
    JM_SESSION_ROWS,
)
from app.services.rqdata_ingest.parquet import sha256_file

SHANGHAI = ZoneInfo("Asia/Shanghai")


def _factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _seed_calendar_and_sessions(session, trading_day: date) -> None:
    previous = trading_day - timedelta(days=14)
    for offset in range(15):
        current = previous + timedelta(days=offset)
        session.add(
            TradingCalendar(
                exchange_code="DCE",
                trade_date=current,
                is_trading_day=current.weekday() < 5,
                has_night_session=current.weekday() < 5,
                provider="fixture",
            )
        )
    for name, start, end in JM_SESSION_ROWS:
        session.add(
            TradingSession(
                exchange_code="DCE",
                instrument_symbol="jm",
                session_name=name,
                start_time=start,
                end_time=end,
                is_active=True,
                provider=JM_SESSION_PROVIDER,
            )
        )


def _canonical_day_bucket_ends(day: date) -> list[datetime]:
    bucket_ends: list[datetime] = []
    for name, start, end in JM_SESSION_ROWS:
        if name == "night":
            continue
        cursor = datetime.combine(day, start)
        session_end = datetime.combine(day, end)
        while cursor < session_end:
            cursor = min(cursor + timedelta(minutes=15), session_end)
            bucket_ends.append(cursor)
    return bucket_ends


def _seed_history(
    session,
    tmp_path: Path,
    trading_day: date,
    *,
    contract: str = "JM2609",
    quality_status: str = "passed",
    contract_role: str = "actual_contract",
    latest_history_day: date | None = None,
    source_interval: str | None = "1m",
) -> None:
    rows = []
    prior_days = []
    current = latest_history_day or trading_day - timedelta(days=1)
    while len(prior_days) < 9:
        if current.weekday() < 5:
            prior_days.append(current)
        current -= timedelta(days=1)
    for current in reversed(prior_days):
        for stamp in _canonical_day_bucket_ends(current):
            close = Decimal("100") + len(rows)
            row = {
                "symbol": "jm",
                "contract": contract,
                "exchange": "DCE",
                "datetime": stamp,
                "trading_day": current,
                "open": close - 1,
                "high": close + 1,
                "low": close - 2,
                "close": close,
                "volume": 10,
                "open_interest": 1,
                "turnover": 1,
                "period": "15m",
                "provider": "rqdata",
                "data_version": "fixture",
            }
            if source_interval is not None:
                row["source_interval"] = source_interval
            rows.append(row)
    path = tmp_path / "jm_15m.parquet"
    pd.DataFrame(rows).to_parquet(path, index=False)
    asset = MarketDataFile(
        provider="rqdata",
        data_type="bars",
        instrument_symbol="jm",
        contract_code=contract,
        period="15m",
        start_time=rows[0]["datetime"],
        end_time=rows[-1]["datetime"],
        file_path=str(path),
        row_count=len(rows),
        file_size_bytes=path.stat().st_size,
        checksum=sha256_file(path),
        data_version="fixture",
        data_role="primary",
        quality_status=quality_status,
    )
    session.add(
        DataProfile(
            profile_id="live_observation_v1",
            label="fixture",
            contract_roles=["dominant_main", "actual_contract"],
            periods=["1m", "15m"],
            quality_policy="active_entry",
            provider="rqdata",
            is_active=True,
        )
    )
    session.add(asset)
    session.flush()
    session.add(
        ProfileActiveBinding(
            profile_id="live_observation_v1",
            instrument_symbol="jm",
            contract_code=contract,
            contract_role=contract_role,
            period="15m",
            data_version="fixture",
            market_data_file_id=asset.id,
            binding_status="active",
        )
    )


def _seed_mapping(session, trading_day: date, *, contract: str = "JM2609") -> None:
    session.add(
        MainContractMap(
            instrument_symbol="jm",
            trade_date=trading_day,
            rank=1,
            contract_code=contract,
            rule="volume_open_interest",
            provider="rqdata",
            data_version="fixture",
        )
    )


def _seed_minutes(
    session,
    trading_day: date,
    *,
    end: datetime,
    contract: str = "JM2609",
    revision: int = 0,
    count: int = 15,
) -> None:
    start = end - timedelta(minutes=count - 1)
    for offset in range(count):
        close = Decimal("100") + offset
        bar_datetime = start + timedelta(minutes=offset)
        session.add(
            LiveMinuteBar(
                provider="rqdata",
                instrument_symbol="jm",
                contract_code=contract,
                exchange_code="DCE",
                period="1m",
                bar_datetime=bar_datetime,
                trading_day=trading_day,
                open=close - 1,
                high=close + 1,
                low=close - 2,
                close=close,
                volume=10,
                open_interest=1,
                turnover=1,
                bar_status="confirmed",
                quality_status="passed",
                confirmed_at=bar_datetime.replace(tzinfo=SHANGHAI).astimezone(UTC),
                revision=revision,
            )
        )


def _seed_prior_sessions(session, day: date, *, contract: str = "JM2609") -> None:
    _seed_minutes(
        session, day, end=datetime(2026, 7, 24, 23), count=120, contract=contract
    )


def _seed_through_day_am(session, day: date) -> None:
    _seed_prior_sessions(session, day)
    _seed_minutes(session, day, end=datetime(2026, 7, 27, 10, 15), count=75)
    _seed_minutes(session, day, end=datetime(2026, 7, 27, 11, 30), count=60)


def _seed_full_trading_day(session, day: date) -> None:
    _seed_through_day_am(session, day)
    _seed_minutes(session, day, end=datetime(2026, 7, 27, 15), count=90)


def _resolver(session, tmp_path: Path):
    from app.services.htdy_realtime_snapshot import HtDyRealtimeSnapshotResolver

    return HtDyRealtimeSnapshotResolver(session, project_root=tmp_path)


def _postgres_shaped_minute(
    *,
    bar_datetime: datetime,
    confirmed_at: datetime,
    row_id: int = 1,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=row_id,
        provider="rqdata",
        instrument_symbol="jm",
        contract_code="JM2609",
        period="1m",
        bar_datetime=bar_datetime,
        trading_day=date(2026, 7, 27),
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100.5"),
        volume=Decimal("10"),
        bar_status="confirmed",
        quality_status="passed",
        confirmed_at=confirmed_at,
        revision=0,
    )


@pytest.mark.parametrize(
    "rows,reason",
    [
        ([], "HTDY_TRADING_CALENDAR_MISSING"),
        (
            [
                SimpleNamespace(
                    exchange_code="DCE",
                    trade_date=date(2026, 7, 26),
                    is_trading_day=False,
                    has_night_session=False,
                    provider="fixture",
                )
            ],
            "HTDY_TRADING_DAY_NOT_OPEN",
        ),
        (
            [
                SimpleNamespace(
                    exchange_code="DCE",
                    trade_date=date(2026, 7, 26),
                    is_trading_day=True,
                    has_night_session=True,
                    provider="fixture",
                )
            ],
            "HTDY_TRADING_DAY_NOT_OPEN",
        ),
        (
            [
                SimpleNamespace(
                    exchange_code="DCE",
                    trade_date=date(2026, 7, 27),
                    is_trading_day=True,
                    has_night_session=True,
                    provider="fixture",
                ),
                SimpleNamespace(
                    exchange_code="DCE",
                    trade_date=date(2026, 7, 27),
                    is_trading_day=True,
                    has_night_session=True,
                    provider="fixture",
                ),
            ],
            "HTDY_TRADING_CALENDAR_DUPLICATE",
        ),
        (
            [
                SimpleNamespace(
                    exchange_code="DCE",
                    trade_date=date(2026, 7, 27),
                    is_trading_day=True,
                    has_night_session=True,
                    provider="fixture",
                ),
                SimpleNamespace(
                    exchange_code="DCE",
                    trade_date=date(2026, 7, 27),
                    is_trading_day=False,
                    has_night_session=False,
                    provider="other",
                ),
            ],
            "HTDY_TRADING_CALENDAR_CONFLICT",
        ),
    ],
)
def test_target_trading_calendar_requires_one_unambiguous_open_dce_row(
    rows: list[SimpleNamespace],
    reason: str,
) -> None:
    import app.services.htdy_realtime_snapshot as module

    with pytest.raises(ValueError, match=reason):
        module._validate_target_calendar_rows(
            rows, rows[0].trade_date if rows else date(2026, 7, 27)
        )


def test_session_aware_bucket_is_confirmed_and_hash_is_restart_stable(
    tmp_path: Path,
) -> None:
    day = date(2026, 7, 27)
    factory = _factory()
    with factory() as session:
        _seed_calendar_and_sessions(session, day)
        _seed_mapping(session, day)
        _seed_history(session, tmp_path, day)
        _seed_prior_sessions(session, day)
        _seed_minutes(session, day, end=datetime(2026, 7, 27, 9, 15))
        session.commit()
        first = _resolver(session, tmp_path).resolve(
            trading_day=day, detected_at=datetime(2026, 7, 27, 1, 16, tzinfo=UTC)
        )
        second = _resolver(session, tmp_path).resolve(
            trading_day=day, detected_at=datetime(2026, 7, 27, 1, 16, tzinfo=UTC)
        )

    assert first.buckets[-1].status == "confirmed"
    assert first.buckets[-1].identity.session_id == "DCE:jm:day_am_1"
    assert first.snapshot_sha256 == second.snapshot_sha256
    assert len(first.source_minutes) == 135
    assert len(first.historical_bars) == 128
    assert all(isinstance(bar, HtDy15mBarSnapshot) for bar in first.historical_bars)
    assert first.historical_bars[-1].identity.session_id == "DCE:jm:day_pm"
    assert first.historical_bars[-1].identity.actual_contract == "JM2609"
    assert first.historical_bars[-1].identity.bucket_start == datetime(
        2026, 7, 24, 14, 45, tzinfo=SHANGHAI
    )
    assert first.historical_bars[-1].identity.bucket_end == datetime(
        2026, 7, 24, 15, tzinfo=SHANGHAI
    )
    assert first.historical_bars[-1].source_minutes == ()
    assert (
        first.historical_identity.binding_snapshot["quality_policy"] == "active_entry"
    )
    assert (
        first.historical_identity.binding_snapshot["source_interval"],
        first.historical_identity.binding_snapshot["source_interval_basis"],
    ) == ("1m", "parquet_column")
    assert first.continuous_contract == "jm.MAIN"
    assert first.has_night_session is True
    assert first.historical_identity.previous_trading_day == date(2026, 7, 24)
    assert first.historical_identity.previous_trading_day_exchange == "DCE"


def test_historical_read_stops_at_physical_asset_end_before_target_session(
    tmp_path: Path,
) -> None:
    day = date(2026, 7, 27)
    factory = _factory()
    with factory() as session:
        _seed_calendar_and_sessions(session, day)
        _seed_mapping(session, day)
        _seed_history(session, tmp_path, day)
        asset = session.query(MarketDataFile).one()
        asset.end_time = (
            pd.read_parquet(asset.file_path)["datetime"].max().to_pydatetime()
        )
        _seed_prior_sessions(session, day)
        _seed_minutes(session, day, end=datetime(2026, 7, 27, 9, 15))
        session.commit()

        snapshot = _resolver(session, tmp_path).resolve(
            trading_day=day,
            detected_at=datetime(2026, 7, 27, 1, 16, tzinfo=UTC),
        )

    assert len(snapshot.historical_bars) == 128
    assert snapshot.historical_bars[-1].identity.bucket_end == datetime(
        2026, 7, 24, 15, tzinfo=SHANGHAI
    )


def test_postgresql_aware_market_file_range_preserves_dce_wall_clock(
    tmp_path: Path,
) -> None:
    day = date(2026, 7, 27)
    factory = _factory()
    with factory() as session:
        _seed_calendar_and_sessions(session, day)
        _seed_mapping(session, day)
        _seed_history(session, tmp_path, day)
        asset = session.query(MarketDataFile).one()
        asset.start_time = asset.start_time.replace(tzinfo=UTC)
        asset.end_time = asset.end_time.replace(tzinfo=UTC)
        _seed_prior_sessions(session, day)
        _seed_minutes(session, day, end=datetime(2026, 7, 27, 9, 15))
        session.commit()

        snapshot = _resolver(session, tmp_path).resolve(
            trading_day=day,
            detected_at=datetime(2026, 7, 27, 1, 16, tzinfo=UTC),
        )

    assert len(snapshot.historical_bars) == 128
    assert snapshot.historical_bars[-1].identity.bucket_end == datetime(
        2026, 7, 24, 15, tzinfo=SHANGHAI
    )


def test_current_bucket_is_partial_then_confirmed_and_revision_changes_hash(
    tmp_path: Path,
) -> None:
    day = date(2026, 7, 27)
    factory = _factory()
    with factory() as session:
        _seed_calendar_and_sessions(session, day)
        _seed_mapping(session, day)
        _seed_history(session, tmp_path, day)
        _seed_prior_sessions(session, day)
        _seed_minutes(session, day, end=datetime(2026, 7, 27, 9, 8), count=8)
        session.commit()
        partial = _resolver(session, tmp_path).resolve(
            trading_day=day, detected_at=datetime(2026, 7, 27, 1, 9, tzinfo=UTC)
        )
        for row in session.query(LiveMinuteBar):
            row.revision = 1
        session.commit()
        revised = _resolver(session, tmp_path).resolve(
            trading_day=day, detected_at=datetime(2026, 7, 27, 1, 9, tzinfo=UTC)
        )

    assert partial.buckets[-1].status == "partial"
    assert partial.snapshot_sha256 != revised.snapshot_sha256


def test_partial_bucket_becomes_confirmed_only_after_all_minutes_arrive(
    tmp_path: Path,
) -> None:
    day = date(2026, 7, 27)
    factory = _factory()
    with factory() as session:
        _seed_calendar_and_sessions(session, day)
        _seed_mapping(session, day)
        _seed_history(session, tmp_path, day)
        _seed_prior_sessions(session, day)
        _seed_minutes(session, day, end=datetime(2026, 7, 27, 9, 8), count=8)
        session.commit()

        resolver = _resolver(session, tmp_path)
        partial = resolver.resolve(
            trading_day=day, detected_at=datetime(2026, 7, 27, 1, 9, tzinfo=UTC)
        )
        _seed_minutes(session, day, end=datetime(2026, 7, 27, 9, 15), count=7)
        session.commit()
        confirmed = resolver.resolve(
            trading_day=day, detected_at=datetime(2026, 7, 27, 1, 16, tzinfo=UTC)
        )

    assert partial.buckets[-1].status == "partial"
    assert len(partial.buckets[-1].source_minutes) == 8
    assert confirmed.buckets[-1].status == "confirmed"
    assert len(confirmed.buckets[-1].source_minutes) == 15
    assert partial.snapshot_sha256 != confirmed.snapshot_sha256


def test_night_session_uses_previous_natural_date_but_target_trading_day(
    tmp_path: Path,
) -> None:
    day = date(2026, 7, 27)
    factory = _factory()
    with factory() as session:
        _seed_calendar_and_sessions(session, day)
        _seed_mapping(session, day)
        _seed_history(session, tmp_path, day)
        _seed_minutes(session, day, end=datetime(2026, 7, 24, 21, 15), count=15)
        session.commit()
        snapshot = _resolver(session, tmp_path).resolve(
            trading_day=day,
            detected_at=datetime(2026, 7, 24, 13, 16, tzinfo=UTC),
        )

    bucket = snapshot.buckets[-1]
    assert bucket.status == "confirmed"
    assert bucket.identity.trading_day == day
    assert bucket.identity.bucket_start == datetime(2026, 7, 24, 21, tzinfo=SHANGHAI)
    assert bucket.identity.bucket_end == datetime(2026, 7, 24, 21, 15, tzinfo=SHANGHAI)
    assert bucket.identity.session_id == "DCE:jm:night"


def test_lunch_break_has_no_bucket_and_day_pm_starts_new_partial(
    tmp_path: Path,
) -> None:
    day = date(2026, 7, 27)
    factory = _factory()
    with factory() as session:
        _seed_calendar_and_sessions(session, day)
        _seed_mapping(session, day)
        _seed_history(session, tmp_path, day)
        _seed_through_day_am(session, day)
        session.commit()
        lunch = _resolver(session, tmp_path).resolve(
            trading_day=day,
            detected_at=datetime(2026, 7, 27, 5, 31, tzinfo=UTC),
        )
        _seed_minutes(session, day, end=datetime(2026, 7, 27, 13, 31), count=1)
        session.commit()
        afternoon = _resolver(session, tmp_path).resolve(
            trading_day=day,
            detected_at=datetime(2026, 7, 27, 5, 32, tzinfo=UTC),
        )

    assert lunch.buckets[-1].identity.bucket_end == datetime(
        2026, 7, 27, 11, 30, tzinfo=SHANGHAI
    )
    assert all(
        not (
            datetime(2026, 7, 27, 11, 30, tzinfo=SHANGHAI)
            < bucket.identity.bucket_start
            < datetime(2026, 7, 27, 13, 30, tzinfo=SHANGHAI)
        )
        for bucket in lunch.buckets
    )
    assert afternoon.buckets[-1].status == "partial"
    assert afternoon.buckets[-1].identity.bucket_start == datetime(
        2026, 7, 27, 13, 30, tzinfo=SHANGHAI
    )
    assert afternoon.buckets[-1].identity.session_id == "DCE:jm:day_pm"


def test_canonical_split_morning_resolver_snapshot_is_accepted(
    tmp_path: Path,
) -> None:
    day = date(2026, 7, 27)
    factory = _factory()
    with factory() as session:
        _seed_calendar_and_sessions(session, day)
        _seed_mapping(session, day)
        _seed_history(session, tmp_path, day)
        _seed_prior_sessions(session, day)
        _seed_minutes(session, day, end=datetime(2026, 7, 27, 9, 15))
        session.commit()

        snapshot = _resolver(session, tmp_path).resolve(
            trading_day=day,
            detected_at=datetime(2026, 7, 27, 1, 16, tzinfo=UTC),
        )

    assert snapshot.buckets[-1].identity.session_name == "day_am_1"
    assert snapshot.buckets[-1].identity.session_id == "DCE:jm:day_am_1"


def test_1015_to_1030_break_has_no_live_or_historical_bucket(
    tmp_path: Path,
) -> None:
    day = date(2026, 7, 27)
    factory = _factory()
    with factory() as session:
        _seed_calendar_and_sessions(session, day)
        _seed_mapping(session, day)
        _seed_history(session, tmp_path, day)
        _seed_through_day_am(session, day)
        session.commit()

        snapshot = _resolver(session, tmp_path).resolve(
            trading_day=day,
            detected_at=datetime(2026, 7, 27, 3, 31, tzinfo=UTC),
        )

    morning = [
        bucket
        for bucket in snapshot.buckets
        if bucket.identity.session_name in {"day_am_1", "day_am_2"}
    ]
    assert [
        bucket.identity.bucket_end.timetz().replace(tzinfo=None)
        for bucket in morning
    ] == [
        time(9, 15),
        time(9, 30),
        time(9, 45),
        time(10),
        time(10, 15),
        time(10, 45),
        time(11),
        time(11, 15),
        time(11, 30),
    ]
    assert [bucket.identity.session_name for bucket in morning] == [
        *(["day_am_1"] * 5),
        *(["day_am_2"] * 4),
    ]
    assert all(
        not (
            time(10, 15)
            < source.datetime.timetz().replace(tzinfo=None)
            <= time(10, 30)
        )
        for source in snapshot.source_minutes
    )
    assert all(
        bar.identity.bucket_end.timetz().replace(tzinfo=None) != time(10, 30)
        for bar in snapshot.historical_bars
    )


def test_day_session_tail_is_exact_confirmed_bucket(tmp_path: Path) -> None:
    day = date(2026, 7, 27)
    factory = _factory()
    with factory() as session:
        _seed_calendar_and_sessions(session, day)
        _seed_mapping(session, day)
        _seed_history(session, tmp_path, day)
        _seed_full_trading_day(session, day)
        session.commit()
        snapshot = _resolver(session, tmp_path).resolve(
            trading_day=day,
            detected_at=datetime(2026, 7, 27, 7, 1, tzinfo=UTC),
        )

    bucket = snapshot.buckets[-1]
    assert bucket.status == "confirmed"
    assert bucket.identity.bucket_start == datetime(
        2026, 7, 27, 14, 45, tzinfo=SHANGHAI
    )
    assert bucket.identity.bucket_end == datetime(2026, 7, 27, 15, tzinfo=SHANGHAI)
    assert len(bucket.source_minutes) == 15


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("missing", "HTDY_SOURCE_MINUTE_MISSING"),
        ("future", "HTDY_SOURCE_MINUTE_FUTURE"),
        ("warning", "HTDY_SOURCE_MINUTE_QUALITY"),
        ("failed", "HTDY_SOURCE_MINUTE_QUALITY"),
        ("unconfirmed", "HTDY_SOURCE_MINUTE_QUALITY"),
        ("ohlcv", "HTDY_SOURCE_MINUTE_OHLCV"),
        ("cross_session", "HTDY_SOURCE_MINUTE_OUTSIDE_SESSION"),
    ],
)
def test_source_contract_violations_fail_closed(
    tmp_path: Path, mutation: str, reason: str
) -> None:
    day = date(2026, 7, 27)
    factory = _factory()
    with factory() as session:
        _seed_calendar_and_sessions(session, day)
        _seed_mapping(session, day)
        _seed_history(session, tmp_path, day)
        _seed_prior_sessions(session, day)
        _seed_minutes(session, day, end=datetime(2026, 7, 27, 9, 15))
        if mutation == "missing":
            session.delete(session.query(LiveMinuteBar).first())
        elif mutation == "future":
            _seed_minutes(session, day, end=datetime(2026, 7, 27, 9, 30))
        elif mutation in {"warning", "failed"}:
            session.query(LiveMinuteBar).first().quality_status = "warning"
            if mutation == "failed":
                session.query(LiveMinuteBar).first().quality_status = "failed"
        elif mutation == "unconfirmed":
            session.query(LiveMinuteBar).first().bar_status = "partial"
        elif mutation == "ohlcv":
            session.query(LiveMinuteBar).first().low = Decimal("1000")
        else:
            _seed_minutes(session, day, end=datetime(2026, 7, 27, 12), count=1)
        detected_at = (
            datetime(2026, 7, 27, 12, 1, tzinfo=UTC)
            if mutation == "cross_session"
            else datetime(2026, 7, 27, 1, 16, tzinfo=UTC)
        )
        session.commit()
        with pytest.raises(ValueError, match=reason):
            _resolver(session, tmp_path).resolve(
                trading_day=day, detected_at=detected_at
            )


@pytest.mark.parametrize(
    "conflicting,reason",
    [(False, "HTDY_SOURCE_MINUTE_DUPLICATE"), (True, "HTDY_SOURCE_MINUTE_CONFLICT")],
)
def test_exact_duplicate_and_ohlcv_conflict_are_distinguished(
    tmp_path: Path,
    conflicting: bool,
    reason: str,
) -> None:
    day = date(2026, 7, 27)
    factory = _factory()
    with factory() as session:
        _seed_calendar_and_sessions(session, day)
        _seed_minutes(session, day, end=datetime(2026, 7, 27, 9, 1), count=1)
        session.commit()
        row = session.query(LiveMinuteBar).one()
        duplicate = SimpleNamespace(
            id=row.id + 1,
            provider=row.provider,
            instrument_symbol=row.instrument_symbol,
            contract_code=row.contract_code,
            period=row.period,
            bar_datetime=row.bar_datetime,
            trading_day=row.trading_day,
            open=row.open,
            high=row.high,
            low=row.low,
            close=row.close + (Decimal("0.5") if conflicting else Decimal("0")),
            volume=row.volume,
            bar_status=row.bar_status,
            quality_status=row.quality_status,
            confirmed_at=row.confirmed_at,
            revision=row.revision,
        )
        resolver = _resolver(session, tmp_path)
        windows = resolver.clock.windows_for_trading_day(
            day, product="jm", exchange="DCE"
        )
        with pytest.raises(ValueError, match=reason):
            resolver._validate_sources(
                [row, duplicate],
                actual_contract="JM2609",
                trading_day=day,
                as_of=datetime(2026, 7, 27, 1, 2, tzinfo=UTC),
                windows=windows,
            )


def test_postgresql_aware_market_bar_preserves_dce_wall_clock_bucket(
    tmp_path: Path,
) -> None:
    day = date(2026, 7, 27)
    factory = _factory()
    with factory() as session:
        _seed_calendar_and_sessions(session, day)
        session.commit()
        resolver = _resolver(session, tmp_path)
        windows = resolver.clock.windows_for_trading_day(
            day, product="jm", exchange="DCE"
        )
        windows = [window for window in windows if window.name == "day_am_1"]
        sources = resolver._validate_sources(
            [
                _postgres_shaped_minute(
                    row_id=minute,
                    bar_datetime=datetime(2026, 7, 27, 9, minute, tzinfo=UTC),
                    confirmed_at=datetime(2026, 7, 27, 1, minute, tzinfo=UTC),
                )
                for minute in range(1, 16)
            ],
            actual_contract="JM2609",
            trading_day=day,
            as_of=datetime(2026, 7, 27, 1, 16, tzinfo=UTC),
            windows=windows,
        )
        buckets = resolver._buckets(
            trading_day=day,
            actual_contract="JM2609",
            as_of=datetime(2026, 7, 27, 1, 16, tzinfo=UTC),
            windows=windows,
            sources=sources,
        )

    assert sources[-1].datetime == datetime(2026, 7, 27, 9, 15, tzinfo=SHANGHAI)
    assert buckets[-1].identity.bucket_start == datetime(
        2026, 7, 27, 9, tzinfo=SHANGHAI
    )
    assert buckets[-1].identity.bucket_end == datetime(
        2026, 7, 27, 9, 15, tzinfo=SHANGHAI
    )


@pytest.mark.parametrize(
    "confirmed_at",
    [
        datetime(2026, 7, 27, 1, 0, 59, tzinfo=UTC),
        datetime(2026, 7, 27, 1, 2, 1, tzinfo=UTC),
    ],
)
def test_source_confirmation_must_be_between_bar_boundary_and_snapshot_as_of(
    tmp_path: Path,
    confirmed_at: datetime,
) -> None:
    day = date(2026, 7, 27)
    factory = _factory()
    with factory() as session:
        _seed_calendar_and_sessions(session, day)
        session.commit()
        resolver = _resolver(session, tmp_path)
        windows = resolver.clock.windows_for_trading_day(
            day, product="jm", exchange="DCE"
        )
        row = _postgres_shaped_minute(
            bar_datetime=datetime(2026, 7, 27, 9, 1, tzinfo=UTC),
            confirmed_at=confirmed_at,
        )

        with pytest.raises(ValueError, match="HTDY_SOURCE_MINUTE_CONFIRMATION_TIME"):
            resolver._validate_sources(
                [row],
                actual_contract="JM2609",
                trading_day=day,
                as_of=datetime(2026, 7, 27, 1, 2, tzinfo=UTC),
                windows=windows,
            )


@pytest.mark.parametrize("rows,reason", [(0, "HTDY_MAPPING_MISSING")])
def test_mapping_contract_is_exact_and_fail_closed(
    tmp_path: Path, rows: int, reason: str
) -> None:
    day = date(2026, 7, 27)
    factory = _factory()
    with factory() as session:
        _seed_calendar_and_sessions(session, day)
        for index in range(rows):
            session.add(
                MainContractMap(
                    instrument_symbol="jm",
                    trade_date=day,
                    rank=1,
                    contract_code="JM2609",
                    rule="volume_open_interest",
                    provider="rqdata",
                    data_version=f"fixture-{index}",
                )
            )
        _seed_history(session, tmp_path, day)
        _seed_minutes(session, day, end=datetime(2026, 7, 27, 9, 15))
        session.commit()
        with pytest.raises(ValueError, match=reason):
            _resolver(session, tmp_path).resolve(
                trading_day=day, detected_at=datetime(2026, 7, 27, 1, 16, tzinfo=UTC)
            )


def test_same_contract_mapping_version_supersession_freezes_selected_identity(
    tmp_path: Path,
) -> None:
    day = date(2026, 7, 27)
    factory = _factory()
    with factory() as session:
        _seed_calendar_and_sessions(session, day)
        _seed_mapping(session, day)
        first = session.query(MainContractMap).one()
        first.created_at = datetime(2026, 7, 26, tzinfo=UTC)
        session.add(
            MainContractMap(
                instrument_symbol="jm",
                trade_date=day,
                rank=1,
                contract_code="JM2609",
                rule="volume_open_interest",
                provider="rqdata",
                data_version="fixture-v2",
                created_at=datetime(2026, 7, 27, tzinfo=UTC),
            )
        )
        _seed_history(session, tmp_path, day)
        _seed_prior_sessions(session, day)
        _seed_minutes(session, day, end=datetime(2026, 7, 27, 9, 15))
        session.commit()

        selected = (
            session.query(MainContractMap)
            .filter(MainContractMap.data_version == "fixture-v2")
            .one()
        )
        snapshot = _resolver(session, tmp_path).resolve(
            trading_day=day,
            detected_at=datetime(2026, 7, 27, 1, 16, tzinfo=UTC),
        )

    assert snapshot.mapping_identity["mapping_id"] == selected.id
    assert snapshot.mapping_identity["data_version"] == "fixture-v2"


@pytest.mark.parametrize(
    "kind,reason",
    [("stale", "HTDY_MAPPING_STALE"), ("conflict", "HTDY_MAPPING_CONFLICT")],
)
def test_stale_or_conflicting_mapping_fails_closed(
    tmp_path: Path, kind: str, reason: str
) -> None:
    day = date(2026, 7, 27)
    factory = _factory()
    with factory() as session:
        _seed_calendar_and_sessions(session, day)
        _seed_history(session, tmp_path, day)
        _seed_prior_sessions(session, day)
        _seed_minutes(session, day, end=datetime(2026, 7, 27, 9, 15))
        if kind == "stale":
            _seed_mapping(session, day - timedelta(days=3))
        else:
            _seed_mapping(session, day, contract="JM2609")
            session.add(
                MainContractMap(
                    instrument_symbol="jm",
                    trade_date=day,
                    rank=1,
                    contract_code="JM2605",
                    rule="volume_open_interest",
                    provider="rqdata",
                    data_version="other",
                )
            )
        session.commit()
        with pytest.raises(ValueError, match=reason):
            _resolver(session, tmp_path).resolve(
                trading_day=day, detected_at=datetime(2026, 7, 27, 1, 16, tzinfo=UTC)
            )


def test_mapping_switch_uses_new_actual_contract_and_requested_contract_is_exact(
    tmp_path: Path,
) -> None:
    day = date(2026, 7, 27)
    factory = _factory()
    with factory() as session:
        _seed_calendar_and_sessions(session, day)
        _seed_mapping(session, day, contract="JM2611")
        _seed_history(session, tmp_path, day, contract="JM2611")
        _seed_prior_sessions(session, day, contract="JM2611")
        _seed_minutes(session, day, end=datetime(2026, 7, 27, 9, 15), contract="JM2611")
        session.commit()
        resolver = _resolver(session, tmp_path)
        snapshot = resolver.resolve(
            trading_day=day,
            detected_at=datetime(2026, 7, 27, 1, 16, tzinfo=UTC),
            requested_contract="JM2611",
        )
        with pytest.raises(ValueError, match="HTDY_REQUESTED_CONTRACT_MISMATCH"):
            resolver.resolve(
                trading_day=day,
                detected_at=datetime(2026, 7, 27, 1, 16, tzinfo=UTC),
                requested_contract="JM2609",
            )

    assert snapshot.actual_contract == "JM2611"
    assert {bar.identity.actual_contract for bar in snapshot.historical_bars} == {
        "JM2611"
    }
    assert {bar.identity.actual_contract for bar in snapshot.buckets} == {"JM2611"}


@pytest.mark.parametrize(
    "profile_mutation,reason",
    [
        ("missing", "HTDY_HISTORICAL_PROFILE_BLOCKED"),
        ("wrong_role", "HTDY_HISTORICAL_PROFILE_IDENTITY"),
        ("warning", "HTDY_HISTORICAL_PROFILE_BLOCKED"),
        ("failed", "HTDY_HISTORICAL_PROFILE_BLOCKED"),
    ],
)
def test_historical_profile_identity_and_quality_fail_closed(
    tmp_path: Path,
    profile_mutation: str,
    reason: str,
) -> None:
    day = date(2026, 7, 27)
    factory = _factory()
    with factory() as session:
        _seed_calendar_and_sessions(session, day)
        _seed_mapping(session, day)
        quality = (
            profile_mutation if profile_mutation in {"warning", "failed"} else "passed"
        )
        role = (
            "dominant_main" if profile_mutation == "wrong_role" else "actual_contract"
        )
        _seed_history(
            session, tmp_path, day, quality_status=quality, contract_role=role
        )
        if profile_mutation == "missing":
            session.query(DataProfile).delete()
        session.commit()
        with pytest.raises(ValueError, match=reason):
            _resolver(session, tmp_path).resolve(
                trading_day=day,
                detected_at=datetime(2026, 7, 27, 1, 16, tzinfo=UTC),
            )


@pytest.mark.parametrize(
    "source_interval,reason",
    [
        ("5m", "HTDY_HISTORICAL_PROFILE_IDENTITY"),
        (None, "HTDY_HISTORICAL_PROFILE_BLOCKED"),
    ],
)
def test_historical_profile_requires_1m_source_interval_provenance(
    tmp_path: Path,
    source_interval: str | None,
    reason: str,
) -> None:
    day = date(2026, 7, 27)
    factory = _factory()
    with factory() as session:
        _seed_calendar_and_sessions(session, day)
        _seed_mapping(session, day)
        _seed_history(
            session,
            tmp_path,
            day,
            source_interval=source_interval,
        )
        session.commit()

        with pytest.raises(ValueError, match=reason):
            _resolver(session, tmp_path).resolve(
                trading_day=day,
                detected_at=datetime(2026, 7, 27, 1, 16, tzinfo=UTC),
            )


def test_actual_contract_history_binding_cannot_fall_back_to_other_contract(
    tmp_path: Path,
) -> None:
    day = date(2026, 7, 27)
    factory = _factory()
    with factory() as session:
        _seed_calendar_and_sessions(session, day)
        _seed_mapping(session, day, contract="JM2611")
        _seed_history(session, tmp_path, day, contract="JM2609")
        session.commit()
        with pytest.raises(ValueError, match="HTDY_HISTORICAL_PROFILE_BLOCKED"):
            _resolver(session, tmp_path).resolve(
                trading_day=day,
                detected_at=datetime(2026, 7, 27, 1, 16, tzinfo=UTC),
            )


def test_historical_checksum_and_previous_day_freshness_fail_closed(
    tmp_path: Path,
) -> None:
    day = date(2026, 7, 27)
    factory = _factory()
    with factory() as session:
        _seed_calendar_and_sessions(session, day)
        _seed_mapping(session, day)
        _seed_history(session, tmp_path, day)
        _seed_prior_sessions(session, day)
        _seed_minutes(session, day, end=datetime(2026, 7, 27, 9, 15))
        session.commit()
        asset = session.query(MarketDataFile).one()
        asset.checksum = "drift"
        with pytest.raises(ValueError, match="HTDY_HISTORICAL_CHECKSUM_DRIFT"):
            _resolver(session, tmp_path).resolve(
                trading_day=day, detected_at=datetime(2026, 7, 27, 1, 16, tzinfo=UTC)
            )

    missing_checksum_factory = _factory()
    with missing_checksum_factory() as session:
        _seed_calendar_and_sessions(session, day)
        _seed_mapping(session, day)
        _seed_history(session, tmp_path, day)
        session.commit()
        session.query(MarketDataFile).one().checksum = None
        with pytest.raises(ValueError, match="HTDY_HISTORICAL_CHECKSUM_MISSING"):
            _resolver(session, tmp_path).resolve(
                trading_day=day,
                detected_at=datetime(2026, 7, 27, 1, 16, tzinfo=UTC),
            )

    stale_factory = _factory()
    with stale_factory() as session:
        _seed_calendar_and_sessions(session, day)
        _seed_mapping(session, day)
        _seed_history(session, tmp_path, day, latest_history_day=date(2026, 7, 23))
        session.commit()
        with pytest.raises(ValueError, match="HTDY_HISTORICAL_PREVIOUS_DAY_STALE"):
            _resolver(session, tmp_path).resolve(
                trading_day=day,
                detected_at=datetime(2026, 7, 27, 1, 16, tzinfo=UTC),
            )


def test_historical_bar_must_match_an_exact_session_bucket_end(tmp_path: Path) -> None:
    day = date(2026, 7, 27)
    factory = _factory()
    with factory() as session:
        _seed_calendar_and_sessions(session, day)
        _seed_mapping(session, day)
        _seed_history(session, tmp_path, day)
        session.commit()
        asset = session.query(MarketDataFile).one()
        frame = pd.read_parquet(asset.file_path)
        frame.loc[10, "datetime"] = frame.loc[10, "datetime"] - timedelta(minutes=1)
        frame.to_parquet(asset.file_path, index=False)
        asset.checksum = sha256_file(Path(asset.file_path))
        session.commit()
        with pytest.raises(ValueError, match="HTDY_HISTORICAL_SESSION_INVALID"):
            _resolver(session, tmp_path).resolve(
                trading_day=day,
                detected_at=datetime(2026, 7, 27, 1, 16, tzinfo=UTC),
            )


def test_snapshot_preserves_all_source_lineage_and_hash_inputs(tmp_path: Path) -> None:
    day = date(2026, 7, 27)
    factory = _factory()
    with factory() as session:
        _seed_calendar_and_sessions(session, day)
        _seed_mapping(session, day)
        _seed_history(session, tmp_path, day)
        _seed_prior_sessions(session, day)
        _seed_minutes(session, day, end=datetime(2026, 7, 27, 9, 15), revision=3)
        session.commit()
        resolver = _resolver(session, tmp_path)
        first = resolver.resolve(
            trading_day=day,
            detected_at=datetime(2026, 7, 27, 1, 16, tzinfo=UTC),
        )
        same_state_later = resolver.resolve(
            trading_day=day,
            detected_at=datetime(2026, 7, 27, 1, 16, 30, tzinfo=UTC),
        )
        last = (
            session.query(LiveMinuteBar)
            .order_by(LiveMinuteBar.bar_datetime.desc())
            .first()
        )
        last.confirmed_at = datetime(2026, 7, 27, 1, 15, 30, tzinfo=UTC)
        session.commit()
        confirmed_at_changed = resolver.resolve(
            trading_day=day,
            detected_at=datetime(2026, 7, 27, 1, 16, tzinfo=UTC),
        )
        last.close += Decimal("0.25")
        session.commit()
        changed = resolver.resolve(
            trading_day=day,
            detected_at=datetime(2026, 7, 27, 1, 16, tzinfo=UTC),
        )

    assert len(first.source_minutes) == 135
    assert tuple(item.live_bar_id for item in first.source_minutes) == tuple(
        item.live_bar_id for bucket in first.buckets for item in bucket.source_minutes
    )
    assert first.source_minutes[-1].revision == 3
    assert first.source_minutes[-1].datetime == datetime(
        2026, 7, 27, 9, 15, tzinfo=SHANGHAI
    )
    assert first.source_minutes[-1].confirmed_at.tzinfo == UTC
    assert first.snapshot_sha256 == same_state_later.snapshot_sha256
    assert first.snapshot_sha256 != confirmed_at_changed.snapshot_sha256
    assert confirmed_at_changed.snapshot_sha256 != changed.snapshot_sha256
    assert first.snapshot_sha256 != changed.snapshot_sha256


def test_mapping_lineage_change_changes_snapshot_hash(tmp_path: Path) -> None:
    day = date(2026, 7, 27)
    factory = _factory()
    with factory() as session:
        _seed_calendar_and_sessions(session, day)
        _seed_mapping(session, day)
        _seed_history(session, tmp_path, day)
        _seed_prior_sessions(session, day)
        _seed_minutes(session, day, end=datetime(2026, 7, 27, 9, 15))
        session.commit()
        resolver = _resolver(session, tmp_path)
        first = resolver.resolve(
            trading_day=day,
            detected_at=datetime(2026, 7, 27, 1, 16, tzinfo=UTC),
        )
        session.query(MainContractMap).one().data_version = "fixture-v2"
        session.commit()
        changed = resolver.resolve(
            trading_day=day,
            detected_at=datetime(2026, 7, 27, 1, 16, tzinfo=UTC),
        )

    assert first.snapshot_sha256 != changed.snapshot_sha256


def test_resolver_and_evaluator_emit_no_write_sql(tmp_path: Path) -> None:
    from app.services.htdy_realtime_evaluator import HtDyRealtimeCandidateEvaluator

    day = date(2026, 7, 27)
    factory = _factory()
    with factory() as session:
        _seed_calendar_and_sessions(session, day)
        _seed_mapping(session, day)
        _seed_history(session, tmp_path, day)
        _seed_prior_sessions(session, day)
        _seed_minutes(session, day, end=datetime(2026, 7, 27, 9, 15))
        session.commit()
        pending = DataProfile(
            profile_id="unrelated_pending_profile",
            label="must-not-autoflush",
            contract_roles=[],
            periods=[],
            quality_policy="passed_only",
            provider="rqdata",
            is_active=True,
        )
        session.add(pending)
        statements: list[str] = []

        def capture_sql(
            _conn, _cursor, statement, _parameters, _context, _executemany
        ) -> None:
            statements.append(statement.lstrip().upper())

        event.listen(session.bind, "before_cursor_execute", capture_sql)
        try:
            snapshot = _resolver(session, tmp_path).resolve(
                trading_day=day,
                detected_at=datetime(2026, 7, 27, 1, 16, tzinfo=UTC),
            )
            HtDyRealtimeCandidateEvaluator().evaluate(
                snapshot, detected_at=snapshot.as_of
            )
        finally:
            event.remove(session.bind, "before_cursor_execute", capture_sql)

    assert statements
    assert pending.id is None
    assert not any(
        statement.startswith(("INSERT", "UPDATE", "DELETE")) for statement in statements
    )


def test_historical_binding_snapshot_is_immutable_after_hashing() -> None:
    from app.services.htdy_realtime_snapshot import _hash

    raw = {
        "profile_id": "live_observation_v1",
        "instrument_symbol": "jm",
        "contract_code": "JM2609",
        "contract_role": "actual_contract",
        "period": "15m",
        "data_version": "fixture",
        "market_data_file_id": 1,
        "binding_status": "active",
        "activated_at": "2026-07-26T00:00:00+00:00",
        "superseded_at": None,
        "updated_at": "2026-07-26T00:00:00+00:00",
        "quality_policy": "active_entry",
        "provider": "rqdata",
        "data_role": "primary",
        "quality_status": "passed",
        "file_data_version": "fixture",
        "source_interval": "1m",
        "source_interval_basis": "parquet_column",
    }
    identity = HistoricalWarmupIdentity(
        profile_id="live_observation_v1",
        binding_snapshot=raw,
        market_data_file_id=1,
        data_version="fixture",
        checksum="a" * 64,
        window_sha256="b" * 64,
        previous_trading_day=date(2026, 7, 24),
    )
    before = _hash(identity)

    raw["contract_role"] = "dominant_main"
    raw["quality_status"] = "failed"

    assert _hash(identity) == before
    assert identity.binding_snapshot["contract_role"] == "actual_contract"
    assert identity.binding_snapshot["quality_status"] == "passed"
    with pytest.raises(TypeError):
        identity.binding_snapshot["contract_role"] = "dominant_main"
