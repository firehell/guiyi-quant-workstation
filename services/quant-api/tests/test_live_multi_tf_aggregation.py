from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import importlib.util
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.data_center import LiveAggregatedBar, LiveAggregationCheckpoint, LiveMinuteBar, MarketDataFile
from app.services.live_multi_tf_aggregation import LiveAggregationConfig, LiveMultiTfAggregationService, _values_equal


SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "rqdata_live_multi_tf_aggregate.py"


def _session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    return SessionLocal()


def _config(periods: tuple[str, ...] = ("5m",)) -> LiveAggregationConfig:
    return LiveAggregationConfig(contract="jm2609", symbol="JM", exchange="dce", periods=periods)


def _add_1m_bars(
    session: Session,
    *,
    start: datetime,
    count: int,
    close_start: int = 100,
    quality_status: str = "passed",
    bar_status: str = "confirmed",
    trading_day: date | None = date(2026, 7, 7),
) -> None:
    for index in range(count):
        close = Decimal(close_start + index)
        session.add(
            LiveMinuteBar(
                provider="rqdata",
                instrument_symbol="jm",
                contract_code="JM2609",
                exchange_code="DCE",
                period="1m",
                bar_datetime=start + timedelta(minutes=index),
                trading_day=trading_day,
                open=close - Decimal("0.5"),
                high=close + Decimal("1.0"),
                low=close - Decimal("1.0"),
                close=close,
                volume=Decimal(10 + index),
                open_interest=Decimal(100 + index),
                turnover=Decimal(1000 + index),
                bar_status=bar_status,
                quality_status=quality_status,
                source_mode="poll_get_price_1m",
                first_seen_at=datetime(2026, 7, 7, 9, 0),
                last_seen_at=datetime(2026, 7, 7, 9, 0),
                confirmed_at=datetime(2026, 7, 7, 9, 0),
                revision=0,
                raw_payload={"index": index},
            )
        )
    session.flush()


def test_aggregates_complete_1m_rows_to_multiple_periods() -> None:
    with _session() as session:
        _add_1m_bars(session, start=datetime(2026, 7, 7, 9, 1), count=16)
        result = LiveMultiTfAggregationService(session=session, now=datetime(2026, 7, 7, 9, 18)).aggregate_once(
            _config(periods=("5m", "15m"))
        )
        session.commit()

        bars = list(session.scalars(select(LiveAggregatedBar).order_by(LiveAggregatedBar.period, LiveAggregatedBar.bar_datetime)))
        checkpoints = list(session.scalars(select(LiveAggregationCheckpoint).order_by(LiveAggregationCheckpoint.period)))

    assert result.period_results["5m"]["upserted_count"] == 3
    assert result.period_results["15m"]["upserted_count"] == 1
    assert [(bar.period, bar.bar_datetime, bar.source_bar_count) for bar in bars] == [
        ("15m", datetime(2026, 7, 7, 9, 15), 15),
        ("5m", datetime(2026, 7, 7, 9, 5), 5),
        ("5m", datetime(2026, 7, 7, 9, 10), 5),
        ("5m", datetime(2026, 7, 7, 9, 15), 5),
    ]
    first_5m = next(bar for bar in bars if bar.period == "5m" and bar.bar_datetime == datetime(2026, 7, 7, 9, 5))
    assert float(first_5m.open) == 99.5
    assert float(first_5m.high) == 105.0
    assert float(first_5m.low) == 99.0
    assert float(first_5m.close) == 104.0
    assert float(first_5m.volume) == 60.0
    assert first_5m.quality_status == "passed"
    assert first_5m.bar_status == "confirmed"
    assert {checkpoint.period: checkpoint.status for checkpoint in checkpoints} == {"15m": "success", "5m": "success"}


def test_skips_latest_open_bucket_until_it_is_closed_by_later_bar() -> None:
    with _session() as session:
        _add_1m_bars(session, start=datetime(2026, 7, 7, 9, 1), count=5)
        result = LiveMultiTfAggregationService(session=session, now=datetime(2026, 7, 7, 9, 6)).aggregate_once(_config())
        session.commit()

        bars = list(session.scalars(select(LiveAggregatedBar)))
        checkpoint = session.scalar(select(LiveAggregationCheckpoint))

    assert result.period_results["5m"]["candidate_count"] == 0
    assert bars == []
    assert checkpoint is not None
    assert checkpoint.status == "warning"
    assert checkpoint.last_error_type == "NoClosedBuckets"


def test_session_gap_closes_short_bucket_as_warning() -> None:
    with _session() as session:
        _add_1m_bars(session, start=datetime(2026, 7, 7, 9, 1), count=3)
        _add_1m_bars(session, start=datetime(2026, 7, 7, 9, 31), count=1, close_start=200)
        result = LiveMultiTfAggregationService(session=session, now=datetime(2026, 7, 7, 9, 32)).aggregate_once(_config())
        session.commit()

        bar = session.scalar(select(LiveAggregatedBar))

    assert result.period_results["5m"]["warning_count"] == 1
    assert bar is not None
    assert bar.bar_datetime == datetime(2026, 7, 7, 9, 3)
    assert bar.source_bar_count == 3
    assert bar.expected_bar_count == 5
    assert bar.quality_status == "warning"
    assert bar.raw_payload["quality_reasons"] == ["incomplete_source_bucket"]


def test_missing_minute_does_not_shift_following_session_bucket() -> None:
    with _session() as session:
        _add_1m_bars(session, start=datetime(2026, 7, 7, 9, 1), count=4)
        _add_1m_bars(session, start=datetime(2026, 7, 7, 9, 6), count=6, close_start=200)
        LiveMultiTfAggregationService(session=session, now=datetime(2026, 7, 7, 9, 13)).aggregate_once(_config())
        session.commit()

        bars = list(session.scalars(select(LiveAggregatedBar).order_by(LiveAggregatedBar.bar_datetime)))

    assert [(bar.bar_datetime, bar.source_bar_count, bar.quality_status) for bar in bars] == [
        (datetime(2026, 7, 7, 9, 4), 4, "warning"),
        (datetime(2026, 7, 7, 9, 10), 5, "passed"),
    ]


def test_rejected_and_failed_1m_rows_are_excluded_and_warning_rows_propagate() -> None:
    with _session() as session:
        _add_1m_bars(session, start=datetime(2026, 7, 7, 9, 1), count=2)
        _add_1m_bars(session, start=datetime(2026, 7, 7, 9, 3), count=1, quality_status="warning", trading_day=None)
        _add_1m_bars(session, start=datetime(2026, 7, 7, 9, 4), count=1, quality_status="failed", bar_status="rejected")
        _add_1m_bars(session, start=datetime(2026, 7, 7, 9, 31), count=1, close_start=200)
        result = LiveMultiTfAggregationService(session=session, now=datetime(2026, 7, 7, 9, 32)).aggregate_once(_config())
        session.commit()

        bar = session.scalar(select(LiveAggregatedBar))

    assert result.source_row_count == 4
    assert result.excluded_row_count == 1
    assert bar is not None
    assert bar.source_bar_count == 3
    assert bar.quality_status == "warning"
    assert sorted(bar.raw_payload["quality_reasons"]) == ["incomplete_source_bucket", "source_quality_warning"]


def test_repeated_aggregation_reuses_bar_and_increments_revision_on_source_change() -> None:
    with _session() as session:
        _add_1m_bars(session, start=datetime(2026, 7, 7, 9, 1), count=6)
        service = LiveMultiTfAggregationService(session=session, now=datetime(2026, 7, 7, 9, 8))
        first = service.aggregate_once(_config())
        session.commit()

        source = session.scalar(select(LiveMinuteBar).where(LiveMinuteBar.bar_datetime == datetime(2026, 7, 7, 9, 5)))
        assert source is not None
        source.close = Decimal("150")
        source.high = Decimal("151")
        second = LiveMultiTfAggregationService(session=session, now=datetime(2026, 7, 7, 9, 9)).aggregate_once(_config())
        session.commit()

        bars = list(session.scalars(select(LiveAggregatedBar)))

    assert first.period_results["5m"]["upserted_count"] == 1
    assert second.period_results["5m"]["upserted_count"] == 0
    assert second.period_results["5m"]["revised_count"] == 1
    assert len(bars) == 1
    assert bars[0].revision == 1
    assert float(bars[0].close) == 150.0


def test_repeated_identical_aggregation_is_unchanged_and_preserves_confirmed_at() -> None:
    with _session() as session:
        _add_1m_bars(session, start=datetime(2026, 7, 7, 9, 1), count=6)
        first = LiveMultiTfAggregationService(session=session, now=datetime(2026, 7, 7, 9, 8)).aggregate_once(_config())
        session.commit()
        bar = session.scalar(select(LiveAggregatedBar))
        assert bar is not None
        first_confirmed_at = bar.confirmed_at

        second = LiveMultiTfAggregationService(session=session, now=datetime(2026, 7, 7, 9, 9)).aggregate_once(_config())
        session.commit()
        bar = session.scalar(select(LiveAggregatedBar))

    assert first.period_results["5m"]["upserted_count"] == 1
    assert second.period_results["5m"]["revised_count"] == 0
    assert second.period_results["5m"]["unchanged_count"] == 1
    assert bar is not None
    assert bar.revision == 0
    assert bar.confirmed_at == first_confirmed_at


def test_aggregate_datetime_equality_normalizes_postgresql_timezone_result() -> None:
    naive = datetime(2026, 7, 20, 21, 5)
    aware = datetime(2026, 7, 20, 21, 5, tzinfo=UTC)

    assert _values_equal(aware, naive) is True
    assert _values_equal(aware, naive + timedelta(minutes=1)) is False


def test_dry_run_does_not_write_aggregation_tables_or_market_data_files() -> None:
    with _session() as session:
        _add_1m_bars(session, start=datetime(2026, 7, 7, 9, 1), count=6)
        result = LiveMultiTfAggregationService(session=session, now=datetime(2026, 7, 7, 9, 8)).aggregate_once(_config(), dry_run=True)

        aggregated_count = len(list(session.scalars(select(LiveAggregatedBar))))
        checkpoint_count = len(list(session.scalars(select(LiveAggregationCheckpoint))))
        market_file_count = len(list(session.scalars(select(MarketDataFile))))

    assert result.dry_run is True
    assert result.period_results["5m"]["candidate_count"] == 1
    assert aggregated_count == 0
    assert checkpoint_count == 0
    assert market_file_count == 0


def test_cli_dry_run_does_not_open_database_or_send_wechat(capsys, monkeypatch) -> None:
    module = _load_script()
    monkeypatch.setenv("QYWX_WEBHOOK_URL", "https://example.invalid/token")

    def fail_session():
        raise AssertionError("dry-run must not open DB session")

    exit_code = module.main(
        ["--contract", "JM2609", "--symbol", "jm", "--exchange", "DCE", "--periods", "5m,15m,30m,60m", "--once", "--dry-run"],
        session_factory=fail_session,
        environ=dict(module.os.environ),
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "https://example.invalid/token" not in output
    assert '"would_open_database_session": false' in output
    assert '"would_send_wechat": false' in output
    assert '"periods": [' in output


def _load_script():
    spec = importlib.util.spec_from_file_location("rqdata_live_multi_tf_aggregate", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
