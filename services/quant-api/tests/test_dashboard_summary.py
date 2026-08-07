from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.data_center import MarketDataFile
from app.models.review import ReviewNote
from app.models.signal import SignalScanTask, StrategySignal


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
        assert payload["strategies"] == 2
        assert payload["latest_scan_task"]["task_no"] == "scan-dash-1"
        assert payload["latest_data_time"] is not None
        assert payload["latest_review"]["review_id"] == 1
        assert payload["unfinished_review_count"] == 1
        assert "latest_confirmed_bar_time" not in payload
        assert "latest_live_signal_event" not in payload
    finally:
        app.dependency_overrides.clear()


def test_strategy_registry_exposes_formal_scan_and_non_executable_knowledge_entry() -> None:
    from app.schemas.signal import SignalScanRequest

    client = TestClient(app)
    response = client.get("/api/v1/strategies/registry")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    assert payload["v1b_count"] == 1
    formal_scan = next(
        item for item in payload["items"] if item["strategy_code"] == "su_bing_ema21"
    )
    assert formal_scan["scan_endpoint"] == "/api/signals/scan"
    assert "historical_scan" in formal_scan["capability_classes"]
    knowledge_entry = next(
        item for item in payload["items"] if item["strategy_code"] == "su_bing_jm_v1b_short_hold"
    )
    assert knowledge_entry["scan_endpoint"] is None
    assert knowledge_entry["capability_classes"] == ["research_only"]
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
