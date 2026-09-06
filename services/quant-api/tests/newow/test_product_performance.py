"""Reproducible P4 backend stage baseline over the owned fake-MDS read seam."""

import json
import platform
import resource
import subprocess
import sys
from time import perf_counter

from app.api.market_newow import _product_response
from app.market_data.newow.product_service import (
    NewowProductService,
    ProductServiceQuery,
)
from app.market_data.newow.snapshot_cache import SnapshotCache


def _p95(values):
    ordered = sorted(values)
    return ordered[max(0, int(len(ordered) * 0.95) - 1)]


def _run(service, request, repetitions):
    samples = []
    last = None
    for _ in range(repetitions):
        started = perf_counter()
        last = service.query(request)
        samples.append((perf_counter() - started) * 1000)
    assert last is not None
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
    pressure_samples, _ = _run(pressure_service, pressure_request, 1)

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
        "warmup_excluded": 1,
        "cold_total_p95_ms": round(_p95(cold_samples), 3),
        "validated_cache_total_p95_ms": round(_p95(warm_samples), 3),
        "pressure_8001_total_ms": round(pressure_samples[0], 3),
        "serialization_response_bytes": response_bytes,
        "rss_max_bytes": rss_bytes,
        "stage_note": "total includes fake-MDS read, identity validation, replay and assembly; serialization measured separately",
    }
    print("NEWOW_P4_PERF=" + json.dumps(report, sort_keys=True))

    assert len(cold_result.chart.value.bars) == 500
    assert (
        cold_result.meta.input_content_sha256 == warm_result.meta.input_content_sha256
    )
    assert _p95(cold_samples) < 5000
    assert _p95(warm_samples) < 500
    assert pressure_samples[0] < 5000
