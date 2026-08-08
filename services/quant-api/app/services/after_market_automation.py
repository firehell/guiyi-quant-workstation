"""Retired after-market automation service (fail-closed stubs)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

PRODUCT = "jm"
EXCHANGE = "DCE"
TASK_ID = "JM-EOD-INCREMENTAL-AUTOMATION-RETIRED"
ENABLE_PACKET_SCHEMA_VERSION = 2


class AfterMarketAutomationError(RuntimeError):
    """Raised when retired after-market automation is invoked."""


@dataclass(frozen=True)
class EligibilityResult:
    days: tuple[date, ...]
    latest_completed_trading_day: date
    latest_eligible_trading_day: date | None
    archive_lag_trading_days: int


@dataclass(frozen=True)
class AutomationPolicy:
    safe_delay_minutes: int = 120
    max_catchup_days: int = 5
    retry_delays_minutes: tuple[int, ...] = (5, 15, 30, 60, 120, 240)
    provider_stability_checks: int = 2
    provider_stability_interval_seconds: int = 30
    scan_interval_seconds: int = 300
    heartbeat_interval_seconds: int = 60
    lock_lease_seconds: int = 180


@dataclass(frozen=True)
class DailyArchiveResult:
    trading_day: date
    status: str
    error_type: str | None = None
    details: dict[str, Any] | None = None


def discover_eligible_trading_days(*args: Any, **kwargs: Any) -> EligibilityResult:
    del args, kwargs
    raise AfterMarketAutomationError("after-market archive automation is retired")


def load_or_seed_checkpoint(*args: Any, **kwargs: Any) -> Any:
    del args, kwargs
    raise AfterMarketAutomationError("after-market archive automation is retired")


def run_delegated_archive_day(*args: Any, **kwargs: Any) -> DailyArchiveResult:
    del args, kwargs
    raise AfterMarketAutomationError("after-market archive automation is retired")


def validate_enable_approval_packet(*args: Any, **kwargs: Any) -> dict[str, Any]:
    del args, kwargs
    raise AfterMarketAutomationError("after-market archive automation is retired")


def build_enable_approval_packet(*args: Any, **kwargs: Any) -> dict[str, Any]:
    del args, kwargs
    raise AfterMarketAutomationError("after-market archive automation is retired")


class AfterMarketAutomationService:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise AfterMarketAutomationError("after-market archive automation is retired")
