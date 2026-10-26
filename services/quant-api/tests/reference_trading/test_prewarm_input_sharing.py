"""Prewarm shares raw inputs per scheduler key, never per-strategy computation."""
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.reference_trading import worker_entry
from app.reference_trading.input_cache import NewowInputCache
from app.reference_trading.runtime import ForwardReferenceWorker
from guiyi_quant.newow.product_identity import InputQualityPolicy


def _warmup(monkeypatch, *, failure=None):
    now = datetime(2026, 10, 27, tzinfo=UTC)
    clock = [0.0]
    monkeypatch.setattr(worker_entry, "monotonic", lambda: clock[0])
    cache, events, reads, evaluated, contexts, checkpoints, pages = NewowInputCache(), [], [], [], [], [], []
    groups = {f"newow:{product}:1d": tuple(f"{product}:{strategy}" for strategy in (
        "trend", "oscillation", "main_rise", "fusion")) for product in ("rb", "cu")}
    keys = tuple(groups)
    def enabled_keys(*, limit, after):
        pages.append((limit, after))
        return (keys[0],) if after is None else (keys[1],) if after == keys[0] else ()
    def context(route):
        contexts.append(route)
        return (SimpleNamespace(frequency="1d"),)
    def checkpoint(route):
        checkpoints.append(route)
        return "token-"+route, "checkpoint-"+route
    repo = SimpleNamespace(enabled_forward_work_keys=enabled_keys,
        enabled_forward_work_routes=lambda key: groups[key],
        enabled_forward_stream_ids=lambda **kwargs: tuple(route for routes in groups.values() for route in routes)
            if kwargs.get("after") is None else (),
        read_pending_capture=lambda _: None, forward_source_context=context, load_checkpoint=checkpoint)
    identity = SimpleNamespace(futures_adaptation_version="adaptation", frequency="1d")
    def read(route, *_):
        if route.endswith(":fusion"):
            return SimpleNamespace(evidence=lambda: {"fusion": route})
        def incremental(**kwargs):
            reads.append(kwargs)
            if failure == "reader":
                raise RuntimeError("EXPECTED_INPUT_FAILURE")
            return object()
        reader = cache.canonical_reader(SimpleNamespace(_input_quality_policy=InputQualityPolicy.DAILY_V2,
            forward_incremental_bar=incremental), identity)
        value = reader.forward_incremental_bar(product=route.split(":")[0], frequency="1d",
            after=now-timedelta(days=1), as_of=now)
        if failure == "timeout":
            clock[0] = 120.0
        return SimpleNamespace(evidence=lambda: {"market": value})
    def service(route):
        def evaluate(token, checkpoint, evidence):
            evaluated.append((route, token, checkpoint, evidence))
            if failure == "evaluator":
                raise RuntimeError("EXPECTED_EVALUATOR_FAILURE")
        return SimpleNamespace(_evaluator=evaluate)
    def begin():
        events.append("begin")
        cache.begin(now)
    def end():
        events.append("end")
        cache.end()
    worker = ForwardReferenceWorker(repo, service, read, enabled=True, begin_unit=begin, end_unit=end)
    worker.scan_live = False
    @contextmanager
    def opened(**kwargs):
        assert kwargs == {"warmup": True, "warmup_deadline": 120.0}
        yield worker, None, None
    monkeypatch.setattr(worker_entry, "open_forward_worker", opened)
    return cache, events, reads, evaluated, contexts, checkpoints, pages, groups


def test_grouped_prewarm_reads_once_per_product_but_evaluates_every_strategy(monkeypatch):
    cache, events, reads, evaluated, contexts, checkpoints, pages, groups = _warmup(monkeypatch)
    assert worker_entry.warmup_reference_worker() == {"calculated": 8}
    routes = tuple(route for group in groups.values() for route in group)
    assert tuple(row[0] for row in evaluated) == routes  # Fusion stays last in each group.
    assert tuple(contexts) == tuple(checkpoints) == routes
    assert events == ["begin", "end", "begin", "end"]
    assert pages == [(512, None), (512, "newow:rb:1d"), (512, "newow:cu:1d")]
    assert len(reads) == 2
    assert evaluated[0][3]["market"] is evaluated[1][3]["market"] is evaluated[2][3]["market"]
    assert cache.observed_at is None and cache._values == {}


@pytest.mark.parametrize("failure,code", (("evaluator", "EXPECTED_EVALUATOR_FAILURE"), ("reader", "EXPECTED_INPUT_FAILURE"), ("timeout", "REFERENCE_WARMUP_TIMEOUT")))
def test_prewarm_error_or_shared_deadline_always_ends_input_unit(monkeypatch, failure, code):
    cache, events, reads, evaluated, *_ = _warmup(monkeypatch, failure=failure)
    with pytest.raises(RuntimeError, match=code):
        worker_entry.warmup_reference_worker()
    assert events == ["begin", "end"]
    assert len(reads) == 1
    assert len(evaluated) == (0 if failure == "reader" else 1)
    assert cache.observed_at is None and cache._values == {}
