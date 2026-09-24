"""CLI composition for Runtime-bound current-day metadata recovery."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import stat
from types import SimpleNamespace
from typing import Any, Iterator, cast

from app.market_data.current_day_metadata_recovery import (
    CurrentDayMetadataRecoveryError,
    apply_current_day_metadata,
    encode_current_day_snapshot,
    import_frozen_current_day_capture,
    plan_current_day_metadata,
)
from app.market_data.closeout_binding import RuntimeRecoveryBindingError


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


def _read_capture(path_value: str) -> bytes:
    """Pin one bounded regular file; never follow a source-data symlink."""
    try:
        path = Path(path_value)
        if not path.is_absolute() or path.resolve(strict=True) != path:
            raise ValueError
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as source:
            before = os.fstat(source.fileno())
            if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= _MAX_SNAPSHOT_BYTES:
                raise ValueError
            content = source.read(_MAX_SNAPSHOT_BYTES + 1)
            after = os.fstat(source.fileno())
            if (
                len(content) != before.st_size
                or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            ):
                raise ValueError
            return content
    except (OSError, ValueError, TypeError):
        raise CurrentDayMetadataRecoveryError("CAPTURE_INVALID") from None


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

    binding = RuntimeDataBinding(
        root, commit, status_sha256, allow_failed_terminal=True,
        allow_calendar_metadata_failure=phase in {"import", "plan", "apply"},
    )
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
                failure_code=binding.failure_code,
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
        except RuntimeRecoveryBindingError:
            raise
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
        if args.phase == "import":
            return import_frozen_current_day_capture(
                _read_capture(args.capture),
                expected_capture_sha256=args.expected_capture_sha256,
                products=runtime.products,
                trading_day=args.trading_day,
            )
        snapshot_payload = _read_snapshot(args.snapshot)
        source = snapshot_payload.get("source")
        frozen = isinstance(source, dict) and source.get("method") == "frozen_rqdata_capture"
        if getattr(runtime, "failure_code", None) == "CALENDAR_NIGHT_AUTHORITY_MISSING" and not frozen:
            raise CurrentDayMetadataRecoveryError("CAPTURE_REQUIRED")
        if frozen:
            assert isinstance(source, dict)
            if (
                not getattr(args, "capture", None)
                or not getattr(args, "expected_capture_sha256", None)
                or source.get("capture_sha256") != args.expected_capture_sha256
            ):
                raise CurrentDayMetadataRecoveryError("CAPTURE_REQUIRED")
        elif getattr(args, "capture", None) or getattr(args, "expected_capture_sha256", None):
            raise CurrentDayMetadataRecoveryError("CAPTURE_INVALID")

        def verify_frozen_capture() -> None:
            if not frozen:
                return
            content = _read_capture(args.capture)
            if hashlib.sha256(content).hexdigest() != args.expected_capture_sha256:
                raise CurrentDayMetadataRecoveryError("CAPTURE_HASH_INVALID")
            replayed = import_frozen_current_day_capture(
                content,
                expected_capture_sha256=args.expected_capture_sha256,
                products=runtime.products,
                trading_day=args.trading_day,
            )
            if replayed["snapshot_sha256"] != args.expected_snapshot_sha256:
                raise CurrentDayMetadataRecoveryError("CAPTURE_SNAPSHOT_MISMATCH")

        verify_frozen_capture()
        if args.phase == "plan":
            return plan_current_day_metadata(
                runtime.catalog,
                snapshot_payload,
                expected_snapshot_sha256=args.expected_snapshot_sha256,
                products=runtime.products,
                trading_day=args.trading_day,
            )
        def verify_apply_identity() -> None:
            runtime.verify_identity()
            verify_frozen_capture()

        return apply_current_day_metadata(
            runtime.synchronizer,
            snapshot_payload,
            expected_snapshot_sha256=args.expected_snapshot_sha256,
            expected_plan_sha256=args.expected_plan_sha256,
            products=runtime.products,
            trading_day=args.trading_day,
            acquire_maintenance_lock=runtime.catalog.acquire_maintenance_lock,
            verify_identity=verify_apply_identity,
        )


class _NoProvider:
    """A capability boundary: plan/apply cannot initialize or call RQData."""

    def fetch_metadata(self, *_args, **_kwargs):
        raise AssertionError("provider is unavailable in plan/apply")

    def fetch_current_day_metadata(self, *_args, **_kwargs):
        raise AssertionError("provider is unavailable in plan/apply")
