from __future__ import annotations

from datetime import date, datetime, timedelta
import json
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.data_center import (
    DataProfile,
    DataQualityReport,
    FeeMarginRule,
    FuturesTradingParameter,
    MainContractMap,
    MarketDataFile,
    ProfileActiveBinding,
)
from app.models.signal import SignalEvent, SignalNotification, StrategySignal
from app.services.rqdata_ingest.quality import RQDATA_CANONICAL_CHECK_RULE_VERSION
from app.signal.stage9_gate import evaluate_stage9_signal_event_gate
from app.signal.stage9_jm_v1b_replay import Stage9JmV1bReplayService


def _session_factory(tmp_path: Path, *, entry_candidate: bool = True):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    with TestingSessionLocal() as session:
        _seed_metadata(session)
        _seed_actual_contract_files(session, tmp_path, entry_candidate=entry_candidate)
        _seed_daily_main_file(session, tmp_path)
        _seed_profiles(session)
        session.commit()
    return TestingSessionLocal


def test_replay_dry_run_finds_candidate_without_writing(tmp_path: Path) -> None:
    TestingSessionLocal = _session_factory(tmp_path)

    with TestingSessionLocal() as session:
        result = Stage9JmV1bReplayService(session).run(period="15m", strategy_params=_fast_params())

        assert result["candidate_found"] is True
        assert result["dry_run"] is True
        assert result["would_write_signal_event"] is True
        assert result["event_id"] is None
        assert result["candidate"]["status"] == "entry_signal"
        assert result["candidate"]["actual_contract"] == "JM2609"
        assert result["gate"]["allowed"] is True
        assert result["gate"]["blocked_reasons"] == []
        assert session.scalar(select(func.count()).select_from(StrategySignal)) == 0
        assert session.scalar(select(func.count()).select_from(SignalEvent)) == 0
        assert session.scalar(select(func.count()).select_from(SignalNotification)) == 0


def test_replay_reads_profile_files_by_id_without_latest_selector(tmp_path: Path) -> None:
    TestingSessionLocal = _session_factory(tmp_path)

    with TestingSessionLocal() as session:
        service = Stage9JmV1bReplayService(session)

        def forbidden_latest(*args, **kwargs):
            raise AssertionError("formal replay must read immutable Profile files by id")

        service.reader.load_latest_bars = forbidden_latest  # type: ignore[method-assign]
        result = service.run(period="15m", strategy_params=_fast_params())

        assert result["candidate_found"] is True


def test_replay_run_write_creates_one_eligible_event_and_is_idempotent(tmp_path: Path) -> None:
    TestingSessionLocal = _session_factory(tmp_path)

    with TestingSessionLocal() as session:
        first = Stage9JmV1bReplayService(session).run(
            period="15m",
            strategy_params=_fast_params(),
            run_write=True,
            confirm_historical_replay=True,
            confirm_observation_only=True,
        )
        second = Stage9JmV1bReplayService(session).run(
            period="15m",
            strategy_params=_fast_params(),
            run_write=True,
            confirm_historical_replay=True,
            confirm_observation_only=True,
        )

        assert first["candidate_found"] is True
        assert first["dry_run"] is False
        assert first["event_id"] is not None
        assert second["event_id"] == first["event_id"]
        assert session.scalar(select(func.count()).select_from(StrategySignal)) == 1
        assert session.scalar(select(func.count()).select_from(SignalEvent)) == 1
        assert session.scalar(select(func.count()).select_from(SignalNotification)) == 0

        event = session.get(SignalEvent, first["event_id"])
        assert event is not None
        assert event.source_mode == "jm_v1b_historical_replay"
        assert event.event_type == "signal_created"
        assert event.signal_status == "entry_signal"
        assert event.contract == "JM2609"
        assert event.continuous_contract == "jm.MAIN"
        assert event.actual_contract == "JM2609"
        assert event.dominant_mapping_date == date(2026, 7, 7)
        assert event.provider == "rqdata"
        assert event.source == "historical_actual_contract_replay"
        assert event.data_role == "primary"
        assert event.quality_status["status"] == "passed"
        assert event.payload["historical_replay"]["observation_only"] is True
        assert event.payload["historical_replay"]["not_trading_instruction"] is True
        assert evaluate_stage9_signal_event_gate(event)["allowed"] is True


def test_replay_without_entry_candidate_returns_blocker_without_writes(tmp_path: Path) -> None:
    TestingSessionLocal = _session_factory(tmp_path, entry_candidate=False)

    with TestingSessionLocal() as session:
        result = Stage9JmV1bReplayService(session).run(period="15m", strategy_params=_fast_params())

        assert result["candidate_found"] is False
        assert result["blocked_reasons"] == ["entry_signal_not_found"]
        assert session.scalar(select(func.count()).select_from(StrategySignal)) == 0
        assert session.scalar(select(func.count()).select_from(SignalEvent)) == 0
        assert session.scalar(select(func.count()).select_from(SignalNotification)) == 0


def test_replay_result_and_event_payload_do_not_expose_sensitive_words(tmp_path: Path) -> None:
    TestingSessionLocal = _session_factory(tmp_path)

    with TestingSessionLocal() as session:
        result = Stage9JmV1bReplayService(session).run(
            period="15m",
            strategy_params=_fast_params(),
            run_write=True,
            confirm_historical_replay=True,
            confirm_observation_only=True,
        )
        event = session.get(SignalEvent, result["event_id"])
        assert event is not None

        assert _contains_no_secret_words(result)
        assert _contains_no_secret_words(event.payload)


def _seed_metadata(session) -> None:
    session.add(
        MainContractMap(
            instrument_symbol="jm",
            trade_date=date(2026, 7, 7),
            rank=1,
            contract_code="JM2609",
            rule="volume_open_interest",
            provider="rqdata",
            data_version="stage9_b2_replay_test_mapping",
        )
    )
    session.add(
        FuturesTradingParameter(
            contract_code="JM2609",
            instrument_symbol="jm",
            exchange_code="DCE",
            trade_date=date(2026, 7, 7),
            long_margin_ratio="0.12",
            short_margin_ratio="0.12",
            open_commission="0.0001",
            close_commission="0.0001",
            close_today_commission="0.0001",
            commission_type="ratio",
            price_tick="0.5",
            contract_multiplier=60,
            provider="rqdata",
            data_version="stage9_b2_replay_test_params",
        )
    )
    session.add(
        FeeMarginRule(
            provider="rqdata",
            exchange_code="DCE",
            instrument_symbol="jm",
            contract_code="JM2609",
            effective_date=date(2026, 7, 7),
            price_tick="0.5",
            volume_multiple=60,
            margin_rate="0.12",
            open_fee="0.0001",
            close_fee="0.0001",
            close_today_fee="0.0001",
        )
    )


def _seed_actual_contract_files(session, tmp_path: Path, *, entry_candidate: bool) -> None:
    _write_market_file(
        session,
        tmp_path / "canonical" / "bars" / "provider=rqdata" / "jm2609_1m.parquet",
        _actual_rows("1m", [100, 101, 102]),
        "jm",
        "JM2609",
        "1m",
    )
    _write_market_file(
        session,
        tmp_path / "canonical" / "bars" / "provider=rqdata" / "jm2609_5m.parquet",
        _actual_rows("5m", [100, 100.5, 101, 100.8, 101.2, 103]),
        "jm",
        "JM2609",
        "5m",
    )
    closes = [100, 100.5, 101, 100.8, 101.2, 103] if entry_candidate else [100, 100, 100, 100, 100, 100]
    _write_market_file(
        session,
        tmp_path / "canonical" / "bars" / "provider=rqdata" / "jm2609_15m.parquet",
        _actual_rows("15m", closes),
        "jm",
        "JM2609",
        "15m",
    )


def _seed_daily_main_file(session, tmp_path: Path) -> None:
    rows = []
    start = date(2026, 7, 1)
    for index, close in enumerate([100, 101, 102, 104, 106]):
        trading_day = start + timedelta(days=index)
        rows.append(
            {
                "symbol": "jm",
                "contract": "jm.MAIN",
                "exchange": "DCE",
                "datetime": datetime.combine(trading_day, datetime.min.time()).replace(hour=15),
                "trading_day": trading_day,
                "open": close - 0.5,
                "high": close + 1,
                "low": close - 1,
                "close": close,
                "volume": 1000,
                "open_interest": 1000 + index,
                "turnover": close * 100,
                "period": "1d",
                "provider": "rqdata",
                "data_version": "stage9_b2_daily_test",
            }
        )
    _write_market_file(session, tmp_path / "canonical" / "bars" / "provider=rqdata" / "jm_MAIN_1d.parquet", rows, "jm", "jm.MAIN", "1d")


def _actual_rows(period: str, closes: list[float]) -> list[dict]:
    minutes = {"1m": 1, "5m": 5, "15m": 15}[period]
    start = datetime(2026, 7, 6, 9, 0)
    rows = []
    previous = closes[0]
    for index, close in enumerate(closes):
        moment = start + timedelta(minutes=index * minutes)
        rows.append(
            {
                "symbol": "jm",
                "contract": "JM2609",
                "exchange": "DCE",
                "datetime": moment,
                "trading_day": moment.date(),
                "open": previous,
                "high": max(previous, close) + 0.2,
                "low": min(previous, close) - 0.2,
                "close": close,
                "volume": 250,
                "open_interest": 1000 + index,
                "turnover": close * 100,
                "period": period,
                "provider": "rqdata",
                "data_version": f"stage9_b2_actual_test_{period}",
            }
        )
        previous = close
    return rows


def _write_market_file(session, path: Path, rows: list[dict], symbol: str, contract: str, period: str) -> MarketDataFile:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(path, index=False)
    market_file = MarketDataFile(
        provider="rqdata",
        data_type="bars",
        instrument_symbol=symbol,
        contract_code=contract,
        period=period,
        start_time=rows[0]["datetime"],
        end_time=rows[-1]["datetime"],
        file_path=str(path),
        row_count=len(rows),
        file_size_bytes=path.stat().st_size,
        data_version=rows[0]["data_version"],
        data_role="primary",
        quality_status="passed",
    )
    session.add(market_file)
    session.flush()
    session.add(
        DataQualityReport(
            file_id=market_file.id,
            provider="rqdata",
            data_type="bars",
            instrument_symbol=symbol,
            contract_code=contract,
            period=period,
            start_time=rows[0]["datetime"],
            end_time=rows[-1]["datetime"],
            status="passed",
            missing_bars=0,
            duplicated_bars=0,
            abnormal_price_count=0,
            abnormal_volume_count=0,
            details={"check_rule_version": RQDATA_CANONICAL_CHECK_RULE_VERSION},
        )
    )
    return market_file


def _seed_profiles(session) -> None:
    session.add_all(
        [
            DataProfile(
                profile_id="intraday_research_v1",
                label="Intraday",
                description="test",
                contract_roles=["actual_contract"],
                periods=["5m", "15m"],
                quality_policy="passed_only",
                provider="rqdata",
                is_active=True,
            ),
            DataProfile(
                profile_id="long_horizon_daily_v1",
                label="Daily",
                description="test",
                contract_roles=["dominant_main"],
                periods=["1d"],
                quality_policy="passed_only",
                provider="rqdata",
                is_active=True,
            ),
        ]
    )
    files = list(session.scalars(select(MarketDataFile)))
    for market_file in files:
        if market_file.period not in {"5m", "15m", "1d"}:
            continue
        profile_id = "long_horizon_daily_v1" if market_file.period == "1d" else "intraday_research_v1"
        session.add(
            ProfileActiveBinding(
                profile_id=profile_id,
                instrument_symbol="jm",
                contract_code=str(market_file.contract_code),
                contract_role="dominant_main" if market_file.period == "1d" else "actual_contract",
                period=str(market_file.period),
                data_version=str(market_file.data_version),
                market_data_file_id=market_file.id,
                binding_status="active",
                activated_at=datetime(2026, 7, 1),
            )
        )


def _fast_params() -> dict:
    return {
        "ema_period": 2,
        "macd_fast": 2,
        "macd_slow": 3,
        "macd_signal": 2,
        "atr_period": 2,
        "volume_window": 2,
        "volume_multiplier_15m": 1.0,
        "volume_multiplier_5m": 1.0,
        "pullback_lookback_bars": 2,
        "pullback_touch_ema_atr": 100.0,
        "max_ema_distance_atr_15m": 100.0,
        "max_ema_distance_atr_5m": 100.0,
        "stop_loss_atr_multiple": 1.0,
        "structure_stop_lookback_bars": 2,
        "stop_buffer_ticks": 0,
        "pricetick": 1.0,
        "submit_vnpy_orders": False,
        "daily_ema_period": 2,
        "daily_ema_slope_lookback": 1,
        "daily_ema_slope_min_atr": 0.0001,
        "daily_macd_fast": 2,
        "daily_macd_slow": 3,
        "daily_macd_signal": 2,
        "daily_atr_period": 2,
        "daily_neutral_ema_band_atr": 0.01,
        "daily_max_ema_distance_atr": 100.0,
    }


def _contains_no_secret_words(payload: dict) -> bool:
    text = json.dumps(payload, ensure_ascii=False, default=str).lower()
    return not any(secret in text for secret in ("webhook", "token", "password", "cookie", "secret"))
