"""Spawn-only socket harness for the real app with owned in-memory MDS facts.

No test endpoints or product-service replacements: the normal route composition
owns its SnapshotCache, HeavyResourceGate and InFlightCoordinator per process.
"""

from contextlib import contextmanager
from dataclasses import replace
import multiprocessing
import os
import socket
from time import monotonic, sleep

import httpx2 as httpx


def _serve(listener):
    # Apply this before app.main imports db.session; never load repository secrets.
    from app.core import env

    env.load_project_env = lambda: None
    os.environ["DATABASE_URL"] = "sqlite:///:memory:"
    from app.api import market_newow
    from app.db.session import get_db
    from app.main import app
    from app.market_data.domain import BarFrequency
    from newow.product_fixtures import ProductCases
    import uvicorn

    cases = ProductCases()
    _, _, facts = cases.paged_reader(prefix_bars=520, frequency="1d")
    primitive = cases.primitive_input("trend", "1d").bars
    key = ("RB2605", BarFrequency.D1)
    # Repeat owned OHLC facts so history has multiple real BUILD/CLEAR pairs.
    facts.physical[key] = tuple(
        replace(
            bar,
            open=source.open,
            high=source.high,
            low=source.low,
            close=source.close,
            volume=source.volume,
            open_interest=source.open_interest,
        )
        for index, bar in enumerate(facts.physical[key])
        for source in (primitive[index % len(primitive)].bar,)
    )
    facts.expected_physical = dict(facts.physical)
    facts.actual[BarFrequency.D1] = tuple(
        bar
        for bar in facts.physical[key]
        if bar.trading_day >= facts.segments[0].start_trading_day
    )
    market_newow.build_market_data_service = lambda _session: facts
    market_newow.build_database_coverage_source = lambda _session: facts.coverage
    market_newow.load_active_products = lambda: ("rb",)
    app.dependency_overrides[get_db] = lambda: object()
    uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=0,
            workers=1,
            loop="asyncio",
            lifespan="off",
            log_level="error",
            access_log=False,
        )
    ).run(sockets=[listener])


@contextmanager
def socket_app():
    """Own a fresh process/cache and an OS-assigned loopback port, always reap it."""
    context = multiprocessing.get_context("spawn")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        url = f"http://127.0.0.1:{listener.getsockname()[1]}"
        process = context.Process(target=_serve, args=(listener,))
        process.start()
        try:
            deadline = monotonic() + 20
            with httpx.Client(base_url=url, trust_env=False, timeout=0.5) as client:
                while monotonic() < deadline:
                    if not process.is_alive():
                        raise AssertionError(f"socket app exited: {process.exitcode}")
                    try:
                        response = client.get("/health")
                        if response.status_code == 200:
                            assert response.json()["service"] == "guiyi-quant-api"
                            break
                    except httpx.TransportError:
                        pass
                    sleep(0.02)
                else:
                    raise AssertionError("socket app did not become ready")
            yield url, process.pid
        finally:
            process.terminate()
            process.join(5)
            if process.is_alive():
                process.kill()
                process.join(5)
            assert not process.is_alive()
