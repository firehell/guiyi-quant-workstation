from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.review import ReviewAttachment, ReviewNote


def _setup_review_data():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    return TestingSessionLocal


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


def test_retired_review_sources_are_hidden_and_rejected_without_writes() -> None:
    TestingSessionLocal = _setup_review_data()
    now = datetime.now(UTC)
    supported_source_types = (
        "strategy_signal",
        "signal_event",
        "manual_trade",
    )
    with TestingSessionLocal() as session:
        session.add_all(
            [
                ReviewNote(
                    source_type=source_type,
                    source_id=index,
                    symbol="jm",
                    lesson=None,
                    mistake_tags=[],
                    rule_tags=[],
                    emotion_tags=[],
                    screenshot_paths=[],
                    extra={},
                    updated_at=now + timedelta(seconds=index),
                )
                for index, source_type in enumerate(supported_source_types, start=1)
            ]
        )
        retired = ReviewNote(
            source_type="backtest_trade",
            source_id=99,
            symbol="jm",
            lesson=None,
            mistake_tags=["legacy"],
            rule_tags=["legacy-rule"],
            emotion_tags=[],
            screenshot_paths=[],
            extra={},
            updated_at=now + timedelta(days=1),
        )
        session.add(retired)
        session.commit()
        retired_id = retired.id

    def override_get_db():
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        listing = client.get("/api/reviews")
        assert listing.status_code == 200
        assert {item["source_type"] for item in listing.json()} == set(supported_source_types)

        paged = client.get("/api/reviews", params={"paged": "true"})
        assert paged.status_code == 200
        assert paged.json()["total"] == len(supported_source_types)
        assert {item["source_type"] for item in paged.json()["items"]} == set(supported_source_types)

        assert client.get("/api/reviews", params={"source_type": "backtest_trade"}).status_code == 404
        assert client.get("/api/reviews", params={"source_type": ""}).status_code == 404
        assert client.get(f"/api/reviews/{retired_id}").status_code == 404
        assert client.put(f"/api/reviews/{retired_id}", json={"lesson": "must not persist"}).status_code == 404
        assert client.get(f"/api/reviews/{retired_id}/bars").status_code == 404
        assert client.post(
            f"/api/reviews/{retired_id}/attachments",
            json={"file_path": "/tmp/retired.png"},
        ).status_code == 404
        assert client.get("/api/reviews/lineage/backtest_trade/99").status_code == 404

        stats = client.get("/api/reviews/stats")
        assert stats.status_code == 200
        assert stats.json()["total_reviews"] == len(supported_source_types)
        assert stats.json()["mistake_tags"] == []

        dashboard = client.get("/api/dashboard/summary")
        assert dashboard.status_code == 200
        assert dashboard.json()["latest_review"]["source_type"] == "manual_trade"
        assert dashboard.json()["unfinished_review_count"] == len(supported_source_types)

        for source_type in supported_source_types:
            response = client.get("/api/reviews", params={"source_type": source_type})
            assert response.status_code == 200
            assert [item["source_type"] for item in response.json()] == [source_type]
    finally:
        app.dependency_overrides.clear()

    with TestingSessionLocal() as session:
        retired = session.get(ReviewNote, retired_id)
        assert retired is not None
        assert retired.lesson is None
        assert retired.screenshot_paths == []
        assert session.scalar(select(func.count()).select_from(ReviewAttachment)) == 0
