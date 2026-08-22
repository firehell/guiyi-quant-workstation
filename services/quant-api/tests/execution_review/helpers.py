from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from threading import Barrier

from sqlalchemy import event as sqlalchemy_event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.alerts.models import AlertEvent, AlertRule
from app.execution_review.errors import ExecutionReviewDomainError
from app.execution_review.queries import ExecutionReviewQueryService
from app.execution_review.service import (
    ExecutedCommand,
    ExecutionReviewService,
    ReviewCommand,
)


BAR_END = datetime(2026, 8, 15, 1, 0, tzinfo=UTC)
SERVER_NOW = BAR_END + timedelta(minutes=20)
QUANT_API_ROOT = Path(__file__).resolve().parents[1]

def _service(session: Session, *, now: datetime = SERVER_NOW) -> ExecutionReviewService:
    return ExecutionReviewService(
        session,
        multipliers={"jm": Decimal("60")},
        clock=lambda: now,
    )


def _query_service(session: Session) -> ExecutionReviewQueryService:
    return ExecutionReviewQueryService(
        session,
        multipliers={"jm": Decimal("60")},
    )


def _executed(**changes: object) -> ExecutedCommand:
    values: dict[str, object] = {
        "executed_at": BAR_END + timedelta(minutes=3),
        "price": Decimal("1268.5"),
        "quantity": 2,
        "execution_reason_tags": ("KEY_LEVEL_BREAKOUT",),
    }
    values.update(changes)
    return ExecutedCommand(**values)  # type: ignore[arg-type]


def _review_command(**changes: object) -> ReviewCommand:
    values: dict[str, object] = {
        "signal_execution_adherence": "ALIGNED",
        "entry_tags": ("REASONABLE",),
        "holding_tags": ("NORMAL",),
        "exit_tags": ("NORMAL",),
        "market_context_tags": ("TREND",),
        "psychology_tags": ("NONE",),
        "summary": "reviewed",
    }
    values.update(changes)
    return ReviewCommand(**values)  # type: ignore[arg-type]


def _event(session: Session, **changes: object) -> AlertEvent:
    rule_code = str(changes.pop("rule_code", "subing_entry_signal_v1"))
    result_codes = changes.pop("result_codes", ["sell"])
    trading_day = changes.pop("trading_day", date(2026, 8, 15))
    contract = changes.pop("contract", "JM2609")
    frequency = changes.pop("frequency", "15m")
    symbol = str(changes.pop("symbol", "jm"))
    bar_end = changes.pop("bar_end", BAR_END)
    lower_tf_confirmation = bool(changes.pop("lower_tf_confirmation", False))
    detected_at = changes.pop("detected_at", bar_end + timedelta(seconds=1))
    notification_attempted_at = changes.pop("notification_attempted_at", None)
    if changes:
        raise AssertionError(f"unknown event changes: {changes}")
    rule = session.scalar(select(AlertRule).where(AlertRule.rule_code == rule_code))
    if rule is None:
        rule = AlertRule(
            rule_code=rule_code,
            enabled=True,
            scope_products=[symbol],
            created_at=BAR_END,
            updated_at=BAR_END,
        )
    event = AlertEvent(
        rule=rule,
        symbol=symbol,
        contract=contract,
        trading_day=trading_day,
        frequency=frequency,
        bar_end=bar_end,
        result_codes=result_codes,
        lower_tf_confirmation=lower_tf_confirmation,
        detected_at=detected_at,
        notification_attempted_at=notification_attempted_at,
    )
    session.add(event)
    session.commit()
    session.refresh(event)
    return event


def _count(session: Session, model: type[object]) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _race_open_events(
    factory: sessionmaker[Session],
    event_ids: tuple[int, int],
) -> tuple[tuple[int, str], ...]:
    barrier = Barrier(2)

    def race(event_id: int, minute: int) -> tuple[int, str]:
        with factory() as local_session:
            intercepted = False

            @sqlalchemy_event.listens_for(
                local_session,
                "do_orm_execute",
                retval=True,
            )
            def synchronize_open_lookup(state: object):
                nonlocal intercepted
                statement = str(state.statement)  # type: ignore[attr-defined]
                if (
                    not intercepted
                    and "trade_episodes" in statement
                    and "closed_at IS NULL" in statement
                ):
                    intercepted = True
                    result = state.invoke_statement()  # type: ignore[attr-defined]
                    barrier.wait(timeout=10)
                    return result
                return state.invoke_statement()  # type: ignore[attr-defined]

            try:
                _service(local_session).record_executed(
                    event_id,
                    _executed(
                        executed_at=BAR_END + timedelta(minutes=minute),
                        quantity=1,
                    ),
                )
                return event_id, "created"
            except ExecutionReviewDomainError as exc:
                return event_id, exc.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        return tuple(executor.map(race, event_ids, (20, 21)))


def _integrity_error(constraint_name: str) -> IntegrityError:
    diagnostics = type("Diagnostics", (), {"constraint_name": constraint_name})()
    original = type("Original", (Exception,), {"diag": diagnostics})(
        "sensitive SQL and values"
    )
    return IntegrityError("sensitive statement", {"secret": "value"}, original)
