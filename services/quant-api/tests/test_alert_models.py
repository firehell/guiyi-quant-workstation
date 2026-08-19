from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY


def test_alert_rule_uses_application_domain_columns_and_array_scope() -> None:
    from app.alerts.models import AlertRule

    table = AlertRule.__table__
    assert table.name == "alert_rules"
    assert {column.name for column in table.columns} == {
        "id",
        "rule_code",
        "enabled",
        "scope_products",
        "created_at",
        "updated_at",
    }
    assert table.c.rule_code.unique is True
    assert isinstance(table.c.scope_products.type, ARRAY)
    assert table.c.scope_products.nullable is False
    assert _check_names(table) == set()


def test_alert_event_enforces_identity_fk_and_range_index() -> None:
    from app.alerts.models import AlertEvent

    table = AlertEvent.__table__
    assert table.name == "alert_events"
    assert {column.name for column in table.columns} == {
        "id",
        "rule_id",
        "symbol",
        "contract",
        "trading_day",
        "frequency",
        "bar_end",
        "result_codes",
        "lower_tf_confirmation",
        "detected_at",
        "notification_attempted_at",
        "created_at",
    }
    assert isinstance(table.c.trading_day.type, Date)
    assert table.c.trading_day.nullable is True
    assert isinstance(table.c.result_codes.type, ARRAY)
    assert table.c.result_codes.nullable is False
    assert isinstance(table.c.lower_tf_confirmation.type, Boolean)
    assert table.c.lower_tf_confirmation.nullable is False
    assert table.c.lower_tf_confirmation.default.arg is False
    assert {fk.target_fullname for fk in table.c.rule_id.foreign_keys} == {"alert_rules.id"}
    assert _unique_columns(table, "uq_alert_events_rule_symbol_bar_end") == (
        "rule_id",
        "symbol",
        "bar_end",
    )
    assert _index_columns(table, "ix_alert_events_symbol_bar_end") == (
        "symbol",
        "bar_end",
    )
    assert _check_names(table) == {
        "ck_alert_events_frequency",
        "ck_alert_events_result_codes",
    }


def test_alert_timestamps_are_timezone_aware_and_required() -> None:
    from app.alerts.models import AlertEvent, AlertRule

    timestamp_columns = (
        AlertRule.__table__.c.created_at,
        AlertRule.__table__.c.updated_at,
        AlertEvent.__table__.c.bar_end,
        AlertEvent.__table__.c.detected_at,
        AlertEvent.__table__.c.created_at,
    )
    assert all(column.nullable is False for column in timestamp_columns)
    assert all(column.type.timezone is True for column in timestamp_columns)
    notification_attempted_at = AlertEvent.__table__.c.notification_attempted_at
    assert notification_attempted_at.nullable is True
    assert notification_attempted_at.type.timezone is True


def test_alert_notification_attempt_tracks_one_recipient_delivery_outcome() -> None:
    """A missing attempt ledger would leave recipient deliveries unaccountable."""

    from app.alerts.models import AlertEvent, AlertNotificationAttempt

    table = AlertNotificationAttempt.__table__
    assert {column.name for column in table.c} == {
        "id",
        "event_id",
        "recipient_alias",
        "channel",
        "status",
        "attempted_at",
        "completed_at",
        "error_code",
        "created_at",
        "updated_at",
    }
    assert table.c.event_id.nullable is False
    assert table.c.recipient_alias.nullable is False
    assert isinstance(table.c.recipient_alias.type, String)
    assert table.c.recipient_alias.type.length == 32
    assert isinstance(table.c.channel.type, String)
    assert table.c.channel.type.length == 64
    assert isinstance(table.c.error_code.type, String)
    assert table.c.error_code.type.length == 64
    assert {fk.target_fullname for fk in table.c.event_id.foreign_keys} == {
        "alert_events.id"
    }
    assert _unique_columns(
        table, "uq_alert_notification_attempts_event_alias_channel"
    ) == ("event_id", "recipient_alias", "channel")
    assert _check_names(table) == {
        "ck_alert_notification_attempts_status",
        "ck_alert_notification_attempts_completion",
    }
    assert _index_columns(table, "ix_alert_notification_attempts_event_id") == (
        "event_id",
    )
    assert _index_columns(
        table, "ix_alert_notification_attempts_status_attempted_at"
    ) == ("status", "attempted_at")
    timestamp_columns = (
        table.c.attempted_at,
        table.c.completed_at,
        table.c.created_at,
        table.c.updated_at,
    )
    assert all(isinstance(column.type, DateTime) for column in timestamp_columns)
    assert all(column.type.timezone is True for column in timestamp_columns)
    assert table.c.completed_at.nullable is True
    assert all(
        column.nullable is False
        for column in (table.c.attempted_at, table.c.created_at, table.c.updated_at)
    )
    assert (
        AlertNotificationAttempt.event.property.back_populates
        == "notification_attempts"
    )
    assert AlertEvent.notification_attempts.property.back_populates == "event"


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
