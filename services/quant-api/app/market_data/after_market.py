"""有界盘后历史维护入口。

该模块不维护队列、检查点或重试状态。每次运行仅检查一次、最多等待一小时后再尝试一次，
并将可公开观察的结果写到本地状态文件。
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import stat
import tempfile
import time
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from app.alerts.notification import (
    ALERT_AUDIENCE_OWNER,
    NotificationDelivery,
    NotificationTransport,
    ProviderAcceptance,
)
from app.core.env import PROJECT_ROOT
from app.market_data.errors import InfrastructureError
from app.market_data.historical_data_manager import HistoricalDataManager, MaintenanceProgressEvent, UpdateRequest
from app.market_data.live_market import RedisLiveStore
from app.market_data.live_recovery_guard import after_market_recovery_guard
from app.market_data.operational_universe import load_operational_products
from app.market_data.rqdata_adapter import RQDataClient
from app.market_data.session_clock import SHANGHAI
from app.market_data.storage import StorageError


_LOGGER = logging.getLogger(__name__)
_MARKET_HOME_PROJECTION_ACTIVATION_MARKER = (
    PROJECT_ROOT / ".run" / "market-home-projection-enabled"
)
_MARKET_HOME_PROJECTION_ACTIVATION_MARKER_MAX_BYTES = 32
_PUBLIC_ERROR_CODES = frozenset(
    {
        "MAINTENANCE_LOCKED",
        "LIVE_DOMINANT_MISMATCH",
        "NON_TRADING_DAY",
        "NEXT_TRADING_SESSION_NOT_READY",
        "PROVIDER_QUOTA_EXHAUSTED",
        "RQDATA_NOT_READY",
        "RQDATA_READY_CHECK_FAILED",
        "UPDATE_FAILED",
        "COMMIT_OUTCOME_UNKNOWN",
        "HISTORICAL_MAINTENANCE_REQUIRED",
    }
)
_PUBLIC_PRODUCT_CODE = re.compile(r"[a-z]{1,4}\Z")
_PUBLIC_NOTIFICATION_ERROR_TYPES = frozenset(
    {
        "ALERT_NOTIFICATION_CONFIG_INVALID",
        "ALERT_NOTIFICATION_TRANSPORT_FAILED",
        "ALERT_NOTIFICATION_TRANSPORT_INVALID",
    }
)


def _diagnostic_warning(template: str, *args: object) -> None:
    """Only fixed call-site templates and bounded values can reach any handler."""
    allowed = _PUBLIC_ERROR_CODES | {
        "RQDATA_READY_RESPONSE_INVALID", "UNEXPECTED_PROVIDER_EXCEPTION",
        "UNEXPECTED_UPDATE_EXCEPTION", "UNEXPECTED_LIVE_EXCEPTION",
        "InfrastructureError", "RuntimeError", "ValueError", "TypeError", "OSError",
        "StorageError", "passed", "noop", "failed", "blocked", "partial",
    }
    safe = tuple(arg if (type(arg) is int and arg in {1, 2})
                 or (isinstance(arg, str) and arg in allowed) else "REDACTED" for arg in args)
    try:
        message = template % safe
        fields = dict(re.findall(r"(stage|detail_code|attempt)=([A-Za-z0-9_]+)", message))
        if "attempt" in fields:
            fields["attempt"] = int(fields["attempt"])
        _LOGGER.warning(message, extra={"diagnostic_code": "AFTER_MARKET_DIAGNOSTIC", "diagnostic_fields": fields})
    except Exception:
        pass


@dataclass(frozen=True, slots=True)
class AfterMarketResult:
    """盘后命令的公开、无敏感信息结果。"""

    status: str
    trading_day: date
    attempts: int
    error_code: str | None

    def as_payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "command": "data.after-market",
            "status": self.status,
            "trading_day": self.trading_day.isoformat(),
            "attempts": self.attempts,
            "error_code": self.error_code,
        }


class _ProgressPersistenceError(RuntimeError):
    code = "AFTER_MARKET_PROGRESS_UNAVAILABLE"

    def __init__(self) -> None:
        super().__init__(self.code)


class AfterMarketUpdater:
    """18:05 本地盘后维护；Canonical 写入仍只经过 HistoricalDataManager。"""

    def __init__(
        self,
        *,
        manager: HistoricalDataManager,
        rqdata: RQDataClient,
        live_store: RedisLiveStore,
        status_path: Path,
        sleep: Callable[[float], None],
        notification_transport: NotificationTransport | None,
        now: Callable[[], datetime],
        market_home_projection_invalidate: Callable[[], None] | None = None,
        market_home_projection_refresh: Callable[[], object] | None = None,
        recovery_guard_factory: Callable[[], AbstractContextManager] | None = None,
    ) -> None:
        self.manager = manager
        self.rqdata = rqdata
        self.live_store = live_store
        self.status_path = status_path
        self.sleep = sleep
        self.notification_transport = notification_transport
        self.now = now
        self.market_home_projection_invalidate = market_home_projection_invalidate
        self.market_home_projection_refresh = market_home_projection_refresh
        self.recovery_guard_factory = recovery_guard_factory or nullcontext
        self.monotonic = time.monotonic
        self._current: dict[str, Any] = {}
        self._progress_failed = False
        self._last_progress_write = 0.0

    def run(self) -> AfterMarketResult:
        """执行一次受限盘后维护，并写入仅含公开字段的状态。"""
        with self.recovery_guard_factory():
            return self._run_guarded()

    def _run_guarded(self) -> AfterMarketResult:
        started_at = _local_timestamp(self.now())
        products = load_operational_products()
        self._write_current_run(started_at, products)
        # 先用仅依赖 Calendar 的日期判断今天是否为交易日。当天 Session 正是下方
        # manager.update() 要同步的 metadata，不能反过来把它作为进入更新的前置条件。
        trading_day = self.manager.coverage.latest_metadata_day(products)
        if trading_day != started_at.date():
            result = AfterMarketResult(
                status="skipped",
                trading_day=trading_day,
                attempts=0,
                error_code="NON_TRADING_DAY",
            )
            self._write_status(result, started_at, products)
            return result

        error_code: str | None = None
        for attempt in (1, 2):
            self._current.update(attempt=attempt, counters={}, stage_durations={}, retry_at=None)
            self._stage("rqdata_readiness")
            error_code = self._attempt(
                products,
                trading_day,
                attempt=attempt,
            )
            if error_code is None:
                # Projection is a performance-only derived read model. Refresh only
                # after Canonical publication, canonical_updated, reconciliation and
                # Live cleanup have all completed successfully.
                self._refresh_market_home_projection()
                result = AfterMarketResult("passed", trading_day, attempt, None)
                self._write_status(result, started_at, products)
                return result
            if attempt == 1 and error_code == "NEXT_TRADING_SESSION_NOT_READY":
                self._current["retry_at"] = (_local_timestamp(self.now()) + timedelta(hours=1)).isoformat()
                self._stage("retry_wait")
                self.sleep(3600)
                continue
            break

        result = AfterMarketResult("failed", trading_day, attempt, error_code)
        self._write_status(result, started_at, products)
        if self.notification_transport is not None:
            notification = self._send_failure_notification(result)
            try:
                self._write_failure_notification(notification)
            except Exception as exc:  # noqa: BLE001 - primary failure remains authoritative
                _diagnostic_warning(
                    "after_market_notification_status_write_failed exception_type=%s",
                    type(exc).__name__,
                )
        return result

    def _send_failure_notification(
        self,
        result: AfterMarketResult,
    ) -> dict[str, object]:
        attempted_at = _local_timestamp(self.now()).isoformat()
        delivery = NotificationDelivery(
            audience=ALERT_AUDIENCE_OWNER,
            title="归一量化 盘后运维失败",
            content=(
                f"trading_day={result.trading_day.isoformat()}\n"
                f"error_code={result.error_code or 'UPDATE_FAILED'}\n"
                f"attempts={result.attempts}\n"
                "系统运维提醒，非交易指令"
            ),
        )
        try:
            transport = self.notification_transport
            if transport is None:
                raise TypeError("AFTER_MARKET_NOTIFICATION_CAPABILITY_MISSING")
            acceptance = transport.send(delivery)
            if not isinstance(acceptance, ProviderAcceptance):
                raise TypeError("AFTER_MARKET_PROVIDER_ACCEPTANCE_INVALID")
        except Exception as exc:  # noqa: BLE001 - notification is one-shot and isolated
            error_type = getattr(exc, "code", None)
            if error_type not in _PUBLIC_NOTIFICATION_ERROR_TYPES:
                error_type = "AFTER_MARKET_FAILURE_NOTIFICATION_FAILED"
            return {
                "attempted_at": attempted_at,
                "state": "failed",
                "error_type": error_type,
            }
        return {
            "attempted_at": attempted_at,
            "state": "provider_accepted",
            "error_type": None,
        }

    def _attempt(
        self,
        products: tuple[str, ...],
        trading_day: date,
        *,
        attempt: int,
    ) -> str | None:
        try:
            ready = self.rqdata.is_future_data_ready(trading_day)
        except Exception as exc:  # noqa: BLE001 - provider detail must not become public state
            detail_code = (
                exc.code
                if isinstance(exc, InfrastructureError)
                else "UNEXPECTED_PROVIDER_EXCEPTION"
            )
            _diagnostic_warning(
                "after_market_attempt_failed stage=rqdata_readiness attempt=%s "
                "detail_code=%s exception_type=%s",
                attempt,
                detail_code,
                type(exc).__name__,
            )
            return "RQDATA_READY_CHECK_FAILED"
        if not ready:
            return "RQDATA_NOT_READY"
        try:
            result = self.manager.update(
                UpdateRequest(
                    products=products,
                    since=None,
                    through=trading_day,
                    apply=True,
                    sync_current_day_metadata=True,
                    mode="daily",
                ),
                before_apply=self._invalidate_market_home_projection,
                observer=self._observe_progress,
            )
        except InfrastructureError as exc:
            if exc.code == "HISTORICAL_MAINTENANCE_REQUIRED":
                return exc.code
            if exc.code == "NEXT_TRADING_SESSION_NOT_READY":
                _diagnostic_warning(
                    "after_market_attempt_failed stage=metadata_readiness attempt=%s "
                    "detail_code=%s exception_type=%s",
                    attempt,
                    exc.code,
                    type(exc).__name__,
                )
                return exc.code
            _diagnostic_warning(
                "after_market_attempt_failed stage=canonical_update attempt=%s "
                "detail_code=UNEXPECTED_UPDATE_EXCEPTION exception_type=%s",
                attempt,
                type(exc).__name__,
            )
            return "UPDATE_FAILED"
        except Exception as exc:  # noqa: BLE001 - provider/catalog detail stays private
            if self._progress_failed:
                raise _ProgressPersistenceError() from None
            if isinstance(exc, StorageError) and exc.code == "COMMIT_OUTCOME_UNKNOWN":
                return exc.code
            if type(exc) is ValueError and exc.args == ("HISTORICAL_MAINTENANCE_REQUIRED",):
                return "HISTORICAL_MAINTENANCE_REQUIRED"
            _diagnostic_warning(
                "after_market_attempt_failed stage=canonical_update attempt=%s "
                "detail_code=UNEXPECTED_UPDATE_EXCEPTION exception_type=%s",
                attempt,
                type(exc).__name__,
            )
            return "UPDATE_FAILED"
        if result.status not in {"passed", "noop"}:
            error_code = _public_maintenance_failure_code(result.stop_reason)
            _diagnostic_warning(
                "after_market_attempt_failed stage=canonical_update_result attempt=%s "
                "detail_code=%s result_status=%s",
                attempt,
                error_code,
                result.status,
            )
            return error_code

        try:
            self._stage("canonical_updated")
            # A successful Canonical write must notify the Web seam even when the
            # temporary intraday snapshot disagrees with the formal map.
            self.live_store.publish_state(
                {
                    "trading_day": trading_day.isoformat(),
                    "reason": "canonical_updated",
                }
            )
            self._stage("live_reconciliation")
            if not _rank1_matches_live_snapshot(
                self.manager, self.live_store, products, trading_day
            ):
                _diagnostic_warning(
                    "after_market_attempt_failed stage=live_reconciliation attempt=%s "
                    "detail_code=LIVE_DOMINANT_MISMATCH",
                    attempt,
                )
                return "LIVE_DOMINANT_MISMATCH"
            self._stage("live_cleanup")
            self.live_store.cleanup_trading_day(trading_day)
        except Exception as exc:  # noqa: BLE001 - catalog/Redis detail stays private
            if self._progress_failed:
                raise _ProgressPersistenceError() from None
            _diagnostic_warning(
                "after_market_attempt_failed stage=live_reconciliation attempt=%s "
                "detail_code=UNEXPECTED_LIVE_EXCEPTION exception_type=%s",
                attempt,
                type(exc).__name__,
            )
            return "UPDATE_FAILED"
        return None

    def _invalidate_market_home_projection(self) -> None:
        if self.market_home_projection_invalidate is not None:
            self.market_home_projection_invalidate()

    def _refresh_market_home_projection(self) -> None:
        if self.market_home_projection_refresh is None:
            return
        self._stage("projection")
        try:
            self.market_home_projection_refresh()
        except Exception as exc:  # noqa: BLE001 - performance projection is isolated
            _diagnostic_warning(
                "market_home_projection_refresh_failed exception_type=%s",
                type(exc).__name__,
            )

    def _write_status(
        self,
        result: AfterMarketResult,
        started_at: datetime,
        products: tuple[str, ...],
    ) -> None:
        previous = _load_status(self.status_path)
        finished_at = _local_timestamp(self.now())
        schema_version = 3
        payload: dict[str, Any] = {
            "schema_version": schema_version,
            "current_run": None,
            "last_run": {
                "trading_day": result.trading_day.isoformat(),
                "status": result.status,
                "attempts": result.attempts,
                "started_at": started_at.isoformat(),
                "finished_at": finished_at.isoformat(),
                "products": list(products),
                "error_code": result.error_code,
                "failure_notification": None,
            },
            "last_successful_trading_day": _public_trading_day(
                previous.get("last_successful_trading_day")
            ),
            "last_failure": _public_last_failure(previous.get("last_failure")),
        }
        if result.status == "passed":
            payload["last_successful_trading_day"] = result.trading_day.isoformat()
            payload["last_failure"] = None
        elif result.status == "failed":
            payload["last_failure"] = {
                "trading_day": result.trading_day.isoformat(),
                "error_code": result.error_code,
            }
        _atomic_write_status(self.status_path, payload)

    def _write_failure_notification(self, notification: Mapping[str, object]) -> None:
        payload = _load_status(self.status_path)
        last_run = payload.get("last_run")
        if not isinstance(last_run, dict) or last_run.get("status") != "failed":
            raise RuntimeError("AFTER_MARKET_FAILURE_STATUS_UNAVAILABLE")
        last_run["failure_notification"] = dict(notification)
        _atomic_write_status(self.status_path, payload)

    def _write_current_run(
        self,
        started_at: datetime,
        products: tuple[str, ...],
    ) -> None:
        previous = _load_status(self.status_path)
        previous_schema_version = (
            int(previous["schema_version"])
            if previous.get("schema_version") in {2, 3}
            else 1
        )
        schema_version = 3
        self._progress_failed = False
        self._current = {
            "scheduled_date": started_at.date().isoformat(),
            "started_at": started_at.isoformat(),
            "products": list(products),
            "attempt": 0, "stage": "calendar", "updated_at": started_at.isoformat(),
            "current_partition": None, "current_symbol": None,
            "stage_started_at": started_at.isoformat(), "elapsed_seconds": 0.0,
            "counters": {}, "stage_durations": {}, "retry_at": None,
        }
        payload: dict[str, Any] = {
            "schema_version": schema_version,
            "current_run": self._current,
            "last_run": _public_last_run(
                previous.get("last_run"),
                schema_version=previous_schema_version,
            ),
            "last_successful_trading_day": _public_trading_day(
                previous.get("last_successful_trading_day")
            ),
            "last_failure": _public_last_failure(previous.get("last_failure")),
        }
        _atomic_write_status(self.status_path, payload)
        self._last_progress_write = self.monotonic()
        self._log_progress()

    def _log_progress(self) -> None:
        # A diagnostic copy of successfully persisted progress, never a checkpoint.
        # Reuse the public schema projection; neither raw objects nor exceptions reach logs.
        try:
            progress = _public_current_run(self._current, schema_version=3)
            if progress is not None:
                _LOGGER.info("AFTER_MARKET_PROGRESS", extra={"diagnostic_fields": {"progress": progress}})
        except Exception:
            pass

    def _stage(self, stage: str) -> None:
        self._current.update(stage=stage, current_partition=None, current_symbol=None,
                             stage_started_at=_local_timestamp(self.now()).isoformat())
        self._persist_progress()

    def _observe_progress(self, event: MaintenanceProgressEvent) -> None:
        changed = self._current["stage"] != event.phase
        if changed:
            self._current["stage_started_at"] = _local_timestamp(self.now()).isoformat()
        self._current["stage"] = event.phase
        self._current["current_symbol"] = event.symbol
        self._current["current_partition"] = (
            {"dataset": list(event.dataset), "year": event.year, "month": event.month}
            if event.dataset is not None else None
        )
        counter = {"completed": event.completed}
        if event.total is not None:
            counter["total"] = event.total
        self._current["counters"][event.phase] = counter
        if event.state == "completed":
            durations = self._current["stage_durations"]
            durations[event.phase] = durations.get(event.phase, 0.0) + event.elapsed_seconds
        if changed or self.monotonic() - self._last_progress_write >= 5:
            self._persist_progress()

    def _persist_progress(self) -> None:
        self._current["updated_at"] = _local_timestamp(self.now()).isoformat()
        self._current["elapsed_seconds"] = max(0.0, (
            _local_timestamp(self.now()) - datetime.fromisoformat(self._current["started_at"])
        ).total_seconds())
        try:
            payload = _load_status(self.status_path)
            if payload.get("schema_version") != 3 or not payload.get("current_run"):
                raise ValueError
            payload["current_run"] = self._current
            _atomic_write_status(self.status_path, payload)
        except Exception:
            self._progress_failed = True
            raise _ProgressPersistenceError() from None
        self._last_progress_write = self.monotonic()
        self._log_progress()


def build_after_market_updater(
    manager: HistoricalDataManager,
    *,
    failure_notification: bool,
) -> AfterMarketUpdater:
    """组装 CLI 盘后入口；只在该命令实际执行时才懒初始化 RQData client。"""
    provider = manager.provider
    client = getattr(provider, "client", None)
    if client is None:
        raise RuntimeError("AFTER_MARKET_RQDATA_CLIENT_UNAVAILABLE")
    from app.market_data.live_market import RedisClient
    from app.market_data.market_home_projection import (
        MarketHomeProjectionStore,
        market_home_projection_path,
    )
    from app.redis_connections import get_redis_connection
    from typing import cast

    projection_store = MarketHomeProjectionStore(
        market_home_projection_path(manager.catalog.canonical_root)
    )

    projection_refresh: Callable[[], object] | None = None
    if _market_home_projection_refresh_enabled():

        def refresh_market_home_projection() -> object | None:
            from app.market_data.composition import build_market_home_projection

            return _refresh_market_home_projection_with_lease(
                manager,
                lambda: build_market_home_projection(
                    manager.catalog.session
                ).refresh(),
            )

        projection_refresh = refresh_market_home_projection

    notification_transport: NotificationTransport | None = None
    if failure_notification:
        notification_transport = _ConfiguredNotificationTransport()
    return AfterMarketUpdater(
        manager=manager,
        rqdata=client,
        live_store=RedisLiveStore(cast(RedisClient, get_redis_connection())),
        status_path=PROJECT_ROOT / ".run" / "after-market-status.json",
        sleep=time.sleep,
        notification_transport=notification_transport,
        now=lambda: datetime.now(SHANGHAI),
        market_home_projection_invalidate=projection_store.invalidate,
        market_home_projection_refresh=projection_refresh,
        recovery_guard_factory=lambda: after_market_recovery_guard(wait=True),
    )


def _market_home_projection_refresh_enabled() -> bool:
    nofollow = getattr(os, "O_NOFOLLOW", None)
    nonblock = getattr(os, "O_NONBLOCK", None)
    if nofollow is None or nonblock is None:
        return False
    parent_descriptor: int | None = None
    descriptor: int | None = None
    try:
        parent_descriptor = os.open(
            _MARKET_HOME_PROJECTION_ACTIVATION_MARKER.parent,
            os.O_RDONLY | os.O_DIRECTORY | nofollow,
        )
        descriptor = os.open(
            _MARKET_HOME_PROJECTION_ACTIVATION_MARKER.name,
            os.O_RDONLY | nofollow | nonblock,
            dir_fd=parent_descriptor,
        )
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_size > _MARKET_HOME_PROJECTION_ACTIVATION_MARKER_MAX_BYTES
        ):
            return False
        return (
            os.read(
                descriptor,
                _MARKET_HOME_PROJECTION_ACTIVATION_MARKER_MAX_BYTES + 1,
            )
            == b"enabled\n"
        )
    except OSError:
        return False
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if parent_descriptor is not None:
            os.close(parent_descriptor)


def _refresh_market_home_projection_with_lease(
    manager: HistoricalDataManager,
    refresh: Callable[[], object],
) -> object | None:
    lease = manager.catalog.acquire_maintenance_lock()
    if lease is None:
        return None
    try:
        return refresh()
    finally:
        lease.release()


class _ConfiguredNotificationTransport:
    """Lazily reuse the active PushPlus transport only after a natural failure."""

    def send(self, delivery: NotificationDelivery) -> ProviderAcceptance:
        from app.alerts.notification_composition import (
            build_notification_transport_from_env,
        )

        return build_notification_transport_from_env().send(delivery)


def _load_status(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _atomic_write_status(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def _public_maintenance_failure_code(stop_reason: str | None) -> str:
    """仅传递明确定义为公开的维护 stop code。"""
    if stop_reason == "maintenance_locked":
        return "MAINTENANCE_LOCKED"
    if stop_reason == "provider_quota_exhausted":
        return "PROVIDER_QUOTA_EXHAUSTED"
    if stop_reason in _PUBLIC_ERROR_CODES:
        return stop_reason
    return "UPDATE_FAILED"


def _rank1_matches_live_snapshot(
    manager: HistoricalDataManager,
    live_store: RedisLiveStore,
    products: tuple[str, ...],
    trading_day: date,
) -> bool:
    """Compare one immutable Live day snapshot with the formal rank-one facts."""
    snapshot = live_store.subscriptions(trading_day)
    if snapshot is None:
        return False
    live = {
        symbol.strip().lower(): contract.strip().upper()
        for symbol, contract in snapshot.items()
        if isinstance(symbol, str)
        and isinstance(contract, str)
        and symbol.strip()
        and contract.strip()
    }
    if set(live) != set(products):
        return False
    formal: dict[str, str] = {}
    for symbol in products:
        facts = manager.catalog.main_map(symbol, trading_day, trading_day)
        if len(facts) != 1:
            return False
        contract = facts[0].contract
        if not isinstance(contract, str) or not contract.strip():
            return False
        formal[symbol] = contract.strip().upper()
    return live == formal


def _public_trading_day(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return None


def _public_last_failure(value: object) -> dict[str, str] | None:
    if not isinstance(value, Mapping):
        return None
    trading_day = _public_trading_day(value.get("trading_day"))
    error_code = value.get("error_code")
    if (
        trading_day is None
        or not isinstance(error_code, str)
        or error_code not in _PUBLIC_ERROR_CODES
    ):
        return None
    return {"trading_day": trading_day, "error_code": error_code}


def public_after_market_status(value: object) -> dict[str, object]:
    """Return the sole public, field-whitelisted view of a local status payload."""
    if not isinstance(value, Mapping):
        return {}
    raw_schema_version = value.get("schema_version", 1)
    if type(raw_schema_version) is not int or raw_schema_version not in {1, 2, 3}:
        return {}
    schema_version = raw_schema_version
    current_run = (
        _public_current_run(value.get("current_run"), schema_version=schema_version) if schema_version >= 2 else None
    )
    last_run = _public_last_run(value.get("last_run"), schema_version=schema_version)
    last_success = _public_trading_day(value.get("last_successful_trading_day"))
    last_failure = _public_last_failure(value.get("last_failure"))
    if (
        (
            schema_version >= 2
            and _present_nonnull_invalid(value, "current_run", current_run)
        )
        or _present_nonnull_invalid(value, "last_run", last_run)
        or _present_nonnull_invalid(
            value,
            "last_successful_trading_day",
            last_success,
        )
        or _present_nonnull_invalid(value, "last_failure", last_failure)
    ):
        return {}
    if (
        current_run is None
        and last_run is None
        and last_success is None
        and last_failure is None
    ):
        return {}
    public: dict[str, object] = {
        "last_run": last_run,
        "last_successful_trading_day": last_success,
        "last_failure": last_failure,
    }
    if schema_version >= 2:
        return {
            "schema_version": schema_version,
            "current_run": current_run,
            **public,
        }
    return public


def _present_nonnull_invalid(
    value: Mapping[object, object],
    field: str,
    normalized: object,
) -> bool:
    return field in value and value.get(field) is not None and normalized is None


def _public_last_run(
    value: object,
    *,
    schema_version: int = 1,
) -> dict[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    trading_day = _public_trading_day(value.get("trading_day"))
    status = value.get("status")
    attempts = value.get("attempts")
    started_at = _public_timestamp(value.get("started_at"))
    finished_at = _public_timestamp(value.get("finished_at"))
    products = value.get("products")
    error_code = value.get("error_code")
    normalized_products = (
        [product.strip().lower() for product in products]
        if isinstance(products, list)
        and all(isinstance(product, str) for product in products)
        else []
    )
    valid_attempts = isinstance(attempts, int) and not isinstance(attempts, bool)
    valid_outcome = valid_attempts and (
        (status == "passed" and attempts in {1, 2} and error_code is None)
        or (
            status == "failed"
            and attempts in {1, 2}
            and isinstance(error_code, str)
            and error_code in _PUBLIC_ERROR_CODES - {"NON_TRADING_DAY"}
        )
        or (status == "skipped" and attempts == 0 and error_code == "NON_TRADING_DAY")
    )
    if (
        trading_day is None
        or started_at is None
        or finished_at is None
        or not valid_outcome
        or not normalized_products
        or any(
            _PUBLIC_PRODUCT_CODE.fullmatch(product) is None
            for product in normalized_products
        )
    ):
        return None
    public = {
        "trading_day": trading_day,
        "status": status,
        "attempts": attempts,
        "started_at": started_at,
        "finished_at": finished_at,
        "products": normalized_products,
        "error_code": error_code,
    }
    if schema_version >= 2:
        failure_notification = _public_failure_notification(
            value.get("failure_notification")
        )
        if (
            value.get("failure_notification") is not None
            and failure_notification is None
        ):
            return None
        public["failure_notification"] = failure_notification
    return public


def _public_current_run(value: object, *, schema_version: int = 2) -> dict[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    scheduled_date = _public_trading_day(value.get("scheduled_date"))
    started_at = _public_timestamp(value.get("started_at"))
    products = value.get("products")
    normalized_products = (
        [product.strip().lower() for product in products]
        if isinstance(products, list)
        and products
        and all(isinstance(product, str) for product in products)
        else []
    )
    if (
        scheduled_date is None
        or started_at is None
        or not normalized_products
        or any(
            _PUBLIC_PRODUCT_CODE.fullmatch(product) is None
            for product in normalized_products
        )
    ):
        return None
    public: dict[str, object] = {
        "scheduled_date": scheduled_date,
        "started_at": started_at,
        "products": normalized_products,
    }
    if schema_version == 3:
        progress = _public_progress(value)
        if progress is None:
            return None
        public.update(progress)
    return public


_MAINTENANCE_PHASES = frozenset({"planning", "reading", "provider", "publishing", "aggregation"})
_AFTER_MARKET_STAGES = _MAINTENANCE_PHASES | {
    "calendar", "rqdata_readiness", "retry_wait", "canonical_updated",
    "live_reconciliation", "live_cleanup", "projection",
}


def _public_progress(value: Mapping) -> dict[str, object] | None:
    stage, attempt = value.get("stage"), value.get("attempt")
    updated = _public_timestamp(value.get("updated_at"))
    stage_started = _public_timestamp(value.get("stage_started_at"))
    run_elapsed = value.get("elapsed_seconds")
    symbol = value.get("current_symbol")
    retry = _public_timestamp(value.get("retry_at"))
    counters, durations = value.get("counters"), value.get("stage_durations")
    if (not isinstance(stage, str) or stage not in _AFTER_MARKET_STAGES
            or type(attempt) is not int or attempt not in {0, 1, 2} or updated is None
            or stage_started is None or run_elapsed is None or type(run_elapsed) not in {int, float}
            or not math.isfinite(run_elapsed) or run_elapsed < 0
            or (symbol is not None and (not isinstance(symbol, str) or symbol not in value.get("products", [])))
            or not isinstance(counters, Mapping) or not isinstance(durations, Mapping)
            or (value.get("retry_at") is not None and retry is None)
            or (stage == "retry_wait") != (retry is not None)):
        return None
    started_time = datetime.fromisoformat(str(value["started_at"]))
    updated_time = datetime.fromisoformat(updated)
    if not started_time <= datetime.fromisoformat(stage_started) <= updated_time:
        return None
    if retry is not None and (attempt != 1 or not updated_time <= datetime.fromisoformat(retry) <= updated_time + timedelta(hours=1)):
        return None
    normalized_counters = {}
    for phase, counter in counters.items():
        if phase not in _MAINTENANCE_PHASES or not isinstance(counter, Mapping):
            return None
        completed, total = counter.get("completed"), counter.get("total")
        if type(completed) is not int or completed < 0 or (
            "total" in counter and (type(total) is not int or total < completed)
        ):
            return None
        normalized_counters[phase] = {"completed": completed}
        if total is not None:
            normalized_counters[phase]["total"] = total
    normalized_durations = {}
    for phase, elapsed in durations.items():
        if (phase not in _MAINTENANCE_PHASES or type(elapsed) not in {int, float}
                or not math.isfinite(elapsed) or elapsed < 0):
            return None
        normalized_durations[phase] = elapsed
    partition = value.get("current_partition")
    normalized_partition = None
    if partition is not None:
        from app.market_data.domain import DatasetKey
        if not isinstance(partition, Mapping):
            return None
        dataset = partition.get("dataset")
        year, month = partition.get("year"), partition.get("month")
        if (not isinstance(dataset, list) or len(dataset) != 4
                or not all(isinstance(item, str) for item in dataset)
                or type(year) is not int or not 1990 <= year <= 2200
                or type(month) is not int or not 1 <= month <= 12):
            return None
        try:
            key = DatasetKey(*dataset)
        except (ValueError, TypeError):
            return None
        if key.symbol != symbol:
            return None
        normalized_partition = {"dataset": list(key.as_tuple()), "year": year, "month": month}
    return {"stage": stage, "attempt": attempt, "updated_at": updated,
            "stage_started_at": stage_started, "elapsed_seconds": run_elapsed, "current_symbol": symbol,
            "retry_at": retry, "counters": normalized_counters,
            "stage_durations": normalized_durations, "current_partition": normalized_partition}


def _public_failure_notification(value: object) -> dict[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    attempted_at = _public_timestamp(value.get("attempted_at"))
    state = value.get("state")
    error_type = value.get("error_type")
    valid = (state == "provider_accepted" and error_type is None) or (
        state == "failed"
        and isinstance(error_type, str)
        and error_type
        in _PUBLIC_NOTIFICATION_ERROR_TYPES
        | {"AFTER_MARKET_FAILURE_NOTIFICATION_FAILED"}
    )
    if attempted_at is None or not valid:
        return None
    return {
        "attempted_at": attempted_at,
        "state": state,
        "error_type": error_type,
    }


def _public_timestamp(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return value


def _local_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=SHANGHAI)
    return value.astimezone(SHANGHAI)
