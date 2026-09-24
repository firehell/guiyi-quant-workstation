"""P9 source planning keeps one frozen window and independent bounded outcomes."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
import runpy
from types import SimpleNamespace

import pytest

from app.market_data.newow.product_release import OPEN_WEEKLY_PRODUCTS
from app.market_data.operational_universe import load_active_products, load_operational_products


_module = runpy.run_path(str(
    Path(__file__).resolve().parents[2] / "scripts/reference_trading_p9_source_plan.py"
))
_formal_requests = _module["_formal_requests"]
plan_batch = _module["plan_batch"]
enumerate_scope = _module["enumerate_scope"]


def _rb_requests():
    scope = enumerate_scope(
        load_active_products(), load_operational_products(), tuple(OPEN_WEEKLY_PRODUCTS), {},
    )
    return _formal_requests(
        scope["streams"], ("RB",), date(2023, 1, 1), date(2026, 9, 23),
        datetime(2026, 9, 24, 8, tzinfo=timezone.utc),
    )


def test_rb_batch_has_exact_ten_formal_historical_streams_and_shared_window():
    requests = _rb_requests()
    assert len(requests) == 10
    assert len({item.identity.stream_id for item in requests}) == 10
    assert all(item.since == date(2023, 1, 1) for item in requests)
    assert all(item.through == date(2026, 9, 23) for item in requests)
    assert all(item.as_of == datetime(2026, 9, 24, 8, tzinfo=timezone.utc) for item in requests)
    assert {item.identity.frequency for item in requests} == {"1d", "1w", "15m", "30m", "60m"}


def test_batch_reports_ready_and_blocked_without_shortening_other_streams():
    requests = _rb_requests()[:3]
    seen = []

    class Planner:
        def plan(self, request):
            stream = request.streams[0]
            seen.append(stream)
            if len(seen) == 2:
                raise ValueError("REFERENCE_INPUT_INCOMPLETE")
            return SimpleNamespace(
                plan_hash=f"hash-{len(seen)}",
                streams=(SimpleNamespace(
                    input_count=100, input_bytes=1000,
                    dependency_digest="source-digest", source_token="token",
                    storage_start=stream.since,
                    target_completed_through=stream.as_of,
                ),),
            )

    @contextmanager
    def planner_context():
        yield Planner()

    report = plan_batch(
        requests, operation="advance", max_streams=3,
        max_total_bars=250, max_total_bytes=2500, max_total_seconds=300,
        max_stream_bars=100, max_stream_bytes=1000, max_stream_seconds=100,
        planner_context=planner_context, clock=lambda: 0,
    )

    assert [item["status"] for item in report["results"]] == ["SOURCE_READY", "BLOCKED", "SOURCE_READY"]
    assert report["results"][1]["reason"] == "REFERENCE_INPUT_INCOMPLETE"
    assert report["counts"] == {"selected": 3, "source_ready": 2, "blocked": 1}
    assert all(item["execution_gate"] == "UNVERIFIED" for item in report["results"])
    assert report["used_input_bars"] == 200
    assert report["used_input_bytes"] == 2000
    assert seen == list(requests)


def test_batch_total_budget_blocks_remaining_stream_without_planner_call():
    requests = _rb_requests()[:2]
    calls = []

    class Planner:
        def plan(self, request):
            calls.append(request)
            stream = request.streams[0]
            return SimpleNamespace(
                plan_hash="plan", streams=(SimpleNamespace(
                    input_count=100, input_bytes=1000, dependency_digest="source",
                    source_token="token", storage_start=stream.since,
                    target_completed_through=stream.as_of,
                ),),
            )

    @contextmanager
    def planner_context():
        yield Planner()

    report = plan_batch(
        requests, operation="build", max_streams=2,
        max_total_bars=100, max_total_bytes=1000, max_total_seconds=300,
        max_stream_bars=100, max_stream_bytes=1000, max_stream_seconds=100,
        planner_context=planner_context, clock=lambda: 0,
    )

    assert len(calls) == 1
    assert report["results"][1]["reason"] == "P9_TOTAL_BUDGET_EXCEEDED"
    assert report["counts"] == {"selected": 2, "source_ready": 1, "blocked": 1}


def test_batch_redacts_untyped_reader_error_and_continues():
    requests = _rb_requests()[:2]
    calls = 0

    class Planner:
        def plan(self, request):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise ValueError("/private/secret/catalog failure")
            stream = request.streams[0]
            return SimpleNamespace(
                plan_hash="plan", streams=(SimpleNamespace(
                    input_count=1, input_bytes=1, dependency_digest="source",
                    source_token="token", storage_start=stream.since,
                    target_completed_through=stream.as_of,
                ),),
            )

    @contextmanager
    def planner_context():
        yield Planner()

    report = plan_batch(
        requests, operation="build", max_streams=2,
        max_total_bars=10, max_total_bytes=10, max_total_seconds=300,
        max_stream_bars=10, max_stream_bytes=10, max_stream_seconds=100,
        planner_context=planner_context, clock=lambda: 0,
    )

    assert [item["status"] for item in report["results"]] == ["BLOCKED", "SOURCE_READY"]
    assert report["results"][0]["reason"] == "P9_SOURCE_BLOCKED"
    assert "/private/secret" not in str(report)


def test_batch_database_identity_drift_aborts_instead_of_blocking_stream():
    requests = _rb_requests()[:2]

    @contextmanager
    def planner_context():
        raise ValueError("P9_DATABASE_IDENTITY_MISMATCH")
        yield  # pragma: no cover

    with pytest.raises(ValueError, match="P9_DATABASE_IDENTITY_MISMATCH"):
        plan_batch(
            requests, operation="build", max_streams=2,
            max_total_bars=10, max_total_bytes=10, max_total_seconds=300,
            max_stream_bars=10, max_stream_bytes=10, max_stream_seconds=100,
            planner_context=planner_context, clock=lambda: 0,
        )
