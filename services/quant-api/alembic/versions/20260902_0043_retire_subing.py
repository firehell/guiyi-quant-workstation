"""Retire the legacy strategy Alert domain and its persisted facts.

Revision ID: 20260902_0043
Revises: 20260826_0042
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
import re

from alembic import op
import sqlalchemy as sa


revision: str = "20260902_0043"
down_revision: str | Sequence[str] | None = "20260826_0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_RETIRED_RULE = "subing_strategy_v1"
_HTDY_RULE = "htdy_original_15m"
_EXPECTED_RULES = frozenset({_HTDY_RULE, _RETIRED_RULE})
_EXPECTED_RULE_COLUMNS = frozenset({
    "id", "rule_code", "enabled", "scope_products",
    "scope_product_frequencies", "created_at", "updated_at",
})
_EXPECTED_EVENT_COLUMNS = frozenset({
    "id", "rule_id", "symbol", "contract", "trading_day", "frequency",
    "bar_end", "result_codes", "action_id", "strategy_payload",
    "detected_at", "notification_attempted_at", "created_at",
})
_HTDY_FREQUENCIES = frozenset({"1m", "5m", "15m", "30m", "60m", "1d", "1w"})
_RESULT_CODE_CONSTRAINT = (
    "cardinality(result_codes) BETWEEN 1 AND 2 "
    "AND result_codes <@ ARRAY['buy','sell']::varchar[]"
)
_SYMBOL_PATTERN = re.compile(r"[a-z]+\Z")


def upgrade() -> None:
    bind = op.get_bind()
    htdy_before, retired_rule_id = _preflight(bind)

    events = sa.table("alert_events", sa.column("rule_id", sa.Integer()))
    rules = sa.table("alert_rules", sa.column("id", sa.Integer()))
    bind.execute(sa.delete(events).where(events.c.rule_id == retired_rule_id))
    bind.execute(sa.delete(rules).where(rules.c.id == retired_rule_id))

    op.drop_index(
        "ux_alert_events_action_id_not_null",
        table_name="alert_events",
    )
    op.drop_constraint(
        "ck_alert_events_result_codes",
        "alert_events",
        type_="check",
    )
    op.drop_column("alert_events", "strategy_payload")
    op.drop_column("alert_events", "action_id")
    op.drop_column("alert_rules", "scope_products")
    op.create_check_constraint(
        "ck_alert_events_result_codes",
        "alert_events",
        _RESULT_CODE_CONSTRAINT,
    )
    _postflight(bind, htdy_before)


def downgrade() -> None:
    raise RuntimeError("SUBING_RETIREMENT_DOWNGRADE_UNSUPPORTED")


def _preflight(bind: sa.Connection) -> tuple[dict[str, object], int]:
    try:
        versions = tuple(
            bind.execute(sa.text("SELECT version_num FROM alembic_version")).scalars()
        )
        rule_columns = _columns(bind, "alert_rules")
        event_columns = _columns(bind, "alert_events")
        rule_rows = bind.execute(sa.text(
            "SELECT id, rule_code, enabled, scope_products, "
            "scope_product_frequencies, created_at, updated_at "
            "FROM alert_rules ORDER BY id"
        )).mappings().all()
        htdy_events = bind.execute(sa.text(
            "SELECT e.symbol, e.contract, e.trading_day, e.frequency, "
            "e.bar_end, e.result_codes, e.detected_at, e.notification_attempted_at "
            "FROM alert_events e JOIN alert_rules r ON r.id = e.rule_id "
            "WHERE r.rule_code = :rule_code"
        ), {"rule_code": _HTDY_RULE}).mappings().all()
        index_count = bind.execute(sa.text(
            "SELECT COUNT(*) FROM pg_indexes "
            "WHERE schemaname = current_schema() AND tablename = 'alert_events' "
            "AND indexname = 'ux_alert_events_action_id_not_null'"
        )).scalar_one()
        constraint_count = bind.execute(sa.text(
            "SELECT COUNT(*) FROM pg_constraint c "
            "JOIN pg_class t ON t.oid = c.conrelid "
            "JOIN pg_namespace n ON n.oid = t.relnamespace "
            "WHERE n.nspname = current_schema() AND t.relname = 'alert_events' "
            "AND c.conname = 'ck_alert_events_result_codes'"
        )).scalar_one()
    except (sa.exc.SQLAlchemyError, TypeError, ValueError):
        raise RuntimeError("SUBING_RETIREMENT_PREFLIGHT_FAILED") from None

    by_code = {row["rule_code"]: row for row in rule_rows}
    if (
        versions != ("20260826_0042",)
        or frozenset(by_code) != _EXPECTED_RULES
        or len(rule_rows) != 2
        or rule_columns != _EXPECTED_RULE_COLUMNS
        or event_columns != _EXPECTED_EVENT_COLUMNS
        or index_count != 1
        or constraint_count != 1
        or not _valid_htdy_rule(by_code[_HTDY_RULE])
        or not _valid_retired_rule(by_code[_RETIRED_RULE])
        or not all(_valid_htdy_event(row) for row in htdy_events)
    ):
        raise RuntimeError("SUBING_RETIREMENT_PREFLIGHT_FAILED")
    return dict(by_code[_HTDY_RULE]), int(by_code[_RETIRED_RULE]["id"])


def _postflight(bind: sa.Connection, htdy_before: Mapping[str, object]) -> None:
    try:
        rows = bind.execute(sa.text(
            "SELECT id, rule_code, enabled, scope_product_frequencies, "
            "created_at, updated_at FROM alert_rules ORDER BY id"
        )).mappings().all()
        rule_columns = _columns(bind, "alert_rules")
        event_columns = _columns(bind, "alert_events")
        retired_event_count = bind.execute(sa.text(
            "SELECT COUNT(*) FROM alert_events e "
            "LEFT JOIN alert_rules r ON r.id = e.rule_id "
            "WHERE r.id IS NULL"
        )).scalar_one()
    except (sa.exc.SQLAlchemyError, TypeError, ValueError):
        raise RuntimeError("SUBING_RETIREMENT_POSTFLIGHT_FAILED") from None
    expected_htdy = {
        key: htdy_before[key]
        for key in (
            "id", "rule_code", "enabled", "scope_product_frequencies",
            "created_at", "updated_at",
        )
    }
    if (
        len(rows) != 1
        or dict(rows[0]) != expected_htdy
        or rule_columns != _EXPECTED_RULE_COLUMNS - {"scope_products"}
        or event_columns != _EXPECTED_EVENT_COLUMNS - {"action_id", "strategy_payload"}
        or retired_event_count != 0
    ):
        raise RuntimeError("SUBING_RETIREMENT_POSTFLIGHT_FAILED")


def _columns(bind: sa.Connection, table_name: str) -> frozenset[str]:
    return frozenset(bind.execute(sa.text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = :table_name"
    ), {"table_name": table_name}).scalars())


def _valid_htdy_rule(row: Mapping[str, object]) -> bool:
    scope = row["scope_product_frequencies"]
    return (
        type(row["enabled"]) is bool
        and row["scope_products"] == []
        and isinstance(scope, dict)
        and all(
            _valid_symbol(symbol)
            and isinstance(frequencies, list)
            and bool(frequencies)
            and len(frequencies) == len(set(frequencies))
            and all(value in _HTDY_FREQUENCIES for value in frequencies)
            for symbol, frequencies in scope.items()
        )
        and _aware_datetime(row["created_at"])
        and _aware_datetime(row["updated_at"])
    )


def _valid_retired_rule(row: Mapping[str, object]) -> bool:
    scope = row["scope_products"]
    return (
        type(row["enabled"]) is bool
        and isinstance(scope, list)
        and scope == sorted(set(scope))
        and all(_valid_symbol(symbol) for symbol in scope)
        and row["scope_product_frequencies"] == {}
        and _aware_datetime(row["created_at"])
        and _aware_datetime(row["updated_at"])
    )


def _valid_htdy_event(row: Mapping[str, object]) -> bool:
    return bool(
        _valid_symbol(row["symbol"])
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
