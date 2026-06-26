from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.backtest import BacktestReportModel, BacktestTask, BacktestTradeModel


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

        created = client.post(f"/api/reviews/from-backtest-trade/{trade_id}")
        assert created.status_code == 200
        payload = created.json()
        assert payload["symbol"] == "rb"
        assert payload["period"] == "5m"
        assert payload["review_object_type"] == "backtest_trade"
        assert payload["entry_reason"].startswith("EMA21")
        assert "EMA21方向过滤" in payload["rule_tags"]
        assert "EMA21方向过滤" in payload["setup_tags"]

        duplicate = client.post(f"/api/reviews/from-backtest-trade/{trade_id}")
        assert duplicate.status_code == 200
        assert duplicate.json()["id"] == payload["id"]

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
