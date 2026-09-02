"""Add the disabled SuBing THS Alert Rule to the generic Alert domain.

Revision ID: 20260902_0044
Revises: 20260902_0043
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
import re

from alembic import op
import sqlalchemy as sa


revision: str = "20260902_0044"
down_revision: str | Sequence[str] | None = "20260902_0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_HTDY_RULE = "htdy_original_15m"
_SUBING_RULE = "subing_ths_alert_15m_v1"
_EXPECTED_RULE_COLUMNS = frozenset({
    "id", "rule_code", "enabled", "scope_product_frequencies", "created_at",
    "updated_at",
})
_EXPECTED_EVENT_COLUMNS = frozenset({
    "id", "rule_id", "symbol", "contract", "trading_day", "frequency",
    "bar_end", "result_codes", "detected_at", "notification_attempted_at",
    "created_at",
})
_HTDY_FREQUENCIES = frozenset({"1m", "5m", "15m", "30m", "60m", "1d", "1w"})
_SYMBOL_PATTERN = re.compile(r"[a-z]+\Z")


def upgrade() -> None:
    bind = op.get_bind()
    htdy_rule_before, htdy_events_before = _preflight(bind)
    now = datetime.now(UTC)
    rules = sa.table(
        "alert_rules",
        sa.column("rule_code", sa.String()),
        sa.column("enabled", sa.Boolean()),
        sa.column("scope_product_frequencies", sa.JSON()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    try:
        bind.execute(sa.insert(rules).values(
            rule_code=_SUBING_RULE,
            enabled=False,
            scope_product_frequencies={},
            created_at=now,
            updated_at=now,
        ))
    except sa.exc.SQLAlchemyError:
        raise RuntimeError("SUBING_THS_ALERT_UPGRADE_FAILED") from None
    _postflight(bind, htdy_rule_before, htdy_events_before)


def downgrade() -> None:
    raise RuntimeError("SUBING_THS_ALERT_DOWNGRADE_UNSUPPORTED")


def _preflight(
    bind: sa.Connection,
) -> tuple[dict[str, object], tuple[dict[str, object], ...]]:
    try:
        versions = tuple(
            bind.execute(sa.text("SELECT version_num FROM alembic_version")).scalars()
        )
        rule_columns = _columns(bind, "alert_rules")
        event_columns = _columns(bind, "alert_events")
        rule_rows = bind.execute(sa.text(
            "SELECT id, rule_code, enabled, scope_product_frequencies, "
            "created_at, updated_at FROM alert_rules ORDER BY id"
        )).mappings().all()
        event_rows = bind.execute(sa.text(
            "SELECT e.id, e.rule_id, e.symbol, e.contract, e.trading_day, "
            "e.frequency, e.bar_end, e.result_codes, e.detected_at, "
            "e.notification_attempted_at, e.created_at, r.rule_code AS rule_code "
            "FROM alert_events e LEFT JOIN alert_rules r ON r.id = e.rule_id "
            "ORDER BY e.id"
        )).mappings().all()
    except (sa.exc.SQLAlchemyError, TypeError, ValueError):
        raise RuntimeError("SUBING_THS_ALERT_PREFLIGHT_FAILED") from None

    by_code = {row["rule_code"]: row for row in rule_rows}
    htdy = by_code.get(_HTDY_RULE)
    if (
        versions != ("20260902_0043",)
        or rule_columns != _EXPECTED_RULE_COLUMNS
        or event_columns != _EXPECTED_EVENT_COLUMNS
        or len(rule_rows) != 1
        or frozenset(by_code) != {_HTDY_RULE}
        or htdy is None
        or not _valid_htdy_rule(htdy)
        or not all(
            row["rule_code"] == _HTDY_RULE
            and row["rule_id"] == htdy["id"]
            and _valid_htdy_event(row)
            for row in event_rows
        )
    ):
        raise RuntimeError("SUBING_THS_ALERT_PREFLIGHT_FAILED")
    return dict(htdy), tuple(dict(row) for row in event_rows)


def _postflight(
    bind: sa.Connection,
    htdy_rule_before: Mapping[str, object],
    htdy_events_before: tuple[Mapping[str, object], ...],
) -> None:
    try:
        rule_rows = bind.execute(sa.text(
            "SELECT id, rule_code, enabled, scope_product_frequencies, "
            "created_at, updated_at FROM alert_rules ORDER BY rule_code"
        )).mappings().all()
        event_rows = bind.execute(sa.text(
            "SELECT e.id, e.rule_id, e.symbol, e.contract, e.trading_day, "
            "e.frequency, e.bar_end, e.result_codes, e.detected_at, "
            "e.notification_attempted_at, e.created_at, r.rule_code AS rule_code "
            "FROM alert_events e LEFT JOIN alert_rules r ON r.id = e.rule_id "
            "ORDER BY e.id"
        )).mappings().all()
        rule_columns = _columns(bind, "alert_rules")
        event_columns = _columns(bind, "alert_events")
    except (sa.exc.SQLAlchemyError, TypeError, ValueError):
        raise RuntimeError("SUBING_THS_ALERT_POSTFLIGHT_FAILED") from None

    by_code = {row["rule_code"]: row for row in rule_rows}
    htdy = by_code.get(_HTDY_RULE)
    subing = by_code.get(_SUBING_RULE)
    if (
        rule_columns != _EXPECTED_RULE_COLUMNS
        or event_columns != _EXPECTED_EVENT_COLUMNS
        or len(rule_rows) != 2
        or frozenset(by_code) != {_HTDY_RULE, _SUBING_RULE}
        or htdy is None
        or subing is None
        or dict(htdy) != dict(htdy_rule_before)
        or not _valid_htdy_rule(htdy)
        or not _valid_subing_rule(subing)
        or tuple(dict(row) for row in event_rows) != tuple(
            dict(row) for row in htdy_events_before
        )
        or not all(
            row["rule_code"] == _HTDY_RULE
            and row["rule_id"] == htdy["id"]
            and _valid_htdy_event(row)
            for row in event_rows
        )
    ):
        raise RuntimeError("SUBING_THS_ALERT_POSTFLIGHT_FAILED")


def _columns(bind: sa.Connection, table_name: str) -> frozenset[str]:
    return frozenset(bind.execute(sa.text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = :table_name"
    ), {"table_name": table_name}).scalars())


def _valid_htdy_rule(row: Mapping[str, object]) -> bool:
    scope = row["scope_product_frequencies"]
    return (
        type(row["id"]) is int
        and row["rule_code"] == _HTDY_RULE
        and type(row["enabled"]) is bool
        and _valid_frequency_scope(scope)
        and _aware_datetime(row["created_at"])
        and _aware_datetime(row["updated_at"])
    )


def _valid_subing_rule(row: Mapping[str, object]) -> bool:
    return (
        type(row["id"]) is int
        and row["rule_code"] == _SUBING_RULE
        and row["enabled"] is False
        and row["scope_product_frequencies"] == {}
        and _aware_datetime(row["created_at"])
        and _aware_datetime(row["updated_at"])
    )


def _valid_frequency_scope(value: object) -> bool:
    return (
        isinstance(value, dict)
        and all(
            _valid_symbol(symbol)
            and isinstance(frequencies, list)
            and bool(frequencies)
            and len(frequencies) == len(set(frequencies))
            and all(frequency in _HTDY_FREQUENCIES for frequency in frequencies)
            for symbol, frequencies in value.items()
        )
    )


def _valid_htdy_event(row: Mapping[str, object]) -> bool:
    return bool(
        type(row["id"]) is int
        and type(row["rule_id"]) is int
        and _valid_symbol(row["symbol"])
        and _valid_contract(row["contract"], row["symbol"])
        and type(row["trading_day"]) is date
        and row["frequency"] in _HTDY_FREQUENCIES
        and _aware_datetime(row["bar_end"])
        and isinstance(row["result_codes"], list)
        and 1 <= len(row["result_codes"]) <= 2
        and len(row["result_codes"]) == len(set(row["result_codes"]))
        and all(value in {"buy", "sell"} for value in row["result_codes"])
        and _aware_datetime(row["detected_at"])
        and (
            row["notification_attempted_at"] is None
            or _aware_datetime(row["notification_attempted_at"])
        )
        and _aware_datetime(row["created_at"])
    )


def _valid_symbol(value: object) -> bool:
    return type(value) is str and _SYMBOL_PATTERN.fullmatch(value) is not None


def _valid_contract(contract: object, symbol: object) -> bool:
    return (
        type(contract) is str
        and type(symbol) is str
        and re.fullmatch(rf"{re.escape(symbol.upper())}[0-9]{{3,4}}", contract)
        is not None
    )


def _aware_datetime(value: object) -> bool:
    return (
        isinstance(value, datetime)
        and value.tzinfo is not None
        and value.utcoffset() is not None
    )
