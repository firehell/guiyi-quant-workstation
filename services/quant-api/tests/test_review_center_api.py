from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.review import ReviewNote


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
