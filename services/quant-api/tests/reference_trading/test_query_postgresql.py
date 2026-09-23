"""Disposable PostgreSQL proof for persisted historical reads."""

from datetime import date
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.orm import sessionmaker

from app.reference_trading.presentation import envelope, presentation_point
from app.reference_trading.query import HistoricalReferenceQuery
from tests.alembic.conftest import isolated_postgres_engine  # noqa: F401
from tests.reference_trading.test_repository import _digest, _open_batch
from tests.reference_trading.test_repository_postgresql import (  # noqa: F401
    _seed, reference_postgresql,
)


pytestmark = pytest.mark.isolated_postgresql


def test_postgresql_query_keeps_decimal_and_initial_trade(reference_postgresql, monkeypatch):  # noqa: F811
    repository, stream, revision, manifest, seed = _seed(reference_postgresql)
    evidence = {"presentation_v1": envelope([
        presentation_point(
            kind="trade_identity", trading_day=date(2026, 9, 19),
            formula_versions=("v1",),
            value={"source_action_id": "build-1", "public_trade_id": "public-one"},
        ),
        presentation_point(
            kind="signal", trading_day=date(2026, 9, 19),
            formula_versions=("v1",),
            value={"bar_end": datetime(2026, 9, 19, 7, tzinfo=UTC)},
        ),
    ])}
    repository.commit_batch(seed, _open_batch(stream, revision, manifest, seed, evidence=evidence))
    token, _ = repository.load_checkpoint(stream.stream_id, revision)
    repository.publish_revision(stream.stream_id, revision, token.row_version, _digest(manifest))
    monkeypatch.setattr(HistoricalReferenceQuery, "_registered", staticmethod(lambda _row: True))
    query = HistoricalReferenceQuery(sessionmaker(reference_postgresql, expire_on_commit=False))
    page = query.trades(
        stream.stream_id, since=date(2026, 9, 20), through=date(2026, 9, 20),
    )
    assert len(page["items"]) == 1
    assert page["items"][0]["public_reference_trade_id"] == "public-one"
    assert Decimal(page["items"][0]["entry_reference_price"]) == Decimal("3500.123456789")
    summary = query.summary(
        stream.stream_id, since=date(2026, 9, 20), through=date(2026, 9, 20),
        snapshot_token=page["snapshot"],
    )
    assert summary["initial_count"] == 1
    points = query.signals(
        stream.stream_id, since=date(2026, 9, 19), through=date(2026, 9, 19),
        point_kind="signal",
    )
    assert len(points["items"]) == 1
