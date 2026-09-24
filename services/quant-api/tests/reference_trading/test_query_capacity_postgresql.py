"""Disposable synthetic row-count workload for the persisted query path.

The rows exercise SQL pagination/summary cost. They are deliberately not
strategy output and must never count as calculation or product evidence.
"""

from __future__ import annotations

from datetime import date, timedelta
import json
import os
from time import perf_counter

import pytest
from sqlalchemy import insert, select
from sqlalchemy.orm import sessionmaker

from app.reference_trading.models import ReferenceTradeRow
from app.reference_trading.presentation import envelope, presentation_point
from app.reference_trading.query import HistoricalReferenceQuery
from tests.alembic.conftest import isolated_postgres_engine  # noqa: F401
from tests.reference_trading.test_repository import AT, _digest, _open_batch
from tests.reference_trading.test_repository_postgresql import (  # noqa: F401
    _seed, reference_postgresql,
)


pytestmark = pytest.mark.isolated_postgresql


@pytest.mark.parametrize("count", [100, 1000, 10000])
def test_postgresql_query_capacity_at_fixed_row_count(
    reference_postgresql, monkeypatch, count,  # noqa: F811
):
    repository, stream, revision, manifest, seed = _seed(reference_postgresql)
    evidence = {"presentation_v1": envelope([presentation_point(
        kind="trade_identity", trading_day=date(2026, 9, 19),
        formula_versions=("v1",),
        value={"source_action_id": "build-1", "public_trade_id": "fixture-public-id"},
    )])}
    repository.commit_batch(
        seed, _open_batch(stream, revision, manifest, seed, evidence=evidence),
    )
    token, _ = repository.load_checkpoint(stream.stream_id, revision)
    repository.publish_revision(stream.stream_id, revision, token.row_version, _digest(manifest))
    factory = sessionmaker(reference_postgresql, expire_on_commit=False)
    with factory.begin() as session:
        original = session.scalar(select(ReferenceTradeRow).where(
            ReferenceTradeRow.stream_id == stream.stream_id,
        ))
        assert original is not None
        base = {
            column.name: getattr(original, column.name)
            for column in ReferenceTradeRow.__table__.columns
        }
        rows = []
        for index in range(count):
            end = AT + timedelta(seconds=index + 1)
            rows.append({
                **base,
                "trade_id": f"synthetic-interrupted-{index:05}",
                "status": "DATA_INTERRUPTED",
                "entry_bar_end": end,
                "effective_bar_end": end,
            })
        session.execute(insert(ReferenceTradeRow), rows)
    monkeypatch.setattr(HistoricalReferenceQuery, "_registered", staticmethod(lambda _row: True))
    query = HistoricalReferenceQuery(factory)
    params = dict(since=date(2026, 9, 19), through=date(2026, 9, 19), limit=50)
    first = query.trades(stream.stream_id, **params)
    assert len(first["items"]) == 50
    assert first["next_cursor"]
    snapshot = first["snapshot"]
    page = first
    deep_cursor = None
    pages = 1
    while page["next_cursor"] is not None:
        cursor_for_page = page["next_cursor"]
        page = query.trades(
            stream.stream_id, **params, cursor=cursor_for_page, snapshot_token=snapshot,
        )
        if len(page["items"]) == 50:
            deep_cursor = cursor_for_page
        pages += 1
    assert pages == (count + 1 + 49) // 50
    assert page["items"] and page["next_cursor"] is None
    assert deep_cursor is not None
    assert len(query.trades(
        stream.stream_id, **params, cursor=deep_cursor, snapshot_token=snapshot,
    )["items"]) == 50
    summary = query.summary(
        stream.stream_id, since=params["since"], through=params["through"],
        snapshot_token=snapshot,
    )
    assert summary["interrupted_count"] == count
    assert summary["open_count"] == 1
    if os.getenv("GUIYI_P8_BENCH_QUERY") == "1":
        durations: dict[str, list[float]] = {
            "first_page": [], "deep_page": [], "summary": [],
        }
        for _ in range(100):
            started = perf_counter()
            query.trades(stream.stream_id, **params, snapshot_token=snapshot)
            durations["first_page"].append((perf_counter() - started) * 1000)
            started = perf_counter()
            query.trades(
                stream.stream_id, **params, cursor=deep_cursor,
                snapshot_token=snapshot,
            )
            durations["deep_page"].append((perf_counter() - started) * 1000)
            started = perf_counter()
            query.summary(
                stream.stream_id, since=params["since"], through=params["through"],
                snapshot_token=snapshot,
            )
            durations["summary"].append((perf_counter() - started) * 1000)
        metrics = {
            key: {"n": len(value), "p50_ms": round(sorted(value)[49], 3),
                  "p95_ms": round(sorted(value)[94], 3)}
            for key, value in durations.items()
        }
        metrics["row_counts"] = {"trade_versions": count + 1, "pages": pages}
        print("P8_QUERY_METRIC=" + json.dumps(metrics, sort_keys=True))
