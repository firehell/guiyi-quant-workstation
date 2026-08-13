from __future__ import annotations

from sqlalchemy import CheckConstraint, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY


def test_alert_rule_uses_application_domain_columns_and_array_scope() -> None:
    from app.alerts.models import AlertRule

    table = AlertRule.__table__
    assert table.name == "alert_rules"
    assert {column.name for column in table.columns} == {
        "id",
        "rule_code",
        "indicator_code",
        "frequency",
        "enabled",
        "scope_mode",
        "scope_products",
        "created_at",
        "updated_at",
    }
    assert table.c.rule_code.unique is True
    assert isinstance(table.c.scope_products.type, ARRAY)
    assert table.c.scope_products.nullable is False
    assert _check_names(table) == {
        "ck_alert_rules_frequency",
        "ck_alert_rules_scope_mode",
    }


def test_alert_event_enforces_identity_fk_and_range_index() -> None:
    from app.alerts.models import AlertEvent

    table = AlertEvent.__table__
    assert table.name == "alert_events"
    assert {column.name for column in table.columns} == {
        "id",
        "rule_id",
        "symbol",
        "contract",
        "frequency",
        "bar_end",
        "observation_types",
        "detected_at",
        "notified_at",
        "created_at",
    }
    assert isinstance(table.c.observation_types.type, ARRAY)
    assert table.c.observation_types.nullable is False
    assert {fk.target_fullname for fk in table.c.rule_id.foreign_keys} == {"alert_rules.id"}
    assert _unique_columns(table, "uq_alert_events_rule_symbol_frequency_bar_end") == (
        "rule_id",
        "symbol",
        "frequency",
        "bar_end",
    )
    assert _index_columns(table, "ix_alert_events_symbol_bar_end") == (
        "symbol",
        "bar_end",
    )
    assert _check_names(table) == {
        "ck_alert_events_frequency",
        "ck_alert_events_observation_types",
    }


def test_alert_timestamps_are_timezone_aware_and_required() -> None:
    from app.alerts.models import AlertEvent, AlertRule

    timestamp_columns = (
        AlertRule.__table__.c.created_at,
        AlertRule.__table__.c.updated_at,
        AlertEvent.__table__.c.bar_end,
        AlertEvent.__table__.c.detected_at,
        AlertEvent.__table__.c.notified_at,
        AlertEvent.__table__.c.created_at,
    )
    assert all(column.nullable is False for column in timestamp_columns)
    assert all(column.type.timezone is True for column in timestamp_columns)


def _check_names(table: object) -> set[str]:
    return {
        constraint.name
        for constraint in table.constraints  # type: ignore[attr-defined]
        if isinstance(constraint, CheckConstraint) and constraint.name is not None
    }


def _unique_columns(table: object, name: str) -> tuple[str, ...]:
    constraint = next(
        item
        for item in table.constraints  # type: ignore[attr-defined]
        if isinstance(item, UniqueConstraint) and item.name == name
    )
    return tuple(column.name for column in constraint.columns)


def _index_columns(table: object, name: str) -> tuple[str, ...]:
    index = next(
        item
        for item in table.indexes  # type: ignore[attr-defined]
        if isinstance(item, Index) and item.name == name
    )
    return tuple(column.name for column in index.columns)
