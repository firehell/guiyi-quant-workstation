"""Reproducible P4 backend stage baseline over the owned fake-MDS read seam."""

import json
import platform
import resource
import subprocess
import sys
from dataclasses import replace
from math import ceil
from time import perf_counter

from guiyi_quant.newow.product_adapters import build_product_identity, replay_strategy
from guiyi_quant.newow.reference_trades import ReferenceTradeProjector

from app.api.market_newow import _product_response
from app.market_data.newow.product_service import (
    NewowProductService,
    ProductServiceQuery,
)
from app.market_data.newow.snapshot_cache import SnapshotCache


def _p95(values):
    ordered = sorted(values)
    return ordered[max(0, ceil(len(ordered) * 0.95) - 1)]


def _run(service, request, repetitions):
    samples = []
    last = None
    for _ in range(repetitions):
        started = perf_counter()
        last = service.query(request)
        samples.append((perf_counter() - started) * 1000)
    assert last is not None
    return samples, last


def _measure(operation, repetitions=30):
    samples = []
    last = None
    for _ in range(repetitions):
        started = perf_counter()
        last = operation()
        samples.append((perf_counter() - started) * 1000)
    return samples, last


def test_p4_representative_cold_warm_and_pressure_baseline(product_cases):
    reader, query, fake = product_cases.paged_reader(prefix_bars=4001, frequency="60m")
    request = ProductServiceQuery(
        "rb",
        "trend",
        "60m",
        since=query.since,
        through=query.through,
        as_of=fake.as_of,
        chart_limit=500,
    )
    cold = NewowProductService(
        lambda _context, _cancelled: reader,
        cache=SnapshotCache(enabled=False),
        now=lambda: fake.as_of,
    )
    cold_samples, cold_result = _run(cold, request, 30)

    warm = NewowProductService(
        lambda _context, _cancelled: reader,
        cache=SnapshotCache(),
        now=lambda: fake.as_of,
    )
    warm.query(request)  # declared warm-up; excluded before the fixed 30 samples
    warm_samples, warm_result = _run(warm, request, 30)
    response_bytes = len(_product_response(warm_result).model_dump_json().encode())

    pressure_reader, pressure_query, pressure_fake = product_cases.paged_reader(
        prefix_bars=8001, frequency="60m"
    )
    pressure_service = NewowProductService(
        lambda _context, _cancelled: pressure_reader,
        cache=SnapshotCache(enabled=False),
        now=lambda: pressure_fake.as_of,
    )
    pressure_request = ProductServiceQuery(
        "rb",
        "trend",
        "60m",
        since=pressure_query.since,
        through=pressure_query.through,
        as_of=pressure_fake.as_of,
        chart_limit=500,
    )
    pressure_samples, _ = _run(pressure_service, pressure_request, 30)

    stage_reader, stage_query, stage_fake = product_cases.paged_reader(
        prefix_bars=601, frequency="60m"
    )
    read_samples, read_set = _measure(
        lambda: stage_reader.load(stage_query, stage_fake.as_of)
    )
    identity = build_product_identity("rb", "trend", "60m")
    replay_samples, replay = _measure(
        lambda: replay_strategy(identity, read_set.replay_bars)
    )
    projection_samples, _ = _measure(
        lambda: ReferenceTradeProjector().project(
            replay, read_set.boundaries, stage_fake.as_of
        )
    )
    serialization_samples, _ = _measure(
        lambda: _product_response(warm_result).model_dump_json()
    )

    reference_service = NewowProductService(
        lambda _context, _cancelled: stage_reader,
        cache=SnapshotCache(enabled=False),
        now=lambda: stage_fake.as_of,
    )
    reference_request = ProductServiceQuery(
        "rb",
        "trend",
        "60m",
        section="reference",
        performance_since=stage_query.performance_since,
        performance_through=stage_query.performance_through,
        as_of=stage_fake.as_of,
    )
    reference_samples, _ = _run(reference_service, reference_request, 30)

    comparator_service = NewowProductService(
        lambda _context, _cancelled: stage_reader,
        cache=SnapshotCache(enabled=False),
        now=lambda: stage_fake.as_of,
    )
    comparator_samples, _ = _run(
        comparator_service,
        ProductServiceQuery(
            "rb",
            "oscillation",
            "60m",
            section="comparator",
            as_of=stage_fake.as_of,
        ),
        30,
    )

    from newow.test_product_service import _Reader

    revision_case = product_cases.primitive_input("trend", "1d")
    revision_as_of = revision_case.bars[-1].bar.bar_end

    def revise_and_revalidate():
        revision_reader = _Reader(revision_case.bars, revision_as_of, revision_as_of)
        revision_service = NewowProductService(
            lambda _context, _cancelled: revision_reader,
            now=lambda: revision_as_of,
        )
        revision_request = ProductServiceQuery(
            "rb", "trend", "1d", as_of=revision_as_of
        )
        before = revision_service.query(revision_request)
        changed = revision_reader.bars[-1]
        revision_reader.bars = (
            *revision_reader.bars[:-1],
            replace(changed, bar=replace(changed.bar, volume=changed.bar.volume + 1)),
        )
        after = revision_service.query(revision_request)
        assert before.meta.input_content_sha256 != after.meta.input_content_sha256
        return after

    revision_samples, _ = _measure(revise_and_revalidate)

    code_identity = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    rss_native = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    rss_bytes = rss_native if sys.platform == "darwin" else rss_native * 1024
    report = {
        "machine": platform.platform(),
        "python": sys.version.split()[0],
        "code_identity": code_identity,
        "fixture": "owned_fake_mds_paged_reader",
        "frequency": "60m",
        "valid_and_warmup_bars": 4001,
        "owner_segments": 1,
        "query_window": [query.since.isoformat(), query.through.isoformat()],
        "input_content_sha256": cold_result.meta.input_content_sha256,
        "cold_repetitions": 30,
        "warm_repetitions": 30,
        "pressure_repetitions": 30,
        "warmup_excluded": 1,
        "cold_total_p95_ms": round(_p95(cold_samples), 3),
        "validated_cache_total_p95_ms": round(_p95(warm_samples), 3),
        "pressure_8001_total_p95_ms": round(_p95(pressure_samples), 3),
        "read_and_validate_601_p95_ms": round(_p95(read_samples), 3),
        "strategy_replay_601_p95_ms": round(_p95(replay_samples), 3),
        "reference_projection_601_p95_ms": round(_p95(projection_samples), 3),
        "reference_total_601_p95_ms": round(_p95(reference_samples), 3),
        "comparator_total_601_p95_ms": round(_p95(comparator_samples), 3),
        "revision_revalidate_90_p95_ms": round(_p95(revision_samples), 3),
        "serialization_p95_ms": round(_p95(serialization_samples), 3),
        "serialization_response_bytes": response_bytes,
        "rss_max_bytes": rss_bytes,
        "stage_note": "queue admission/cancellation are deterministic concurrency tests; fake-MDS read+validation, replay, projection, comparator and serialization are timed separately",
    }
    print("NEWOW_P4_PERF=" + json.dumps(report, sort_keys=True))

    assert len(cold_result.chart.value.bars) == 500
    assert (
        cold_result.meta.input_content_sha256 == warm_result.meta.input_content_sha256
    )
    assert _p95(cold_samples) < 5000
    assert _p95(warm_samples) < 500
    assert _p95(pressure_samples) < 5000
