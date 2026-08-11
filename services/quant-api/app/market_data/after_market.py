"""有界盘后历史维护入口。

该模块不维护队列、检查点或重试状态。每次运行仅检查一次、最多等待一小时后再尝试一次，
并将可公开观察的结果写到本地状态文件。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
import json
import logging
from pathlib import Path
import re
import subprocess
import time
from typing import Any

from app.market_data.infrastructure import InfrastructureError, RQDataClient, SHANGHAI
from app.market_data.live_market import RedisLiveStore
from app.market_data.maintenance import HistoricalDataManager, UpdateRequest
from app.market_data.operational_universe import load_operational_products
from app.core.env import PROJECT_ROOT


_NOTIFICATION_TITLE = "Guiyi Quant After-Market"
_LOGGER = logging.getLogger(__name__)
_PUBLIC_ERROR_CODES = frozenset(
    {
        "MAINTENANCE_LOCKED",
        "LIVE_DOMINANT_MISMATCH",
        "NON_TRADING_DAY",
        "PROVIDER_QUOTA_EXHAUSTED",
        "RQDATA_NOT_READY",
        "RQDATA_READY_CHECK_FAILED",
        "UPDATE_FAILED",
    }
)
_PUBLIC_NOTIFICATION_MESSAGES = {
    "MAINTENANCE_LOCKED": "Historical maintenance remained locked after one retry.",
    "LIVE_DOMINANT_MISMATCH": "Live dominant contract did not match the formal rank-one map.",
    "PROVIDER_QUOTA_EXHAUSTED": "RQData quota remained unavailable after one retry.",
    "RQDATA_NOT_READY": "RQData futures data is not ready after one retry.",
    "RQDATA_READY_CHECK_FAILED": "RQData readiness check failed after one retry.",
    "UPDATE_FAILED": "Historical data update failed after one retry.",
}
_PUBLIC_PRODUCT_CODE = re.compile(r"[a-z]{1,4}\Z")


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


class AfterMarketUpdater:
    """17:00 本地盘后维护：最多两次尝试，唯一写入口仍为 HistoricalDataManager。"""

    def __init__(
        self,
        *,
        manager: HistoricalDataManager,
        rqdata: RQDataClient,
        live_store: RedisLiveStore,
        status_path: Path,
        sleep: Callable[[float], None],
        notifier: Callable[[str], None],
        now: Callable[[], datetime],
    ) -> None:
        self.manager = manager
        self.rqdata = rqdata
        self.live_store = live_store
        self.status_path = status_path
        self.sleep = sleep
        self.notifier = notifier
        self.now = now

    def run(self) -> AfterMarketResult:
        """执行一次受限盘后维护，并写入仅含公开字段的状态。"""
        started_at = _local_timestamp(self.now())
        products = load_operational_products()
        trading_day = self.manager.coverage.latest_complete_day(products)
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
            error_code = self._attempt(products, trading_day, attempt=attempt)
            if error_code is None:
                result = AfterMarketResult("passed", trading_day, attempt, None)
                self._write_status(result, started_at, products)
                return result
            if attempt == 1:
                self.sleep(3600)

        result = AfterMarketResult("failed", trading_day, 2, error_code)
        self._write_status(result, started_at, products)
        self.notifier(error_code or "UPDATE_FAILED")
        return result

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
            _LOGGER.warning(
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
                )
            )
        except Exception as exc:  # noqa: BLE001 - provider/catalog detail stays private
            _LOGGER.warning(
                "after_market_attempt_failed stage=canonical_update attempt=%s "
                "detail_code=UNEXPECTED_UPDATE_EXCEPTION exception_type=%s",
                attempt,
                type(exc).__name__,
            )
            return "UPDATE_FAILED"
        if result.status not in {"passed", "noop"}:
            error_code = _public_maintenance_failure_code(result.stop_reason)
            _LOGGER.warning(
                "after_market_attempt_failed stage=canonical_update_result attempt=%s "
                "detail_code=%s result_status=%s",
                attempt,
                error_code,
                result.status,
            )
            return error_code
        try:
            # A successful Canonical write must notify the Web seam even when the
            # temporary intraday snapshot disagrees with the formal map.
            self.live_store.publish_state({"trading_day": trading_day.isoformat()})
            if not _rank1_matches_live_snapshot(self.manager, self.live_store, products, trading_day):
                _LOGGER.warning(
                    "after_market_attempt_failed stage=live_reconciliation attempt=%s "
                    "detail_code=LIVE_DOMINANT_MISMATCH",
                    attempt,
                )
                return "LIVE_DOMINANT_MISMATCH"
            self.live_store.cleanup_trading_day(trading_day)
        except Exception as exc:  # noqa: BLE001 - catalog/Redis detail stays private
            _LOGGER.warning(
                "after_market_attempt_failed stage=live_reconciliation attempt=%s "
                "detail_code=UNEXPECTED_LIVE_EXCEPTION exception_type=%s",
                attempt,
                type(exc).__name__,
            )
            return "UPDATE_FAILED"
        return None

    def _write_status(
        self,
        result: AfterMarketResult,
        started_at: datetime,
        products: tuple[str, ...],
    ) -> None:
        previous = _load_status(self.status_path)
        finished_at = _local_timestamp(self.now())
        payload: dict[str, Any] = {
            "last_run": {
                "trading_day": result.trading_day.isoformat(),
                "status": result.status,
                "attempts": result.attempts,
                "started_at": started_at.isoformat(),
                "finished_at": finished_at.isoformat(),
                "products": list(products),
                "error_code": result.error_code,
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
        self.status_path.parent.mkdir(parents=True, exist_ok=True)
        self.status_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )


def default_after_market_notifier(error_code: str) -> None:
    """发出固定标题、公开状态码限定的 macOS 通知。"""
    message = _PUBLIC_NOTIFICATION_MESSAGES.get(error_code, _PUBLIC_NOTIFICATION_MESSAGES["UPDATE_FAILED"])
    script = f'display notification "{message}" with title "{_NOTIFICATION_TITLE}"'
    subprocess.run(
        ["/usr/bin/osascript", "-e", script],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def build_after_market_updater(manager: HistoricalDataManager) -> AfterMarketUpdater:
    """组装 CLI 盘后入口；只在该命令实际执行时才懒初始化 RQData client。"""
    provider = manager.provider
    client = getattr(provider, "client", None)
    if client is None:
        raise RuntimeError("AFTER_MARKET_RQDATA_CLIENT_UNAVAILABLE")
    from app.market_data.live_market import RedisClient
    from app.queue import get_redis_connection
    from typing import cast

    return AfterMarketUpdater(
        manager=manager,
        rqdata=client,
        live_store=RedisLiveStore(cast(RedisClient, get_redis_connection())),
        status_path=PROJECT_ROOT / ".run" / "after-market-status.json",
        sleep=time.sleep,
        notifier=default_after_market_notifier,
        now=lambda: datetime.now(SHANGHAI),
    )


def _load_status(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


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
        if isinstance(symbol, str) and isinstance(contract, str) and symbol.strip() and contract.strip()
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
    last_run = _public_last_run(value.get("last_run"))
    last_success = _public_trading_day(value.get("last_successful_trading_day"))
    last_failure = _public_last_failure(value.get("last_failure"))
    if last_run is None and last_success is None and last_failure is None:
        return {}
    return {
        "last_run": last_run,
        "last_successful_trading_day": last_success,
        "last_failure": last_failure,
    }


def _public_last_run(value: object) -> dict[str, object] | None:
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
        if isinstance(products, list) and all(isinstance(product, str) for product in products)
        else []
    )
    valid_attempts = isinstance(attempts, int) and not isinstance(attempts, bool)
    valid_outcome = valid_attempts and (
        (status == "passed" and attempts in {1, 2} and error_code is None)
        or (
            status == "failed"
            and attempts == 2
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
        or any(_PUBLIC_PRODUCT_CODE.fullmatch(product) is None for product in normalized_products)
    ):
        return None
    return {
        "trading_day": trading_day,
        "status": status,
        "attempts": attempts,
        "started_at": started_at,
        "finished_at": finished_at,
        "products": normalized_products,
        "error_code": error_code,
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
