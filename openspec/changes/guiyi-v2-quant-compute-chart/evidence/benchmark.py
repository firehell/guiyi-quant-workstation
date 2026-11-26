"""Measure comparable generic work and the full registered workload on frozen Market input."""

import argparse
from collections import Counter, deque
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
from importlib.metadata import version
import json
from pathlib import Path
import platform
import resource
from time import perf_counter, process_time

import numpy as np

from app.compute_runtime.contracts import ComputeWindow
from app.compute_runtime.runtime import ComputeRuntime
from app.compute_runtime.scheduler import ComputeBusy

from guiyi_quant.compute import (
    REGISTRY, BarSeries, CompletedBar, FeatureRequest, SeriesIdentity, advance, open_incremental,
)
from guiyi_quant.indicators.atr import atr_series
from guiyi_quant.indicators.ema import ema_series
from guiyi_quant.indicators.macd import macd_series
from guiyi_quant.newow.models import NewowDailyBar
from guiyi_quant.newow.subplots import calculate_zhaoyao_mirror


GENERIC = tuple(FeatureRequest(name) for name in ("ema10", "ema21", "ema60", "macd", "atr"))
EXPANDED = GENERIC + tuple(FeatureRequest(name) for name in (
    "stddev", "boll", "obv", "volume_ratio", "trend_direction", "support_resistance", "retest",
))
FIELDS = ("open", "high", "low", "close", "volume")


def series(entry):
    owner = entry["physical"]
    segment = f"{owner}:{entry['segment_start']}"
    identity = SeriesIdentity(entry["product"], owner, segment, entry["frequency"], entry["revision"])
    bars = []
    source = []
    for row in entry["rows"]:
        bar_end = datetime.fromisoformat(row["bar_end"])
        day = date.fromisoformat(row["trading_day"])
        fields = tuple(Decimal(row[key]) for key in FIELDS)
        no_trade = all(value == 0 for value in fields) and row["turnover"] is not None and Decimal(row["turnover"]) == 0
        # No-trade boundary restarts the analytical series, with no fabricated inputs or output.
        if no_trade:
            if bars:
                yield BarSeries(identity, tuple(bars)), tuple(source)
            segment = f"{owner}:{bar_end.isoformat()}:after-no-trade"
            identity = replace(identity, segment_id=segment)
            bars, source = [], []
            continue
        bars.append(CompletedBar(
            owner, segment, day, f"historical:{day.isoformat()}", bar_end, bar_end, bar_end,
            *map(float, fields), "VALID",
        ))
        source.append(NewowDailyBar(
            identity.product, owner, segment, day, bar_end, *fields[:4], int(fields[4]),
            None, identity.source_revision, True, True,
        ))
    if bars:
        yield BarSeries(identity, tuple(bars)), tuple(source)


def old_generic(data):
    (inputs, _) = data
    close = [bar.close for bar in inputs.bars]
    high = [bar.high for bar in inputs.bars]
    low = [bar.low for bar in inputs.bars]
    return (
        *(ema_series(close, period) for period in (10, 21, 60)),
        macd_series(close, 12, 26, 9, ema_seed_policy="sma_window", histogram_scale=2),
        atr_series(high, low, close, 14, smoothing_policy="wilder_sma_seed"),
    )


def new_generic(data):
    inputs, _ = data
    return REGISTRY.calculate(inputs, GENERIC, as_of=inputs.bars[-1].available_at, use="web")


def expanded(data):
    inputs, source = data
    return (
        REGISTRY.calculate(inputs, EXPANDED, as_of=inputs.bars[-1].available_at, use="web"),
        calculate_zhaoyao_mirror(source) if inputs.identity.frequency != "1m" else None,
    )


def warm_and_incremental(data):
    inputs, _ = data
    as_of = inputs.bars[-1].available_at
    cache = {}
    REGISTRY.calculate(inputs, GENERIC, as_of=as_of, use="web", result_cache=cache)
    start = perf_counter()
    REGISTRY.calculate(inputs, GENERIC, as_of=as_of, use="web", result_cache=cache)
    cache_hit = perf_counter() - start
    prefix = BarSeries(inputs.identity, inputs.bars[:-1])
    states = [
        open_incremental(prefix, request, as_of=as_of, mode="incremental", use="research")
        for request in GENERIC
    ]
    start = perf_counter()
    for state in states:
        advance(state, inputs.identity, inputs.bars[-1])
    return cache_hit, perf_counter() - start


def measure(function, matrix, repeats):
    started = process_time()
    elapsed = []
    for _ in range(repeats):
        for entry in matrix:
            before = perf_counter()
            function(entry)
            elapsed.append(perf_counter() - before)
    return {
        "segment_latency_ms": [round(float(v) * 1000, 4) for v in np.percentile(elapsed, [50, 95, 99])],
        "total_seconds": round(sum(elapsed), 4), "cpu_seconds": round(process_time() - started, 4),
        "process_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    }


def measure_queue(matrix):
    pending = deque()
    elapsed = []
    cap = 4
    started = process_time()
    def collect():
        requested, future = pending.popleft()
        future.result(timeout=10)
        elapsed.append(perf_counter() - requested)

    with ComputeRuntime(REGISTRY, batch_pending=cap) as runtime:
        for inputs, _ in matrix:
            window = ComputeWindow.from_series(inputs, as_of=inputs.bars[-1].available_at)
            while True:
                requested = perf_counter()
                try:
                    future = runtime.submit_batch(window, EXPANDED, use="web", load=lambda series=inputs: series)
                    pending.append((requested, future))
                    if len(pending) > cap:
                        collect()
                    break
                except ComputeBusy:
                    collect()
        while pending:
            collect()
        queues = runtime.queue_load()
    return {
        "batch_job_latency_ms": [round(float(v) * 1000, 4) for v in np.percentile(elapsed, [50, 95, 99])],
        "queue_load": queues,
        "cpu_seconds": round(process_time() - started, 4),
        "process_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    }


def main(frozen, output, repeats):
    raw = frozen.read_bytes()
    payload = json.loads(raw)
    matrix = tuple(data for entry in payload["series"] for data in series(entry))
    scope = {(inputs.identity.product, inputs.identity.frequency) for inputs, _ in matrix}
    counts = Counter(inputs.identity.frequency for inputs, _ in matrix)
    result = {
        "source_sha256": sha256(raw).hexdigest(),
        "missing": payload["missing"],
        "through": payload["through"], "covered_product_frequencies": len(scope),
        "owner_segments_by_frequency": dict(counts), "bars": sum(len(inputs.bars) for inputs, _ in matrix),
        "repeats": repeats, "host": platform.platform(), "ta_lib": version("ta-lib"), "numpy": np.__version__,
        "old_comparable_batch": measure(old_generic, matrix, repeats),
        "new_comparable_batch": measure(new_generic, matrix, repeats),
        "new_expanded_batch": measure(expanded, matrix, repeats),
    }
    cached, update = zip(*(warm_and_incremental(data) for data in matrix), strict=True)
    result["cache_hot_latency_ms"] = [round(float(v) * 1000, 4) for v in np.percentile(cached, [50, 95, 99])]
    result["queued_full_registry"] = measure_queue(matrix)
    result["incremental_latency_ms"] = [round(float(v) * 1000, 4) for v in np.percentile(update, [50, 95, 99])]
    with output.open("x", encoding="utf-8") as file:
        json.dump(result, file, indent=2, sort_keys=True)
        file.write("\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("frozen", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    main(args.frozen, args.output, args.repeats)
