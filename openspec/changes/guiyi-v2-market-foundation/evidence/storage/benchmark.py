#!/usr/bin/env python3
"""Compare locked VeighNa native PostgreSQL against Canonical + Catalog.

Never run a destination against a service database. All writable data and
VeighNa settings belong to a private /private/tmp workspace.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import UTC, date, timedelta
from decimal import Decimal
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import platform
import re
import resource
import statistics
import sys
from threading import Barrier
from time import perf_counter, process_time
from zoneinfo import ZoneInfo

import pyarrow as pa
import pyarrow.parquet as pq
from sqlalchemy import URL, create_engine, text
from sqlalchemy.orm import Session

from app.db.readonly import readonly_transaction
from app.db.url import normalize_database_url
from app.market_data.catalog import MarketCatalog
from app.market_data.domain import (
    BarFrequency, CanonicalBar, DatasetKey, DatasetKind, SeriesKind, SeriesQuery,
)
from app.market_data.market_data_service import MarketDataService
from app.market_data.storage import CANONICAL_SCHEMA, CanonicalMonthlyStore, PublishRequest
from app.models.market_tables import Base, MarketDataset, MarketPartition
from app.private_settings import load_private_readonly_settings


DAY_ZONE = ZoneInfo("Asia/Shanghai")
PRODUCTS = {"rb": "SHFE", "cu": "SHFE", "jm": "DCE", "ta": "CZCE", "ec": "INE"}
PORTABLE_INTERVALS = {"1m": "1m", "60m": "1h", "1d": "d", "1w": "w"}
PHYSICAL_SAMPLE = ("rb", "RB2701")
SIZES = (500, 5_000, 100_000)
NUMERIC_FIELDS = {
    "open": "open_price", "high": "high_price",
    "low": "low_price", "close": "close_price",
    "volume": "volume", "turnover": "turnover", "open_interest": "open_interest",
}


@dataclass(frozen=True)
class Sample:
    key: DatasetKey
    bars: tuple[CanonicalBar, ...]

    @property
    def name(self) -> str:
        return f"{self.key.symbol}-{self.key.series_or_contract}-{self.key.frequency.value}"

    @property
    def native_symbol(self) -> str:
        return (
            self.key.symbol.upper() + "88"
            if self.key.kind is DatasetKind.CONTINUOUS else self.key.series_or_contract
        )

    def query(self, bars: tuple[CanonicalBar, ...]) -> SeriesQuery:
        kind = SeriesKind(self.key.kind.value)
        return SeriesQuery(
            kind, self.key.symbol, self.key.frequency,
            bars[0].bar_end - timedelta(microseconds=1), bars[-1].bar_end,
            self.key.series_or_contract if kind is SeriesKind.CONTRACT else None,
        )


def frozen_keys() -> list[tuple[DatasetKey, int]]:
    samples = []
    for product in PRODUCTS:
        for frequency in BarFrequency:
            if frequency is BarFrequency.M1:
                count = 100_001 if product == "rb" else 6_000
            elif frequency is BarFrequency.D1:
                count = 250
            elif frequency is BarFrequency.W1:
                count = 100
            else:
                count = 1_200
            samples.append((DatasetKey(DatasetKind.CONTINUOUS, product, "MAIN", frequency), count))
    symbol, contract = PHYSICAL_SAMPLE
    samples.append((DatasetKey(DatasetKind.CONTRACT, symbol, contract, BarFrequency.M1), 5_000))
    return samples


def freeze(work: Path, config: Path, cutoff: date) -> None:
    """Export only a bounded slice from successful Catalog-resolved immutable assets."""
    values, _ = load_private_readonly_settings(config)
    catalog_root = Path(values["GUIYI_CANONICAL_DATA_ROOT"])
    engine = create_engine(
        normalize_database_url(values["DATABASE_URL"]), hide_parameters=True,
        connect_args={"connect_timeout": 5, "options": "-c default_transaction_read_only=on"},
    )
    folder = work / "frozen"
    folder.mkdir(mode=0o700)
    store = CanonicalMonthlyStore(catalog_root)
    manifest: list[dict] = []
    try:
        with Session(engine, autoflush=False) as session, readonly_transaction(session, timeout_seconds=120):
            catalog = MarketCatalog(session, catalog_root)
            market = MarketDataService(catalog, store)
            for key, minimum in frozen_keys():
                retained = []
                proofs = []
                for partition in reversed(catalog.all_partitions(key)):
                    if (partition.year, partition.month) > (cutoff.year, cutoff.month):
                        continue
                    verified = store.verified_partition_fingerprint(partition)
                    rows = store.read_catalog_partition(partition)
                    segments = tuple(bar for bar in rows if bar.trading_day <= cutoff)
                    if not segments:
                        continue
                    retained.extend(reversed(segments))
                    proofs.append(verified)
                    if len(retained) >= minimum:
                        break
                if len(retained) < minimum:
                    raise ValueError(f"FROZEN_HISTORY_INCOMPLETE_{key.symbol}_{key.frequency.value}")
                sample = Sample(key, tuple(reversed(retained[:minimum])))
                # Prove completeness using the actual reader and Catalog's calendar/session checks.
                if market.query(sample.query(sample.bars)).bars != sample.bars:
                    raise ValueError("FROZEN_HISTORY_MDS_MISMATCH")
                file = folder / f"{sample.name}.parquet"
                pq.write_table(
                    pa.Table.from_pylist([bar.as_record() for bar in sample.bars], schema=CANONICAL_SCHEMA),
                    file, compression="zstd",
                )
                manifest.append({
                    "name": sample.name, "key": [key.kind.value, key.symbol,
                        key.series_or_contract, key.frequency.value],
                    "rows": len(sample.bars), "first": sample.bars[0].bar_end.isoformat(),
                    "last": sample.bars[-1].bar_end.isoformat(),
                    "source_partition_sha256": proofs, "sha256": digest(file),
                })
    finally:
        engine.dispose()
    dump(folder / "manifest.json", {"through": cutoff.isoformat(), "samples": manifest})


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def dump(path: Path, payload: object) -> None:
    with path.open("x", encoding="utf-8") as target:
        json.dump(payload, target, indent=2, sort_keys=True)
        target.write("\n")


def load_frozen(work: Path) -> tuple[Sample, ...]:
    folder = work / "frozen"
    manifest = json.loads((folder / "manifest.json").read_bytes())
    samples: list[Sample] = []
    entries = manifest["samples"]
    if [row["key"] for row in entries] != [
        [key.kind.value, key.symbol, key.series_or_contract, key.frequency.value]
        for key, _ in frozen_keys()
    ]:
        raise ValueError("FROZEN_SCOPE_INVALID")
    for row in entries:
        key = DatasetKey(*row["key"])
        name = Sample(key, ()).name
        file = folder / f"{name}.parquet"
        if row["name"] != name or digest(file) != row["sha256"]:
            raise ValueError("FROZEN_HASH_INVALID")
        table = pq.ParquetFile(file).read()
        if table.schema != CANONICAL_SCHEMA or len(table) != row["rows"]:
            raise ValueError("FROZEN_SCHEMA_INVALID")
        samples.append(Sample(key, tuple(CanonicalBar(**bar) for bar in table.to_pylist())))
    return tuple(samples)


def monthly_requests(sample: Sample, rows: tuple[CanonicalBar, ...]):
    groups: dict[tuple[int, int], list[CanonicalBar]] = defaultdict(list)
    for bar in rows:
        day = bar.trading_day
        groups[day.year, day.month].append(bar)
    for (year, month), monthly in groups.items():
        yield PublishRequest(sample.key, year, month, tuple(monthly), tuple(bar.bar_end for bar in monthly))


class Canonical:
    def __init__(self, engine, root: Path) -> None:
        self.engine = engine
        self.root = root
        self.store = CanonicalMonthlyStore(root)

    def read(self, sample: Sample, rows: tuple[CanonicalBar, ...]):
        with Session(self.engine) as session:
            market = MarketDataService(MarketCatalog(session, self.root), self.store)
            result = market.query_maintenance_expected(
                sample.query(rows), tuple(row.bar_end for row in rows),
            ).bars
        return result

    def write(self, sample: Sample, rows: tuple[CanonicalBar, ...], *, commit=True, before_commit=None):
        for request in monthly_requests(sample, rows):
            partition = self.store.publish(request)
            with Session(self.engine) as session:
                catalog = MarketCatalog(session, self.root)
                catalog.register_partition(partition)
                market = MarketDataService(catalog, self.store)
                visible = market.query_maintenance_expected(
                    sample.query(request.bars), request.expected_bar_ends,
                ).bars
                if visible != request.bars:
                    raise ValueError("CANONICAL_ROUNDTRIP_MISMATCH")
                if before_commit is not None:
                    before_commit()
                if commit:
                    session.commit()

    def cold(self):
        self.store.release_decoded_read_caches()


class Native:
    def __init__(self, port: int, password: str) -> None:
        from vnpy.trader.setting import SETTINGS

        SETTINGS.update({
            "database.database": "guiyi_market_foundation_bench",
            "database.user": "postgres", "database.password": password,
            "database.host": "127.0.0.1", "database.port": port,
            "database.timezone": "Asia/Shanghai",
        })
        from vnpy.trader.constant import Exchange, Interval
        from vnpy.trader.database import BaseDatabase
        from vnpy.trader.object import BarData
        from vnpy_postgresql.postgresql_database import PostgresqlDatabase

        self.exchange = Exchange
        self.interval = Interval
        self.bar_data = BarData
        self.database: BaseDatabase = PostgresqlDatabase()

    def bar(self, sample: Sample, bar: CanonicalBar):
        fields = {remote: getattr(bar, name) for name, remote in NUMERIC_FIELDS.items()}
        return self.bar_data(
            symbol=sample.native_symbol, exchange=self.exchange(PRODUCTS[sample.key.symbol]),
            interval=self.interval(PORTABLE_INTERVALS[sample.key.frequency.value]),
            datetime=bar.bar_end, gateway_name="ISOLATED_BENCH",
            **{field: float(value) if value is not None else None for field, value in fields.items()},
        )

    def write(self, sample: Sample, rows: tuple[CanonicalBar, ...]):
        if not self.database.save_bar_data([self.bar(sample, bar) for bar in rows]):
            raise ValueError("NATIVE_WRITE_FAILED")

    def read(self, sample: Sample, rows: tuple[CanonicalBar, ...]):
        return self.database.load_bar_data(
            sample.native_symbol, self.exchange(PRODUCTS[sample.key.symbol]),
            self.interval(PORTABLE_INTERVALS[sample.key.frequency.value]),
            rows[0].bar_end.astimezone(DAY_ZONE).replace(tzinfo=None),
            rows[-1].bar_end.astimezone(DAY_ZONE).replace(tzinfo=None),
        )

    def cold(self):
        self.database.db.close()


def mismatch(sample: Sample, expected: tuple[CanonicalBar, ...], observed: list) -> dict[str, int]:
    counts: Counter[str] = Counter()
    if len(expected) != len(observed):
        raise ValueError("NATIVE_ROW_COUNT_MISMATCH")
    for row, native in zip(expected, observed, strict=True):
        if native.datetime.astimezone(UTC) != row.bar_end:
            counts["bar_end"] += 1
        if native.symbol != sample.native_symbol or native.exchange.value != PRODUCTS[sample.key.symbol]:
            counts["identity"] += 1
        for name, remote in NUMERIC_FIELDS.items():
            value, read = getattr(row, name), getattr(native, remote)
            if read is not None:
                read = Decimal(str(read))
            if value != read:
                counts[name] += 1
    return dict(counts)


def concurrent_readback(store, reader: Sample, writer: Sample, repetitions: int) -> dict:
    """Query RB history while repeatedly publishing the same CU trading day."""
    window = reader.bars[-5_000:]
    latest_day = writer.bars[-1].trading_day
    daily = tuple(row for row in writer.bars if row.trading_day == latest_day)
    month = tuple(row for row in writer.bars if row.trading_day.replace(day=1) == latest_day.replace(day=1))
    barrier = Barrier(2, timeout=10)

    def write():
        barrier.wait()
        started = perf_counter()
        try:
            for _ in range(8):
                store.write(writer, month if isinstance(store, Canonical) else daily)
            return perf_counter() - started
        finally:
            if isinstance(store, Native):
                store.cold()

    def read():
        result = store.read(reader, window)
        if len(result) != len(window):
            raise ValueError("CONCURRENT_ROW_COUNT_MISMATCH")
        if isinstance(store, Canonical):
            if result != window:
                raise ValueError("CONCURRENT_CANONICAL_MISMATCH")
        elif any(key != "turnover" for key in mismatch(reader, window, result)):
            raise ValueError("CONCURRENT_NATIVE_IDENTITY_MISMATCH")

    with ThreadPoolExecutor(max_workers=1) as executor:
        operation = executor.submit(write)
        # Warm the target before the writers start. Each measurement materializes
        # all requested rows; full per-field validation is done afterward.
        read()
        barrier.wait()
        stats = measure(lambda: store.read(reader, window), lambda: None, repetitions)
        update_seconds = operation.result(timeout=30)
        read()
    return {"reader": "rb-MAIN-1m", "writer": "cu-MAIN-1m",
            "writer_runs": 8, "logical_rows_per_update": len(daily),
            "writer_wall_ms": round(update_seconds * 1_000, 3), **stats}


def measure(action: Callable, cold: Callable, repetitions: int) -> dict:
    def timed() -> tuple[float, float]:
        wall, cpu = perf_counter(), process_time()
        action()
        return 1_000 * (perf_counter() - wall), 1_000 * (process_time() - cpu)

    cold()
    first, first_cpu = timed()
    samples = [timed() for _ in range(repetitions)]
    times = sorted(wall for wall, _ in samples)
    return {"first_read_ms": round(first, 3), "first_client_cpu_ms": round(first_cpu, 3),
            "warm": {"runs": repetitions, "p50_ms": round(statistics.median(times), 3),
                     "p95_ms": round(times[math.ceil(0.95 * len(times)) - 1], 3),
                     "p99_ms": round(times[math.ceil(0.99 * len(times)) - 1], 3),
                     "client_cpu_mean_ms": round(statistics.mean(cpu for _, cpu in samples), 3)}}


def run(work: Path, port: int, repetitions: int) -> None:
    # Files are written only after the new database is bound to a program-created random secret.
    secret_file = work / "pg.env"
    if secret_file.is_symlink() or secret_file.stat().st_mode & 0o077:
        raise ValueError("ISOLATED_SECRET_FILE_UNSAFE")
    password_record = secret_file.read_text().strip()
    if not re.fullmatch(r"POSTGRES_PASSWORD=[0-9a-f]{48}", password_record):
        raise ValueError("ISOLATED_SECRET_INVALID")
    password = password_record.removeprefix("POSTGRES_PASSWORD=")
    samples = load_frozen(work)
    os.environ["TZ"] = "Asia/Shanghai"
    import time
    time.tzset()
    import importlib.metadata

    start = perf_counter()
    engine = create_engine(URL.create(
        "postgresql+psycopg", username="postgres", password=password,
        host="127.0.0.1", port=port, database="guiyi_market_foundation_bench",
    ), hide_parameters=True, connect_args={"connect_timeout": 5})
    with engine.connect() as connection:
        if connection.scalar(text("SELECT current_database()")) != "guiyi_market_foundation_bench":
            raise ValueError("ISOLATED_DB_NAME_INVALID")
        if connection.scalar(text("SELECT count(*) FROM pg_tables WHERE schemaname = 'public'")):
            raise ValueError("ISOLATED_DB_NOT_EMPTY")
    root = work / "candidate"
    root.mkdir(mode=0o700)
    canonical = Canonical(engine, root)
    Base.metadata.create_all(engine, tables=[MarketDataset.__table__, MarketPartition.__table__])
    native = Native(port, password)
    inventory = dict(versions={name: importlib.metadata.version(name)
        for name in ("vnpy", "vnpy_postgresql", "peewee", "pyarrow", "sqlalchemy")},
        machine=platform.machine(), host_version=platform.mac_ver()[0],
        frozen_manifest_sha256=digest(work / "frozen" / "manifest.json"))

    eligible = [sample for sample in samples if sample.key.frequency.value in PORTABLE_INTERVALS]
    rb, = [sample for sample in samples if sample.name == "rb-MAIN-1m"]
    initial = rb.bars[0:next(i for i, bar in enumerate(rb.bars) if bar.trading_day == rb.bars[-1].trading_day)]
    increment = rb.bars[len(initial):]
    writes = {}
    reads = {}
    mismatch_counts: Counter[str] = Counter()
    concurrency = {}
    for backend, store in (("canonical", canonical), ("native_postgresql", native)):
        wall, cpu = perf_counter(), process_time()
        for sample in eligible:
            store.write(sample, initial if sample is rb else sample.bars)
        writes[backend] = {"initial_wall_ms": round(1000 * (perf_counter() - wall), 3),
                           "initial_client_cpu_ms": round(1000 * (process_time() - cpu), 3),
                           "initial_rows": sum(len(initial) if item is rb else len(item.bars) for item in eligible)}
        wall, cpu = perf_counter(), process_time()
        if backend == "canonical":
            prefix = tuple(row for row in initial
                           if row.trading_day.replace(day=1) == increment[0].trading_day.replace(day=1))
            store.write(rb, prefix + increment)
        else:
            store.write(rb, increment)
        writes[backend].update(increment_ms=round(1000 * (perf_counter()-wall), 3),
                               increment_client_cpu_ms=round(1000 * (process_time()-cpu), 3),
                               increment_rows=len(increment))
        if backend == "canonical":
            extra = [sample for sample in samples if sample not in eligible]
            wall = perf_counter()
            for sample in extra:
                store.write(sample, sample.bars)
            writes[backend].update(extra_interval_write_ms=round(1_000 * (perf_counter() - wall), 3),
                                   extra_interval_rows=sum(len(sample.bars) for sample in extra))

        supported = samples if backend == "canonical" else eligible
        for count in SIZES:
            window = rb.bars[-count:]
            def query():
                return store.read(rb, window)
            reads[f"{backend}/{count}"] = measure(query, store.cold, repetitions)
            returned = query()
            if backend == "canonical" and returned != window:
                raise ValueError("CANONICAL_ROUNDTRIP_MISMATCH")
        scan = [item for item in supported if item.key.frequency.value == "1m" and item.key.kind is DatasetKind.CONTINUOUS]
        def scan_products():
            return tuple(store.read(item, item.bars[-5_000:]) for item in scan)
        reads[f"{backend}/multi_product_25000"] = measure(scan_products, store.cold, repetitions)
        cu, = [item for item in scan if item.key.symbol == "cu"]
        concurrency[backend] = concurrent_readback(store, rb, cu, repetitions)
        for frequency in BarFrequency:
            frequency_sample = next((item for item in supported if item.key.symbol == "rb"
                                     and item.key.frequency is frequency), None)
            if frequency_sample is None:
                reads[f"{backend}/frequency/{frequency.value}"] = "UNSUPPORTED_INTERVAL"
                continue
            frequency_window = frequency_sample.bars[-500:]
            reads[f"{backend}/frequency/{frequency.value}"] = measure(
                lambda: store.read(frequency_sample, frequency_window), store.cold, repetitions)
        if backend == "native_postgresql":
            for sample in supported:
                mismatch_counts.update(mismatch(sample, sample.bars, store.read(sample, sample.bars)))

    def old_canonical_visible():
        if canonical.read(rb, increment) != increment:
            raise ValueError("CANONICAL_ROLLBACK_READBACK_INVALID")

    old_bar = increment[-1]
    updated_bar = replace(old_bar, open_interest=(old_bar.open_interest or Decimal(0)) + 1)
    updated = (*increment[:-1], updated_bar)
    canonical.write(rb, prefix + updated, commit=False, before_commit=old_canonical_visible)
    old_canonical_visible()
    canonical.write(rb, prefix + updated, before_commit=old_canonical_visible)
    if canonical.read(rb, updated) != updated:
        raise ValueError("CANONICAL_COMMIT_READBACK_INVALID")
    canonical.write(rb, prefix + increment)
    canonical.cold()
    engine.dispose()
    old_canonical_visible()

    from peewee import IntegrityError

    original_native = native.read(rb, increment)
    null_bar = replace(old_bar, turnover=None)
    altered_head = replace(increment[0], open_interest=(increment[0].open_interest or Decimal(0)) + 128)
    try:
        native.write(rb, (altered_head, *increment[1:-1], null_bar))
    except IntegrityError:
        pass
    else:
        raise ValueError("NATIVE_NULL_UNEXPECTEDLY_ACCEPTED")
    native.cold()
    if native.read(rb, increment) != original_native:
        raise ValueError("NATIVE_BATCH_ROLLBACK_INVALID")

    with engine.connect() as connection:
        sizes = {
            table: size for table, size in connection.execute(text(
                "SELECT tablename, pg_total_relation_size(format('%I.%I', schemaname, tablename)) "
                "FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
            ))
        }
        count_columns = dict(connection.execute(text(
            "SELECT column_name, data_type || '/' || is_nullable FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name='dbbardata' ORDER BY ordinal_position"
        )).tuples().all())
        pg_version = connection.scalar(text("SHOW server_version"))
    native.cold()
    engine.dispose()
    dump(work / "result.json", {
        "environment": inventory, "pg_server_version": pg_version, "writes": writes, "reads": reads,
        "native_mismatch_fields": dict(mismatch_counts), "native_columns": count_columns,
        "concurrent_day_updates": concurrency,
        "table_bytes": sizes, "parquet_bytes": sum(path.stat().st_size for path in root.rglob("*.parquet")),
        "peak_client_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "wall_seconds": round(perf_counter() - start, 3),
        "recovery": {"canonical_commit_visibility": "passed", "canonical_rollback_reopen": "passed",
                     "native_failed_chunk_rollback_reopen": "passed", "native_rejects_null": "confirmed"},
        "cache_scope": "first application read after decoded-cache clear/reconnection; no host disk-cache flush",
    })


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, required=True)
    subparsers = parser.add_subparsers(dest="action", required=True)
    freeze_parser = subparsers.add_parser("freeze")
    freeze_parser.add_argument("--config", type=Path, required=True)
    freeze_parser.add_argument("--through", type=date.fromisoformat, required=True)
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--port", type=int, required=True)
    run_parser.add_argument("--repetitions", default=15, type=int)
    args = parser.parse_args()
    try:
        work = args.work.resolve(strict=True)
        if work.parent != Path("/private/tmp") or not work.name.startswith("guiyi-v2-market-storage."):
            raise ValueError("ISOLATED_WORKSPACE_INVALID")
        if args.action == "freeze":
            freeze(work, args.config, args.through)
        else:
            if not 49152 <= args.port <= 65535 or not 5 <= args.repetitions <= 100:
                raise ValueError("ISOLATED_RUN_OPTIONS_INVALID")
            if Path.cwd() != work or not (work / ".vntrader").is_dir():
                raise ValueError("ISOLATED_VNTRADER_REQUIRED")
            run(work, args.port, args.repetitions)
    except Exception as exc:
        # SQL/SaaS errors can carry private URLs or statements. Only allow short codes.
        code = getattr(exc, "code", None)
        if code is None and type(exc) is ValueError:
            code = str(exc)
        if not isinstance(code, str) or re.fullmatch(r"[-_0-9A-Za-z]{1,100}", code) is None:
            code = type(exc).__name__
        print(code, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
