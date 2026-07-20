from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
import pandas as pd
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
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
    TradingCalendar,
)
from app.models.signal import SignalNotification, SignalScanTask, StrategySignal
from app.models.signal import SignalEvent
from app.services.rqdata_ingest.parquet import sha256_file
from app.services.rqdata_ingest.quality import RQDATA_CANONICAL_CHECK_RULE_VERSION


def _session_factory(tmp_path: Path, *, with_daily: bool = True):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    with TestingSessionLocal() as session:
        _add_live_target_metadata(session, tmp_path)
        if with_daily:
            _add_daily_bars(session, tmp_path)
        session.commit()
    return TestingSessionLocal


def test_live_signal_evaluator_preview_reads_live_bars_without_writing_signal_tables(tmp_path: Path) -> None:
    TestingSessionLocal = _session_factory(tmp_path)
    with TestingSessionLocal() as session:
        _add_live_bars(session, "15m", count=50)
        _add_live_bars(session, "5m", count=50, minutes=5)
        session.commit()

    def override_get_db():
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        response = client.post(
            "/api/signals/live-evaluator/preview",
            json={
                "symbol": "jm",
                "contract": "JM2609",
                "entry_intervals": ["15m", "5m"],
                "provider": "rqdata",
                "source_mode": "live_1m_sequential_bucket",
                "limit": 100,
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["strategy_code"] == "jm_v1b_daily_direction_fast_entry"
        assert payload["strategy_version"] == "v1b.0"
        assert payload["contract"] == "JM2609"
        assert payload["continuous_contract"] == "jm.MAIN"
        assert payload["actual_contract"] == "JM2609"
        assert payload["dominant_mapping_date"] == "2026-07-07"
        assert payload["quality_summary"]["preview_only"] is True
        assert payload["quality_summary"]["writes_strategy_signal"] is False
        assert payload["quality_summary"]["live_target_status"] == "ready"
        assert {item["entry_interval"] for item in payload["results"]} == {"15m", "5m"}
        assert all(item["contract"] == "JM2609" for item in payload["results"])
        assert all(item["continuous_contract"] == "jm.MAIN" for item in payload["results"])
        assert all(item["actual_contract"] == "JM2609" for item in payload["results"])
        assert all(item["dominant_mapping_date"] == "2026-07-07" for item in payload["results"])
        assert all(item["source"]["entry_data_source"] == "historical_actual_plus_live_confirmed" for item in payload["results"])
        assert all(item["source"]["daily_data_source"] == "active_standard_parquet_continuous" for item in payload["results"])
        assert all(item["source"]["auto_order"] is False for item in payload["results"])
        assert all(item["bar_time"] for item in payload["results"])
        assert all(item["bar_end"] == item["bar_time"] for item in payload["results"])
        assert all(item["trigger_price"] is None for item in payload["results"] if item["status"] != "entry_signal")

        with TestingSessionLocal() as session:
            assert session.scalar(select(func.count()).select_from(StrategySignal)) == 0
            assert session.scalar(select(func.count()).select_from(SignalNotification)) == 0
            assert session.scalar(select(func.count()).select_from(SignalScanTask)) == 0
    finally:
        app.dependency_overrides.clear()


def test_live_signal_evaluator_resolves_actual_contract_when_request_omits_contract(tmp_path: Path) -> None:
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
            json={"symbol": "jm", "entry_intervals": ["15m"], "limit": 100},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["contract"] == "JM2609"
        assert payload["actual_contract"] == "JM2609"
        assert payload["results"][0]["source"]["actual_contract"] == "JM2609"
    finally:
        app.dependency_overrides.clear()


def test_live_signal_evaluator_rejects_main_or_mismatched_contract(tmp_path: Path) -> None:
    TestingSessionLocal = _session_factory(tmp_path)

    def override_get_db():
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        main_response = client.post(
            "/api/signals/live-evaluator/preview",
            json={"symbol": "jm", "contract": "jm.MAIN", "entry_intervals": ["15m"], "limit": 100},
        )
        assert main_response.status_code == 422
        assert "actual_contract" in main_response.json()["detail"]

        mismatch = client.post(
            "/api/signals/live-evaluator/preview",
            json={"symbol": "jm", "contract": "JM2605", "entry_intervals": ["15m"], "limit": 100},
        )
        assert mismatch.status_code == 422
        assert "does not match live target" in mismatch.json()["detail"]

        wrong_profile = client.post(
            "/api/signals/live-evaluator/preview",
            json={
                "symbol": "jm",
                "contract": "JM2609",
                "profile_id": "intraday_research_v1",
                "entry_intervals": ["15m"],
            },
        )
        assert wrong_profile.status_code == 422
        assert "live_observation_v1" in str(wrong_profile.json())
    finally:
        app.dependency_overrides.clear()


def test_live_signal_evaluator_blocks_warning_partial_bucket_by_default(tmp_path: Path) -> None:
    TestingSessionLocal = _session_factory(tmp_path)
    with TestingSessionLocal() as session:
        _add_live_bars(session, "15m", count=50, warning_index=49)
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
        item = response.json()["results"][0]
        assert item["status"] == "no_signal"
        assert item["direction"] == "neutral"
        assert item["no_signal_reason"] == "live_data_quality_warning_blocked"
        assert item["context"]["status"] == "ready"
    finally:
        app.dependency_overrides.clear()


def test_live_signal_evaluator_uses_historical_warmup_when_live_has_three_bars(tmp_path: Path) -> None:
    TestingSessionLocal = _session_factory(tmp_path)
    with TestingSessionLocal() as session:
        _add_live_bars(session, "5m", count=3, minutes=5)
        session.commit()

    def override_get_db():
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        response = client.post(
            "/api/signals/live-evaluator/preview",
            json={"symbol": "jm", "contract": "JM2609", "entry_intervals": ["5m"], "limit": 100},
        )

        assert response.status_code == 200
        item = response.json()["results"][0]
        assert item["context"]["status"] == "ready"
        assert item["context"]["live_bar_id"] is not None
        assert item["context"]["historical_context_bar_count"] >= 50
        assert item["context"]["merged_bar_count"] >= 50
        assert item["no_signal_reason"] != "entry_bars_insufficient"
    finally:
        app.dependency_overrides.clear()


def test_live_signal_evaluator_reports_missing_historical_daily_data(tmp_path: Path) -> None:
    TestingSessionLocal = _session_factory(tmp_path, with_daily=False)
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
        item = response.json()["results"][0]
        assert item["status"] == "no_signal"
        assert item["no_signal_reason"] == "daily_data_missing"
        assert item["quality"]["daily"]["status"] == "missing"
    finally:
        app.dependency_overrides.clear()


def test_live_signal_evaluator_entry_uses_live_trigger_and_complete_context_lineage(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from guiyi_quant.strategies.jm_v1b_daily_direction_fast_entry import vnpy_strategy

    TestingSessionLocal = _session_factory(tmp_path)
    with TestingSessionLocal() as session:
        _add_live_bars(session, "15m", count=1)
        session.commit()

    monkeypatch.setattr(
        vnpy_strategy,
        "confirmed_daily_direction_snapshot",
        lambda **_: vnpy_strategy.DailyDirectionSnapshot("long", date(2026, 7, 7), 1000, 999, 20, 1, 0, "test"),
    )
    monkeypatch.setattr(
        vnpy_strategy,
        "decide_entry",
        lambda *_: vnpy_strategy.EntryDecision("long", "forced_test_entry", "long", 990),
    )

    def override_get_db():
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = TestClient(app).post(
            "/api/signals/live-evaluator/preview",
            json={"symbol": "jm", "contract": "JM2609", "entry_intervals": ["15m"], "limit": 100},
        )
        assert response.status_code == 200
        item = response.json()["results"][0]
        assert item["status"] == "entry_signal"
        assert item["source"].get("formal_lineage_blocked") is None, item["source"].get("formal_lineage_blocked")
        assert "formal_lineage" in item["source"]
        lineage = item["source"]["formal_lineage"]
        assert lineage["context_contract_version"] == "historical_live_context_v1"
        assert lineage["historical_context"]["historical_context_file_id"] == item["context"]["historical_context_file_id"]
        assert lineage["historical_context"]["historical_context_hash"] == item["context"]["historical_context_hash"]
        assert lineage["live_trigger"]["live_bar_id"] == item["context"]["live_bar_id"]
        assert lineage["live_trigger"]["live_bar_revision"] == 0
        assert lineage["live_trigger"]["confirmed_at"] == item["context"]["confirmed_at"]
        assert lineage["live_trigger"]["actual_contract"] == "JM2609"
        assert lineage["live_trigger"]["dominant_mapping_date"] == "2026-07-07"

        with TestingSessionLocal() as session:
            assert session.scalar(select(func.count()).select_from(StrategySignal)) == 0
            assert session.scalar(select(func.count()).select_from(SignalEvent)) == 0
            assert session.scalar(select(func.count()).select_from(SignalNotification)) == 0
    finally:
        app.dependency_overrides.clear()


def test_live_signal_evaluator_restart_reuses_same_context_identity(tmp_path: Path) -> None:
    TestingSessionLocal = _session_factory(tmp_path)
    with TestingSessionLocal() as session:
        _add_live_bars(session, "15m", count=1)
        session.commit()

    def override_get_db():
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        request = {"symbol": "jm", "contract": "JM2609", "entry_intervals": ["15m"], "limit": 100}
        first = client.post("/api/signals/live-evaluator/preview", json=request).json()["results"][0]["context"]
        second = client.post("/api/signals/live-evaluator/preview", json=request).json()["results"][0]["context"]
        assert first == second
    finally:
        app.dependency_overrides.clear()


def test_live_signal_evaluator_main_switch_never_falls_back_to_old_contract(tmp_path: Path) -> None:
    TestingSessionLocal = _session_factory(tmp_path)
    with TestingSessionLocal() as session:
        mapping = session.scalar(select(MainContractMap))
        assert mapping is not None
        mapping.contract_code = "JM2611"
        session.add(
            FuturesTradingParameter(
                contract_code="JM2611",
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
                data_version="params-new-v1",
            )
        )
        for period in ("1m", "5m", "15m"):
            session.add(
                MarketDataFile(
                    provider="rqdata",
                    data_type="bars",
                    instrument_symbol="jm",
                    contract_code="JM2611",
                    period=period,
                    start_time=datetime(2026, 7, 6, 9, 0),
                    end_time=datetime(2026, 7, 6, 15, 0),
                    file_path=f"/tmp/jm2611_{period}.parquet",
                    row_count=100,
                    data_version=f"new-{period}-v1",
                    data_role="primary",
                    quality_status="passed",
                )
            )
        _add_live_bars(session, "15m", count=1)
        session.commit()

    def override_get_db():
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        payload = TestClient(app).post(
            "/api/signals/live-evaluator/preview",
            json={"symbol": "jm", "entry_intervals": ["15m"], "limit": 100},
        ).json()
        assert payload["actual_contract"] == "JM2611"
        assert payload["results"][0]["actual_contract"] == "JM2611"
        assert payload["results"][0]["no_signal_reason"] == "historical_context_profile_binding_missing"
        assert payload["results"][0]["context"]["status"] == "blocked"
    finally:
        app.dependency_overrides.clear()


def _add_live_target_metadata(session: Session, tmp_path: Path) -> None:
    session.add(
        MainContractMap(
            instrument_symbol="jm",
            trade_date=date(2026, 7, 7),
            rank=1,
            contract_code="JM2609",
            rule="volume_open_interest",
            provider="rqdata",
            data_version="map-v1",
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
            data_version="params-v1",
        )
    )
    session.add(
        DataProfile(
            profile_id="live_observation_v1",
            label="Live observation",
            description="test",
            contract_roles=["actual_contract"],
            periods=["5m", "15m"],
            quality_policy="passed_only",
            provider="rqdata",
            is_active=True,
        )
    )
    session.add_all(
        [
            TradingCalendar(exchange_code="DCE", trade_date=date(2026, 7, 6), is_trading_day=True, provider="rqdata"),
            TradingCalendar(exchange_code="DCE", trade_date=date(2026, 7, 7), is_trading_day=True, provider="rqdata"),
        ]
    )
    for period in ("1m", "5m", "15m"):
        if period in {"5m", "15m"}:
            market_file = _add_historical_actual_bars(session, tmp_path, period)
            session.add(
                ProfileActiveBinding(
                    profile_id="live_observation_v1",
                    instrument_symbol="jm",
                    contract_code="JM2609",
                    contract_role="actual_contract",
                    period=period,
                    data_version=market_file.data_version,
                    market_data_file_id=market_file.id,
                    binding_status="active",
                )
            )
            continue
        session.add(
            MarketDataFile(
                provider="rqdata",
                data_type="bars",
                instrument_symbol="jm",
                contract_code="JM2609",
                period=period,
                start_time=datetime(2026, 7, 7, 9, 1),
                end_time=datetime(2026, 7, 7, 15, 0),
                file_path=f"/tmp/canonical/bars/jm2609_{period}.parquet",
                row_count=100,
                data_version=f"actual-{period}-v1",
                data_role="primary",
                quality_status="passed",
            )
        )


def _add_historical_actual_bars(session: Session, tmp_path: Path, period: str) -> MarketDataFile:
    minutes = int(period.removesuffix("m"))
    rows = []
    start = datetime(2026, 7, 6, 0, 0)
    for index in range(100):
        timestamp = start + timedelta(minutes=(index + 1) * minutes)
        close = 900 + index
        rows.append(
            {
                "symbol": "jm",
                "contract": "JM2609",
                "exchange": "DCE",
                "datetime": timestamp,
                "trading_day": date(2026, 7, 6),
                "open": close - 1,
                "high": close + 3,
                "low": close - 3,
                "close": close,
                "volume": 100,
                "open_interest": 1000,
                "turnover": 10000,
                "period": period,
                "provider": "rqdata",
                "data_version": f"actual-{period}-v1",
                "source_interval": "1m",
            }
        )
    path = tmp_path / "canonical" / "bars" / f"jm2609_{period}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(path, index=False)
    market_file = MarketDataFile(
        provider="rqdata",
        data_type="bars",
        instrument_symbol="jm",
        contract_code="JM2609",
        period=period,
        start_time=rows[0]["datetime"],
        end_time=rows[-1]["datetime"],
        file_path=str(path),
        row_count=len(rows),
        file_size_bytes=path.stat().st_size,
        checksum=sha256_file(path),
        data_version=f"actual-{period}-v1",
        data_role="primary",
        quality_status="passed",
    )
    session.add(market_file)
    session.flush()
    return market_file


def _add_daily_bars(session: Session, tmp_path: Path) -> None:
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
                "source_interval": "1d",
            }
        )
    path = tmp_path / "canonical" / "bars" / "jm_MAIN_1d.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(path, index=False)
    market_file = MarketDataFile(
        provider="rqdata",
        data_type="bars",
        instrument_symbol="jm",
        contract_code="jm.MAIN",
        period="1d",
        start_time=rows[0]["datetime"],
        end_time=rows[-1]["datetime"],
        file_path=str(path),
        row_count=len(rows),
        file_size_bytes=path.stat().st_size,
        data_version="daily_test",
        data_role="primary",
        quality_status="passed",
    )
    session.add(market_file)
    session.flush()
    session.add(
        DataProfile(
            profile_id="long_horizon_daily_v1",
            label="Long horizon daily",
            description="test",
            contract_roles=["dominant_main"],
            periods=["1d"],
            quality_policy="passed_only",
            provider="rqdata",
            is_active=True,
        )
    )
    session.add(
        ProfileActiveBinding(
            profile_id="long_horizon_daily_v1",
            instrument_symbol="jm",
            contract_code="jm.MAIN",
            contract_role="dominant_main",
            period="1d",
            data_version=market_file.data_version,
            market_data_file_id=market_file.id,
            binding_status="active",
        )
    )
    session.add(
        DataQualityReport(
            file_id=market_file.id,
            provider="rqdata",
            data_type="bars",
            instrument_symbol="jm",
            contract_code="jm.MAIN",
            period="1d",
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


def _add_live_bars(
    session: Session,
    period: str,
    *,
    count: int,
    minutes: int = 15,
    warning_index: int | None = None,
) -> None:
    start = datetime(2026, 7, 7, 9, 0)
    for index in range(count):
        timestamp = start + timedelta(minutes=(index + 1) * minutes)
        price = Decimal(1000 + index)
        warning = warning_index == index
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
                trading_day=date(2026, 7, 7),
                source_start_datetime=timestamp - timedelta(minutes=minutes - 1),
                source_end_datetime=timestamp,
                source_bar_count=minutes - 1 if warning else minutes,
                expected_bar_count=minutes,
                open=price - Decimal("1"),
                high=price + Decimal("3"),
                low=price - Decimal("3"),
                close=price,
                volume=Decimal("100"),
                open_interest=Decimal("1000"),
                turnover=Decimal("10000"),
                bar_status="confirmed",
                quality_status="warning" if warning else "passed",
                first_seen_at=timestamp + timedelta(seconds=2),
                last_seen_at=timestamp + timedelta(seconds=3),
                confirmed_at=timestamp + timedelta(seconds=3),
                revision=0,
                raw_payload={"quality_reasons": ["incomplete_source_bucket"]} if warning else {},
            )
        )
