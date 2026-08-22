"""Canonical Execution Review Event eligibility and context rules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts.models import AlertEvent, AlertRule
from app.alerts.registry import SUBING_RULE
from app.execution_review.errors import conflict, invalid, not_found


ELIGIBLE_RULE_CODE = SUBING_RULE.rule_code
ELIGIBLE_FREQUENCIES = frozenset({"5m", "15m"})


@dataclass(frozen=True, slots=True)
class EventContext:
    id: int
    rule_code: str
    symbol: str
    contract: str
    trading_day: date
    frequency: str
    bar_end: datetime
    result_codes: tuple[str, ...]
    lower_tf_confirmation: bool
    detected_at: datetime
    notification_attempted_at: datetime | None


def eligible_direction(event: AlertEvent, rule_code: str) -> str | None:
    if (
        rule_code != ELIGIBLE_RULE_CODE
        or event.trading_day is None
        or not str(event.contract or "").strip()
        or event.frequency not in ELIGIBLE_FREQUENCIES
    ):
        return None
    result_codes = tuple(event.result_codes or ())
    if result_codes == ("buy",):
        return "LONG"
    if result_codes == ("sell",):
        return "SHORT"
    return None


def require_eligible_direction(event: AlertEvent, rule_code: str) -> str:
    if (
        rule_code != ELIGIBLE_RULE_CODE
        or event.trading_day is None
        or not str(event.contract or "").strip()
        or event.frequency not in ELIGIBLE_FREQUENCIES
    ):
        raise invalid("EVENT_NOT_EXECUTION_REVIEW_ELIGIBLE")
    direction = eligible_direction(event, rule_code)
    if direction is None:
        raise invalid("EVENT_DIRECTION_INVALID")
    return direction


def eligible_event(session: Session, event_id: int) -> tuple[AlertEvent, str]:
    row = session.execute(
        select(AlertEvent, AlertRule.rule_code)
        .join(AlertRule, AlertEvent.rule_id == AlertRule.id)
        .where(AlertEvent.id == event_id)
    ).one_or_none()
    if row is None:
        raise not_found("EXECUTION_REVIEW_EVENT_NOT_FOUND")
    event, rule_code = row
    return event, require_eligible_direction(event, rule_code)


def event_context(event: AlertEvent, rule_code: str) -> EventContext:
    if event.trading_day is None:
        raise conflict("DECISION_LINEAGE_INVALID")
    return EventContext(
        id=event.id,
        rule_code=rule_code,
        symbol=event.symbol,
        contract=event.contract,
        trading_day=event.trading_day,
        frequency=event.frequency,
        bar_end=event.bar_end,
        result_codes=tuple(event.result_codes),
        lower_tf_confirmation=event.lower_tf_confirmation,
        detected_at=event.detected_at,
        notification_attempted_at=event.notification_attempted_at,
    )
