"""有界盘后历史维护入口。

该模块不维护队列、检查点或重试状态。每次运行仅检查一次、最多等待一小时后再尝试一次，
并将可公开观察的结果写到本地状态文件。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
import json
from pathlib import Path
import subprocess
import time
from typing import Any

from app.market_data.infrastructure import RQDataClient, SHANGHAI
from app.market_data.maintenance import HistoricalDataManager, UpdateRequest
from app.market_data.operational_universe import load_operational_products
from app.core.env import PROJECT_ROOT


_NOTIFICATION_TITLE = "Guiyi Quant After-Market"
_PUBLIC_ERROR_CODES = frozenset(
    {
        "MAINTENANCE_LOCKED",
        "NON_TRADING_DAY",
        "PROVIDER_QUOTA_EXHAUSTED",
        "RQDATA_NOT_READY",
        "RQDATA_READY_CHECK_FAILED",
        "UPDATE_FAILED",
    }
)
_PUBLIC_NOTIFICATION_MESSAGES = {
    "MAINTENANCE_LOCKED": "Historical maintenance remained locked after one retry.",
    "PROVIDER_QUOTA_EXHAUSTED": "RQData quota remained unavailable after one retry.",
    "RQDATA_NOT_READY": "RQData futures data is not ready after one retry.",
    "RQDATA_READY_CHECK_FAILED": "RQData readiness check failed after one retry.",
    "UPDATE_FAILED": "Historical data update failed after one retry.",
}


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
        status_path: Path,
        sleep: Callable[[float], None],
        notifier: Callable[[str], None],
        now: Callable[[], datetime],
    ) -> None:
        self.manager = manager
        self.rqdata = rqdata
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
            error_code = self._attempt(products, trading_day)
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

    def _attempt(self, products: tuple[str, ...], trading_day: date) -> str | None:
        try:
            ready = self.rqdata.is_future_data_ready(trading_day)
        except Exception:  # noqa: BLE001 - provider detail must not become public state
            return "RQDATA_READY_CHECK_FAILED"
        if not ready:
            return "RQDATA_NOT_READY"
        try:
            result = self.manager.update(
                UpdateRequest(products=products, since=None, through=trading_day, apply=True)
            )
        except Exception:  # noqa: BLE001 - do not persist exceptions or provider text
            return "UPDATE_FAILED"
        if result.status in {"passed", "noop"}:
            return None
        return _public_maintenance_failure_code(result.stop_reason)

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
    return AfterMarketUpdater(
        manager=manager,
        rqdata=client,
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
    if trading_day is None or error_code not in _PUBLIC_ERROR_CODES:
        return None
    return {"trading_day": trading_day, "error_code": error_code}


def _local_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=SHANGHAI)
    return value.astimezone(SHANGHAI)
