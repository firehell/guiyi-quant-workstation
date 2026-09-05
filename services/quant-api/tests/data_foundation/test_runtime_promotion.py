"""Market Runtime promotion preflight contracts."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from contextlib import nullcontext
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session

from app.db.base import Base
from app.market_data.runtime_promotion import _first_session_starts_for_products
from app.market_data.market_phase import MarketPhase, ProductMarketPhase
from app.market_data.runtime_promotion import (
    PROMOTION_STATE_UNAVAILABLE,
    PROMOTION_LIVE_SNAPSHOT_INVALID,
    PROMOTION_LIVE_SNAPSHOT_REQUIRED,
    evaluate_market_runtime_promotion,
    run_market_runtime_promotion_preflight,
)
from app.models import Exchange, Instrument, TradingCalendar, TradingSession


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
    ("status", "expected_reason"),
    [
        (
            {
                "schema_version": 2,
                "last_run": {**_passed_status()["last_run"], "status": "failed", "error_code": "UPDATE_FAILED"},
            },
            PROMOTION_LIVE_SNAPSHOT_REQUIRED,
        ),
        (
            {
                "schema_version": 2,
                "current_run": {
                    "scheduled_date": DAY.isoformat(),
                    "started_at": "2026-09-03T18:05:00+08:00",
                    "products": list(PRODUCTS),
                },
            },
            PROMOTION_STATE_UNAVAILABLE,
        ),
    ],
)
def test_failed_or_running_after_market_status_does_not_replace_required_snapshot(
    status: dict[str, object], expected_reason: str
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
    assert decision.reason == expected_reason


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
def test_non_trading_interval_cannot_bypass_running_or_corrupt_status(
    status: dict[str, object],
) -> None:
    decision = evaluate_market_runtime_promotion(
        products=PRODUCTS,
        phases={
            symbol: _phase(symbol, MarketPhase.CLOSED, trading_day=None)
            for symbol in PRODUCTS
        },
        now=NOW,
        snapshot=None,
        after_market_status=status,
        first_session_starts=None,
    )

    assert decision.status == "blocked"
    assert decision.reason == PROMOTION_STATE_UNAVAILABLE


def test_non_trading_interval_allows_well_formed_historical_failed_status() -> None:
    failed = _passed_status()
    failed["last_run"] = {
        **failed["last_run"],
        "status": "failed",
        "error_code": "UPDATE_FAILED",
    }

    decision = evaluate_market_runtime_promotion(
        products=PRODUCTS,
        phases={
            symbol: _phase(symbol, MarketPhase.CLOSED, trading_day=None)
            for symbol in PRODUCTS
        },
        now=NOW,
        snapshot=None,
        after_market_status=failed,
        first_session_starts=None,
    )

    assert decision.status == "passed"
    assert decision.reason == "non_trading_interval"


def test_non_trading_interval_rejects_reversed_passed_history() -> None:
    status = _passed_status()
    status["last_run"] = {
        **status["last_run"],
        "started_at": "2026-09-03T15:07:00+08:00",
        "finished_at": "2026-09-03T14:07:00+08:00",
    }

    decision = evaluate_market_runtime_promotion(
        products=PRODUCTS,
        phases={
            symbol: _phase(symbol, MarketPhase.CLOSED, trading_day=None)
            for symbol in PRODUCTS
        },
        now=NOW,
        snapshot=None,
        after_market_status=status,
        first_session_starts=None,
    )

    assert decision.reason == PROMOTION_STATE_UNAVAILABLE


def test_snapshot_rejects_future_different_day_passed_history() -> None:
    status = _passed_status()
    status["last_run"] = {
        **status["last_run"],
        "trading_day": "2026-09-02",
        "started_at": "2026-09-03T18:05:00+08:00",
        "finished_at": "2026-09-03T18:07:00+08:00",
    }

    decision = evaluate_market_runtime_promotion(
        products=PRODUCTS,
        phases=_phases(MarketPhase.CLOSED),
        now=NOW,
        snapshot={"j": "J2601", "jm": "JM2601"},
        after_market_status=status,
        first_session_starts=_first_session_starts(),
    )

    assert decision.reason == PROMOTION_STATE_UNAVAILABLE


@pytest.mark.parametrize(
    ("started_at", "finished_at"),
    [
        ("2026-09-03T18:05:00+08:00", "2026-09-03T18:07:00+08:00"),
        ("2026-09-03T15:07:00+08:00", "2026-09-03T14:07:00+08:00"),
    ],
)
def test_failed_history_with_impossible_chronology_is_unavailable(
    started_at: str, finished_at: str
) -> None:
    status = _passed_status()
    status["last_run"] = {
        **status["last_run"],
        "status": "failed",
        "error_code": "UPDATE_FAILED",
        "started_at": started_at,
        "finished_at": finished_at,
    }

    decision = evaluate_market_runtime_promotion(
        products=PRODUCTS,
        phases=_phases(MarketPhase.CLOSED),
        now=NOW,
        snapshot={"j": "J2601", "jm": "JM2601"},
        after_market_status=status,
        first_session_starts=_first_session_starts(),
    )

    assert decision.reason == PROMOTION_STATE_UNAVAILABLE


def test_skipped_history_with_impossible_chronology_is_unavailable() -> None:
    status = _passed_status()
    status["last_run"] = {
        **status["last_run"],
        "status": "skipped",
        "attempts": 0,
        "error_code": "NON_TRADING_DAY",
        "started_at": "2026-09-03T15:07:00+08:00",
        "finished_at": "2026-09-03T14:07:00+08:00",
    }

    decision = evaluate_market_runtime_promotion(
        products=PRODUCTS,
        phases=_phases(MarketPhase.CLOSED),
        now=NOW,
        snapshot={"j": "J2601", "jm": "JM2601"},
        after_market_status=status,
        first_session_starts=_first_session_starts(),
    )

    assert decision.reason == PROMOTION_STATE_UNAVAILABLE


def test_sane_different_day_history_does_not_block_valid_snapshot() -> None:
    status = _passed_status()
    status["last_run"] = {**status["last_run"], "trading_day": "2026-09-02"}

    decision = evaluate_market_runtime_promotion(
        products=PRODUCTS,
        phases=_phases(MarketPhase.CLOSED),
        now=NOW,
        snapshot={"j": "J2601", "jm": "JM2601"},
        after_market_status=status,
        first_session_starts=_first_session_starts(),
    )

    assert decision.reason == "snapshot_ready"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda status: status.update(
            {"last_run": {**status["last_run"], "trading_day": "2026-09-04"}}
        ),
        lambda status: status.update({"last_successful_trading_day": "2026-09-04"}),
        lambda status: status.update(
            {"last_failure": {"trading_day": "2026-09-04", "error_code": "UPDATE_FAILED"}}
        ),
    ],
)
def test_future_public_status_day_blocks_before_snapshot_or_nontrading_pass(
    mutate: object,
) -> None:
    status = _passed_status()
    assert callable(mutate)
    mutate(status)
    decision = evaluate_market_runtime_promotion(
        products=PRODUCTS,
        phases=_phases(MarketPhase.CLOSED),
        now=NOW,
        snapshot={"j": "J2601", "jm": "JM2601"},
        after_market_status=status,
        first_session_starts=_first_session_starts(),
    )
    assert decision.reason == PROMOTION_STATE_UNAVAILABLE


def test_future_last_failure_day_blocks_clean_nontrading_interval() -> None:
    status = _passed_status()
    status["last_failure"] = {"trading_day": "2026-09-04", "error_code": "UPDATE_FAILED"}
    decision = evaluate_market_runtime_promotion(
        products=PRODUCTS,
        phases={
            symbol: _phase(symbol, MarketPhase.CLOSED, trading_day=None)
            for symbol in PRODUCTS
        },
        now=NOW,
        snapshot=None,
        after_market_status=status,
        first_session_starts=None,
    )
    assert decision.reason == PROMOTION_STATE_UNAVAILABLE


@pytest.mark.parametrize("products", [["jm", "j"], ["j", "jm", "rb"]])
def test_after_market_complete_requires_exact_ordered_products(products: list[str]) -> None:
    status = _passed_status()
    status["last_run"] = {**status["last_run"], "products": products}
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


@pytest.mark.parametrize(
    ("attempted_at", "phases", "snapshot"),
    [
        (
            "2026-09-03T18:07:00+08:00",
            _phases(MarketPhase.CLOSED),
            {"j": "J2601", "jm": "JM2601"},
        ),
        (
            "2026-09-03T13:07:00+08:00",
            {
                symbol: _phase(symbol, MarketPhase.CLOSED, trading_day=None)
                for symbol in PRODUCTS
            },
            None,
        ),
    ],
)
def test_failure_notification_impossible_chronology_blocks_before_passes(
    attempted_at: str,
    phases: dict[str, ProductMarketPhase],
    snapshot: object,
) -> None:
    status = _passed_status()
    status["last_run"] = {
        **status["last_run"],
        "status": "failed",
        "error_code": "UPDATE_FAILED",
        "failure_notification": {
            "attempted_at": attempted_at,
            "state": "failed",
            "error_type": "AFTER_MARKET_FAILURE_NOTIFICATION_FAILED",
        },
    }
    decision = evaluate_market_runtime_promotion(
        products=PRODUCTS,
        phases=phases,
        now=NOW,
        snapshot=snapshot,
        after_market_status=status,
        first_session_starts=_first_session_starts() if snapshot is not None else None,
    )
    assert decision.reason == PROMOTION_STATE_UNAVAILABLE


def test_sane_failure_notification_can_coexist_with_valid_snapshot() -> None:
    status = _passed_status()
    status["last_run"] = {
        **status["last_run"],
        "status": "failed",
        "error_code": "UPDATE_FAILED",
        "failure_notification": {
            "attempted_at": "2026-09-03T14:08:00+08:00",
            "state": "failed",
            "error_type": "AFTER_MARKET_FAILURE_NOTIFICATION_FAILED",
        },
    }
    decision = evaluate_market_runtime_promotion(
        products=PRODUCTS,
        phases=_phases(MarketPhase.CLOSED),
        now=NOW,
        snapshot={"j": "J2601", "jm": "JM2601"},
        after_market_status=status,
        first_session_starts=_first_session_starts(),
    )
    assert decision.reason == "snapshot_ready"


def test_first_session_loader_uses_calendar_night_eligibility_and_fails_closed() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    trading_day = date(2026, 9, 3)
    with Session(engine) as session:
        session.add_all(
            (
                Exchange(code="DCE", name="DCE"),
                Instrument(symbol="j", name="J", exchange_code="DCE", is_active=True),
                TradingCalendar(exchange_code="DCE", trade_date=date(2026, 9, 2), is_trading_day=True),
                TradingCalendar(exchange_code="DCE", trade_date=trading_day, is_trading_day=True, has_night_session=True),
                TradingSession(exchange_code="DCE", instrument_symbol="j", session_name="day", start_time=time(9), end_time=time(10), effective_from=date(2026, 1, 1), crosses_midnight=False, is_active=True),
                TradingSession(exchange_code="DCE", instrument_symbol="j", session_name="night", start_time=time(21), end_time=time(23), effective_from=date(2026, 1, 1), crosses_midnight=False, is_active=True),
            )
        )
        session.commit()
        starts = _first_session_starts_for_products(session, ("j",), trading_day)
        assert starts["j"].isoformat() == "2026-09-02T13:00:00+00:00"
        calendar = session.get(TradingCalendar, 2)
        assert calendar is not None
        calendar.has_night_session = False
        session.commit()
        assert _first_session_starts_for_products(session, ("j",), trading_day)["j"].isoformat() == "2026-09-03T01:00:00+00:00"
        session.execute(delete(TradingSession))
        session.commit()
        with pytest.raises(ValueError, match="PROMOTION_SESSION_AUTHORITY_UNAVAILABLE"):
            _first_session_starts_for_products(session, ("j",), trading_day)


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
