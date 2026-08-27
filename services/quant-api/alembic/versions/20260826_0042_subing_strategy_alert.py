"""Replace the legacy SuBing signal Alert with Strategy Action events.

Revision ID: 20260826_0042
Revises: 20260826_0041
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
import re

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260826_0042"
down_revision: str | Sequence[str] | None = "20260826_0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_OLD_SUBING_RULE = "subing_entry_signal_v1"
_NEW_SUBING_RULE = "subing_strategy_v1"
_HTDY_RULE = "htdy_original_15m"
_KNOWN_RULES = frozenset({_OLD_SUBING_RULE, _HTDY_RULE})
_HTDY_FREQUENCIES = ("1m", "5m", "15m", "30m", "60m", "1d", "1w")
_OLD_SUBING_FREQUENCIES = frozenset({"5m", "15m"})
_OLD_RESULT_CODES = frozenset({"buy", "sell"})
_RESULT_CODE_CONSTRAINT = (
    "cardinality(result_codes) BETWEEN 1 AND 2 "
    "AND result_codes <@ ARRAY["
    "'buy','sell','open_long','open_short','close_long','close_short'"
    "]::varchar[]"
)
_SYMBOL_PATTERN = re.compile(r"[a-z]+\Z")


def upgrade() -> None:
    bind = op.get_bind()
    _preflight(bind)

    rules = sa.table(
        "alert_rules",
        sa.column("id", sa.Integer()),
        sa.column("rule_code", sa.String(64)),
    )
    events = sa.table(
        "alert_events",
        sa.column("rule_id", sa.Integer()),
    )
    old_rule_id = bind.execute(
        sa.select(rules.c.id).where(rules.c.rule_code == _OLD_SUBING_RULE)
    ).scalar_one()
    bind.execute(sa.delete(events).where(events.c.rule_id == old_rule_id))
    bind.execute(
        sa.update(rules)
        .where(rules.c.id == old_rule_id)
        .values(rule_code=_NEW_SUBING_RULE)
    )

    op.drop_constraint(
        "ck_alert_events_result_codes",
        "alert_events",
        type_="check",
    )
    op.alter_column(
        "alert_events",
        "result_codes",
        existing_type=postgresql.ARRAY(sa.String(8)),
        type_=postgresql.ARRAY(sa.String(16)),
        existing_nullable=False,
        postgresql_using="result_codes::varchar(16)[]",
    )
    op.create_check_constraint(
        "ck_alert_events_result_codes",
        "alert_events",
        _RESULT_CODE_CONSTRAINT,
    )
    op.drop_column("alert_events", "lower_tf_confirmation")
    op.add_column(
        "alert_events",
        sa.Column("action_id", sa.String(96), nullable=True),
    )
    op.add_column(
        "alert_events",
        sa.Column("strategy_payload", sa.JSON(), nullable=True),
    )
    op.create_index(
        "ux_alert_events_action_id_not_null",
        "alert_events",
        ["action_id"],
        unique=True,
        postgresql_where=sa.text("action_id IS NOT NULL"),
    )


def downgrade() -> None:
    raise RuntimeError("SUBING_STRATEGY_ALERT_DOWNGRADE_UNSUPPORTED")


def _preflight(bind: sa.Connection) -> None:
    try:
        versions = tuple(
            bind.execute(sa.text("SELECT version_num FROM alembic_version")).scalars()
        )
        rule_rows = (
            bind.execute(
                sa.text(
                    "SELECT id, rule_code, enabled, scope_products, "
                    "scope_product_frequencies FROM alert_rules ORDER BY id"
                )
            )
            .mappings()
            .all()
        )
        event_rows = (
            bind.execute(
                sa.text(
                    "SELECT r.rule_code, e.symbol, e.contract, e.trading_day, "
                    "e.frequency, e.bar_end, e.result_codes, "
                    "e.lower_tf_confirmation, e.detected_at, "
                    "e.notification_attempted_at "
                    "FROM alert_events e JOIN alert_rules r ON r.id = e.rule_id"
                )
            )
            .mappings()
            .all()
        )
    except (sa.exc.SQLAlchemyError, TypeError, ValueError):
        raise RuntimeError("SUBING_STRATEGY_ALERT_PREFLIGHT_FAILED") from None

    old_rows = [row for row in rule_rows if row["rule_code"] == _OLD_SUBING_RULE]
    new_rows = [row for row in rule_rows if row["rule_code"] == _NEW_SUBING_RULE]
    htdy_rows = [row for row in rule_rows if row["rule_code"] == _HTDY_RULE]
    active_codes = {row["rule_code"] for row in rule_rows if row["enabled"] is True}
    if (
        versions != ("20260826_0041",)
        or len(old_rows) != 1
        or new_rows
        or len(htdy_rows) != 1
        or not active_codes.issubset(_KNOWN_RULES)
        or not _valid_product_rule(old_rows[0])
        or not _valid_htdy_rule(htdy_rows[0])
        or not all(_valid_event(row) for row in event_rows)
    ):
        raise RuntimeError("SUBING_STRATEGY_ALERT_PREFLIGHT_FAILED")


def _valid_product_rule(row: Mapping[str, object]) -> bool:
    scope = row["scope_products"]
    return (
        type(row["enabled"]) is bool
        and isinstance(scope, list)
        and scope == sorted(set(scope))
        and all(_valid_symbol(symbol) for symbol in scope)
        and row["scope_product_frequencies"] == {}
    )


def _valid_htdy_rule(row: Mapping[str, object]) -> bool:
    scope = row["scope_product_frequencies"]
    if (
        type(row["enabled"]) is not bool
        or row["scope_products"] != []
        or not isinstance(scope, dict)
    ):
        return False
    allowed = frozenset(_HTDY_FREQUENCIES)
    return all(
        _valid_symbol(symbol)
        and isinstance(frequencies, list)
        and bool(frequencies)
        and len(frequencies) == len(set(frequencies))
        and all(type(value) is str and value in allowed for value in frequencies)
        for symbol, frequencies in scope.items()
    )


def _valid_event(row: Mapping[str, object]) -> bool:
    rule_code = row["rule_code"]
    symbol = row["symbol"]
    contract = row["contract"]
    frequency = row["frequency"]
    result_codes = row["result_codes"]
    if (
        rule_code not in _KNOWN_RULES
        or not _valid_symbol(symbol)
        or not _valid_contract_for_symbol(contract, symbol)
        or type(row["trading_day"]) is not date
        or type(frequency) is not str
        or not _aware_datetime(row["bar_end"])
        or not isinstance(result_codes, list)
        or not 1 <= len(result_codes) <= 2
        or len(result_codes) != len(set(result_codes))
        or any(
            type(value) is not str or value not in _OLD_RESULT_CODES
            for value in result_codes
        )
        or type(row["lower_tf_confirmation"]) is not bool
        or not _aware_datetime(row["detected_at"])
        or (
            row["notification_attempted_at"] is not None
            and not _aware_datetime(row["notification_attempted_at"])
        )
    ):
        return False
    if rule_code == _HTDY_RULE:
        return (
            frequency in _HTDY_FREQUENCIES
            and row["lower_tf_confirmation"] is False
        )
    return frequency in _OLD_SUBING_FREQUENCIES


def _valid_symbol(value: object) -> bool:
    return type(value) is str and _SYMBOL_PATTERN.fullmatch(value) is not None


def _valid_contract_for_symbol(contract: object, symbol: object) -> bool:
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
