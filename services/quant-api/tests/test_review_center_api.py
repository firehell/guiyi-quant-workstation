from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.backtest import BacktestReportModel, BacktestTask, BacktestTradeModel
from app.models.review import ReviewNote


def _setup_review_data():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    with TestingSessionLocal() as session:
        task = BacktestTask(task_no="BTB-review-test", request_payload={}, result_payload={})
        session.add(task)
        session.flush()
        report = BacktestReportModel(
            task_id=task.id,
            task_no=task.task_no,
            report_no="RPT-review-test",
            template_name="default",
            strategy_code="jm_v1b_daily_direction_fast_entry",
            strategy_version="v1b.0",
            symbol="rb",
            contract="rb.MAIN",
            period="5m",
            status="completed",
            summary={},
        )
        session.add(report)
        session.flush()
        trade = BacktestTradeModel(
            report_id=report.id,
            trade_no="TRD-000001",
            symbol="rb",
            contract="rb.MAIN",
            direction="long",
            open_time=datetime(2024, 1, 1, 9, 10, tzinfo=UTC),
            open_price=100,
            close_time=datetime(2024, 1, 1, 10, 0, tzinfo=UTC),
            close_price=105,
            volume=1,
            turnover=2050,
            commission=2,
            slippage=1,
            gross_pnl=50,
            net_pnl=47,
            return_pct=0.02,
            holding_bars=10,
            entry_reason="EMA21上方只做多; 成交量放大; 带量突破",
            exit_reason="止盈",
            raw_payload={
                "entry_interval": "5m",
                "hold_bars": 10,
                "daily_direction": "long",
                "stop_loss_price": 98.5,
            },
        )
        session.add(trade)
        session.commit()
    return TestingSessionLocal


def test_create_update_and_stats_review_from_backtest_trade() -> None:
    TestingSessionLocal = _setup_review_data()

    def override_get_db():
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        sources = client.get("/api/reviews/sources/backtest-trades")
        assert sources.status_code == 200
        trade_id = sources.json()[0]["id"]
        assert sources.json()[0]["reviewed"] is False

        paged_sources = client.get(
            "/api/reviews/sources/backtest-trades",
            params={"paged": "true", "limit": 1, "offset": 0},
        )
        assert paged_sources.status_code == 200
        assert paged_sources.json()["total"] == 1
        assert paged_sources.json()["items"][0]["id"] == trade_id

        created = client.post(f"/api/reviews/from-backtest-trade/{trade_id}")
        assert created.status_code == 200
        payload = created.json()
        assert payload["symbol"] == "rb"
        assert payload["period"] == "5m"
        assert payload["report_id"]
        assert payload["trade_id"] == trade_id
        assert payload["entry_interval"] == "5m"
        assert payload["entry_time"] == "2024-01-01T09:10:00"
        assert payload["exit_time"] == "2024-01-01T10:00:00"
        assert payload["hold_bars"] == 10
        assert payload["trade_no"] == "TRD-000001"
        assert payload["review_object_type"] == "backtest_trade"
        assert payload["entry_reason"].startswith("EMA21")
        assert "EMA21方向过滤" in payload["rule_tags"]
        assert "EMA21方向过滤" in payload["setup_tags"]
        assert payload["extra"]["report_id"] == payload["report_id"]
        assert payload["extra"]["trade_id"] == trade_id
        assert payload["extra"]["entry_interval"] == "5m"

        duplicate = client.post(f"/api/reviews/from-backtest-trade/{trade_id}")
        assert duplicate.status_code == 200
        assert duplicate.json()["id"] == payload["id"]
        assert duplicate.json()["report_id"] == payload["report_id"]

        updated = client.put(
            f"/api/reviews/{payload['id']}",
            json={
                "market_phase": "趋势启动",
                "is_system_compliant": True,
                "mistake_tags": ["追价"],
                "setup_tags": ["带量突破试单"],
                "execution_note": "按下一根K线撮合记录复盘",
                "improvement_note": "突破有效但需要继续观察回踩质量",
                "screenshot_path": "data/review/screenshots/rb-note.png",
            },
        )
        assert updated.status_code == 200
        assert updated.json()["market_phase"] == "趋势启动"
        assert updated.json()["is_system_compliant"] is True
        assert updated.json()["setup_tags"] == ["带量突破试单"]
        assert updated.json()["rule_tags"] == ["带量突破试单"]
        assert updated.json()["execution_note"] == "按下一根K线撮合记录复盘"
        assert updated.json()["improvement_note"].startswith("突破有效")
        assert updated.json()["screenshot_path"] == "data/review/screenshots/rb-note.png"

        attachment = client.post(
            f"/api/reviews/{payload['id']}/attachments",
            json={"file_path": "data/review/screenshots/rb-test.png", "file_type": "image", "title": "rb test"},
        )
        assert attachment.status_code == 200

        stats = client.get("/api/reviews/stats")
        assert stats.status_code == 200
        assert stats.json()["total_reviews"] == 1
        assert any(item["name"] == "追价" for item in stats.json()["mistake_tags"])
        assert any(item["name"] == "带量突破试单" for item in stats.json()["rule_effectiveness"])

        tags = client.get("/api/reviews/tags")
        assert tags.status_code == 200
        mistake_names = {item["name"] for item in tags.json() if item["tag_type"] == "mistake"}
        assert {"追价", "震荡区", "逆势", "过早进场", "过早止损", "未按系统执行"} <= mistake_names

        paper = client.get("/api/reviews/sources/paper-trades")
        assert paper.status_code == 200
        assert paper.json() == []
    finally:
        app.dependency_overrides.clear()


def test_list_reviews_filters_exact_source_type_and_source_id() -> None:
    TestingSessionLocal = _setup_review_data()
    with TestingSessionLocal() as session:
        session.add_all(
            [
                ReviewNote(source_type="signal_event", source_id=7, symbol="jm", mistake_tags=[], rule_tags=[], emotion_tags=[], screenshot_paths=[], extra={}),
                ReviewNote(source_type="signal_event", source_id=8, symbol="jm", mistake_tags=[], rule_tags=[], emotion_tags=[], screenshot_paths=[], extra={}),
                ReviewNote(source_type="strategy_signal", source_id=7, symbol="jm", mistake_tags=[], rule_tags=[], emotion_tags=[], screenshot_paths=[], extra={}),
            ]
        )
        session.commit()

    def override_get_db():
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = TestClient(app).get(
            "/api/reviews",
            params={"source_type": "signal_event", "source_id": 7},
        )
        assert response.status_code == 200
        assert [(item["source_type"], item["source_id"]) for item in response.json()] == [("signal_event", 7)]

        paged = TestClient(app).get(
            "/api/reviews",
            params={"paged": "true", "source_type": "signal_event", "limit": 1, "offset": 1},
        )
        assert paged.status_code == 200
        assert paged.json()["total"] == 2
        assert len(paged.json()["items"]) == 1
    finally:
        app.dependency_overrides.clear()
