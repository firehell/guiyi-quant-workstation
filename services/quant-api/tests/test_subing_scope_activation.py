from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.alerts import subing_scope_activation
from app.alerts.models import AlertRule
from app.alerts.subing_scope_activation import (
    SubingScopeActivationError,
    activate_subing_ths_scope,
)


_SUBING_RULE = "subing_ths_alert_15m_v1"


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    AlertRule.__table__.create(engine)
    with Session(engine) as value:
        value.execute(text("CREATE TABLE alembic_version (version_num varchar(32) NOT NULL)"))
        value.execute(text(
            "INSERT INTO alembic_version (version_num) VALUES ('20260903_0045')"
        ))
        value.add_all([
            AlertRule(
                rule_code="htdy_original_15m",
                enabled=True,
                scope_product_frequencies={"jm": ["15m"]},
            ),
            AlertRule(
                rule_code=_SUBING_RULE,
                enabled=False,
                scope_product_frequencies={},
            ),
        ])
        value.commit()
        yield value
    engine.dispose()


def test_dry_run_returns_stable_sorted_scope_without_db_mutation(session: Session) -> None:
    htdy_before = _rule_snapshot(session, "htdy_original_15m")
    subing_before = _rule_snapshot(session, _SUBING_RULE)
    commits: list[object] = []
    event.listen(session, "after_commit", lambda value: commits.append(value))

    result = activate_subing_ths_scope(
        session,
        operational_products=(" JM ", "al"),
        apply=False,
    )

    assert result.status == "planned"
    assert result.readonly is True
    assert result.rule_code == _SUBING_RULE
    assert result.symbol_count == 2
    assert result.scope_sha256 == (
        "747b4506c773dce5264e57a32077375e8990bed308ba81ce435bc1ac130ee9f3"
    )
    assert result.enabled is False
    assert _rule_snapshot(session, "htdy_original_15m") == htdy_before
    assert _rule_snapshot(session, _SUBING_RULE) == subing_before
    assert commits == []


@pytest.mark.parametrize("operational_products", [(), ("JM", "jm")])
def test_dry_run_rejects_empty_or_normalized_duplicate_operational_products(
    session: Session,
    operational_products: tuple[str, ...],
) -> None:
    subing_before = _rule_snapshot(session, _SUBING_RULE)

    with pytest.raises(
        SubingScopeActivationError,
        match="^SUBING_SCOPE_ACTIVATION_PREFLIGHT_FAILED$",
    ):
        activate_subing_ths_scope(
            session,
            operational_products=operational_products,
            apply=False,
        )

    assert _rule_snapshot(session, _SUBING_RULE) == subing_before


def test_dry_run_refreshes_current_rule_state_before_planning(session: Session) -> None:
    _rule(session, _SUBING_RULE)
    with Session(session.get_bind()) as competing_session:
        competing_rule = _rule(competing_session, _SUBING_RULE)
        competing_rule.scope_product_frequencies = {"jm": ["15m"]}
        competing_rule.enabled = True
        competing_session.commit()

    with pytest.raises(
        SubingScopeActivationError,
        match="^SUBING_SCOPE_ACTIVATION_PREFLIGHT_FAILED$",
    ):
        activate_subing_ths_scope(
            session,
            operational_products=("al",),
            apply=False,
        )

    session.expire_all()
    assert _rule_snapshot(session, _SUBING_RULE) == {
        "enabled": True,
        "scope_product_frequencies": {"jm": ["15m"]},
    }


def test_apply_publishes_full_scope_and_preserves_htdy_in_one_commit(
    session: Session,
) -> None:
    htdy_before = _rule_snapshot(session, "htdy_original_15m")
    commits: list[object] = []
    event.listen(session, "after_commit", lambda value: commits.append(value))

    result = activate_subing_ths_scope(
        session,
        operational_products=("al", "JM"),
        apply=True,
    )

    assert result.status == "published"
    assert result.readonly is False
    assert result.rule_code == _SUBING_RULE
    assert result.symbol_count == 2
    assert result.scope_sha256 == (
        "747b4506c773dce5264e57a32077375e8990bed308ba81ce435bc1ac130ee9f3"
    )
    assert result.enabled is True
    assert _rule_snapshot(session, "htdy_original_15m") == htdy_before
    assert _rule_snapshot(session, _SUBING_RULE) == {
        "enabled": True,
        "scope_product_frequencies": {"al": ["15m"], "jm": ["15m"]},
    }
    assert len(commits) == 1


def test_apply_rejects_nonexact_0045_state_before_mutation(session: Session) -> None:
    session.execute(text("UPDATE alembic_version SET version_num = '20260902_0044'"))
    session.commit()
    subing_before = _rule_snapshot(session, _SUBING_RULE)
    commits: list[object] = []
    event.listen(session, "after_commit", lambda value: commits.append(value))

    with pytest.raises(
        SubingScopeActivationError,
        match="^SUBING_SCOPE_ACTIVATION_PREFLIGHT_FAILED$",
    ):
        activate_subing_ths_scope(
            session,
            operational_products=("jm",),
            apply=True,
        )

    assert _rule_snapshot(session, _SUBING_RULE) == subing_before
    assert commits == []


def test_apply_rechecks_revision_after_locking_rules(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_rules = subing_scope_activation._rules

    def change_revision_before_locked_read(*args, **kwargs):
        if kwargs["for_update"]:
            session.execute(text(
                "UPDATE alembic_version SET version_num = '20260902_0044'"
            ))
        return original_rules(*args, **kwargs)

    monkeypatch.setattr(subing_scope_activation, "_rules", change_revision_before_locked_read)

    with pytest.raises(
        SubingScopeActivationError,
        match="^SUBING_SCOPE_ACTIVATION_PREFLIGHT_FAILED$",
    ):
        activate_subing_ths_scope(
            session,
            operational_products=("jm",),
            apply=True,
        )

    assert session.scalar(text("SELECT version_num FROM alembic_version")) == (
        "20260903_0045"
    )
    assert _rule_snapshot(session, _SUBING_RULE) == {
        "enabled": False,
        "scope_product_frequencies": {},
    }


@pytest.mark.parametrize(
    "invalid_scope",
    [
        {"JM": ["15m"]},
        {"jm": ["4h"]},
        {"jm": []},
        {"jm": ["15m", "15m"]},
    ],
)
def test_preflight_rejects_invalid_htdy_frequency_scope(
    session: Session,
    invalid_scope: dict[str, list[str]],
) -> None:
    htdy = _rule(session, "htdy_original_15m")
    htdy.scope_product_frequencies = invalid_scope
    session.commit()

    with pytest.raises(
        SubingScopeActivationError,
        match="^SUBING_SCOPE_ACTIVATION_PREFLIGHT_FAILED$",
    ):
        activate_subing_ths_scope(
            session,
            operational_products=("jm",),
            apply=False,
        )

    assert _rule_snapshot(session, _SUBING_RULE) == {
        "enabled": False,
        "scope_product_frequencies": {},
    }


def test_apply_locked_reread_rejects_concurrent_first_activation(session: Session) -> None:
    _rule(session, _SUBING_RULE)
    with Session(session.get_bind()) as competing_session:
        competing_rule = _rule(competing_session, _SUBING_RULE)
        competing_rule.scope_product_frequencies = {"jm": ["15m"]}
        competing_rule.enabled = True
        competing_session.commit()

    with pytest.raises(
        SubingScopeActivationError,
        match="^SUBING_SCOPE_ACTIVATION_PREFLIGHT_FAILED$",
    ):
        activate_subing_ths_scope(
            session,
            operational_products=("al",),
            apply=True,
        )

    session.expire_all()
    assert _rule_snapshot(session, _SUBING_RULE) == {
        "enabled": True,
        "scope_product_frequencies": {"jm": ["15m"]},
    }


def test_apply_rejects_post_commit_readback_mismatch(session: Session) -> None:
    def corrupt_after_commit(_session: Session) -> None:
        with Session(session.get_bind()) as competing_session:
            competing_rule = _rule(competing_session, _SUBING_RULE)
            competing_rule.scope_product_frequencies = {"ag": ["15m"]}
            competing_rule.enabled = True
            competing_session.commit()

    event.listen(session, "after_commit", corrupt_after_commit)

    with pytest.raises(
        SubingScopeActivationError,
        match="^SUBING_SCOPE_ACTIVATION_PERSIST_FAILED$",
    ):
        activate_subing_ths_scope(
            session,
            operational_products=("jm",),
            apply=True,
        )


def test_apply_reports_persist_failure_when_post_commit_readback_query_fails(
    session: Session,
) -> None:
    def drop_rules_after_commit(_session: Session) -> None:
        with Session(session.get_bind()) as competing_session:
            competing_session.execute(text("DROP TABLE alert_rules"))
            competing_session.commit()

    event.listen(session, "after_commit", drop_rules_after_commit)

    with pytest.raises(
        SubingScopeActivationError,
        match="^SUBING_SCOPE_ACTIVATION_PERSIST_FAILED$",
    ):
        activate_subing_ths_scope(
            session,
            operational_products=("jm",),
            apply=True,
        )


def test_preflight_database_failure_rolls_back_session(session: Session) -> None:
    session.execute(text("DROP TABLE alembic_version"))
    session.commit()
    rollbacks: list[object] = []
    event.listen(session, "after_rollback", lambda value: rollbacks.append(value))

    with pytest.raises(
        SubingScopeActivationError,
        match="^SUBING_SCOPE_ACTIVATION_PREFLIGHT_FAILED$",
    ):
        activate_subing_ths_scope(
            session,
            operational_products=("jm",),
            apply=True,
        )

    assert rollbacks == [session]


def test_apply_rolls_back_when_database_flush_fails(session: Session) -> None:
    def fail_scope_flush(_session, _flush_context, _instances) -> None:
        subing = _rule(session, _SUBING_RULE)
        if subing.enabled:
            raise SQLAlchemyError("simulated database failure")

    event.listen(session, "before_flush", fail_scope_flush)

    with pytest.raises(
        SubingScopeActivationError,
        match="^SUBING_SCOPE_ACTIVATION_PERSIST_FAILED$",
    ):
        activate_subing_ths_scope(
            session,
            operational_products=("jm",),
            apply=True,
        )

    session.expire_all()
    assert _rule_snapshot(session, _SUBING_RULE) == {
        "enabled": False,
        "scope_product_frequencies": {},
    }


def _rule_snapshot(session: Session, rule_code: str) -> dict[str, object]:
    rule = _rule(session, rule_code)
    return {
        "enabled": rule.enabled,
        "scope_product_frequencies": rule.scope_product_frequencies,
    }


def _rule(session: Session, rule_code: str) -> AlertRule:
    rule = session.scalar(select(AlertRule).where(AlertRule.rule_code == rule_code))
    assert rule is not None
    return rule
