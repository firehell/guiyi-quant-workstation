from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.middleware.request_timing import RequestTimingMiddleware
from app.read_timings import detail_timings, phase, timed


def test_phase_timings_are_request_local_and_clear_after_failure():
    @timed("read")
    def read():
        with phase("verify"):
            return 3

    def run():
        with detail_timings() as metrics:
            assert read() == 3
            assert set(metrics.values) == {"read", "verify"}
            return metrics
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: run(), range(2)))
    assert results[0] is not results[1]
    try:
        with detail_timings():
            with phase("compute"):
                raise ValueError("test")
    except ValueError:
        pass
    with detail_timings() as metrics:
        assert metrics.values == {}


def test_server_timing_covers_worker_phases_without_payload_or_query_data():
    app = FastAPI()
    app.add_middleware(RequestTimingMiddleware)

    @app.get("/api/market/newow/strategy-detail")
    def detail():
        with phase("read"):
            return {"ok": True}

    with TestClient(app) as client:
        response = client.get("/api/market/newow/strategy-detail?private=secret-value")
        header = response.headers["Server-Timing"]
        assert "read;dur=" in header and "total;dur=" in header
        assert "secret" not in header and response.json() == {"ok": True}


def test_concurrent_http_worker_timings_and_error_cleanup_are_isolated():
    app = FastAPI()
    app.add_middleware(RequestTimingMiddleware)
    barrier = Barrier(2)

    @app.get("/api/market/newow/strategy-detail")
    def detail(kind: Literal["read", "compute", "error"], paired: bool = False):
        with phase("verify" if kind == "error" else kind):
            if paired:
                barrier.wait(timeout=2)
            if kind == "error":
                raise HTTPException(409, detail={"code": "CONTROLLED_TEST_FAILURE"})
            return {"ok": True}

    with TestClient(app) as client:
        def get(kind):
            return client.get("/api/market/newow/strategy-detail", params={"kind": kind, "paired": True})
        with ThreadPoolExecutor(max_workers=2) as pool:
            read, compute = list(pool.map(get, ["read", "compute"]))
        assert read.status_code == compute.status_code == 200
        assert "read;dur=" in read.headers["Server-Timing"]
        assert "compute;dur=" not in read.headers["Server-Timing"]
        assert "compute;dur=" in compute.headers["Server-Timing"]
        assert "read;dur=" not in compute.headers["Server-Timing"]
        failure = client.get("/api/market/newow/strategy-detail?kind=error")
        assert failure.status_code == 409 and "verify;dur=" in failure.headers["Server-Timing"]
        after = client.get("/api/market/newow/strategy-detail?kind=read")
        assert after.status_code == 200
        assert "verify;dur=" not in after.headers["Server-Timing"]
        assert "compute;dur=" not in after.headers["Server-Timing"]
