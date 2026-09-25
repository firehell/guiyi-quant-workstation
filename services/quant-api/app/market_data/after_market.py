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
import subprocess
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
from app.market_data.metadata import CalendarNightAuthorityError
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
        "TRADING_CALENDAR_CONFLICT",
        "TRADING_CALENDAR_MISSING",
        "UPDATE_FAILED",
        "COMMIT_OUTCOME_UNKNOWN",
        "HISTORICAL_MAINTENANCE_REQUIRED",
        "CALENDAR_NIGHT_AUTHORITY_MISSING",
        "AFTER_MARKET_INTERRUPTED",
    }
)
_CALENDAR_CLASSIFICATION_ERROR_CODES = frozenset(
    {"TRADING_CALENDAR_CONFLICT", "TRADING_CALENDAR_MISSING"}
)
_MAINTENANCE_DIAGNOSTIC_REASON_CODES = frozenset({
    "SOURCE_QUALITY_CLASSIFICATION_UNSUPPORTED",
    "SOURCE_QUALITY_EVIDENCE_INVALID",
    "WEEKLY_SOURCE_PRICE_UNAVAILABLE",
    "WEEKLY_SOURCE_BAR_CONFLICT",
    "WEEKLY_SOURCE_ENDPOINTS_MISSING",
    "StorageError", "InfrastructureError", "ValueError", "TypeError",
    "OTHER_TARGET_FAILURE",
})
_PUBLIC_PRODUCT_CODE = re.compile(r"[a-z]{1,4}\Z")
_PUBLIC_NOTIFICATION_ERROR_TYPES = frozenset(
    {
        "ALERT_NOTIFICATION_CONFIG_INVALID",
        "ALERT_NOTIFICATION_TRANSPORT_FAILED",
        "ALERT_NOTIFICATION_TRANSPORT_INVALID",
    }
)


def _diagnostic_warning(
    template: str, *args: object, stage: str | None = None,
    detail_code: str | None = None, attempt: int | None = None,
    exception_type: str | None = None,
    failure_context: Mapping[str, str] | None = None,
) -> None:
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
        fields = {key: value for key, value in {
            "stage": stage, "detail_code": detail_code,
            "attempt": attempt, "exception_type": exception_type,
            **(failure_context or {}),
        }.items() if value is not None}
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
        rqdata: RQDataClient | None,
        live_store: RedisLiveStore,
        status_path: Path,
        sleep: Callable[[float], None],
        notification_transport: NotificationTransport | None,
        now: Callable[[], datetime],
        rqdata_factory: Callable[[], RQDataClient] | None = None,
        market_home_projection_invalidate: Callable[[], None] | None = None,
        market_home_projection_refresh: Callable[[], object] | None = None,
        recovery_guard_factory: Callable[[], AbstractContextManager] | None = None,
        consumer_guard_factory: Callable[[], AbstractContextManager] | None = None,
        consumer_audit: Callable[[tuple[str, ...], date], Mapping[str, object]] | None = None,
        consumer_revision: Callable[[tuple[str, ...], date], str | Mapping[str, str]] | None = None,
        consumer_check_keys: tuple[str, ...] = ("newow_d1",),
    ) -> None:
        self.manager = manager
        self.rqdata = rqdata
        self.rqdata_factory = rqdata_factory
        self.live_store = live_store
        self.status_path = status_path
        self.sleep = sleep
        self.notification_transport = notification_transport
        self.now = now
        self.market_home_projection_invalidate = market_home_projection_invalidate
        self.market_home_projection_refresh = market_home_projection_refresh
        self.recovery_guard_factory = recovery_guard_factory or nullcontext
        self.consumer_guard_factory = consumer_guard_factory or self.recovery_guard_factory
        self.consumer_audit = consumer_audit
        self.consumer_revision = consumer_revision
        if (
            not consumer_check_keys
            or len(set(consumer_check_keys)) != len(consumer_check_keys)
            or any(key not in {"newow_d1", "newow_w1"} for key in consumer_check_keys)
        ):
            raise ValueError("AFTER_MARKET_CONSUMER_CHECKS_INVALID")
        self.consumer_check_keys = consumer_check_keys
        self._run_started_at: str | None = None
        self.monotonic = time.monotonic
        self._current: dict[str, Any] = {}
        self._progress_failed = False
        self._last_progress_write = 0.0
        self._failure_context: dict[str, str] | None = None

    def run(self) -> AfterMarketResult:
        """执行一次受限盘后维护，并写入仅含公开字段的状态。"""
        self._failure_context = None
        with self.recovery_guard_factory():
            result = self._run_guarded()
        if self.consumer_audit is not None:
            self._run_consumer_audit(result)
        return result

    def _run_consumer_audit(self, result: AfterMarketResult) -> None:
        checks = {key: {"status": "not_verified"} for key in self.consumer_check_keys}
        if result.error_code != "NON_TRADING_DAY":
            try:
                # Probe the guard briefly, then run the bounded read outside it.
                with self.consumer_guard_factory():
                    pass
                products = load_operational_products()
                raw = self.consumer_audit(products, result.trading_day)
                checks = _consumer_audit_checks(raw, self.consumer_check_keys)
                checked_at = _local_timestamp(self.now()).isoformat()
                code_commit = _local_code_commit()
                for check in checks.values():
                    check.update(
                        trading_day=result.trading_day.isoformat(),
                        checked_at=checked_at,
                        run_started_at=self._run_started_at,
                    )
                    if code_commit is not None:
                        check["code_commit"] = code_commit
                # A concurrent maintenance run cannot be recorded as this run's
                # acceptance. The callback also compares DB revision before/after.
                with self.consumer_guard_factory():
                    if self.consumer_revision is not None:
                        revisions = self.consumer_revision(products, result.trading_day)
                        for key, check in checks.items():
                            expected = check.get("input_revision")
                            if expected is None:
                                continue
                            actual = revisions.get(key) if isinstance(revisions, Mapping) else revisions
                            if actual != expected:
                                check["status"] = "input_changed"
                    self._write_consumer_checks(result, checks)
                    return
            except RuntimeError as exc:
                if str(exc) == "LIVE_RECOVERY_BUSY":
                    # The primary status already carries not_verified.
                    return
                _diagnostic_warning(
                    "after_market_consumer_audit_failed exception_type=%s",
                    type(exc).__name__,
                    exception_type=type(exc).__name__,
                )
            except Exception as exc:  # noqa: BLE001 - primary result remains authoritative
                _diagnostic_warning(
                    "after_market_consumer_audit_failed exception_type=%s",
                    type(exc).__name__,
                    exception_type=type(exc).__name__,
                )
        checked_at = _local_timestamp(self.now()).isoformat()
        for check in checks.values():
            check.update(
                trading_day=result.trading_day.isoformat(),
                checked_at=checked_at,
                run_started_at=self._run_started_at,
            )
        try:
            with self.consumer_guard_factory():
                self._write_consumer_checks(result, checks)
        except Exception as exc:  # noqa: BLE001 - diagnostic status cannot change maintenance
            _diagnostic_warning(
                "after_market_consumer_status_write_failed exception_type=%s",
                type(exc).__name__,
                exception_type=type(exc).__name__,
            )

    def _write_consumer_checks(
        self, result: AfterMarketResult, checks: Mapping[str, Mapping[str, object]],
    ) -> None:
        try:
            payload = _load_status(self.status_path)
            last = payload.get("last_run")
            if (
                not isinstance(last, dict)
                or last.get("started_at") != self._run_started_at
                or last.get("status") != result.status
                or payload.get("current_run") is not None
            ):
                return
            payload["consumer_checks"] = {key: dict(checks[key]) for key in self.consumer_check_keys}
            _atomic_write_status(self.status_path, payload)
        except Exception as exc:  # noqa: BLE001 - diagnostic write cannot alter maintenance
            _diagnostic_warning(
                "after_market_consumer_status_write_failed exception_type=%s",
                type(exc).__name__,
                exception_type=type(exc).__name__,
            )

    def _run_guarded(self) -> AfterMarketResult:
        started_at = _local_timestamp(self.now())
        self._run_started_at = started_at.isoformat()
        products = load_operational_products()
        self._write_current_run(started_at, products)
        # 先用仅依赖 Calendar 的日期判断今天是否为交易日。当天 Session 正是下方
        # manager.update() 要同步的 metadata，不能反过来把它作为进入更新的前置条件。
        try:
            trading_day = self.manager.coverage.latest_metadata_day(products)
        except Exception as exc:  # noqa: BLE001 - metadata details stay private
            calendar_error_code = (
                exc.code
                if isinstance(exc, InfrastructureError)
                and exc.code in _CALENDAR_CLASSIFICATION_ERROR_CODES
                else "UPDATE_FAILED"
            )
            _diagnostic_warning(
                "after_market_attempt_failed stage=calendar attempt=0 "
                "detail_code=%s exception_type=%s",
                calendar_error_code,
                type(exc).__name__,
                stage="calendar", attempt=0, detail_code=calendar_error_code,
                exception_type=type(exc).__name__,
            )
            return self._finish_failure(
                AfterMarketResult(
                    "failed", started_at.date(), 0, calendar_error_code
                ),
                started_at,
                products,
            )
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
            if attempt == 1 and error_code in {
                "NEXT_TRADING_SESSION_NOT_READY",
                "RQDATA_NOT_READY",
            }:
                self._current["retry_at"] = (_local_timestamp(self.now()) + timedelta(hours=1)).isoformat()
                self._stage("retry_wait")
                self.sleep(3600)
                continue
            break

        return self._finish_failure(
            AfterMarketResult("failed", trading_day, attempt, error_code),
            started_at,
            products,
        )

    def _finish_failure(
        self,
        result: AfterMarketResult,
        started_at: datetime,
        products: tuple[str, ...],
    ) -> AfterMarketResult:
        self._write_status(result, started_at, products)
        if self.notification_transport is not None:
            notification = self._send_failure_notification(result)
            try:
                self._write_failure_notification(notification)
            except Exception as exc:  # noqa: BLE001 - primary failure remains authoritative
                _diagnostic_warning(
                    "after_market_notification_status_write_failed exception_type=%s",
                    type(exc).__name__,
                    exception_type=type(exc).__name__,
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
            if self.rqdata is None:
                if self.rqdata_factory is None:
                    raise RuntimeError("AFTER_MARKET_RQDATA_CLIENT_UNAVAILABLE")
                self.rqdata = self.rqdata_factory()
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
                stage="rqdata_readiness", attempt=attempt, detail_code=detail_code,
                exception_type=type(exc).__name__,
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
                    stage="metadata_readiness", attempt=attempt, detail_code=exc.code,
                    exception_type=type(exc).__name__,
                )
                return exc.code
            _diagnostic_warning(
                "after_market_attempt_failed stage=canonical_update attempt=%s "
                "detail_code=UNEXPECTED_UPDATE_EXCEPTION exception_type=%s",
                attempt,
                type(exc).__name__,
                stage="canonical_update", attempt=attempt,
                detail_code="UNEXPECTED_UPDATE_EXCEPTION", exception_type=type(exc).__name__,
            )
            return "UPDATE_FAILED"
        except Exception as exc:  # noqa: BLE001 - provider/catalog detail stays private
            if self._progress_failed:
                raise _ProgressPersistenceError() from None
            if isinstance(exc, StorageError) and exc.code == "COMMIT_OUTCOME_UNKNOWN":
                return exc.code
            if isinstance(exc, CalendarNightAuthorityError):
                context = {
                    "exchange_code": exc.exchange_code,
                    "calendar_day": exc.calendar_day.isoformat(),
                    "reason_code": exc.reason_code,
                }
                self._failure_context = context
                _diagnostic_warning(
                    "after_market_attempt_failed stage=canonical_update attempt=%s "
                    "detail_code=%s exception_type=%s",
                    attempt, exc.code, "ValueError",
                    stage="canonical_update", attempt=attempt,
                    detail_code=exc.code, exception_type="ValueError",
                    failure_context=context,
                )
                return exc.code
            if (
                type(exc) is ValueError
                and len(exc.args) == 1
                and exc.args[0] in _PUBLIC_ERROR_CODES
            ):
                if exc.args[0] != "HISTORICAL_MAINTENANCE_REQUIRED":
                    _diagnostic_warning(
                        "after_market_attempt_failed stage=canonical_update attempt=%s "
                        "detail_code=%s exception_type=%s",
                        attempt,
                        exc.args[0],
                        type(exc).__name__,
                        stage="canonical_update", attempt=attempt,
                        detail_code=exc.args[0], exception_type=type(exc).__name__,
                    )
                return exc.args[0]
            _diagnostic_warning(
                "after_market_attempt_failed stage=canonical_update attempt=%s "
                "detail_code=UNEXPECTED_UPDATE_EXCEPTION exception_type=%s",
                attempt,
                type(exc).__name__,
                stage="canonical_update", attempt=attempt,
                detail_code="UNEXPECTED_UPDATE_EXCEPTION", exception_type=type(exc).__name__,
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
                stage="canonical_update_result", attempt=attempt, detail_code=error_code,
            )
            if result.failures:
                _log_first_maintenance_failure(result.failures[0], attempt, len(result.failures))
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
                    stage="live_reconciliation", attempt=attempt,
                    detail_code="LIVE_DOMINANT_MISMATCH",
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
                stage="live_reconciliation", attempt=attempt,
                detail_code="UNEXPECTED_LIVE_EXCEPTION", exception_type=type(exc).__name__,
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
                exception_type=type(exc).__name__,
            )

    def _write_status(
        self,
        result: AfterMarketResult,
        started_at: datetime,
        products: tuple[str, ...],
    ) -> None:
        previous = _load_status(self.status_path)
        finished_at = _local_timestamp(self.now())
        interruption = previous.get("last_interruption")
        schema_version = 5 if interruption is not None else 3
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
                "failure_context": (
                    self._failure_context
                    if result.error_code == "CALENDAR_NIGHT_AUTHORITY_MISSING" else None
                ),
                "failure_notification": None,
            },
            "last_successful_trading_day": _public_trading_day(
                previous.get("last_successful_trading_day")
            ),
            "last_failure": _public_last_failure(previous.get("last_failure")),
            "consumer_checks": {
                key: {
                    "status": "not_verified",
                    "trading_day": result.trading_day.isoformat(),
                    "checked_at": finished_at.isoformat(),
                    "run_started_at": started_at.isoformat(),
                }
                for key in self.consumer_check_keys
            },
        }
        if interruption is not None:
            payload["last_interruption"] = interruption
        if result.status == "passed":
            payload["last_successful_trading_day"] = result.trading_day.isoformat()
            payload["last_failure"] = None
        elif result.status == "failed":
            payload["last_failure"] = {
                "trading_day": result.trading_day.isoformat(),
                "error_code": result.error_code,
            }
        self._write_required_status(payload)

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
        # Establish negative evidence on the SAME file before this run can start.
        # If atomic initial publication fails, readers see invalid/unknown, not old success.
        try:
            previous = _invalidate_status_before_run(self.status_path)
        except Exception:
            self._progress_failed = True
            raise _ProgressPersistenceError() from None
        previous_schema_version = (
            int(previous["schema_version"])
            if previous.get("schema_version") in {2, 3, 4, 5}
            else 1
        )
        schema_version = max(3, previous_schema_version)
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
        if previous_schema_version == 5:
            payload["last_interruption"] = previous["last_interruption"]
        self._write_required_status(payload)
        self._last_progress_write = self.monotonic()
        self._log_progress()

    def _write_required_status(self, payload: Mapping[str, object]) -> None:
        try:
            _atomic_write_status(self.status_path, payload)
        except Exception:
            self._progress_failed = True
            raise _ProgressPersistenceError() from None

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
            if payload.get("schema_version") not in {3, 4, 5} or not payload.get("current_run"):
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
    def ready_client() -> RQDataClient:
        client = getattr(provider, "client", None)
        if client is None:
            raise RuntimeError("AFTER_MARKET_RQDATA_CLIENT_UNAVAILABLE")
        return client
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

    def audit_newow_consumers(
        products: tuple[str, ...], _trading_day: date,
    ) -> Mapping[str, object]:
        from datetime import UTC
        from app.db.readonly import readonly_transaction
        from app.db.session import SessionLocal
        from app.market_data.newow.after_market_consumer_audit import (
            audit_newow_consumers as run_consumer_audit,
        )

        audit_now = datetime.now(UTC)
        status = public_after_market_status(_load_status(
            PROJECT_ROOT / ".run" / "after-market-status.json"
        ))
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=1300):
            return run_consumer_audit(
                session,
                products=products,
                trading_day=_trading_day,
                audit_now=audit_now,
                after_market_status=status,
                clock=time.monotonic,
            )
    return AfterMarketUpdater(
        manager=manager,
        rqdata=None,
        rqdata_factory=ready_client,
        live_store=RedisLiveStore(cast(RedisClient, get_redis_connection())),
        status_path=PROJECT_ROOT / ".run" / "after-market-status.json",
        sleep=time.sleep,
        notification_transport=notification_transport,
        now=lambda: datetime.now(SHANGHAI),
        market_home_projection_invalidate=projection_store.invalidate,
        market_home_projection_refresh=projection_refresh,
        recovery_guard_factory=lambda: after_market_recovery_guard(wait=True),
        consumer_guard_factory=lambda: after_market_recovery_guard(wait=False),
        consumer_audit=audit_newow_consumers,
        consumer_revision=lambda products, day: _read_newow_consumer_revisions(products, day),
        consumer_check_keys=("newow_d1", "newow_w1"),
    )


def _newow_d1_catalog_revision(session: Any, products: tuple[str, ...], day: date) -> str:
    """Hash the D1 Catalog inputs, including immutable partition pointers."""
    return _newow_catalog_revision(session, products, day, ("1d",))


def _newow_catalog_revision(
    session: Any,
    products: tuple[str, ...],
    day: date,
    frequencies: tuple[str, ...],
) -> str:
    from app.market_data.newow.after_market_consumer_audit import catalog_revision

    return catalog_revision(session, products, day, frequencies)


def _local_code_commit() -> str | None:
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT,
            capture_output=True, text=True, check=True, timeout=5,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return sha if re.fullmatch(r"[0-9a-f]{40}", sha) else None


def _read_newow_d1_catalog_revision(products: tuple[str, ...], day: date) -> str:
    from app.db.readonly import readonly_transaction
    from app.db.session import SessionLocal

    with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
        return _newow_d1_catalog_revision(session, products, day)


def _read_newow_consumer_revisions(
    products: tuple[str, ...], day: date,
) -> dict[str, str]:
    from app.db.readonly import readonly_transaction
    from app.db.session import SessionLocal
    from app.market_data.newow.product_release import CANDIDATE_WEEKLY_PRODUCTS

    with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
        return {
            "newow_d1": _newow_catalog_revision(session, products, day, ("1d",)),
            "newow_w1": _newow_catalog_revision(
                session, tuple(CANDIDATE_WEEKLY_PRODUCTS), day, ("1d", "1w"),
            ),
        }


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


def _invalidate_status_before_run(path: Path) -> dict[str, Any]:
    """Retain prior summary in memory, then durably invalidate only this owned file.

    No alias traversal, special files or hardlinks. Failure before invalidation is
    a rejected startup, not an established run; a file-only reader cannot observe
    an attempt that produced no durable change at all.
    """
    path = path.absolute()
    if ".." in path.parts:
        raise ValueError
    directory = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    descriptor = None
    try:
        for part in path.parts[1:-1]:
            try:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            except FileNotFoundError:
                os.mkdir(part, mode=0o700, dir_fd=directory)
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        descriptor = os.open(path.name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                             0o600, dir_fd=directory)
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
            raise ValueError
        content = os.read(descriptor, 1024 * 1024 + 1)
        try:
            previous = json.loads(content) if len(content) <= 1024 * 1024 else {}
        except (ValueError, TypeError):
            previous = {}
        os.ftruncate(descriptor, 0)
        os.fsync(descriptor)
        os.fsync(directory)
        return previous if isinstance(previous, dict) else {}
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(directory)


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


def _log_first_maintenance_failure(
    failure: Mapping[str, object], attempt: int, failure_count: int,
) -> None:
    """Log bounded target identity and reason without exposing provider text."""
    fields: dict[str, object] = {
        "stage": "canonical_update_result", "attempt": attempt,
        "failure_count": min(failure_count, 100000),
    }
    dataset = failure.get("dataset")
    if isinstance(dataset, (tuple, list)) and len(dataset) == 4:
        kind, symbol, contract, frequency = dataset
        if kind in {"contract", "continuous"} and isinstance(symbol, str) and _PUBLIC_PRODUCT_CODE.fullmatch(symbol):
            fields["symbol"] = symbol
            if kind == "contract" and isinstance(contract, str) and re.fullmatch(r"[A-Z]{1,2}[0-9]{3,4}\Z", contract):
                fields["contract"] = contract
        if isinstance(frequency, str) and frequency in {"1m", "1d", "1w", "5m", "15m", "30m", "60m"}:
            fields["frequency"] = frequency
    for name, upper in (("year", 9999), ("month", 12)):
        value = failure.get(name)
        if type(value) is int and 1 <= value <= upper:
            fields[name] = value
    reason = failure.get("reason_code")
    fields["reason_code"] = (
        reason if isinstance(reason, str) and reason in _MAINTENANCE_DIAGNOSTIC_REASON_CODES
        else "OTHER_TARGET_FAILURE"
    )
    _LOGGER.warning(
        "after_market_target_failure",
        extra={
            "diagnostic_code": "AFTER_MARKET_TARGET_FAILURE",
            "diagnostic_fields": fields,
        },
    )


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
    return _rank1_matches_snapshot(manager, live_store.subscriptions(trading_day), products, trading_day)


def _rank1_matches_snapshot(
    manager: HistoricalDataManager, snapshot: Mapping[str, Any] | None,
    products: tuple[str, ...], trading_day: date,
) -> bool:
    """Compare already-read subscription facts; callers own observation timing."""
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
    if type(raw_schema_version) is not int or raw_schema_version not in {1, 2, 3, 4, 5}:
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
    if schema_version == 5:
        interruption = _public_last_interruption(value.get("last_interruption"))
        if interruption is None:
            return {}
        if isinstance(last_run, Mapping) and last_run.get("status") == "interrupted":
            if (last_run["trading_day"] != interruption["trading_day"]
                    or last_run["started_at"] != interruption["started_at"]
                    or last_run["finished_at"] != interruption["closed_at"]):
                return {}
        closed_at = datetime.fromisoformat(str(interruption["closed_at"]))
        for run in (current_run, last_run):
            if isinstance(run, Mapping) and run.get("status") != "interrupted":
                if closed_at > datetime.fromisoformat(str(run["started_at"])):
                    return {}
        public["last_interruption"] = interruption
    if schema_version >= 2:
        result = {
            "schema_version": schema_version,
            "current_run": current_run,
            **public,
        }
        consumer_checks = value.get("consumer_checks")
        if isinstance(consumer_checks, Mapping):
            public_checks: dict[str, object] = {}
            for key in ("newow_d1", "newow_w1"):
                check = consumer_checks.get(key)
                if not isinstance(check, Mapping):
                    continue
                sanitized = _public_consumer_audit(check)
                day = _public_trading_day(check.get("trading_day"))
                checked = _public_timestamp(check.get("checked_at"))
                if day is not None and checked is not None:
                    public_checks[key] = {
                        **sanitized, "trading_day": day, "checked_at": checked,
                    }
            if public_checks:
                result["consumer_checks"] = public_checks
        return result
    return public


def _public_consumer_audit(value: object) -> dict[str, object]:
    if isinstance(value, Mapping) and value.get("status") == "not_verified":
        started = _public_timestamp(value.get("run_started_at"))
        return {"status": "not_verified", **({"run_started_at": started} if started else {})}
    if not isinstance(value, Mapping) or value.get("status") not in {"audited", "incomplete", "input_changed"}:
        return {"status": "not_verified"}
    run_started_at = value.get("run_started_at")
    if run_started_at is not None and _public_timestamp(run_started_at) is None:
        return {"status": "not_verified"}
    counts = ("case_count", "main_ready_count", "reference_ready_count", "auxiliary_ready_count")
    if any(type(value.get(key)) is not int or not 0 <= value[key] <= 1800 for key in counts):
        return {"status": "not_verified"}
    if type(value.get("budget_exhausted")) is not bool:
        return {"status": "not_verified"}
    audit_as_of = value.get("as_of")
    if audit_as_of is not None and _public_timestamp(audit_as_of) is None:
        return {"status": "not_verified"}
    revision = value.get("input_revision")
    if revision is not None and (not isinstance(revision, str) or re.fullmatch(r"[0-9a-f]{64}", revision) is None):
        return {"status": "not_verified"}
    code_commit = value.get("code_commit")
    if code_commit is not None and (not isinstance(code_commit, str) or re.fullmatch(r"[0-9a-f]{40}", code_commit) is None):
        return {"status": "not_verified"}
    frequency = value.get("frequency")
    if frequency is not None and frequency not in {"1d", "1w"}:
        return {"status": "not_verified"}
    raw_unverified = value.get("unverified_products")
    if raw_unverified is not None and (not isinstance(raw_unverified, list) or len(raw_unverified) > 60 or any(
        not isinstance(item, str) or _PUBLIC_PRODUCT_CODE.fullmatch(item) is None for item in raw_unverified
    ) or len(set(raw_unverified)) != len(raw_unverified)):
        return {"status": "not_verified"}
    raw_cutoffs = value.get("product_cutoffs")
    if raw_cutoffs is not None and (not isinstance(raw_cutoffs, list) or len(raw_cutoffs) > 60):
        return {"status": "not_verified"}
    cutoffs: list[dict[str, str]] = []
    if isinstance(raw_cutoffs, list):
        for row in raw_cutoffs:
            if not isinstance(row, Mapping) or not isinstance(row.get("product"), str) or _PUBLIC_PRODUCT_CODE.fullmatch(row["product"]) is None or _public_timestamp(row.get("as_of")) is None:
                return {"status": "not_verified"}
            cutoffs.append({"product": row["product"], "as_of": row["as_of"]})
        if len({row["product"] for row in cutoffs}) != len(cutoffs):
            return {"status": "not_verified"}
    raw_failures = value.get("failures")
    if not isinstance(raw_failures, list) or len(raw_failures) > 1800:
        return {"status": "not_verified"}
    failures: list[dict[str, str]] = []
    for row in raw_failures:
        if not isinstance(row, Mapping):
            return {"status": "not_verified"}
        product = row.get("product")
        strategy = row.get("strategy")
        section = row.get("section")
        reason = row.get("reason")
        if (
            not isinstance(product, str) or _PUBLIC_PRODUCT_CODE.fullmatch(product) is None
            or strategy not in {"trend", "oscillation", "main_rise"}
            or section not in {"chart", "reference", "auxiliary:macd", "auxiliary:main_force_control", "auxiliary:up_down_energy", "auxiliary:zhaoyao_mirror", "auxiliary:cup_handle"}
            or not isinstance(reason, str) or re.fullmatch(r"[A-Z][A-Z0-9_]{0,79}", reason) is None
        ):
            return {"status": "not_verified"}
        failures.append({"product": product, "strategy": strategy, "section": section, "reason": reason})
    raw_proposals = value.get("warmup_proposals")
    if raw_proposals is not None and (
        not isinstance(raw_proposals, list) or len(raw_proposals) > 60
    ):
        return {"status": "not_verified"}
    proposals: list[dict[str, object]] = []
    if isinstance(raw_proposals, list):
        for row in raw_proposals:
            if not isinstance(row, Mapping):
                return {"status": "not_verified"}
            product, contract = row.get("product"), row.get("contract")
            through, proposal_frequency = row.get("through"), row.get("frequency")
            proposal_status = row.get("status")
            plan_hash = row.get("plan_sha256")
            expected_count = row.get("expected_bar_count")
            request_count = row.get("provider_request_count")
            if (
                not isinstance(product, str) or _PUBLIC_PRODUCT_CODE.fullmatch(product) is None
                or not isinstance(contract, str)
                or re.fullmatch(r"[A-Z]{1,4}[0-9]{3,4}", contract) is None
                or proposal_frequency not in {"1d", "1w"}
                or not isinstance(through, str) or _public_trading_day(through) is None
                or proposal_status not in {"PROPOSED", "REVIEW_REQUIRED"}
                or (plan_hash is not None and (
                    not isinstance(plan_hash, str)
                    or re.fullmatch(r"[0-9a-f]{64}", plan_hash) is None
                ))
                or (expected_count is not None and (
                    type(expected_count) is not int or expected_count < 0
                ))
                or (request_count is not None and (
                    type(request_count) is not int or request_count < 0
                ))
            ):
                return {"status": "not_verified"}
            proposals.append({
                "product": product,
                "contract": contract,
                "frequency": proposal_frequency,
                "through": through,
                "status": proposal_status,
                "expected_bar_count": expected_count,
                "provider_request_count": request_count,
                "plan_sha256": plan_hash,
            })
    return {
        "status": value["status"],
        **{key: value[key] for key in counts},
        "budget_exhausted": value["budget_exhausted"],
        "failures": failures,
        **({"frequency": frequency} if frequency is not None else {}),
        **({"warmup_proposals": proposals} if raw_proposals is not None else {}),
        **({"as_of": audit_as_of} if audit_as_of is not None else {}),
        **({"input_revision": revision} if revision is not None else {}),
        **({"code_commit": code_commit} if code_commit is not None else {}),
        **({"product_cutoffs": cutoffs} if raw_cutoffs is not None else {}),
        **({"unverified_products": raw_unverified} if raw_unverified is not None else {}),
        **({"run_started_at": run_started_at} if run_started_at is not None else {}),
    }


def _consumer_audit_checks(
    value: Mapping[str, object], keys: tuple[str, ...],
) -> dict[str, dict[str, object]]:
    if "status" in value:
        if keys != ("newow_d1",):
            raise ValueError("AFTER_MARKET_CONSUMER_CHECKS_INVALID")
        return {"newow_d1": _public_consumer_audit(value)}
    if set(value) != set(keys):
        raise ValueError("AFTER_MARKET_CONSUMER_CHECKS_INVALID")
    result: dict[str, dict[str, object]] = {}
    for key in keys:
        check = value.get(key)
        if not isinstance(check, Mapping):
            raise ValueError("AFTER_MARKET_CONSUMER_CHECKS_INVALID")
        result[key] = _public_consumer_audit(check)
    return result


def _public_last_interruption(value: object) -> dict[str, object] | None:
    """Bounded administrative evidence; never an after-market success receipt."""
    if not isinstance(value, Mapping):
        return None
    day = _public_trading_day(value.get("trading_day"))
    started = _public_timestamp(value.get("started_at"))
    closed = _public_timestamp(value.get("closed_at"))
    checked = _public_timestamp(value.get("snapshot_checked_at"))
    classification = value.get("snapshot_classification")
    verified = value.get("reconciliation_verified")
    if (day is None or started is None or closed is None or checked is None
            or classification not in ("not_verified_missing", "verified_match")
            or type(verified) is not bool or verified != (classification == "verified_match")):
        return None
    if (datetime.fromisoformat(started).astimezone(SHANGHAI).date().isoformat() != day
            or not datetime.fromisoformat(started) <= datetime.fromisoformat(checked) <= datetime.fromisoformat(closed)):
        return None
    return {"trading_day": day, "started_at": started, "closed_at": closed,
            "snapshot_checked_at": checked, "snapshot_classification": classification,
            "reconciliation_verified": verified}


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
    failure_context = _public_calendar_failure_context(value.get("failure_context"))
    if value.get("failure_context") is not None and (
        error_code != "CALENDAR_NIGHT_AUTHORITY_MISSING" or failure_context is None
    ):
        return None
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
            and isinstance(error_code, str)
            and (
                (
                    attempts == 0
                    and schema_version >= 3
                    and error_code
                    in _CALENDAR_CLASSIFICATION_ERROR_CODES | {"UPDATE_FAILED"}
                )
                or (
                    attempts in {1, 2}
                    and error_code
                    in _PUBLIC_ERROR_CODES
                    - {"NON_TRADING_DAY"}
                    - _CALENDAR_CLASSIFICATION_ERROR_CODES
                )
            )
        )
        or (status == "skipped" and attempts == 0 and error_code == "NON_TRADING_DAY")
    )
    if schema_version >= 4 and status == "interrupted":
        valid_outcome = (error_code == "AFTER_MARKET_INTERRUPTED"
                         and (attempts is None or valid_attempts and attempts in {0, 1, 2})
                         and value.get("failure_notification") is None)
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
    if failure_context is not None:
        public["failure_context"] = failure_context
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


def _public_calendar_failure_context(value: object) -> dict[str, str] | None:
    if not isinstance(value, Mapping) or set(value) != {
        "exchange_code", "calendar_day", "reason_code"
    }:
        return None
    exchange = value.get("exchange_code")
    day = _public_trading_day(value.get("calendar_day"))
    reason = value.get("reason_code")
    if (type(exchange) is not str
            or exchange not in {"CFFEX", "CZCE", "DCE", "GFEX", "INE", "SHFE"}
            or day is None or type(reason) is not str
            or reason not in CalendarNightAuthorityError.reasons):
        return None
    return {"exchange_code": exchange, "calendar_day": day, "reason_code": reason}


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
    if schema_version >= 3:
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
