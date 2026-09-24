from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import json
import os
from time import perf_counter

import pytest
from sqlalchemy import event, text

from app.reference_trading.query import HistoricalReferenceQuery, QueryConflict

from app.reference_trading.planning import HistoricalReferencePlanner, HistoricalReferenceRequest
from app.reference_trading.planning import HistoricalStreamRequest, WorkBudget
from app.reference_trading.service import HistoricalReferenceService
from app.reference_trading.service import ServiceInterrupted
from tests.alembic.conftest import isolated_postgres_engine  # noqa: F401
from tests.reference_trading.test_bootstrap import Reader, _plan, _repository
from tests.reference_trading.test_repository_postgresql import reference_postgresql  # noqa: F401


def _reference_relation_bytes(engine) -> dict[str, dict[str, int]]:
    schema = engine.get_execution_options()["schema_translate_map"][None]
    result = {}
    with engine.connect() as connection:
        for table in ("reference_trades", "reference_actions", "reference_marks", "reference_batches"):
            relation = f"{schema}.{table}"
            table_bytes, index_bytes = connection.execute(text(
                "SELECT pg_table_size(to_regclass(:relation)), "
                "pg_indexes_size(to_regclass(:relation))"
            ), {"relation": relation}).one()
            result[table] = {"table_bytes": table_bytes, "index_bytes": index_bytes}
    return result


def _reference_query_plan(engine, invoke) -> dict[str, object]:
    captured = []

    def on_execute(_connection, _cursor, statement, parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT") and "reference_trades" in statement:
            captured.append((statement, parameters))

    event.listen(engine, "before_cursor_execute", on_execute)
    try:
        invoke()
    finally:
        event.remove(engine, "before_cursor_execute", on_execute)
    assert captured
    statement, parameters = captured[-1]
    with engine.connect() as connection:
        raw = connection.exec_driver_sql(
            "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + statement, parameters,
        ).scalar_one()
    plan = (json.loads(raw) if isinstance(raw, str) else raw)[0]
    scans = []

    def buffers(node):
        return {
            name: node.get(name, 0)
            for name in (
                "Shared Hit Blocks", "Shared Read Blocks", "Shared Dirtied Blocks",
                "Shared Written Blocks", "Local Hit Blocks", "Local Read Blocks",
                "Temp Read Blocks", "Temp Written Blocks",
            )
        }

    def walk(node):
        if "Scan" in node["Node Type"]:
            scans.append({
                "node": node["Node Type"], "index": node.get("Index Name"),
                "relation": node.get("Relation Name"),
                "rows": node["Actual Rows"], "loops": node["Actual Loops"],
                "removed": node.get("Rows Removed by Filter", 0),
                "index_cond": node.get("Index Cond"),
                "buffers": buffers(node),
            })
        for child in node.get("Plans", ()):
            walk(child)

    walk(plan["Plan"])
    return {
        "execution_ms": round(plan["Execution Time"], 3),
        "buffers": buffers(plan["Plan"]), "scans": scans,
    }


def test_rebuild_invalidates_changed_active_and_publishes_complete_new_revision() -> None:
    reader = Reader()
    repository = _repository()
    initial = _plan(reader, batch_size=9)
    first = HistoricalReferenceService(repository, reader).execute(initial, initial.plan_hash)
    old_revision = first.streams[0].active_revision_id
    assert old_revision is not None
    reader.bars = Reader(prices=[100] * 50 + [120, 80, 120, 120]).bars
    reader.token = "source-revised"
    original = reader._snapshot

    def revised(req):
        result = original(req)
        manifest = {**result.dependency_manifest}
        manifest["partitions"] = [{"key": "RB2605", "sha256": "e" * 64}]
        return replace(result, dependency_manifest=manifest)

    reader._snapshot = revised
    requested = HistoricalReferenceRequest(
        "rebuild", (initial.streams[0].request,), initial.budget, initial.batch_size,
    )
    plan = HistoricalReferencePlanner(
        reader, now=lambda: initial.streams[0].request.as_of,
    ).plan(requested)

    result = HistoricalReferenceService(repository, reader).rebuild(plan, plan.plan_hash)

    assert result.status == "completed"
    assert result.streams[0].active_revision_id != old_revision
    assert repository.read_state(
        initial.streams[0].request.identity.stream_id, old_revision,
    ).revision_status == "invalid"
    assert repository.read_state(
        initial.streams[0].request.identity.stream_id,
    ).revision_status == "active"


def test_interrupted_rebuild_resumes_its_existing_candidate() -> None:
    reader = Reader()
    repository = _repository()
    initial = _plan(reader, batch_size=9)
    HistoricalReferenceService(repository, reader).execute(initial, initial.plan_hash)
    requested = HistoricalReferenceRequest(
        "rebuild", (initial.streams[0].request,), initial.budget, 10,
    )
    plan = HistoricalReferencePlanner(
        reader, now=lambda: initial.streams[0].request.as_of,
    ).plan(requested)

    def stop(_stage, _context):
        raise ServiceInterrupted("stop")

    partial = HistoricalReferenceService(
        repository, reader, after_batch=stop,
    ).rebuild(plan, plan.plan_hash)
    token = partial.streams[0].resume_token
    assert partial.status == "partial"
    assert token is not None

    resumed = HistoricalReferenceService(repository, reader).resume(
        plan, token, plan.plan_hash,
    )

    assert resumed.status == "completed"
    assert resumed.streams[0].candidate_revision_id == token.revision_id


@pytest.mark.isolated_postgresql
def test_postgresql_rebuild_rejects_old_snapshot_and_reads_new_revision(
    reference_postgresql,  # noqa: F811
) -> None:
    from sqlalchemy.orm import sessionmaker

    from app.reference_trading.repository import ReferenceRepository

    reader = Reader()
    factory = sessionmaker(reference_postgresql, expire_on_commit=False)
    repository = ReferenceRepository(factory)
    initial = _plan(reader, batch_size=9)
    first = HistoricalReferenceService(repository, reader).execute(initial, initial.plan_hash)
    assert first.status == "completed"
    stream_id = initial.streams[0].request.identity.stream_id
    params = {
        "since": reader.bars[0].trading_day,
        "through": reader.bars[-1].trading_day,
    }
    query = HistoricalReferenceQuery(factory)
    old = query.trades(stream_id, **params)
    old_summary = query.summary(stream_id, snapshot_token=old["snapshot"], **params)

    reader.bars = Reader(prices=[100] * 50 + [120, 80, 120, 120]).bars
    reader.token = "source-revised"
    original = reader._snapshot

    def revised(request):
        result = original(request)
        return replace(result, dependency_manifest={
            **result.dependency_manifest,
            "partitions": [{"key": "RB2605", "sha256": "e" * 64}],
        })

    reader._snapshot = revised
    requested = HistoricalReferenceRequest(
        "rebuild", (initial.streams[0].request,), initial.budget, initial.batch_size,
    )
    plan = HistoricalReferencePlanner(
        reader, now=lambda: initial.streams[0].request.as_of,
    ).plan(requested)
    rebuilt = HistoricalReferenceService(repository, reader).rebuild(plan, plan.plan_hash)
    assert rebuilt.status == "completed"
    current = query.trades(stream_id, **params)
    current_summary = query.summary(stream_id, snapshot_token=current["snapshot"], **params)
    assert current["revision_id"] != old["revision_id"]
    assert current["items"] != old["items"]
    assert current_summary["sum_return_percentage_points"] != old_summary["sum_return_percentage_points"]
    with pytest.raises(QueryConflict, match="SNAPSHOT_INVALIDATED"):
        query.trades(stream_id, snapshot_token=old["snapshot"], **params)


@pytest.mark.isolated_postgresql
@pytest.mark.parametrize("count", [1000, 10000])
def test_postgresql_long_history_price_rebuild_keeps_past_cutoff(
    reference_postgresql, count: int,  # noqa: F811
) -> None:
    from sqlalchemy.orm import sessionmaker

    from app.reference_trading.repository import ReferenceRepository
    from tests.reference_trading.test_bootstrap import _stream

    prices = [100] * 50 + [120, 80] * ((count - 50) // 2)
    reader = Reader(prices=prices, at=datetime(1990, 1, 1, 15, tzinfo=UTC))
    stream = _stream()
    as_of = reader.bars[-1].bar_end.replace(microsecond=1)
    stream_request = HistoricalStreamRequest(
        stream, reader.bars[0].trading_day, reader.bars[-1].trading_day, as_of,
    )
    budget = WorkBudget(1, count, 120, 4_000_000)
    planner = HistoricalReferencePlanner(reader, now=lambda: as_of)
    build_request = HistoricalReferenceRequest("build", (stream_request,), budget, 128)
    build_plan = planner.plan(build_request)
    factory = sessionmaker(reference_postgresql, expire_on_commit=False)
    repository = ReferenceRepository(factory)
    started = perf_counter()
    built = HistoricalReferenceService(repository, reader).execute(build_plan, build_plan.plan_hash)
    build_seconds = perf_counter() - started
    assert built.status == "completed"
    index_probe = count == 10000 and os.getenv("GUIYI_P8_BENCH_INDEX") == "1"
    built_bytes = _reference_relation_bytes(reference_postgresql) if index_probe else None
    query = HistoricalReferenceQuery(factory)
    window = {"since": reader.bars[0].trading_day, "through": reader.bars[-1].trading_day}
    cutoff = reader.bars[499].bar_end
    old_full = query.trades(stream.stream_id, **window)
    old_summary = query.summary(stream.stream_id, snapshot_token=old_full["snapshot"], **window)
    old_prefix = query.trades(stream.stream_id, cutoff=cutoff, **window)
    old_prefix_summary = query.summary(
        stream.stream_id, cutoff=cutoff, snapshot_token=old_prefix["snapshot"], **window,
    )

    revised_prices = [*prices]
    revised_prices[-1] = 120
    reader.bars = Reader(prices=revised_prices, at=datetime(1990, 1, 1, 15, tzinfo=UTC)).bars
    reader.token = "source-revised-tail-price"
    original_snapshot = reader._snapshot

    def revised(request):
        result = original_snapshot(request)
        return replace(result, dependency_manifest={
            **result.dependency_manifest,
            "partitions": [{"key": "RB2605", "sha256": "e" * 64}],
        })

    reader._snapshot = revised
    rebuild_request = HistoricalReferenceRequest("rebuild", (stream_request,), budget, 128)
    rebuild_plan = planner.plan(rebuild_request)
    started = perf_counter()
    rebuilt = HistoricalReferenceService(repository, reader).rebuild(
        rebuild_plan, rebuild_plan.plan_hash,
    )
    rebuild_seconds = perf_counter() - started
    assert rebuilt.status == "completed"
    rebuilt_bytes = _reference_relation_bytes(reference_postgresql) if index_probe else None
    first_use_started = perf_counter()
    current_full = query.trades(stream.stream_id, **window)
    first_page_ms = round((perf_counter() - first_use_started) * 1000, 3)
    first_use_started = perf_counter()
    current_summary = query.summary(
        stream.stream_id, snapshot_token=current_full["snapshot"], **window,
    )
    first_summary_ms = round((perf_counter() - first_use_started) * 1000, 3)
    current_prefix = query.trades(stream.stream_id, cutoff=cutoff, **window)
    current_prefix_summary = query.summary(
        stream.stream_id, cutoff=cutoff, snapshot_token=current_prefix["snapshot"], **window,
    )
    assert current_full["revision_id"] != old_full["revision_id"]
    assert current_full["items"] != old_full["items"]
    assert current_summary["sum_return_percentage_points"] != old_summary["sum_return_percentage_points"]
    assert current_prefix["items"] == old_prefix["items"]
    assert current_prefix_summary["sum_return_percentage_points"] == old_prefix_summary["sum_return_percentage_points"]
    with pytest.raises(QueryConflict, match="SNAPSHOT_INVALIDATED"):
        query.trades(stream.stream_id, snapshot_token=old_prefix["snapshot"], cutoff=cutoff, **window)
    print(f"P8_LONG_REBUILD bars={count} build_s={build_seconds:.3f} rebuild_s={rebuild_seconds:.3f}")
    if count == 10000 and os.getenv("GUIYI_P8_BENCH_QUERY") == "1":
        page_params = {**window, "limit": 50, "snapshot_token": current_full["snapshot"]}
        deep = current_full
        for _ in range(100):
            assert deep["next_cursor"] is not None
            cursor = deep["next_cursor"]
            deep = query.trades(stream.stream_id, cursor=cursor, **page_params)
        assert len(deep["items"]) == 50
        timings: dict[str, list[float]] = {"first_page": [], "deep_page": [], "summary": []}
        for _ in range(100):
            started = perf_counter()
            query.trades(stream.stream_id, **page_params)
            timings["first_page"].append((perf_counter() - started) * 1000)
            started = perf_counter()
            query.trades(stream.stream_id, cursor=cursor, **page_params)
            timings["deep_page"].append((perf_counter() - started) * 1000)
            started = perf_counter()
            query.summary(stream.stream_id, snapshot_token=current_full["snapshot"], **window)
            timings["summary"].append((perf_counter() - started) * 1000)
        metrics = {
            key: {
                "n": len(values), "p50_ms": round(sorted(values)[49], 3),
                "p95_ms": round(sorted(values)[94], 3),
            }
            for key, values in timings.items()
        }
        metrics["row_counts"] = {"bars": count, "closed_trades": current_summary["closed_count"]}
        assert metrics["first_page"]["p95_ms"] <= 500
        assert metrics["deep_page"]["p95_ms"] <= 500
        assert metrics["summary"]["p95_ms"] <= 1000
        print("P8_QUERY_METRIC=" + json.dumps(metrics, sort_keys=True), flush=True)
        if index_probe:
            plans = {
                "first_page": _reference_query_plan(
                    reference_postgresql,
                    lambda: query.trades(stream.stream_id, **page_params),
                ),
                "deep_page": _reference_query_plan(
                    reference_postgresql,
                    lambda: query.trades(stream.stream_id, cursor=cursor, **page_params),
                ),
                "summary": _reference_query_plan(
                    reference_postgresql,
                    lambda: query.summary(
                        stream.stream_id, snapshot_token=current_full["snapshot"], **window,
                    ),
                ),
            }
            print("P8_INDEX_METRIC=" + json.dumps({
                "first_use_ms": {"first_page": first_page_ms, "summary": first_summary_ms},
                "relation_bytes": {"built": built_bytes, "rebuilt": rebuilt_bytes},
                "plans": plans,
            }, sort_keys=True), flush=True)
