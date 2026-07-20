from __future__ import annotations

from datetime import UTC, date, datetime
import importlib.util
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.data_center import LiveIngestCheckpoint, LiveMinuteBar, MarketDataFile
from app.services.live_1m_ingest import LiveIngestConfig, LiveMinuteIngestService


SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "rqdata_live_1m_ingest.py"


class FakeClient:
    def __init__(self, frame: pd.DataFrame | None = None, exc: Exception | None = None) -> None:
        self.frame = frame if frame is not None else pd.DataFrame()
        self.exc = exc
        self.calls: list[tuple[str, object, object, str]] = []

    def contract_bars(self, contract, start_date, end_date, frequency):
        self.calls.append((contract, start_date, end_date, frequency))
        if self.exc is not None:
            raise self.exc
        return self.frame


def _session():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    return SessionLocal()


def _config() -> LiveIngestConfig:
    return LiveIngestConfig(contract="jm2609", symbol="JM", exchange="dce", lookback_minutes=10)


def _frame(close: float = 100.5, *, include_trading_day: bool = True, invalid_ohlc: bool = False) -> pd.DataFrame:
    row = {
        "datetime": pd.Timestamp("2026-07-07 09:02:00"),
        "open": 100.0,
        "high": max(101.0, close + 0.5) if not invalid_ohlc else 99.0,
        "low": 99.0,
        "close": close,
        "volume": 10,
        "open_interest": 20,
        "turnover": 1000.0,
    }
    if include_trading_day:
        row["trading_day"] = "2026-07-07"
    return pd.DataFrame([row])


def test_live_ingest_upserts_confirmed_bar_and_skips_current_minute() -> None:
    frame = pd.concat(
        [
            _frame(),
            pd.DataFrame(
                [
                    {
                        "datetime": pd.Timestamp("2026-07-07 09:04:00"),
                        "trading_day": "2026-07-07",
                        "open": 101,
                        "high": 102,
                        "low": 100,
                        "close": 101.5,
                        "volume": 5,
                        "open_interest": 25,
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    with _session() as session:
        result = LiveMinuteIngestService(session=session, client=FakeClient(frame), now=datetime(2026, 7, 7, 9, 4, 30)).poll_once(_config())
        session.commit()

        bar = session.scalar(select(LiveMinuteBar))
        checkpoint = session.scalar(select(LiveIngestCheckpoint))

    assert result.row_count == 2
    assert result.confirmed_candidates == 1
    assert result.upserted_count == 1
    assert result.skipped_count == 1
    assert bar is not None
    assert bar.provider == "rqdata"
    assert bar.instrument_symbol == "jm"
    assert bar.contract_code == "JM2609"
    assert bar.exchange_code == "DCE"
    assert bar.period == "1m"
    assert bar.bar_status == "confirmed"
    assert bar.quality_status == "passed"
    assert bar.revision == 0
    assert checkpoint is not None
    assert checkpoint.status == "success"
    assert checkpoint.last_confirmed_bar_at == datetime(2026, 7, 7, 9, 2)


def test_live_ingest_reuses_unique_bar_and_increments_revision_on_changed_values() -> None:
    with _session() as session:
        service = LiveMinuteIngestService(session=session, client=FakeClient(_frame(close=100.5)), now=datetime(2026, 7, 7, 9, 4, 30))
        first = service.poll_once(_config())
        session.commit()

        second_service = LiveMinuteIngestService(session=session, client=FakeClient(_frame(close=101.5)), now=datetime(2026, 7, 7, 9, 5, 30))
        second = second_service.poll_once(_config())
        session.commit()

        bars = list(session.scalars(select(LiveMinuteBar)))
        checkpoint = session.scalar(select(LiveIngestCheckpoint))

    assert first.upserted_count == 1
    assert second.upserted_count == 0
    assert second.revised_count == 1
    assert len(bars) == 1
    assert bars[0].revision == 1
    assert float(bars[0].close) == 101.5
    assert checkpoint is not None
    assert checkpoint.consecutive_error_count == 0


def test_live_ingest_identical_bar_is_unchanged_and_preserves_confirmed_at() -> None:
    with _session() as session:
        first = LiveMinuteIngestService(
            session=session,
            client=FakeClient(_frame()),
            now=datetime(2026, 7, 7, 9, 4, 30),
        ).poll_once(_config())
        session.commit()
        bar = session.scalar(select(LiveMinuteBar))
        assert bar is not None
        first_confirmed_at = bar.confirmed_at

        second = LiveMinuteIngestService(
            session=session,
            client=FakeClient(_frame()),
            now=datetime(2026, 7, 7, 9, 5, 30),
        ).poll_once(_config())
        session.commit()
        bar = session.scalar(select(LiveMinuteBar))

    assert first.upserted_count == 1
    assert second.revised_count == 0
    assert second.unchanged_count == 1
    assert bar is not None
    assert bar.revision == 0
    assert bar.confirmed_at == first_confirmed_at


def test_live_ingest_uses_expected_trading_day_and_shanghai_cutoff() -> None:
    frame = pd.DataFrame(
        [
            {
                "datetime": pd.Timestamp("2026-07-20 15:00:00"),
                "trading_day": "2026-07-20",
                "open": 100,
                "high": 101,
                "low": 99,
                "close": 100,
                "volume": 10,
                "open_interest": 20,
            },
            {
                "datetime": pd.Timestamp("2026-07-20 21:01:00"),
                "trading_day": "2026-07-21",
                "open": 101,
                "high": 102,
                "low": 100,
                "close": 101,
                "volume": 11,
                "open_interest": 21,
            },
            {
                "datetime": pd.Timestamp("2026-07-20 21:10:00"),
                "trading_day": "2026-07-21",
                "open": 102,
                "high": 103,
                "low": 101,
                "close": 102,
                "volume": 12,
                "open_interest": 22,
            },
        ]
    )
    client = FakeClient(frame)
    config = LiveIngestConfig(
        contract="JM2609",
        symbol="jm",
        exchange="DCE",
        expected_trading_day=date(2026, 7, 21),
    )

    with _session() as session:
        result = LiveMinuteIngestService(
            session=session,
            client=client,
            now=datetime(2026, 7, 20, 13, 10, 30, tzinfo=UTC),
        ).poll_once(config)
        session.commit()
        bars = list(session.scalars(select(LiveMinuteBar)))

    assert client.calls[0][1:3] == (date(2026, 7, 20), date(2026, 7, 21))
    assert result.confirmed_candidates == 1
    assert result.max_trading_day == date(2026, 7, 21)
    assert result.max_bar_datetime == datetime(2026, 7, 20, 21, 1)
    assert result.skipped_count == 2
    assert [bar.trading_day for bar in bars] == [date(2026, 7, 21)]


def test_live_ingest_cold_start_uses_shanghai_date_after_local_midnight() -> None:
    client = FakeClient(pd.DataFrame())
    config = LiveIngestConfig(
        contract="JM2609",
        symbol="jm",
        exchange="DCE",
        expected_trading_day=date(2026, 7, 21),
    )

    with _session() as session:
        LiveMinuteIngestService(
            session=session,
            client=client,
            now=datetime(2026, 7, 20, 16, 30, tzinfo=UTC),
        ).poll_once(config, dry_run=True)

    assert client.calls[0][1:3] == (date(2026, 7, 21), date(2026, 7, 21))


def test_missing_trading_day_is_warning_not_failed() -> None:
    with _session() as session:
        result = LiveMinuteIngestService(
            session=session,
            client=FakeClient(_frame(include_trading_day=False)),
            now=datetime(2026, 7, 7, 9, 4, 30),
        ).poll_once(_config())
        session.commit()

        bar = session.scalar(select(LiveMinuteBar))

    assert result.confirmed_candidates == 1
    assert bar is not None
    assert bar.bar_status == "confirmed"
    assert bar.quality_status == "warning"
    assert bar.raw_payload["validation_errors"] == ["missing_trading_day"]


def test_invalid_ohlc_is_stored_as_rejected_and_checkpoint_warns() -> None:
    with _session() as session:
        result = LiveMinuteIngestService(
            session=session,
            client=FakeClient(_frame(invalid_ohlc=True)),
            now=datetime(2026, 7, 7, 9, 4, 30),
        ).poll_once(_config())
        session.commit()

        bar = session.scalar(select(LiveMinuteBar))
        checkpoint = session.scalar(select(LiveIngestCheckpoint))

    assert result.confirmed_candidates == 0
    assert result.rejected_count == 1
    assert result.checkpoint_status == "warning"
    assert bar is not None
    assert bar.bar_status == "rejected"
    assert bar.quality_status == "failed"
    assert checkpoint is not None
    assert checkpoint.status == "warning"
    assert checkpoint.last_error_type == "NoConfirmedBars"


def test_client_exception_updates_checkpoint_failure_without_crashing() -> None:
    with _session() as session:
        result = LiveMinuteIngestService(
            session=session,
            client=FakeClient(exc=PermissionError("bad secret-value")),
            now=datetime(2026, 7, 7, 9, 4, 30),
        ).poll_once(_config())
        session.commit()

        checkpoint = session.scalar(select(LiveIngestCheckpoint))

    assert result.error_type == "PermissionError"
    assert result.checkpoint_status == "failed"
    assert checkpoint is not None
    assert checkpoint.status == "failed"
    assert checkpoint.consecutive_error_count == 1
    assert checkpoint.last_error_type == "PermissionError"


def test_service_dry_run_fetches_but_does_not_write_tables() -> None:
    with _session() as session:
        result = LiveMinuteIngestService(
            session=session,
            client=FakeClient(_frame()),
            now=datetime(2026, 7, 7, 9, 4, 30),
        ).poll_once(_config(), dry_run=True)

        bar_count = len(list(session.scalars(select(LiveMinuteBar))))
        checkpoint_count = len(list(session.scalars(select(LiveIngestCheckpoint))))

    assert result.dry_run is True
    assert result.confirmed_candidates == 1
    assert result.upserted_count == 0
    assert bar_count == 0
    assert checkpoint_count == 0


def test_live_tables_do_not_register_market_data_files() -> None:
    with _session() as session:
        LiveMinuteIngestService(session=session, client=FakeClient(_frame()), now=datetime(2026, 7, 7, 9, 4, 30)).poll_once(_config())
        session.commit()

        market_file_count = len(list(session.scalars(select(MarketDataFile))))

    assert market_file_count == 0


def test_cli_dry_run_does_not_construct_client_or_session_and_redacts(capsys, monkeypatch) -> None:
    module = _load_script()
    monkeypatch.setenv("RQDATA_PASSWORD", "secret-password")
    monkeypatch.setenv("QYWX_WEBHOOK_URL", "https://example.invalid/token")

    def fail_client():
        raise AssertionError("dry-run must not construct RQData client")

    def fail_session():
        raise AssertionError("dry-run must not open DB session")

    exit_code = module.main(
        ["--contract", "JM2609", "--symbol", "jm", "--exchange", "DCE", "--once", "--dry-run"],
        client_factory=fail_client,
        session_factory=fail_session,
        environ=dict(module.os.environ),
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "secret-password" not in output
    assert "https://example.invalid/token" not in output
    assert '"would_write_database": false' in output
    assert '"would_trigger_strategy": false' in output


def _load_script():
    spec = importlib.util.spec_from_file_location("rqdata_live_1m_ingest", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
