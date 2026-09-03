"""Market Runtime promotion preflight contracts."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from contextlib import nullcontext
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from app.market_data.market_phase import MarketPhase, ProductMarketPhase
from app.market_data.runtime_promotion import (
    PROMOTION_STATE_UNAVAILABLE,
    PROMOTION_LIVE_SNAPSHOT_INVALID,
    PROMOTION_LIVE_SNAPSHOT_REQUIRED,
    evaluate_market_runtime_promotion,
    run_market_runtime_promotion_preflight,
)


DAY = date(2026, 9, 3)
NOW = datetime(2026, 9, 3, 8, 0, tzinfo=UTC)
PRODUCTS = ("j", "jm")


def _phase(
    symbol: str,
    phase: MarketPhase,
    *,
    trading_day: date | None = DAY,
    next_session_start: datetime | None = None,
) -> ProductMarketPhase:
    return ProductMarketPhase(
        symbol=symbol,
        phase=phase,
        trading_day=trading_day,
        current_session=None,
        next_session_start=next_session_start,
    )


def _phases(phase: MarketPhase = MarketPhase.TRADING) -> dict[str, ProductMarketPhase]:
    return {symbol: _phase(symbol, phase) for symbol in PRODUCTS}


def _first_session_starts(
    start: datetime = NOW - timedelta(hours=1),
) -> dict[str, datetime]:
    return {symbol: start for symbol in PRODUCTS}


def _passed_status() -> dict[str, object]:
    return {
        "schema_version": 2,
        "last_run": {
            "trading_day": DAY.isoformat(),
            "status": "passed",
            "attempts": 1,
            "started_at": "2026-09-03T14:05:00+08:00",
            "finished_at": "2026-09-03T14:07:00+08:00",
            "products": list(PRODUCTS),
            "error_code": None,
        },
    }


def test_present_complete_snapshot_allows_promotion_without_rank1_reconciliation() -> None:
    decision = evaluate_market_runtime_promotion(
        products=PRODUCTS,
        phases=_phases(),
        now=NOW,
        snapshot={"j": "J2601", "jm": "JM2601"},
        after_market_status=None,
        first_session_starts=_first_session_starts(),
    )

    assert decision.payload() == {
        "schema_version": 1,
        "command": "runtime.market-promotion-preflight",
        "status": "passed",
        "reason": "snapshot_ready",
        "trading_day": DAY.isoformat(),
        "operational_count": 2,
        "snapshot_count": 2,
    }


@pytest.mark.parametrize(
    ("snapshot", "expected_reason"),
    [
        ({"j": "J2601"}, PROMOTION_LIVE_SNAPSHOT_INVALID),
        ({"j": "JM2601", "jm": "JM2601"}, PROMOTION_LIVE_SNAPSHOT_INVALID),
        ({"j": "J2601", "jm": object()}, PROMOTION_LIVE_SNAPSHOT_INVALID),
    ],
)
def test_present_partial_or_malformed_snapshot_blocks(
    snapshot: dict[str, object], expected_reason: str
) -> None:
    decision = evaluate_market_runtime_promotion(
        products=PRODUCTS,
        phases=_phases(),
        now=NOW,
        snapshot=snapshot,
        after_market_status=None,
        first_session_starts=_first_session_starts(),
    )

    assert decision.status == "blocked"
    assert decision.reason == expected_reason
    assert decision.snapshot_count == len(snapshot)


def test_absent_snapshot_before_first_session_allows_promotion() -> None:
    first_start = NOW + timedelta(hours=1)
    decision = evaluate_market_runtime_promotion(
        products=PRODUCTS,
        phases={
            symbol: _phase(
                symbol,
                MarketPhase.CLOSED,
                next_session_start=NOW + timedelta(hours=3),
            )
            for symbol in PRODUCTS
        },
        now=NOW,
        snapshot=None,
        after_market_status=None,
        first_session_starts=_first_session_starts(first_start),
    )

    assert decision.status == "passed"
    assert decision.reason == "before_first_session"


def test_absent_snapshot_after_start_requires_live_snapshot() -> None:
    decision = evaluate_market_runtime_promotion(
        products=PRODUCTS,
        phases=_phases(),
        now=NOW,
        snapshot=None,
        after_market_status=None,
        first_session_starts=_first_session_starts(),
    )

    assert decision.status == "blocked"
    assert decision.reason == PROMOTION_LIVE_SNAPSHOT_REQUIRED


def test_absent_snapshot_after_same_day_passed_after_market_allows_promotion() -> None:
    decision = evaluate_market_runtime_promotion(
        products=PRODUCTS,
        phases=_phases(MarketPhase.CLOSED),
        now=NOW,
        snapshot=None,
        after_market_status=_passed_status(),
        first_session_starts=_first_session_starts(),
    )

    assert decision.status == "passed"
    assert decision.reason == "after_market_complete"


@pytest.mark.parametrize(
    "status",
    [
        {
            "schema_version": 2,
            "current_run": {
                "scheduled_date": DAY.isoformat(),
                "started_at": "2026-09-03T14:05:00+08:00",
                "products": list(PRODUCTS),
            },
        },
        {"schema_version": 99},
    ],
)
def test_valid_snapshot_cannot_bypass_running_or_corrupt_after_market_status(
    status: dict[str, object],
) -> None:
    decision = evaluate_market_runtime_promotion(
        products=PRODUCTS,
        phases=_phases(MarketPhase.CLOSED),
        now=NOW,
        snapshot={"j": "J2601", "jm": "JM2601"},
        after_market_status=status,
        first_session_starts=_first_session_starts(),
    )

    assert decision.reason == PROMOTION_STATE_UNAVAILABLE


def test_valid_snapshot_can_allow_when_only_historical_failed_status_remains() -> None:
    failed = _passed_status()
    failed["last_run"] = {
        **failed["last_run"],
        "status": "failed",
        "error_code": "UPDATE_FAILED",
    }

    decision = evaluate_market_runtime_promotion(
        products=PRODUCTS,
        phases=_phases(MarketPhase.CLOSED),
        now=NOW,
        snapshot={"j": "J2601", "jm": "JM2601"},
        after_market_status=failed,
        first_session_starts=_first_session_starts(),
    )

    assert decision.reason == "snapshot_ready"


def test_runner_observes_current_run_written_after_snapshot_read(tmp_path: Path) -> None:
    class Resolver:
        def resolve(self, symbol: str, _now: datetime) -> ProductMarketPhase:
            return _phase(symbol, MarketPhase.CLOSED)

    status_path = tmp_path / "after-market-status.json"

    class Store:
        def subscriptions(self, _trading_day: date) -> dict[str, str]:
            status_path.write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "current_run": {
                            "scheduled_date": DAY.isoformat(),
                            "started_at": "2026-09-03T14:05:00+08:00",
                            "products": list(PRODUCTS),
                        },
                    }
                ),
                encoding="utf-8",
            )
            return {"j": "J2601", "jm": "JM2601"}

    decision = run_market_runtime_promotion_preflight(
        session_factory=lambda: nullcontext(object()),
        phase_resolver_factory=lambda _session: Resolver(),
        live_store_factory=lambda: Store(),  # type: ignore[arg-type]
        products_loader=lambda: PRODUCTS,
        first_session_starts_loader=lambda _session, _products, _day: _first_session_starts(),
        status_path=status_path,
        now=lambda: NOW,
    )

    assert decision.reason == PROMOTION_STATE_UNAVAILABLE


def test_preflight_module_contains_bootstrap_failure_in_one_bounded_json_line() -> None:
    environment = {
        **os.environ,
        "PYTHONPATH": "services/quant-api:packages/quant-core",
        "DATABASE_URL": "bootstrap-secret://invalid",
    }
    result = subprocess.run(
        [sys.executable, "-m", "app.market_data.runtime_promotion"],
        cwd=Path(__file__).resolve().parents[4],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    lines = result.stdout.splitlines()
    assert result.returncode == 1
    assert len(lines) == 1
    assert json.loads(lines[0]) == {
        "schema_version": 1,
        "command": "runtime.market-promotion-preflight",
        "status": "blocked",
        "reason": PROMOTION_STATE_UNAVAILABLE,
        "trading_day": None,
        "operational_count": 0,
        "snapshot_count": 0,
    }
    assert result.stderr == ""
    assert "bootstrap-secret" not in result.stdout + result.stderr
    assert "Traceback" not in result.stdout + result.stderr


def test_future_or_reversed_after_market_completion_blocks_state_unavailable() -> None:
    future = _passed_status()
    future["last_run"] = {
        **future["last_run"],
        "started_at": "2026-09-03T18:05:00+08:00",
        "finished_at": "2026-09-03T18:07:00+08:00",
    }
    reversed_times = _passed_status()
    reversed_times["last_run"] = {
        **reversed_times["last_run"],
        "started_at": "2026-09-03T15:07:00+08:00",
        "finished_at": "2026-09-03T14:07:00+08:00",
    }

    for status in (future, reversed_times):
        decision = evaluate_market_runtime_promotion(
            products=PRODUCTS,
            phases=_phases(MarketPhase.CLOSED),
            now=NOW,
            snapshot=None,
            after_market_status=status,
            first_session_starts=_first_session_starts(),
        )
        assert decision.reason == PROMOTION_STATE_UNAVAILABLE


@pytest.mark.parametrize(
    "status",
    [
        {
            "schema_version": 2,
            "last_run": {**_passed_status()["last_run"], "status": "failed", "error_code": "UPDATE_FAILED"},
        },
        {
            "schema_version": 2,
            "current_run": {
                "scheduled_date": DAY.isoformat(),
                "started_at": "2026-09-03T18:05:00+08:00",
                "products": list(PRODUCTS),
            },
        },
    ],
)
def test_failed_or_running_after_market_status_does_not_replace_required_snapshot(
    status: dict[str, object],
) -> None:
    decision = evaluate_market_runtime_promotion(
        products=PRODUCTS,
        phases=_phases(MarketPhase.CLOSED),
        now=NOW,
        snapshot=None,
        after_market_status=status,
        first_session_starts=_first_session_starts(),
    )

    assert decision.status == "blocked"
    assert decision.reason == PROMOTION_LIVE_SNAPSHOT_REQUIRED


@pytest.mark.parametrize(
    "status",
    [
        {"schema_version": 99},
        {"schema_version": 2, "last_run": {"status": "passed"}},
    ],
)
def test_corrupt_after_market_status_blocks_state_unavailable(
    status: dict[str, object],
) -> None:
    decision = evaluate_market_runtime_promotion(
        products=PRODUCTS,
        phases=_phases(MarketPhase.CLOSED),
        now=NOW,
        snapshot=None,
        after_market_status=status,
        first_session_starts=_first_session_starts(),
    )

    assert decision.status == "blocked"
    assert decision.reason == PROMOTION_STATE_UNAVAILABLE


def test_clean_non_trading_interval_allows_absent_snapshot() -> None:
    decision = evaluate_market_runtime_promotion(
        products=PRODUCTS,
        phases={
            symbol: _phase(symbol, MarketPhase.CLOSED, trading_day=None)
            for symbol in PRODUCTS
        },
        now=NOW,
        snapshot=None,
        after_market_status=None,
        first_session_starts=None,
    )

    assert decision.status == "passed"
    assert decision.reason == "non_trading_interval"
    assert decision.trading_day is None


def test_day_end_to_night_gap_is_not_before_first_session() -> None:
    decision = evaluate_market_runtime_promotion(
        products=PRODUCTS,
        phases={
            symbol: _phase(
                symbol,
                MarketPhase.CLOSED,
                next_session_start=NOW + timedelta(hours=3),
            )
            for symbol in PRODUCTS
        },
        now=NOW,
        snapshot=None,
        after_market_status=None,
        first_session_starts=_first_session_starts(NOW - timedelta(hours=12)),
    )

    assert decision.reason == PROMOTION_LIVE_SNAPSHOT_REQUIRED


def test_missing_or_ambiguous_first_session_metadata_blocks_state_unavailable() -> None:
    missing = evaluate_market_runtime_promotion(
        products=PRODUCTS,
        phases=_phases(MarketPhase.CLOSED),
        now=NOW,
        snapshot=None,
        after_market_status=None,
        first_session_starts=None,
    )
    ambiguous = evaluate_market_runtime_promotion(
        products=PRODUCTS,
        phases=_phases(MarketPhase.CLOSED),
        now=NOW,
        snapshot=None,
        after_market_status=None,
        first_session_starts={"j": NOW - timedelta(hours=1)},
    )

    assert missing.reason == PROMOTION_STATE_UNAVAILABLE
    assert ambiguous.reason == PROMOTION_STATE_UNAVAILABLE


def test_session_authority_dependency_failure_blocks_without_reading_snapshot() -> None:
    class Resolver:
        def resolve(self, symbol: str, _now: datetime) -> ProductMarketPhase:
            return _phase(symbol, MarketPhase.CLOSED)

    class Store:
        def subscriptions(self, _trading_day: date) -> object:
            raise AssertionError("snapshot must not be read before Session authority")

    def unavailable_session_authority(
        _session: object, _products: tuple[str, ...], _trading_day: date
    ) -> dict[str, datetime]:
        raise ValueError("session facts unavailable")

    decision = run_market_runtime_promotion_preflight(
        session_factory=lambda: nullcontext(object()),
        phase_resolver_factory=lambda _session: Resolver(),
        live_store_factory=lambda: Store(),  # type: ignore[arg-type]
        products_loader=lambda: PRODUCTS,
        first_session_starts_loader=unavailable_session_authority,
        status_path=Path("/definitely/unreadable-status-file"),
        now=lambda: NOW,
    )

    assert decision.reason == PROMOTION_STATE_UNAVAILABLE


def test_phase_disagreement_or_dependency_error_blocks_state_unavailable() -> None:
    disagreement = evaluate_market_runtime_promotion(
        products=PRODUCTS,
        phases={"j": _phase("j", MarketPhase.TRADING), "jm": _phase("jm", MarketPhase.TRADING, trading_day=date(2026, 9, 4))},
        now=NOW,
        snapshot=None,
        after_market_status=None,
        first_session_starts=_first_session_starts(),
    )
    dependency_failure = evaluate_market_runtime_promotion(
        products=PRODUCTS,
        phases=None,
        now=NOW,
        snapshot=None,
        after_market_status=None,
        first_session_starts=_first_session_starts(),
    )
    missing_closed_day = evaluate_market_runtime_promotion(
        products=PRODUCTS,
        phases={
            "j": _phase("j", MarketPhase.CLOSED),
            "jm": _phase("jm", MarketPhase.CLOSED, trading_day=None),
        },
        now=NOW,
        snapshot=None,
        after_market_status=None,
        first_session_starts=_first_session_starts(),
    )

    assert disagreement.reason == PROMOTION_STATE_UNAVAILABLE
    assert dependency_failure.reason == PROMOTION_STATE_UNAVAILABLE
    assert missing_closed_day.reason == PROMOTION_STATE_UNAVAILABLE
