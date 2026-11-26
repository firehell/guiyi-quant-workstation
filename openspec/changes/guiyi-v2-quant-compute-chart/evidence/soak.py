"""Repeat the real scheduler and kernels on frozen inputs, without external services."""

import argparse
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from hashlib import sha256
from importlib.metadata import version
import json
from os import getpid
from pathlib import Path
import platform
import resource
from subprocess import check_output
from threading import Barrier, enumerate as all_threads
from time import perf_counter, process_time, sleep, time

import numpy as np

from benchmark import EXPANDED, series
from app.compute_runtime.contracts import CommittedLiveBar, ComputeScope, ComputeWindow
from app.compute_runtime.runtime import ComputeRuntime
from app.compute_runtime.scheduler import ComputeBusy
from app.market_data.market_archive import MarketArchiveReceipt
from guiyi_quant.compute import REGISTRY, FeatureRequest


FEATURES = tuple(FeatureRequest(name) for name in ("ema21", "macd", "atr"))
BATCH_LIMIT = 4
START_INDEX = 40
STEP_SECONDS = 0.03


def latency(values):
    percentiles = np.round(np.percentile(values, [50, 95, 99]) * 1000, 4).tolist() if values else None
    return {"count": len(values), "p50_p95_p99_ms": percentiles}


def exact_scope(bars, name, revision=None):
    source = bars.identity
    return ComputeScope(name, source.product, source.physical_contract, source.segment_id, source.frequency, FEATURES, revision)


def submit_live(runtime, bars, index, checkpoints=()):
    bar = bars.bars[index]
    commit = CommittedLiveBar(bars.identity, bar, f"frozen:{index}", bars.bars[index - 1].bar_end)
    return runtime.submit_live("subing_simulation", commit, load=lambda: bars, checkpoints=checkpoints)


def completion_clock(future):
    finished = Future()
    future.add_done_callback(lambda _: finished.set_result(perf_counter()))
    return finished


def queue_batch(runtime, windows, deadline):
    cold, hot, pending = [], [], deque()
    admitted, hot_misses, loads = 0, 0, 0

    def load(bars):
        nonlocal loads
        loads += 1
        return bars

    def complete():
        start, window, result, finished = pending.popleft()
        readings = result.result(timeout=15)
        cold.append(finished.result(timeout=15) - start)
        assert len(readings) == len(EXPANDED)
        assert all(item.identity.input_digest == window.input_digest and item.identity.source == window.source for item in readings)
        start = perf_counter()
        hit = runtime.read_batch(window, EXPANDED, use="web")
        if hit is not None:
            hot.append(perf_counter() - start)
            assert hit == readings
        return hit is None

    while perf_counter() < deadline:
        window, bars = windows[admitted % len(windows)]
        start = perf_counter()
        try:
            output = runtime.submit_batch(window, EXPANDED, use="web", load=lambda bars=bars: load(bars))
        except ComputeBusy:
            hot_misses += complete()
            continue
        pending.append((start, window, output, completion_clock(output)))
        admitted += 1
        if len(pending) > BATCH_LIMIT:
            hot_misses += complete()
    while pending:
        hot_misses += complete()
    return {"batch_admission_to_completion": latency(cold), "batch_source_loads": loads,
            "hot_cache": latency(hot), "post_completion_evictions": hot_misses,
            "unique_windows": min(admitted, len(windows)), "matrix_passes": admitted / len(windows)}


def replay(runtime, rows, deadline, *, canonical=False):
    warm, first, checkpoints, pending = [], [], {}, deque()
    consumer = "canonical_research" if canonical else "subing_simulation"
    start = perf_counter()
    slots = int((deadline - start) / STEP_SECONDS)
    offered = admitted = refused = peak_in_flight = 0

    def complete():
        due, bars, index, future, finished = pending.popleft()
        updates = future.result(timeout=10)
        sample = first if index == START_INDEX else warm
        sample.append(finished.result(timeout=10) - due)
        assert len(updates) == len(FEATURES)
        assert all(item.point and item.point.bar_end == bars.bars[index].bar_end for item in updates)
        if index != START_INDEX:
            assert all(item.resumed_bars == index for item in updates)
        checkpoints[bars.identity] = (bars, index, updates)

    while offered < slots and perf_counter() < deadline:
        while pending and pending[0][3].done():
            complete()
        due = start + offered * STEP_SECONDS
        remaining = due - perf_counter()
        if remaining > 0:
            sleep(remaining)
        bars = rows[admitted % len(rows)]
        index = START_INDEX + admitted // len(rows)
        if index >= len(bars.bars):
            raise RuntimeError("FROZEN_SOAK_WINDOW_EXHAUSTED")
        bar = bars.bars[index]
        offered += 1
        try:
            if canonical:
                window = ComputeWindow.from_series(bars, as_of=bar.available_at)
                receipt = MarketArchiveReceipt(f"frozen:{bars.identity.product}:{index}", bar.trading_day, bar.available_at,
                                               {bars.identity.product: bars.identity.source_revision})
                job = runtime.submit_canonical(receipt, window, consumer=consumer, load=lambda bars=bars: bars)
            else:
                job = submit_live(runtime, bars, index)
        except ComputeBusy:
            refused += 1
            continue  # Retry the same completed Bar in the next slot to preserve its owner sequence.
        pending.append((due, bars, index, job, completion_clock(job)))
        peak_in_flight = max(peak_in_flight, len(pending))
        admitted += 1
    while pending:
        complete()
    return {"scheduled_slots": slots, "offered": offered, "admitted": admitted, "refused_attempts": refused,
            "peak_client_uncollected_futures": peak_in_flight, "first_owner": latency(first), "steady": latency(warm)}, checkpoints


def memory():
    rss = int(check_output(["ps", "-o", "rss=", "-p", str(getpid())], text=True).strip()) * 1024
    return {"resident_bytes": rss, "peak_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}


def exercise(rows, base, windows, seconds, *, profile):
    workers = {}
    if profile != "historical":
        workers["live"] = (replay, rows, {})
    if profile != "live":
        workers["canonical"] = (replay, rows, {"canonical": True})
        workers["batch"] = (queue_batch, windows, {})
    gate = Barrier(len(workers) + 1)
    start = perf_counter()
    epoch_start = time()
    deadline = start + seconds
    cpu = process_time()
    samples = []
    with ComputeRuntime(REGISTRY, batch_pending=BATCH_LIMIT, live_scopes=base,
                        canonical_scopes=tuple(exact_scope(row, "canonical_research") for row in rows)) as runtime:
        def run(worker, *args, **kwargs):
            gate.wait(timeout=10)
            return worker(runtime, *args, deadline, **kwargs)

        with ThreadPoolExecutor(max_workers=3) as executor:
            jobs = {key: executor.submit(run, worker, data, **options) for key, (worker, data, options) in workers.items()}
            gate.wait(timeout=10)
            while perf_counter() < deadline:
                sample = {"elapsed_seconds": round(perf_counter() - start, 2), **memory(), "queues": runtime.queue_load()}
                samples.append(sample)
                print(json.dumps({"mode": profile, **sample}), flush=True)
                for job in jobs.values():
                    if job.done():
                        job.result()
                sleep(min(15, max(0, deadline - perf_counter())))
            readings = {name: job.result() for name, job in jobs.items()}
            result = {"wall_seconds": round(perf_counter() - start, 3), "cpu_seconds": round(process_time() - cpu, 3),
                      "started_epoch_seconds": epoch_start, "finished_epoch_seconds": time(),
                      "samples": samples, "final_queues": runtime.queue_load(), **memory()}
            assert all(not item["pending"] for item in result["final_queues"].values())
            if "batch" in readings:
                result.update(readings["batch"])
                result["canonical"] = readings["canonical"][0]
                assert result["final_queues"]["batch"]["peak_pending"] == BATCH_LIMIT
                assert result["unique_windows"] == len(windows)
            continuations = {}
            if "live" in readings:
                for source, (bars, index, _) in readings["live"][1].items():
                    continuations[source] = submit_live(runtime, bars, index + 1).result(timeout=10)
    if "live" in readings:
        result["live"], checkpoints = readings["live"]
        with ComputeRuntime(REGISTRY, live_scopes=base) as restarted:
            for bars, index, original in checkpoints.values():
                recovered = submit_live(restarted, bars, index, tuple(item.checkpoint for item in original)).result(timeout=10)
                assert all(new.duplicate and new.point == old.point and new.checkpoint == old.checkpoint
                           for new, old in zip(recovered, original, strict=True))
                following = submit_live(restarted, bars, index + 1).result(timeout=10)
                assert following == continuations[bars.identity]
        result["runtime_recreations_verified"] = len(checkpoints)
    result["remaining_compute_threads"] = sum(thread.name.startswith("compute-") for thread in all_threads())
    assert result["remaining_compute_threads"] == 0
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("frozen", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--mode", choices=("combined", "live", "historical"), default="combined")
    parser.add_argument("--control-seconds", type=int, default=30)
    parser.add_argument("--mixed-seconds", type=int, default=180)
    args = parser.parse_args()
    if min(args.control_seconds, args.mixed_seconds) <= 0:
        parser.error("durations must be positive")
    raw = args.frozen.read_bytes()
    snapshot = json.loads(raw)
    matrix = [bars for entry in snapshot["series"] for bars, _ in series(entry)]
    windows = tuple((ComputeWindow.from_series(bars, as_of=bars.bars[-1].available_at), bars) for bars in matrix)
    assert len({window for window, _ in windows}) == len(windows)
    intraday = {bars.identity.product: bars for bars in matrix if bars.identity.frequency == "1m" and len(bars.bars) > 200}
    rows = tuple(intraday.values())
    assert len(rows) == 60
    scopes = tuple(exact_scope(bars, "subing_simulation", bars.identity.source_revision) for bars in rows)
    result = {"commit": args.commit, "core": version("guiyi-quant-core"), "ta_lib": version("ta-lib"),
              "numpy": np.__version__, "host": platform.platform(),
              "source_sha256": sha256(raw).hexdigest(), "covered_product_frequencies": len({(bar.identity.product, bar.identity.frequency) for bar in matrix}),
              "missing": snapshot["missing"]}
    if args.mode == "combined":
        result["control"] = exercise(rows, scopes, windows, args.control_seconds, profile="live")
        result["mixed"] = exercise(rows, scopes, windows, args.mixed_seconds, profile="mixed")
    else:
        result[args.mode] = exercise(rows, scopes, windows, args.mixed_seconds, profile=args.mode)
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(result, output, indent=2)
        output.write("\n")


if __name__ == "__main__":
    main()
