"""Bounded, stable cursor reads for immutable Alert Events."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import UTC, date, datetime
import json

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.alerts.models import AlertEvent, AlertRule
from app.alerts.registry import alert_rule_definitions


_MAX_CURSOR_LENGTH = 2048


class AlertHistoryCursorError(ValueError):
    pass


class AlertHistoryFactsError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AlertHistoryQuery:
    start_day: date
    end_day: date
    symbol: str | None
    rule_code: str | None
    limit: int
    before: str | None

    @property
    def identity(self) -> dict[str, object]:
        return {
            "start_day": self.start_day.isoformat(),
            "end_day": self.end_day.isoformat(),
            "symbol": self.symbol,
            "rule_code": self.rule_code,
            "limit": self.limit,
        }


@dataclass(frozen=True, slots=True)
class AlertHistoryPage:
    items: tuple[AlertEvent, ...]
    next_before: str | None


def read_alert_history(session: Session, query: AlertHistoryQuery) -> AlertHistoryPage:
    cursor = _decode_cursor(query.before, query.identity) if query.before else None
    allowed_rule_codes = tuple(
        definition.rule_code for definition in alert_rule_definitions()
    )
    filters = [
        AlertEvent.trading_day >= query.start_day,
        AlertEvent.trading_day <= query.end_day,
    ]
    if query.symbol is not None:
        filters.append(AlertEvent.symbol == query.symbol)
    if query.rule_code is not None:
        filters.append(AlertRule.rule_code == query.rule_code)

    unknown = session.scalar(
        select(AlertEvent.id)
        .join(AlertRule, AlertEvent.rule_id == AlertRule.id)
        .where(*filters, AlertRule.rule_code.not_in(allowed_rule_codes))
        .limit(1)
    )
    if unknown is not None:
        raise AlertHistoryFactsError

    if cursor is not None:
        detected_at, bar_end, event_id = cursor
        filters.append(
            or_(
                AlertEvent.detected_at < detected_at,
                and_(
                    AlertEvent.detected_at == detected_at,
                    AlertEvent.bar_end < bar_end,
                ),
                and_(
                    AlertEvent.detected_at == detected_at,
                    AlertEvent.bar_end == bar_end,
                    AlertEvent.id < event_id,
                ),
            )
        )

    rows = tuple(
        session.scalars(
            select(AlertEvent)
            .join(AlertRule, AlertEvent.rule_id == AlertRule.id)
            .where(*filters, AlertRule.rule_code.in_(allowed_rule_codes))
            .order_by(
                AlertEvent.detected_at.desc(),
                AlertEvent.bar_end.desc(),
                AlertEvent.id.desc(),
            )
            .limit(query.limit + 1)
        ).all()
    )
    page = rows[: query.limit]
    next_before = None
    if len(rows) > query.limit:
        last = page[-1]
        next_before = _encode_cursor(
            query.identity,
            detected_at=_utc(last.detected_at),
            bar_end=_utc(last.bar_end),
            event_id=last.id,
        )
    return AlertHistoryPage(page, next_before)


def _encode_cursor(
    query_identity: dict[str, object],
    *,
    detected_at: datetime,
    bar_end: datetime,
    event_id: int,
) -> str:
    payload = {
        "v": 1,
        "query": query_identity,
        "key": [detected_at.isoformat(), bar_end.isoformat(), event_id],
    }
    raw = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _decode_cursor(
    value: str,
    query_identity: dict[str, object],
) -> tuple[datetime, datetime, int]:
    if len(value) > _MAX_CURSOR_LENGTH:
        raise AlertHistoryCursorError
    try:
        padding = "=" * (-len(value) % 4)
        payload = json.loads(
            base64.b64decode(
                (value + padding).encode("ascii"),
                altchars=b"-_",
                validate=True,
            ).decode("utf-8")
        )
        if (
            not isinstance(payload, dict)
            or set(payload) != {"v", "query", "key"}
            or payload.get("v") != 1
            or payload.get("query") != query_identity
            or not isinstance(payload.get("key"), list)
            or len(payload["key"]) != 3
            or not isinstance(payload["key"][0], str)
            or not isinstance(payload["key"][1], str)
            or not isinstance(payload["key"][2], int)
            or isinstance(payload["key"][2], bool)
            or payload["key"][2] <= 0
        ):
            raise ValueError("cursor")
        detected_at = datetime.fromisoformat(payload["key"][0])
        bar_end = datetime.fromisoformat(payload["key"][1])
        if (
            detected_at.tzinfo is None
            or detected_at.utcoffset() is None
            or bar_end.tzinfo is None
            or bar_end.utcoffset() is None
        ):
            raise ValueError("cursor timezone")
        return detected_at.astimezone(UTC), bar_end.astimezone(UTC), payload["key"][2]
    except (ValueError, TypeError, KeyError, json.JSONDecodeError, UnicodeError):
        raise AlertHistoryCursorError from None


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
