from datetime import date, datetime, timedelta
from decimal import Decimal
import json
from pathlib import Path

from fastapi.testclient import TestClient
import pandas as pd
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.data_center import (
    DataProfile,
    DataQualityReport,
    FuturesTradingParameter,
    LiveAggregatedBar,
    MainContractMap,
    MarketDataFile,
    ProfileActiveBinding,
)
from app.models.signal import SignalEvent, SignalScanTask, StrategySignal
from app.services.rqdata_ingest.quality import RQDATA_CANONICAL_CHECK_RULE_VERSION
from app.signal.events import SIGNAL_CREATED, record_signal_scan_event


def _session_factory(tmp_path: Path):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    with TestingSessionLocal() as session:
        _add_rb_signal_bars(session, tmp_path)
        _add_jm_daily_bars(session, tmp_path)
        _add_jm_actual_contract_metadata(session, tmp_path)
        session.commit()
    return TestingSessionLocal


def test_signal_scan_writes_created_event_once_and_exposes_event_api(tmp_path: Path) -> None:
    TestingSessionLocal = _session_factory(tmp_path)

    def override_get_db():
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        with TestingSessionLocal() as session:
            signal, event = _add_canonical_signal_event(session)
            session.commit()
            session.refresh(signal)
            events = list(session.scalars(select(SignalEvent).order_by(SignalEvent.id)))

        assert len(events) == 1
        event = events[0]
        assert event.event_type == "signal_created"
        assert event.event_key == f"signal_created:{signal.dedupe_key}"
        assert event.signal_id == signal.id
        assert event.task_no == signal.task_no
        assert event.source_mode == "historical_scan"
        assert event.signal_status == signal.status
        assert event.lifecycle_status == "new"
        assert event.data_role == "primary"
        assert signal.product == "jm"
        assert signal.continuous_contract == "JM.MAIN"
        assert signal.actual_contract == "JM2609"
        assert signal.bar_end == signal.signal_time
        assert signal.bar_start == signal.signal_time - timedelta(minutes=5)
        assert signal.trigger_price == signal.current_price
        assert signal.provider == "rqdata"
        assert signal.source == "historical_canonical"
        assert signal.data_role == "primary"
        assert event.product == signal.product
        assert event.continuous_contract == signal.continuous_contract
        assert event.actual_contract == "JM2609"
        assert event.bar_start == signal.bar_start
        assert event.bar_end == signal.bar_end
        assert event.trigger_price == signal.trigger_price
        assert event.provider == signal.provider
        assert event.source == signal.source
        assert event.payload["signal"]["id"] == signal.id
        assert event.payload["signal"]["product"] == "jm"
        assert event.payload["signal"]["continuous_contract"] == "JM.MAIN"
        assert event.payload["signal"]["actual_contract"] == "JM2609"
        assert signal.profile_id is None
        assert signal.market_data_file_id is None
        assert event.payload["input_identity"]["schema_version"] == "canonical_consumer_input_v1"
        assert _contains_no_secret_words(event.payload)

        list_response = client.get("/api/signals/events", params={"symbol": "jm", "event_type": "signal_created"})
        assert list_response.status_code == 200
        event_items = list_response.json()
        assert [item["id"] for item in event_items] == [event.id]
        assert event_items[0]["product"] == "jm"
        assert event_items[0]["continuous_contract"] == "JM.MAIN"
        assert event_items[0]["actual_contract"] == "JM2609"
        assert event_items[0]["trigger_price"] == signal.current_price

        filtered_response = client.get("/api/signals/events", params={"product": "jm", "provider": "rqdata", "data_role": "primary"})
        assert filtered_response.status_code == 200
        assert [item["id"] for item in filtered_response.json()] == [event.id]

        paged_events = client.get("/api/signals/events", params={"paged": "true", "limit": 1, "offset": 0})
        assert paged_events.status_code == 200
        assert paged_events.json()["total"] == 1
        assert paged_events.json()["items"][0]["id"] == event.id

        paged_latest = client.get("/api/signals/latest", params={"paged": "true", "limit": 1, "offset": 0})
        assert paged_latest.status_code == 200
        assert paged_latest.json()["total"] == 1
        assert paged_latest.json()["items"][0]["id"] == signal.id

        signal_response = client.get(f"/api/signals/{signal.id}/events")
        assert signal_response.status_code == 200
        assert [item["event_key"] for item in signal_response.json()] == [event.event_key]

        event_response = client.get(f"/api/signals/events/{event.id}")
        assert event_response.status_code == 200
        assert event_response.json()["id"] == event.id
        assert event_response.json()["source_mode"] == "historical_scan"

        missing_event_response = client.get("/api/signals/events/999999")
        assert missing_event_response.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_signal_status_changes_write_append_only_events_only_when_status_changes(tmp_path: Path) -> None:
    TestingSessionLocal = _session_factory(tmp_path)

    def override_get_db():
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        with TestingSessionLocal() as session:
            _add_canonical_signal_event(session)
            session.commit()
        signal = client.get("/api/signals/latest", params={"watchlist_code": "black"}).json()[0]

        watching = client.patch(f"/api/signals/{signal['id']}/status", json={"status": "watching"})
        assert watching.status_code == 200
        duplicate_watching = client.patch(f"/api/signals/{signal['id']}/status", json={"status": "watching"})
        assert duplicate_watching.status_code == 200
        ignored = client.patch(f"/api/signals/{signal['id']}/status", json={"status": "ignored"})
        assert ignored.status_code == 200

        with TestingSessionLocal() as session:
            events = list(session.scalars(select(SignalEvent).order_by(SignalEvent.id)))

        assert [event.event_type for event in events] == [
            "signal_created",
            "signal_status_changed",
            "signal_status_changed",
        ]
        assert events[1].source_mode == "manual_api"
        assert events[1].payload["status_change"] == {"old_status": "new", "new_status": "watching"}
        assert events[2].payload["status_change"] == {"old_status": "watching", "new_status": "ignored"}
        assert events[1].event_key != events[2].event_key
    finally:
        app.dependency_overrides.clear()


def test_live_signal_evaluator_preview_does_not_write_signal_events(tmp_path: Path) -> None:
    TestingSessionLocal = _session_factory(tmp_path)
    with TestingSessionLocal() as session:
        _add_live_bars(session, "15m", count=50)
        session.commit()

    def override_get_db():
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        response = client.post(
            "/api/signals/live-evaluator/preview",
            json={"symbol": "jm", "contract": "JM2609", "entry_intervals": ["15m"], "limit": 100},
        )
        assert response.status_code == 200

        with TestingSessionLocal() as session:
            assert session.scalar(select(func.count()).select_from(SignalEvent)) == 0
    finally:
        app.dependency_overrides.clear()


def _scan_payload() -> dict:
    return {
        "watchlist_code": "black",
        "symbols": ["rb"],
        "periods": ["5m"],
        "run_inline": True,
        "min_score_bucket": 0,
        "strategy_params": {
            "ema_period": 3,
            "macd_fast": 2,
            "macd_slow": 4,
            "macd_signal": 2,
            "atr_period": 3,
            "breakout_lookback": 3,
            "confirmation_bars": 2,
            "volume_ratio_intraday": 1.5,
            "zero_axis_atr_threshold": 10,
            "max_distance_from_ema_atr": 99,
            "confluence_threshold": 3,
            "volume_lookback": 3,
            "macd_cross_lookback": 5,
            "chop_cross_threshold": 99,
            "rapid_move_atr_threshold": 99,
        },
    }


def _add_canonical_signal_event(session) -> tuple[StrategySignal, SignalEvent]:
    signal_time = datetime(2026, 7, 10, 1, 30)
    input_identity = {
        "schema_version": "canonical_consumer_input_v1",
        "request": {"dataset_kind": "actual_dominant"},
    }
    signal = StrategySignal(
        task_no="SIG-CANONICAL-1",
        dedupe_key="canonical:signal-events-test",
        watchlist_code="black",
        symbol="jm",
        contract="JM2609",
        product="jm",
        continuous_contract="JM.MAIN",
        actual_contract="JM2609",
        dominant_mapping_date=date(2026, 7, 10),
        exchange="DCE",
        period="5m",
        signal_time=signal_time,
        bar_start=signal_time - timedelta(minutes=5),
        bar_end=signal_time,
        trigger_price=102.4,
        provider="rqdata",
        source="historical_canonical",
        data_role="primary",
        status="entry_signal",
        direction="long",
        signal_level=80,
        score_bucket=80,
        bucket_label="重点关注",
        current_price=102.4,
        reasons=["canonical test"],
        features={
            "input_identity": input_identity,
            "formal_lineage": {
                "schema_version": "signal_canonical_inputs_v1",
                "input_identity": input_identity,
            },
        },
        quality_status={"status": "passed"},
        profile_id=None,
        market_data_file_id=None,
        research_contract=False,
    )
    task = SignalScanTask(
        task_no=signal.task_no,
        status="completed",
        progress=100,
        watchlist_code="black",
        periods=["5m"],
        total_items=1,
        completed_items=1,
        request_payload={
            "mode": "scan",
            "research_only": False,
            "dataset_kind": "actual_dominant",
        },
        result_payload={},
    )
    session.add_all([task, signal])
    session.flush()
    event = record_signal_scan_event(session, signal, SIGNAL_CREATED, task)
    assert event is not None
    return signal, event


def _add_rb_signal_bars(session, tmp_path: Path) -> None:
    closes = [100, 99.8, 99.6, 99.4, 99.2, 99.3, 99.5, 99.8, 101.5, 101.8, 102.0, 102.2, 102.4]
    rows = []
    previous = closes[0]
    timestamp = datetime(2024, 1, 1, 9, 5)
    for index, close in enumerate(closes):
        bar_time = timestamp + timedelta(minutes=index * 5)
        rows.append(
            {
                "symbol": "rb",
                "contract": "rb2405",
                "exchange": "SHFE",
                "datetime": bar_time,
                "trading_day": bar_time.date(),
                "open": previous,
                "close": close,
                "high": max(previous, close) + 0.2,
                "low": min(previous, close) - 0.2,
                "volume": 300 if index == 7 else 100,
                "open_interest": 1000 + index,
                "turnover": 1000,
                "period": "5m",
                "provider": "rqdata",
                "data_version": "signal_events_test",
            }
        )
        previous = close
    market_file = _write_market_file(session, tmp_path / "canonical" / "bars" / "rb_5m.parquet", rows, "rb", "rb2405", "5m")
    session.add(
        DataProfile(
            profile_id="intraday_research_v1",
            label="Intraday",
            description="test",
            contract_roles=["actual_contract"],
            periods=["5m", "15m"],
            quality_policy="passed_only",
            provider="rqdata",
            is_active=True,
        )
    )
    session.add(
        ProfileActiveBinding(
            profile_id="intraday_research_v1",
            instrument_symbol="rb",
            contract_code="rb2405",
            contract_role="actual_contract",
            period="5m",
            data_version=market_file.data_version,
            market_data_file_id=market_file.id,
            binding_status="active",
            activated_at=timestamp,
        )
    )
    higher_rows = []
    for index in range(5):
        bar_time = timestamp + timedelta(minutes=index * 15)
        close = 100 + index
        higher_rows.append(
            {
                "symbol": "rb",
                "contract": "rb2405",
                "exchange": "SHFE",
                "datetime": bar_time,
                "trading_day": bar_time.date(),
                "open": close - 0.5,
                "close": close,
                "high": close + 1,
                "low": close - 1,
                "volume": 100,
                "open_interest": 1000 + index,
                "turnover": 1000,
                "period": "15m",
                "provider": "rqdata",
                "data_version": "signal_events_15m_test",
            }
        )
    higher_file = _write_market_file(
        session,
        tmp_path / "canonical" / "bars" / "rb_15m.parquet",
        higher_rows,
        "rb",
        "rb2405",
        "15m",
    )
    session.add(
        ProfileActiveBinding(
            profile_id="intraday_research_v1",
            instrument_symbol="rb",
            contract_code="rb2405",
            contract_role="actual_contract",
            period="15m",
            data_version=higher_file.data_version,
            market_data_file_id=higher_file.id,
            binding_status="active",
            activated_at=timestamp,
        )
    )
    session.add(
        MainContractMap(
            instrument_symbol="rb",
            trade_date=rows[-1]["trading_day"],
            rank=1,
            contract_code="rb2405",
            rule="volume_open_interest",
            provider="rqdata",
            data_version="rb-mapping-v1",
        )
    )


def _add_jm_daily_bars(session, tmp_path: Path) -> None:
    rows = []
    start = datetime(2026, 4, 1)
    for index in range(70):
        timestamp = start + timedelta(days=index)
        close = 1000 + index * 2
        rows.append(
            {
                "symbol": "jm",
                "contract": "jm.MAIN",
                "exchange": "DCE",
                "datetime": timestamp,
                "trading_day": timestamp.date(),
                "open": close - 1,
                "high": close + 4,
                "low": close - 4,
                "close": close,
                "volume": 100 + index,
                "open_interest": 1000,
                "turnover": close * 100,
                "period": "1d",
                "provider": "rqdata",
                "data_version": "daily_test",
            }
        )
    _write_market_file(session, tmp_path / "canonical" / "bars" / "jm_1d.parquet", rows, "jm", "jm.MAIN", "1d")


def _add_jm_actual_contract_metadata(session, tmp_path: Path) -> None:
    session.add(
        MainContractMap(
            instrument_symbol="jm",
            trade_date=date(2026, 7, 7),
            rank=1,
            contract_code="JM2609",
            rule="volume_open_interest",
            provider="rqdata",
            data_version="stage9_gate_test_mapping",
        )
    )
    session.add(
        FuturesTradingParameter(
            contract_code="JM2609",
            instrument_symbol="jm",
            exchange_code="DCE",
            trade_date=date(2026, 7, 7),
            long_margin_ratio=Decimal("0.12"),
            short_margin_ratio=Decimal("0.12"),
            open_commission=Decimal("0.0001"),
            close_commission=Decimal("0.0001"),
            close_today_commission=Decimal("0.0001"),
            commission_type="ratio",
            price_tick=Decimal("0.5"),
            contract_multiplier=60,
            provider="rqdata",
            data_version="stage9_gate_test_params",
        )
    )
    for period in ("1m", "5m", "15m"):
        _write_market_file(
            session,
            tmp_path / "canonical" / "bars" / f"jm2609_{period}.parquet",
            _jm_actual_rows(period),
            "jm",
            "JM2609",
            period,
        )


def _jm_actual_rows(period: str) -> list[dict]:
    start = datetime(2026, 7, 7, 9, 0)
    minutes = {"1m": 1, "5m": 5, "15m": 15}[period]
    rows = []
    for index in range(3):
        timestamp = start + timedelta(minutes=(index + 1) * minutes)
        close = 1000 + index
        rows.append(
            {
                "symbol": "jm",
                "contract": "JM2609",
                "exchange": "DCE",
                "datetime": timestamp,
                "trading_day": timestamp.date(),
                "open": close - 1,
                "high": close + 2,
                "low": close - 2,
                "close": close,
                "volume": 100 + index,
                "open_interest": 1000 + index,
                "turnover": close * 100,
                "period": period,
                "provider": "rqdata",
                "data_version": f"actual_contract_test_{period}",
            }
        )
    return rows


def _write_market_file(session, path: Path, rows: list[dict], symbol: str, contract: str, period: str) -> MarketDataFile:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(rows)
    frame["source_interval"] = frame.get("source_interval", "1m")
    frame.to_parquet(path, index=False)
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


def _add_live_bars(session, period: str, *, count: int) -> None:
    start = datetime(2026, 7, 7, 9, 0)
    for index in range(count):
        timestamp = start + timedelta(minutes=(index + 1) * 15)
        close = 1000 + index
        session.add(
            LiveAggregatedBar(
                provider="rqdata",
                instrument_symbol="jm",
                contract_code="JM2609",
                exchange_code="DCE",
                period=period,
                source_period="1m",
                source_mode="live_1m_sequential_bucket",
                bar_datetime=timestamp,
                trading_day=timestamp.date(),
                source_start_datetime=timestamp - timedelta(minutes=14),
                source_end_datetime=timestamp,
                source_bar_count=15,
                expected_bar_count=15,
                open=close - 1,
                high=close + 2,
                low=close - 2,
                close=close,
                volume=100 + index,
                open_interest=1000 + index,
                turnover=close * 100,
                bar_status="confirmed",
                quality_status="passed",
                confirmed_at=timestamp,
                raw_payload={},
            )
        )


def _contains_no_secret_words(payload: dict) -> bool:
    text = json.dumps(payload, ensure_ascii=False, default=str).lower()
    return not any(secret in text for secret in ("webhook", "token", "password", "cookie", "secret"))
