"""Measure the existing 16-product isolation test with an optional Canonical worker.

Run from the repository root with PYTHONPATH=services/quant-api:packages/quant-core:.
Use disposable loopback PostgreSQL/Redis as required by the integration fixture.
"""

import argparse
from collections.abc import Iterable
from contextlib import ExitStack
from dataclasses import replace
from datetime import timedelta
from importlib.metadata import version
import json
import multiprocessing
import os
from pathlib import Path
from platform import machine
from tempfile import TemporaryDirectory
from time import monotonic_ns
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.compute_runtime import ComputeRuntime, ComputeScope
from app.compute_runtime.canonical_publications import CanonicalPublicationCompute, CanonicalResearchWindow
from app.db.base import Base
from app.market_data.after_market import _evidence_hash
from app.market_data.aggregation import SessionWindow, aggregate_from_1m
from app.market_data.catalog import MarketCatalog
from app.market_data.domain import BarFrequency, ContractTradingDayQuery, DatasetKey
from app.market_data.market_archive import reference_catalog_revision, retain_archive_status
from app.market_data.market_data_service import MarketDataService
from app.market_data.market_feed import DurableLiveMarketService
from app.market_data.observation_stream import ObservationStream
from app.market_data.storage import CanonicalMonthlyStore, PublishRequest
from guiyi_quant import compute as core_compute
from guiyi_quant.compute import FeatureRequest
from guiyi_quant.htdy_account_execution import LocalStore
from guiyi_quant.htdy_account_execution.model import TqKqObservedSignalV1
from guiyi_quant.trading_universe import TRADING_PRODUCTS
from tests.data_foundation.test_market_archive import FINISHED, _status
from tests.data_foundation.test_tick_htdy_integration import DAY, OPEN, _seed_history

TEST = ("services/quant-api/tests/data_foundation/test_tick_htdy_integration.py"
        "::test_isolated_htdy_live_restarts_all_trading_products")
END = OPEN + timedelta(hours=2)
FIRST = DAY - timedelta(days=6)
LAST = DAY - timedelta(days=1)
CANONICAL_PRODUCTS = ("ag", "al", "au", "cu", "ni", "pb", "sn", "zn")
FEATURES = tuple(FeatureRequest(name) for name in ("ema10", "ema21", "macd", "atr"))


def isolated_database():
    url = make_url(os.environ["GUIYI_MARKET_FOUNDATION_TEST_DATABASE_URL"])
    if (url.get_backend_name() != "postgresql" or url.host != "127.0.0.1" or url.query
            or url.database != "guiyi_market_foundation" or not url.port or url.port <= 5432):
        raise ValueError("Disposable loopback PostgreSQL required")
    return create_engine(url)


def receipt(engine, root, instant):
    with Session(engine) as db:
        revisions = {product: reference_catalog_revision(db, product, DAY) for product in CANONICAL_PRODUCTS}
    status = _status(finished=instant)
    status["last_run"]["products"] = list(CANONICAL_PRODUCTS)
    status["last_run"]["live_evidence"].update(
        scope_sha256=_evidence_hash(list(CANONICAL_PRODUCTS)), canonical_readback=revisions,
    )
    path = retain_archive_status(status, now=instant, archive_root=root.parent, formal=False)
    assert path is not None
    return path


def revise(engine, root, targets):
    store = CanonicalMonthlyStore(root)
    with Session(engine) as db:
        catalog = MarketCatalog(db, root)
        market = MarketDataService(catalog, store)
        for target in targets:
            product, contract = target.scope.product, target.scope.physical_contract
            bars = market.query_contract_trading_days(ContractTradingDayQuery(
                product, contract, BarFrequency.M1, FIRST, LAST,
            )).bars
            assert len(bars) == 2160
            value = bars[-1].close + 33
            assert value > bars[-1].close
            revised = (*bars[:-1], replace(bars[-1], high=value, close=value))
            sessions = tuple(SessionWindow(bars[i].bar_end - timedelta(minutes=1), bars[i + 359].bar_end)
                             for i in range(0, len(bars), 360))
            hours = aggregate_from_1m(revised, target_frequency=BarFrequency.H1, sessions=sessions)
            for frequency, changed in ((BarFrequency.M1, revised), (BarFrequency.H1, hours)):
                partition = store.publish(PublishRequest(
                    DatasetKey("contract", product, contract, frequency), DAY.year, DAY.month,
                    changed, tuple(bar.bar_end for bar in changed),
                ))
                catalog.register_partition(partition)
        db.commit()


def canonical_worker(root, connection):
    engine = isolated_database()
    schema = "htdy_canonical_measure_" + uuid4().hex
    with engine.begin() as db:
        db.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    scoped = engine.execution_options(schema_translate_map={None: schema})
    try:
        Base.metadata.create_all(scoped)
        root.mkdir()
        scope = tuple((p, p.upper() + "2701", "SHFE") for p in CANONICAL_PRODUCTS)
        _seed_history(scoped, root, scope)
        targets = tuple(CanonicalResearchWindow(
            ComputeScope("canonical_research", p, contract, f"contract:{contract}", "1m", FEATURES), FIRST, LAST,
        ) for p, contract, _ in scope)
        instant = FINISHED + timedelta(minutes=1)
        with CanonicalPublicationCompute(scoped, root, targets, now=lambda: instant) as compute:
            initial = compute.accept(receipt(scoped, root, FINISHED), DAY)
            revise(scoped, root, targets)
            revised_receipt = receipt(scoped, root, instant)
            connection.send("ready")
            assert connection.poll(90) and connection.recv() == "start"
            jobs = []
            runtime = compute._runtime
            run_canonical = runtime._state._run_canonical

            def measured_job(*args, **kwargs):
                interval = [monotonic_ns(), None]
                jobs.append(interval)
                if len(jobs) == 1:
                    connection.send("first_job")
                try:
                    return run_canonical(*args, **kwargs)
                finally:
                    interval[1] = monotonic_ns()

            accept_started = monotonic_ns()
            with patch.object(runtime._state, "_run_canonical", measured_job):
                changed = compute.accept(revised_receipt, DAY)
            accept_finished = monotonic_ns()
            assert len(initial) == len(changed) == len(targets) * len(FEATURES)
            assert len(jobs) == len(targets) and all(end is not None for _, end in jobs)
            for prior, update in zip(initial, changed, strict=True):
                a, b = prior.checkpoint.identity.source, update.checkpoint.identity.source
                assert a.product == b.product and a.source_revision != b.source_revision
                assert prior.point.bar_end == update.point.bar_end
                assert prior.point.values != update.point.values and update.point.available_at == instant
            assert compute.accept(revised_receipt, DAY) == ()
        connection.send({"accept_ns": [accept_started, accept_finished], "jobs_ns": jobs,
                         "queue": runtime.queue_load()["incremental"], "updates": len(changed),
                         "replayed_updates": 0})
    finally:
        with engine.begin() as db:
            db.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()
        connection.close()


class Measure:
    def __init__(self, canonical):
        self.canonical = canonical
        self.publish_ns = None
        self.ledger_ns = {}
        self.live_jobs_ns = {}
        self.replays = 0
        self.runtime = None
        self.publisher = None

    @pytest.hookimpl(wrapper=True)
    def pytest_runtest_call(self, item):
        commit_market = DurableLiveMarketService._commit
        execute = LocalStore.execute
        submit_live = ComputeRuntime.submit_owned_live

        def publish(publisher, observations, **kwargs):
            live_batch = tuple(row for row in observations if row[1] is BarFrequency.H1 and row[2].bar_end == END)
            if live_batch and self.canonical is not None:
                self.canonical.send("start")
                assert self.canonical.poll(30) and self.canonical.recv() == "first_job"
            result = commit_market(publisher, observations, **kwargs)
            if live_batch:
                assert len(live_batch) == 16 and self.publish_ns is None
                self.publish_ns = monotonic_ns()
                self.publisher = publisher
            return result

        def ledger(store, key, command, **kwargs):
            result = execute(store, key, command, **kwargs)
            if type(command) is TqKqObservedSignalV1 and command.signal.bar_end == END:
                product = command.signal.product
                if result.duplicate:
                    self.replays += 1
                else:
                    assert product not in self.ledger_ns
                    self.ledger_ns[product] = monotonic_ns()
            return result

        def submit(runtime, commit, *, owner, run):
            if commit.bar_end != END:
                return submit_live(runtime, commit, owner=owner, run=run)
            self.runtime = runtime

            def measured_live():
                started = monotonic_ns()
                try:
                    return run()
                finally:
                    assert commit.scope.product not in self.live_jobs_ns
                    self.live_jobs_ns[commit.scope.product] = (started, monotonic_ns())

            return submit_live(runtime, commit, owner=owner, run=measured_live)

        with ExitStack() as stack:
            stack.enter_context(patch.object(DurableLiveMarketService, "_commit", publish))
            stack.enter_context(patch.object(LocalStore, "execute", ledger))
            stack.enter_context(patch.object(ComputeRuntime, "submit_owned_live", submit))
            result = yield
        source = self.publisher.source_provider.stream
        cursor = source.cursor("live", DAY)
        self.feed_backlog = len(source.redis.xrange(source.key(DAY), min="(" + cursor))
        completed = ObservationStream(source.redis, kind="completed")
        self.h1_count = sum(json.loads(fields["envelope"])["channel"].endswith(":60m")
                            for _, fields in source.redis.xrange(completed.key(DAY)))
        return result

    def result(self):
        assert self.publish_ns is not None and set(self.ledger_ns) == {p.upper() for p in TRADING_PRODUCTS}
        assert set(self.live_jobs_ns) == set(TRADING_PRODUCTS)
        assert self.h1_count == 32 and self.replays == 16 and self.feed_backlog == 0
        queue = self.runtime.queue_load()["live"]
        assert queue["pending"] == queue["rejected"] == 0
        elapsed = {product: milliseconds(at - self.publish_ns) for product, at in sorted(self.ledger_ns.items())}
        return {"completed_publish_return_to_sqlite_commit_return_ms": elapsed, "live_queue": queue,
                "source_backlog": self.feed_backlog,
                "completed_h1_originals": self.h1_count, "new_h1_ledger_commands": len(self.ledger_ns),
                "idempotent_h1_ledger_replays": self.replays, "all_16_watermarks_at": END.isoformat()}


def milliseconds(nanoseconds):
    return round(nanoseconds / 1_000_000, 3)


def measure(mode):
    with TemporaryDirectory(prefix="guiyi-htdy-canonical-") as directory:
        connection = worker = None
        if mode == "parallel":
            context = multiprocessing.get_context("spawn")
            connection, endpoint = context.Pipe()
            worker = context.Process(target=canonical_worker, args=(Path(directory).resolve() / "canonical", endpoint))
            worker.start()
            endpoint.close()
        try:
            if connection is not None:
                assert connection.poll(90) and connection.recv() == "ready"
            probe = Measure(connection)
            assert pytest.main(["-q", "-p", "no:cacheprovider", "--tb=short", TEST], plugins=[probe]) == 0
            result = probe.result()
            if connection is not None:
                assert connection.poll(35)
                canonical = connection.recv()
                left, right = probe.publish_ns, max(probe.ledger_ns.values())
                jobs = canonical.pop("jobs_ns")
                overlap = {
                    product.upper(): sum(max(0, min(end, live_end) - max(start, live_start)) for start, end in jobs)
                    for product, (live_start, live_end) in sorted(probe.live_jobs_ns.items())
                }
                started, finished = canonical.pop("accept_ns")
                canonical["queued_jobs"] = len(jobs)
                canonical["receipt_accept_ms"] = milliseconds(finished - started)
                canonical["receipt_to_h1_pipeline_overlap_ms"] = milliseconds(min(right, finished) - max(left, started))
                canonical["worker_overlap_by_live_product_ms"] = {
                    product: milliseconds(duration) for product, duration in overlap.items() if duration > 0
                }
                assert any(overlap.values()) and canonical["receipt_to_h1_pipeline_overlap_ms"] > 0
                assert canonical["queue"]["pending"] == canonical["queue"]["rejected"] == 0
                result["canonical"] = canonical
                worker.join(15)
                assert worker.exitcode == 0
            core_path = Path(core_compute.__file__).resolve()
            return {"mode": mode, "architecture": machine(), "logical_cpus": os.cpu_count(),
                    "core_import": "checkout_source" if core_path.is_relative_to(Path.cwd()) else "installed",
                    "core_distribution_metadata_version": version("guiyi-quant-core"), **result}
        finally:
            if connection is not None:
                connection.close()
                worker.join(2)
                if worker.is_alive():
                    worker.terminate()
                worker.join(10)


def main(argv: Iterable[str] | None = None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("baseline", "parallel"))
    parser.add_argument("output", type=Path)
    args = parser.parse_args(argv)
    result = measure(args.mode)
    args.output.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
