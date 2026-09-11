"""CLI composition for Runtime-bound current-day metadata recovery."""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterator, cast

from app.market_data.current_day_metadata_recovery import (
    CurrentDayMetadataRecoveryError,
    apply_current_day_metadata,
    encode_current_day_snapshot,
    plan_current_day_metadata,
)


_MAX_SNAPSHOT_BYTES = 16 * 1024 * 1024


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise CurrentDayMetadataRecoveryError("PAYLOAD_INVALID")
        result[key] = value
    return result


def _read_snapshot(path: str) -> dict[str, Any]:
    try:
        with Path(path).open("rb") as source:
            content = source.read(_MAX_SNAPSHOT_BYTES + 1)
        if not content or len(content) > _MAX_SNAPSHOT_BYTES:
            raise ValueError
        value = json.loads(content, object_pairs_hook=_unique_object)
        if not isinstance(value, dict):
            raise ValueError
        return value
    except CurrentDayMetadataRecoveryError:
        raise
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        raise CurrentDayMetadataRecoveryError("PAYLOAD_INVALID") from None


@contextmanager
def open_runtime_bound_current_day_metadata(
    root: Path,
    commit: str,
    status_sha256: str,
    *,
    phase: str,
) -> Iterator[Any]:
    """Build provider only for capture; plan/apply have no provider capability."""
    from datetime import datetime

    from redis import Redis
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.db.url import normalize_database_url
    from app.market_data.catalog import MarketCatalog
    from app.market_data.closeout_binding import RuntimeDataBinding, _redis_url
    from app.market_data.live_market import RedisClient, RedisLiveStore
    from app.market_data.metadata import MetadataSynchronizer
    from app.market_data.rqdata_adapter import RQDataMarketAdapter
    from app.market_data.session_clock import SHANGHAI

    binding = RuntimeDataBinding(root, commit, status_sha256)
    engine = create_engine(normalize_database_url(binding.settings["DATABASE_URL"]))
    redis = None
    try:
        redis = Redis.from_url(_redis_url(binding.settings))
        store = RedisLiveStore(cast(RedisClient, redis))
        with Session(engine, autoflush=False) as session:
            catalog = MarketCatalog(
                session, Path(binding.settings["GUIYI_CANONICAL_DATA_ROOT"])
            )
            adapter = (
                RQDataMarketAdapter(session=session, provider_settings=binding.settings)
                if phase == "capture"
                else _NoProvider()
            )
            synchronizer = MetadataSynchronizer(adapter, catalog)

            def verify_identity() -> None:
                binding.check_catalog(
                    catalog,
                    session,
                    redis,
                    store,
                    lambda: datetime.now(SHANGHAI),
                )

            yield SimpleNamespace(
                products=binding.products,
                adapter=adapter,
                synchronizer=synchronizer,
                catalog=catalog,
                verify_identity=verify_identity,
            )
    finally:
        try:
            if redis is not None:
                redis.close()
        finally:
            engine.dispose()


def run_current_day_metadata_recovery(
    args,
    *,
    runtime_context_factory=open_runtime_bound_current_day_metadata,
) -> dict[str, Any]:
    """Execute exactly one capture, read-only plan, or one lease-bound apply."""
    with runtime_context_factory(
        Path(args.runtime_root),
        args.runtime_commit,
        args.expected_status_sha256,
        phase=args.phase,
    ) as runtime:
        try:
            runtime.verify_identity()
        except Exception:
            raise CurrentDayMetadataRecoveryError("RUNTIME_IDENTITY_DRIFT") from None
        if args.phase == "capture":
            snapshot = runtime.synchronizer.capture_current_day(
                runtime.products, args.trading_day
            )
            return encode_current_day_snapshot(
                snapshot,
                products=runtime.products,
                trading_day=args.trading_day,
            )
        snapshot_payload = _read_snapshot(args.snapshot)
        if args.phase == "plan":
            return plan_current_day_metadata(
                runtime.catalog,
                snapshot_payload,
                expected_snapshot_sha256=args.expected_snapshot_sha256,
                products=runtime.products,
                trading_day=args.trading_day,
            )
        return apply_current_day_metadata(
            runtime.synchronizer,
            snapshot_payload,
            expected_snapshot_sha256=args.expected_snapshot_sha256,
            expected_plan_sha256=args.expected_plan_sha256,
            products=runtime.products,
            trading_day=args.trading_day,
            acquire_maintenance_lock=runtime.catalog.acquire_maintenance_lock,
            verify_identity=runtime.verify_identity,
        )


class _NoProvider:
    """A capability boundary: plan/apply cannot initialize or call RQData."""

    def fetch_metadata(self, *_args, **_kwargs):
        raise AssertionError("provider is unavailable in plan/apply")

    def fetch_current_day_metadata(self, *_args, **_kwargs):
        raise AssertionError("provider is unavailable in plan/apply")
