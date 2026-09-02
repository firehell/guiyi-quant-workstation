from __future__ import annotations

import logging
from datetime import date, datetime

import pytest

from app.market_data.after_market import AfterMarketUpdater
from app.market_data.historical_data_manager import MaintenanceResult
from app.market_data.operational_universe import load_active_products


_PRODUCTS = load_active_products()
_CONTRACTS = {symbol: f"{symbol.upper()}2701" for symbol in _PRODUCTS}
_DAY = date(2026, 9, 2)


class _Coverage:
    def latest_metadata_day(self, products: tuple[str, ...]) -> date:
        assert products == _PRODUCTS
        return _DAY


class _Catalog:
    def main_map(self, symbol: str, start: date, end: date):
        assert start == _DAY
        assert end == _DAY
        return [type("Fact", (), {"contract": _CONTRACTS[symbol]})()]


class _Manager:
    def __init__(self, result: MaintenanceResult) -> None:
        self.coverage = _Coverage()
        self.catalog = _Catalog()
        self.result = result
        self.calls = 0

    def update(self, _request) -> MaintenanceResult:
        self.calls += 1
        return self.result


class _RQData:
    def __init__(self, ready: bool) -> None:
        self.ready = ready

    def is_future_data_ready(self, trading_day: date) -> bool:
        assert trading_day == _DAY
        return self.ready


class _LiveStore:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.cleaned: list[date] = []
        self.fail_stage: str | None = None

    def subscriptions(self, trading_day: date):
        assert trading_day == _DAY
        if self.fail_stage == "reconciliation":
            return {}
        return dict(_CONTRACTS)

    def publish_state(self, payload: dict[str, str]) -> None:
        assert payload == {
            "trading_day": _DAY.isoformat(),
            "reason": "canonical_updated",
        }
        if self.fail_stage == "canonical_updated":
            raise RuntimeError("private canonical publish detail")
        self.events.append("canonical_updated")

    def cleanup_trading_day(self, trading_day: date) -> None:
        if self.fail_stage == "cleanup":
            raise RuntimeError("private cleanup detail")
        self.cleaned.append(trading_day)


def _maintenance(status: str) -> MaintenanceResult:
    return MaintenanceResult(
        action="update",
        status=status,
        through=_DAY,
        planned=0,
        applied=0,
        blocked=0,
        failed=0,
        provider_requests=0,
        stop_reason=None if status in {"passed", "noop"} else "UPDATE_FAILED",
    )


def _updater(
    tmp_path,
    *,
    status: str = "passed",
    ready: bool = True,
    invalidate=None,
    refresh=None,
):
    events: list[str] = []
    live_store = _LiveStore(events)
    manager = _Manager(_maintenance(status))
    updater = AfterMarketUpdater(
        manager=manager,
        rqdata=_RQData(ready),
        live_store=live_store,
        status_path=tmp_path / "after-market-status.json",
        sleep=lambda _seconds: None,
        notification_transport=None,
        market_home_projection_invalidate=invalidate,
        market_home_projection_refresh=refresh,
        now=lambda: datetime(2026, 9, 2, 18, 5),
    )
    return updater, events, live_store, manager


@pytest.mark.parametrize("status", ["passed", "noop"])
def test_successful_or_noop_maintenance_invalidates_before_apply_and_refreshes_after_core(
    tmp_path,
    status: str,
) -> None:
    events: list[str] = []

    updater, _live_events, live_store, manager = _updater(
        tmp_path,
        status=status,
        invalidate=lambda: events.append("invalidate"),
        refresh=lambda: events.append("projection"),
    )
    live_store.events = events

    result = updater.run()

    assert result.status == "passed"
    assert manager.calls == 1
    assert events == ["invalidate", "canonical_updated", "projection"]
    assert live_store.cleaned == [_DAY]


def test_provider_not_ready_does_not_invalidate_or_refresh_projection(tmp_path) -> None:
    calls: list[str] = []
    updater, events, _live_store, manager = _updater(
        tmp_path,
        ready=False,
        invalidate=lambda: calls.append("invalidate"),
        refresh=lambda: calls.append("projection"),
    )

    result = updater.run()

    assert result.status == "failed"
    assert manager.calls == 0
    assert calls == []
    assert events == []


def test_update_failure_keeps_projection_invalidated_and_does_not_refresh(tmp_path) -> None:
    calls: list[str] = []
    updater, events, _live_store, manager = _updater(
        tmp_path,
        status="failed",
        invalidate=lambda: calls.append("invalidate"),
        refresh=lambda: calls.append("projection"),
    )

    result = updater.run()

    assert result.status == "failed"
    assert manager.calls == 1
    assert calls == ["invalidate"]
    assert events == []


def test_invalidation_failure_blocks_manager_before_authoritative_mutation(tmp_path) -> None:
    def fail_invalidation() -> None:
        raise RuntimeError("private invalidation detail")

    updater, events, _live_store, manager = _updater(
        tmp_path,
        invalidate=fail_invalidation,
        refresh=lambda: events.append("projection"),
    )

    result = updater.run()

    assert result.status == "failed"
    assert manager.calls == 0
    assert events == []


def test_projection_refresh_failure_is_performance_only_after_core_success(
    tmp_path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def fail_projection() -> None:
        raise RuntimeError("private projection detail must stay out of logs")

    updater, events, live_store, manager = _updater(
        tmp_path,
        invalidate=lambda: events.append("invalidate"),
        refresh=fail_projection,
    )
    live_store.events = events

    with caplog.at_level(logging.WARNING, logger="app.market_data.after_market"):
        result = updater.run()

    assert result.status == "passed"
    assert manager.calls == 1
    assert events == ["invalidate", "canonical_updated"]
    assert live_store.cleaned == [_DAY]
    assert "market_home_projection_refresh_failed" in caplog.text
    assert "RuntimeError" in caplog.text
    assert "private projection detail" not in caplog.text


@pytest.mark.parametrize(
    "stage",
    ["canonical_updated", "reconciliation", "cleanup"],
)
def test_core_seam_failure_never_refreshes_projection(tmp_path, stage: str) -> None:
    calls: list[str] = []
    updater, _events, live_store, manager = _updater(
        tmp_path,
        invalidate=lambda: calls.append("invalidate"),
        refresh=lambda: calls.append("projection"),
    )
    live_store.fail_stage = stage

    result = updater.run()

    assert result.status == "failed"
    assert manager.calls == 1
    assert calls == ["invalidate"]
