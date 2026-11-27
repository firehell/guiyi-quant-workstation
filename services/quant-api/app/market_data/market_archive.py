"""Verified post-close Market publication and retained receipt intake."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import json
import logging
import os
from pathlib import Path
import re
import stat
from urllib.parse import urlsplit

from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from typing import TYPE_CHECKING

from app.db.readonly import readonly_transaction
from app.market_data.after_market import (
    AfterMarketUpdater, _evidence_hash, public_after_market_status,
)
from app.market_data.after_market_history import _bytes, publish_history
from app.market_data.catalog import CatalogPartition
from app.market_data.domain import BarFrequency, ContractTradingDayQuery, INTRADAY_FREQUENCIES
from app.market_data.historical_data_manager import HistoricalDataManager
from app.market_data.live_market import RedisLiveStore
from app.market_data.live_recovery_guard import after_market_recovery_guard
from app.market_data.market_foundation_scope import bind_market_redis
from app.market_data.newow.after_market_consumer_audit import catalog_revision
from app.market_data.operational_universe import load_operational_products
from app.market_data.session_clock import SHANGHAI
from app.services.newow_reference_mode import require_isolated_redis

if TYPE_CHECKING:
    from app.compute_runtime.canonical_publications import CanonicalPublicationCompute


FREQUENCIES = tuple(frequency.value for frequency in BarFrequency)
RECEIPT_DIRECTORY = "market-archive-receipts"
_CLEANUP_DIRECTORY = "market-archive-cleanup"
_MAX_DAY_SCOPE_PROOFS = 64


@dataclass(frozen=True)
class MarketArchiveReceipt:
    identity: str
    trading_day: date
    finished_at: datetime
    revisions: Mapping[str, str]


def archive_receipt(status: object, *, now: datetime) -> MarketArchiveReceipt | None:
    public = public_after_market_status(status)
    run = public.get("last_run") or {}
    evidence = run.get("live_evidence") or {}
    revisions = evidence.get("canonical_readback")
    if (public.get("current_run") is not None or run.get("status") != "passed"
            or run["trading_day"] != public.get("last_successful_trading_day")
            or not isinstance(run.get("historical_publications"), list)
            or evidence.get("cleanup_verified") is not True or revisions is None):
        return None
    started = datetime.fromisoformat(run["started_at"])
    finished = datetime.fromisoformat(run["finished_at"])
    if not started <= datetime.fromisoformat(evidence["cleanup_checked_at"]) <= finished <= now:
        return None
    # A successful retry with identical inputs is one logical publication.
    identity = _evidence_hash({"trading_day": run["trading_day"], "revisions": revisions})
    return MarketArchiveReceipt(identity, date.fromisoformat(run["trading_day"]), finished, revisions)


def _cleanup_scope(sandbox: Path, day: date, products: tuple[str, ...]) -> Path:
    return sandbox / _CLEANUP_DIRECTORY / day.isoformat() / _evidence_hash(sorted(products))


def retain_archive_receipt(
    status_path: Path, *, now: datetime, archive_root: Path | None = None,
) -> Path | None:
    try:
        status = json.loads(_bytes(status_path))
    except FileNotFoundError:
        return
    return retain_archive_status(
        status, now=now, archive_root=archive_root or status_path.parent, formal=archive_root is not None,
    )


def retain_archive_status(
    status: dict, *, now: datetime, archive_root: Path, formal: bool,
) -> Path | None:
    """Retain verified archive evidence independently of the mutable natural-run status."""
    status = public_after_market_status(status)
    receipt = archive_receipt(status, now=now)
    if receipt is None:
        return
    sandbox = archive_root
    if formal:
        sandbox.mkdir(mode=0o700, exist_ok=True)
        info = sandbox.lstat()
        if (not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o700
                or info.st_uid != os.getuid() or sandbox.resolve() != sandbox):
            raise ValueError("MARKET_FORMAL_ARCHIVE_ROOT_INVALID")
    target = sandbox / RECEIPT_DIRECTORY / f"{receipt.identity}.json"
    try:
        _read_archive_receipt(target, now=now)
    except FileNotFoundError:
        publish_history(target, status)
    run = status["last_run"]
    products = tuple(run["products"])
    rank1 = run["live_evidence"]["formal_rank1_sha256"]
    scope_path = _cleanup_scope(sandbox, receipt.trading_day, products) / f"{rank1}.json"
    if retained_cleanup_receipt(
        sandbox, day=receipt.trading_day, now=now, products=products, formal_rank1_sha256=rank1,
    ) is None:
        # Each exact rank1 map needs one verified cleanup. Later Canonical
        # revisions retain their own receipts without replacing this proof.
        publish_history(scope_path, {"receipt": receipt.identity})
    if formal:
        from app.runtime_handover import _read, _write

        pointer = archive_root / "latest-receipt.json"
        previous = _read(pointer)
        if previous is None or previous.get("receipt") != receipt.identity:
            if previous is not None:
                prior = _open_formal_receipt(archive_root, previous, now=now)
                # A verified older-day repair remains directly claimable by SHA.
                if (receipt.trading_day, receipt.finished_at) < (prior.trading_day, prior.finished_at):
                    return target
            _write(pointer, {"receipt": receipt.identity})
    return target


def _read_archive_receipt(path: Path, *, now: datetime) -> tuple[MarketArchiveReceipt, dict]:
    status = public_after_market_status(json.loads(_bytes(path)))
    receipt = archive_receipt(status, now=now)
    if receipt is None or path.name != f"{receipt.identity}.json":
        raise ValueError("MARKET_ARCHIVE_RECEIPT_INVALID")
    return receipt, status["last_run"]


def read_archive_receipt(path: Path, *, now: datetime) -> MarketArchiveReceipt:
    return _read_archive_receipt(path, now=now)[0]


def retained_cleanup_receipt(
    sandbox: Path, *, day: date, now: datetime, products: tuple[str, ...],
    formal_rank1_sha256: str | None = None,
) -> Mapping[str, object] | None:
    """Read exact immutable day/scope cleanup proof even after a later failed run."""
    if not products or len(products) != len(set(products)):
        return None
    scope_path = _cleanup_scope(sandbox, day, products)
    if formal_rank1_sha256 is not None:
        if re.fullmatch(r"[0-9a-f]{64}", formal_rank1_sha256) is None:
            raise ValueError("MARKET_ARCHIVE_CLEANUP_RECEIPT_INVALID")
        candidates = (scope_path / f"{formal_rank1_sha256}.json",)
    else:
        from itertools import islice

        try:
            candidates = tuple(islice(scope_path.iterdir(), _MAX_DAY_SCOPE_PROOFS + 1))
        except FileNotFoundError:
            return None
        if len(candidates) > _MAX_DAY_SCOPE_PROOFS:
            raise ValueError("MARKET_ARCHIVE_CLEANUP_SCOPE_LIMIT")
    for path in candidates:
        if re.fullmatch(r"[0-9a-f]{64}\.json", path.name) is None:
            continue
        try:
            index = json.loads(_bytes(path))
        except FileNotFoundError:
            continue
        identity = index["receipt"] if isinstance(index, dict) and set(index) == {"receipt"} else None
        if not isinstance(identity, str) or re.fullmatch(r"[0-9a-f]{64}", identity) is None:
            raise ValueError("MARKET_ARCHIVE_CLEANUP_RECEIPT_INVALID")
        receipt, run = _read_archive_receipt(sandbox / RECEIPT_DIRECTORY / f"{identity}.json", now=now)
        evidence = run["live_evidence"]
        if (receipt.trading_day != day or set(run["products"]) != set(products)
                or evidence["formal_rank1_sha256"] != path.stem):
            raise ValueError("MARKET_ARCHIVE_CLEANUP_RECEIPT_INVALID")
        return evidence
    return None


def verified_retained_cleanup(store, root: Path, *, day: date, products: tuple[str, ...], now: datetime) -> dict | None:
    evidence = retained_cleanup_receipt(root, day=day, products=products, now=now)
    if evidence is None:
        return None
    actual = store.cleanup_readback(day)
    if actual != {"remaining_bar_keys": 0, "subscription_present": False}:
        return None
    return {**evidence, **actual}


def _partition_identity(partition: CatalogPartition) -> tuple[str, str, str, str, int, int]:
    key = partition.dataset
    return key.kind.value, key.symbol, key.series_or_contract, key.frequency.value, partition.year, partition.month


@contextmanager
def verified_archive_readback(
    open_manager: Callable[[], HistoricalDataManager],
    products: tuple[str, ...],
    trading_day: date,
    publications: list[dict[str, object]],
    *,
    verify_rank1_day: bool = False,
) -> Iterator[Mapping[str, str]]:
    """Verify fresh committed pointers and the full daily plan before evicting Live."""
    with open_manager() as manager:
        lock = manager.catalog.acquire_maintenance_lock(caller="market-archive-readback")
        if lock is None:
            raise ValueError("MAINTENANCE_LOCKED")
        try:
            with readonly_transaction(manager.catalog.session, timeout_seconds=120):
                if manager._plan_daily_recovery(products, trading_day).planned_targets:
                    raise ValueError("MARKET_ARCHIVE_SCOPE_INCOMPLETE")
                expected = {(*item["dataset"], item["year"], item["month"]): item["file_name"]
                            for item in publications}
                revisions = {}
                for product in products:
                    for partition in manager.catalog.product_partitions(product):
                        identity = _partition_identity(partition)
                        if identity in expected:
                            if partition.file_path.name != expected.pop(identity):
                                raise ValueError("MARKET_ARCHIVE_POINTER_CHANGED")
                            manager.store.read_catalog_partition_quality(partition)
                    if verify_rank1_day:
                        _verify_rank1_day(manager, product, trading_day)
                    revisions[product] = reference_catalog_revision(
                        manager.catalog.session, product, trading_day, archive_scope=verify_rank1_day,
                    )
                if expected:
                    raise ValueError("MARKET_ARCHIVE_POINTER_MISSING")
                yield revisions
        finally:
            lock.release()


def _verify_rank1_day(manager: HistoricalDataManager, symbol: str, day: date) -> None:
    """Even a no-op must read the day's active physical bars and quality facts."""
    from app.market_data.market_data_service import MarketDataService

    reader = MarketDataService(manager.catalog, manager.store)
    owner = reader.dominant_segment_for_day(symbol, day).contract
    sessions = reader.session_windows(symbol=symbol, trading_day=day)
    close = sessions[-1].end
    for frequency in INTRADAY_FREQUENCIES:
        reader.query_contract_trading_days(ContractTradingDayQuery(symbol, owner, frequency, day, day))
    bars, breaks = reader.query_contract_replay_quality_union(
        symbol=symbol, contract=owner, through=day, cutoff=close, since=day,
    )
    if tuple((row.bar_end, row.trading_day) for row in (*bars, *breaks)) != ((close, day),):
        raise ValueError("MARKET_ARCHIVE_DAILY_ENDPOINT_UNPROVEN")
    monday = day - timedelta(days=day.weekday())
    week = tuple(date_ for date_, trading in reader.calendar_week_facts(symbol=symbol, week_monday=monday) if trading)
    if not week or day not in week:
        raise ValueError("MARKET_ARCHIVE_CALENDAR_UNPROVEN")
    if day == week[-1]:
        bars, interruptions = reader.query_contract_weekly_replay_quality(
            symbol=symbol, contract=owner, through=day, cutoff=close, since=monday,
        )
        if not bars and not interruptions:
            # A weekly contract whose lifecycle started during the week has
            # no required W1 endpoint under the existing expectation rules.
            expected = reader.expected_contract_replay_endpoints(
                symbol=symbol, contract=owner, frequency=BarFrequency.W1,
                trading_day=day, cutoff=close, since=monday,
            )
            if expected:
                raise ValueError("MARKET_ARCHIVE_WEEKLY_ENDPOINT_UNPROVEN")


def reference_catalog_revision(
    session: Session, product: str, day: date, *, archive_scope: bool = False,
) -> str:
    return catalog_revision(session, (product,), day, FREQUENCIES, archive_scope=archive_scope)


def formal_after_market_status_path() -> Path:
    from app.runtime_bindings import resolve_service_binding

    binding = resolve_service_binding("after-market")
    if binding is None or not binding.enabled:
        raise ValueError("MARKET_FORMAL_ARCHIVE_OWNER_UNPROVEN")
    root = Path(binding.root) / ".run"
    if not root.is_absolute() or root.resolve() != root:
        raise ValueError("MARKET_FORMAL_ARCHIVE_ROOT_INVALID")
    return root / "after-market-status.json"


def formal_archive_root() -> Path:
    """Receipt files, acknowledgements and saved sections survive release rotation."""
    from app.runtime_handover import runtime_directory

    formal_after_market_status_path()
    root = runtime_directory() / "market-foundation"
    if not root.is_absolute() or root.resolve() != root:
        raise ValueError("MARKET_FORMAL_ARCHIVE_ROOT_INVALID")
    return root


def _open_formal_receipt(root: Path, pointer: dict, *, now: datetime) -> MarketArchiveReceipt:
    identity = pointer.get("receipt")
    if (set(pointer) != {"receipt"} or type(identity) is not str
            or re.fullmatch(r"[0-9a-f]{64}", identity) is None):
        raise ValueError("MARKET_ARCHIVE_RECEIPT_INVALID")
    return read_archive_receipt(root / RECEIPT_DIRECTORY / f"{identity}.json", now=now)


def current_retained_receipt(root: Path, *, now: datetime) -> MarketArchiveReceipt | None:
    from app.runtime_handover import _read

    pointer = _read(root / "latest-receipt.json")
    return None if pointer is None else _open_formal_receipt(root, pointer, now=now)


def require_isolated_archive(url: URL, redis_url: str, canonical_root: Path) -> Path:
    require_isolated_redis(redis_url)
    sandbox = Path(os.environ.get("GUIYI_MARKET_FOUNDATION_SANDBOX", ""))
    if (not sandbox.is_absolute() or sandbox.resolve(strict=True) != sandbox
            or not sandbox.is_dir()
            or canonical_root != sandbox / "canonical" or not canonical_root.is_dir()
            or canonical_root.is_symlink()
            or url.get_backend_name() != "postgresql" or url.host != "127.0.0.1"
            or url.port in {None, 5432} or url.database != "guiyi_market_foundation"
            or url.query):
        raise ValueError("MARKET_FOUNDATION_ISOLATION_REQUIRED")
    return sandbox


def isolated_archive_products(raw: str) -> tuple[str, ...]:
    products = tuple(raw.split(","))
    allowed = set(load_operational_products())
    if "" in products or len(products) != len(set(products)) or not set(products) <= allowed:
        raise ValueError("MARKET_ARCHIVE_SCOPE_INVALID")
    return products


def build_isolated_archive(
    manager: HistoricalDataManager, *,
    redis_url: str, live_store: RedisLiveStore, rqdata_factory, sleep,
    products: tuple[str, ...] | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(SHANGHAI),
    canonical_compute: CanonicalPublicationCompute | None = None,
) -> AfterMarketUpdater:
    """Compose one explicit sandbox without notification, RQAlpha or Runtime state."""
    from app.market_data.composition import build_historical_data_manager

    bind = manager.catalog.session.get_bind()
    canonical_root = manager.catalog.canonical_root
    sandbox = require_isolated_archive(bind.url, redis_url, canonical_root)
    if canonical_compute is not None and (
        canonical_compute.engine is not bind or canonical_compute.canonical_root != canonical_root
    ):
        raise ValueError("COMPUTE_CANONICAL_BINDING_MISMATCH")
    guard_root = sandbox / "live-recovery-guards"
    redis = live_store._redis
    expected = urlsplit(redis_url)
    options = redis.connection_pool.connection_kwargs
    if (options.get("host"), options.get("port"), options.get("db", 0)) != (
        expected.hostname, expected.port, int(expected.path.lstrip("/") or "0"),
    ):
        raise ValueError("MARKET_FOUNDATION_REDIS_BINDING_CONFLICT")
    products = isolated_archive_products(",".join(products or ()))

    @contextmanager
    def archive_guard():
        with after_market_recovery_guard(root=guard_root, wait=True, legacy_root=True):
            bind_market_redis(redis, sandbox, bind.url)
            yield

    def refresh_consumers(path, day):
        from app.market_data.newow.market_reference_after_close import run_receipt

        if canonical_compute is not None:
            try:
                canonical_compute.accept(path, day)
            except (OSError, RuntimeError, ValueError, SQLAlchemyError):
                logging.getLogger(__name__).warning("market_archive_compute_pending")
        try:
            receipt = read_archive_receipt(path, now=now())
            if receipt.trading_day != day:
                raise ValueError("MARKET_ARCHIVE_RECEIPT_INVALID")
            run_receipt(sandbox, receipt, session_factory=lambda: Session(bind))
        except (OSError, RuntimeError, ValueError, SQLAlchemyError):
            # Market status and the immutable receipt survive a separate consumer failure.
            logging.getLogger(__name__).warning("market_archive_reference_pending")

    @contextmanager
    def open_manager():
        with Session(bind) as session:
            yield build_historical_data_manager(session, data_root=canonical_root)

    return AfterMarketUpdater(
        manager=manager,
        rqdata=None,
        rqdata_factory=rqdata_factory,
        live_store=live_store,
        status_path=sandbox / "after-market-status.json",
        sleep=sleep,
        notification_transport=None,
        now=now,
        products=products,
        archive_readback=lambda products, day, publications: verified_archive_readback(
            open_manager, products, day, publications,
        ),
        recovery_guard_factory=archive_guard,
        research_update=refresh_consumers,
    )
