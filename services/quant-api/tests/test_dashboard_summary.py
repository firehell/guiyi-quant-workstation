from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.backtest import BacktestReportModel, BacktestTask
from app.models.data_center import LiveIngestCheckpoint, MarketDataFile
from app.models.review import ReviewNote
from app.models.signal import SignalEvent, SignalScanTask, StrategySignal


def _client(session_factory):
    def override_get_db():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def test_dashboard_summary_returns_live_aggregates() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    now = datetime.now(UTC)
    with TestingSessionLocal() as session:
        session.add(
            StrategySignal(
                dedupe_key="dash-test-1",
                strategy_name="jm_v1b_daily_direction_fast_entry",
                symbol="jm",
                contract="jm.MAIN",
                period="15m",
                signal_time=now,
                status="entry_signal",
                direction="long",
                current_price=1200.0,
            )
        )
        session.add(BacktestTask(task_no="bt-dash-1", status="success"))
        session.add(
            BacktestReportModel(
                task_id=1,
                task_no="bt-dash-1",
                report_no="rpt-dash-1",
                template_name="vnpy",
                symbol="jm.MAIN",
                contract="jm.MAIN",
                period="15m",
                status="success",
            )
        )
        session.add(
            MarketDataFile(
                provider="rqdata",
                data_type="bars",
                instrument_symbol="jm",
                contract_code="jm.MAIN",
                period="15m",
                data_role="primary",
                quality_status="passed",
                file_path="/tmp/jm_15m.parquet",
                row_count=100,
                start_time=now,
                end_time=now,
            )
        )
        session.add(
            SignalScanTask(
                task_no="scan-dash-1",
                status="success",
                progress=1.0,
                watchlist_code="jm_v1b",
                periods=["15m"],
            )
        )
        session.add(
            LiveIngestCheckpoint(
                provider="rqdata",
                instrument_symbol="jm",
                contract_code="JM2609",
                period="1m",
                source_mode="poll_get_price_1m",
                last_confirmed_bar_at=now,
                status="ok",
            )
        )
        session.add(
            SignalEvent(
                event_key="dashboard-live-event-1",
                event_type="created",
                source_mode="live_confirmed",
                strategy_name="jm_v1b_daily_direction_fast_entry",
                strategy_version="v1",
                symbol="jm",
                contract="JM2609",
                period="15m",
                signal_time=now,
                direction="long",
                signal_status="entry_signal",
                lifecycle_status="new",
            )
        )
        session.add(
            ReviewNote(
                source_type="signal_event",
                source_id=1,
                symbol="jm",
                contract="JM2609",
                period="15m",
            )
        )
        session.commit()

    client = _client(TestingSessionLocal)
    try:
        response = client.get("/api/dashboard/summary")
        assert response.status_code == 200
        payload = response.json()
        assert payload["data_status"] == "live"
        assert payload["risk_status"] == "research_only"
        assert payload["signals_today"] == 1
        assert payload["backtests"] == 1
        assert payload["backtest_reports"] == 1
        assert payload["strategies"] >= 5
        assert payload["latest_scan_task"]["task_no"] == "scan-dash-1"
        assert payload["latest_jm_report"]["report_id"] == 1
        assert payload["latest_data_time"] is not None
        assert payload["latest_confirmed_bar_time"] is not None
        assert payload["latest_live_signal_event"]["event_id"] == 1
        assert payload["latest_live_signal_event"]["source_mode"] == "live_confirmed"
        assert payload["latest_live_signal_event"]["lifecycle_status"] == "new"
        assert payload["latest_review"]["review_id"] == 1
        assert payload["unfinished_review_count"] == 1
    finally:
        app.dependency_overrides.clear()


def test_strategy_registry_lists_v1b_entries() -> None:
    from app.schemas.signal import SignalScanRequest

    client = TestClient(app)
    response = client.get("/api/v1/strategies/registry")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] >= 5
    assert payload["v1b_count"] >= 4
    codes = {item["strategy_code"] for item in payload["items"]}
    assert "jm_v1b_daily_direction_fast_entry" in codes
    assert "su_bing_jm_daily_ema21_macd_volume" in codes
    jm_v1b = next(item for item in payload["items"] if item["strategy_code"] == "jm_v1b_daily_direction_fast_entry")
    assert len(jm_v1b["backtest_endpoints"]) == 2
    assert jm_v1b["scan_endpoint"] is None
    assert "historical_scan" not in jm_v1b["capability_classes"]
    assert all(
        item.get("scan_endpoint") != "/api/signals/v1b/jm/scan"
        for item in payload["items"]
    )
    formal_scan = next(
        item for item in payload["items"] if item["strategy_code"] == "su_bing_ema21"
    )
    assert formal_scan["scan_endpoint"] == "/api/signals/scan"
    assert "historical_scan" in formal_scan["capability_classes"]
    request = SignalScanRequest.model_validate(
        {
            "dataset_kind": "actual_dominant",
            "instrument_symbol": "jm",
            "contract_or_series": "JM2609",
            "periods": [formal_scan["periods"][0]],
            "start": "2026-07-10T00:00:00+00:00",
            "end": "2026-07-10T01:00:00+00:00",
            "strategy_code": formal_scan["strategy_code"],
            "strategy_version": formal_scan["strategy_version"],
        }
    )
    assert request.strategy_version == "v0"
