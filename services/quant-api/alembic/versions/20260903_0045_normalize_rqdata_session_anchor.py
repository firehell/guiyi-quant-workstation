"""Normalize RQData first-minute session labels to exclusive boundaries.

Revision ID: 20260903_0045
Revises: 20260902_0044
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, time, timedelta

from alembic import op
import sqlalchemy as sa


revision: str = "20260903_0045"
down_revision: str | Sequence[str] | None = "20260902_0044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_HTDY_RULE = "htdy_original_15m"
_SUBING_RULE = "subing_ths_alert_15m_v1"


def upgrade() -> None:
    bind = op.get_bind()
    sessions_before, rules_before = _preflight(bind)
    try:
        bind.execute(sa.text(
            "UPDATE trading_sessions "
            "SET start_time = (start_time - INTERVAL '1 minute')::time, "
            "crosses_midnight = "
            "end_time <= (start_time - INTERVAL '1 minute')::time "
            "WHERE provider = 'rqdata'"
        ))
    except sa.exc.SQLAlchemyError:
        raise RuntimeError("RQDATA_SESSION_ANCHOR_UPGRADE_FAILED") from None
    _postflight(bind, sessions_before, rules_before)


def downgrade() -> None:
    raise RuntimeError("RQDATA_SESSION_ANCHOR_DOWNGRADE_UNSUPPORTED")


def _exclusive_start(provider_label: time) -> time:
    anchor = datetime.combine(date(2000, 1, 2), provider_label)
    return (anchor - timedelta(minutes=1)).time()


def _preflight(
    bind: sa.Connection,
) -> tuple[tuple[dict[str, object], ...], tuple[dict[str, object], ...]]:
    try:
        versions = tuple(
            bind.execute(sa.text("SELECT version_num FROM alembic_version")).scalars()
        )
        sessions = tuple(dict(row) for row in bind.execute(sa.text(
            "SELECT id, exchange_code, instrument_symbol, session_name, "
            "start_time, end_time, effective_from, effective_to, "
            "crosses_midnight, is_active, provider, created_at "
            "FROM trading_sessions ORDER BY id"
        )).mappings())
        rules = tuple(dict(row) for row in bind.execute(sa.text(
            "SELECT id, rule_code, enabled, scope_product_frequencies, "
            "created_at, updated_at FROM alert_rules ORDER BY id"
        )).mappings())
        subing_events = bind.scalar(sa.text(
            "SELECT COUNT(*) FROM alert_events e JOIN alert_rules r "
            "ON r.id = e.rule_id WHERE r.rule_code = :rule_code"
        ), {"rule_code": _SUBING_RULE})
    except (sa.exc.SQLAlchemyError, TypeError, ValueError):
        raise RuntimeError("RQDATA_SESSION_ANCHOR_PREFLIGHT_FAILED") from None
    by_code = {row["rule_code"]: row for row in rules}
    subing = by_code.get(_SUBING_RULE)
    if (
        versions != ("20260902_0044",)
        or set(by_code) != {_HTDY_RULE, _SUBING_RULE}
        or len(rules) != 2
        or subing is None
        or subing["enabled"] is not False
        or subing["scope_product_frequencies"] != {}
        or subing_events != 0
        or not _valid_sessions(sessions)
    ):
        raise RuntimeError("RQDATA_SESSION_ANCHOR_PREFLIGHT_FAILED")
    return sessions, rules


def _postflight(
    bind: sa.Connection,
    sessions_before: tuple[Mapping[str, object], ...],
    rules_before: tuple[Mapping[str, object], ...],
) -> None:
    try:
        sessions_after = tuple(dict(row) for row in bind.execute(sa.text(
            "SELECT id, exchange_code, instrument_symbol, session_name, "
            "start_time, end_time, effective_from, effective_to, "
            "crosses_midnight, is_active, provider, created_at "
            "FROM trading_sessions ORDER BY id"
        )).mappings())
        rules_after = tuple(dict(row) for row in bind.execute(sa.text(
            "SELECT id, rule_code, enabled, scope_product_frequencies, "
            "created_at, updated_at FROM alert_rules ORDER BY id"
        )).mappings())
    except (sa.exc.SQLAlchemyError, TypeError, ValueError):
        raise RuntimeError("RQDATA_SESSION_ANCHOR_POSTFLIGHT_FAILED") from None
    expected = tuple(_normalized_session(row) for row in sessions_before)
    if sessions_after != expected or rules_after != tuple(map(dict, rules_before)):
        raise RuntimeError("RQDATA_SESSION_ANCHOR_POSTFLIGHT_FAILED")


def _valid_sessions(rows: tuple[Mapping[str, object], ...]) -> bool:
    identities: set[tuple[object, ...]] = set()
    groups: dict[tuple[object, ...], list[tuple[time, time]]] = {}
    for row in rows:
        start = row.get("start_time")
        end = row.get("end_time")
        if not isinstance(start, time) or not isinstance(end, time):
            return False
        if start.second or start.microsecond or end.second or end.microsecond:
            return False
        normalized = _exclusive_start(start) if row.get("provider") == "rqdata" else start
        identity = (
            row.get("exchange_code"),
            row.get("instrument_symbol"),
            row.get("session_name"),
            normalized,
            end,
            row.get("effective_from"),
        )
        if identity in identities:
            return False
        identities.add(identity)
        group = (
            row.get("exchange_code"),
            row.get("instrument_symbol"),
            row.get("effective_from"),
            row.get("effective_to"),
            row.get("is_active"),
        )
        groups.setdefault(group, []).append((normalized, end))
    return all(_non_overlapping(periods) for periods in groups.values())


def _non_overlapping(periods: list[tuple[time, time]]) -> bool:
    has_night = any(start >= time(18) for start, _ in periods)
    intervals: list[tuple[int, int]] = []
    for start, end in periods:
        left = start.hour * 60 + start.minute
        right = end.hour * 60 + end.minute
        if has_night and start < time(18):
            left += 24 * 60
            right += 24 * 60
        elif right <= left:
            right += 24 * 60
        if right <= left:
            return False
        intervals.append((left, right))
    ordered = sorted(intervals)
    return not any(
        previous[1] > current[0]
        for previous, current in zip(ordered, ordered[1:])
    )


def _normalized_session(row: Mapping[str, object]) -> dict[str, object]:
    result = dict(row)
    if result["provider"] != "rqdata":
        return result
    start = result["start_time"]
    end = result["end_time"]
    assert isinstance(start, time) and isinstance(end, time)
    normalized = _exclusive_start(start)
    result["start_time"] = normalized
    result["crosses_midnight"] = end <= normalized
    return result
