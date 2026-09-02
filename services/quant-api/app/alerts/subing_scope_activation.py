"""Atomic first activation for the SuBing THS 15m Alert Scope."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import re
from typing import Literal, Sequence

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.alerts.models import AlertRule
from app.market_data.product_retirement import normalize_symbol


_ALEMBIC_REVISION = "20260902_0044"
_HTDY_RULE = "htdy_original_15m"
_SUBING_RULE = "subing_ths_alert_15m_v1"
_SYMBOL_PATTERN = re.compile(r"[a-z]+\Z")


class SubingScopeActivationError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class SubingScopeActivationResult:
    status: Literal["planned", "published"]
    readonly: bool
    rule_code: str
    symbol_count: int
    scope_sha256: str
    enabled: bool


@dataclass(frozen=True, slots=True)
class _RuleSnapshot:
    id: int
    rule_code: str
    enabled: bool
    scope_product_frequencies: str
    created_at: datetime
    updated_at: datetime


def activate_subing_ths_scope(
    session: Session,
    *,
    operational_products: tuple[str, ...],
    apply: bool,
) -> SubingScopeActivationResult:
    """Plan or atomically publish the first operational×15m SuBing Scope."""

    symbols = _normalize_operational_products(operational_products)
    scope = {symbol: ["15m"] for symbol in symbols}
    scope_sha256 = _scope_sha256(scope)
    htdy_before, _subing_before = _preflight(session)
    if not apply:
        return SubingScopeActivationResult(
            status="planned",
            readonly=True,
            rule_code=_SUBING_RULE,
            symbol_count=len(symbols),
            scope_sha256=scope_sha256,
            enabled=False,
        )

    try:
        _require_alembic_0044(session)
        locked_rules = tuple(session.scalars(
            select(AlertRule)
            .order_by(AlertRule.rule_code)
            .with_for_update()
        ).all())
        htdy, subing = _exact_rules(locked_rules)
        if _snapshot(htdy) != htdy_before or not _subing_is_disabled_empty(subing):
            raise SubingScopeActivationError("SUBING_SCOPE_ACTIVATION_PREFLIGHT_FAILED")

        subing.scope_product_frequencies = scope
        subing.enabled = True
        session.flush()

        persisted_rules = tuple(session.scalars(
            select(AlertRule)
            .order_by(AlertRule.rule_code)
            .execution_options(populate_existing=True)
        ).all())
        persisted_htdy, persisted_subing = _exact_rules(persisted_rules)
        if (
            _snapshot(persisted_htdy) != htdy_before
            or persisted_subing.enabled is not True
            or persisted_subing.scope_product_frequencies != scope
        ):
            raise SubingScopeActivationError("SUBING_SCOPE_ACTIVATION_PERSIST_FAILED")
        session.commit()
    except SubingScopeActivationError:
        session.rollback()
        raise
    except SQLAlchemyError:
        session.rollback()
        raise SubingScopeActivationError(
            "SUBING_SCOPE_ACTIVATION_PERSIST_FAILED"
        ) from None

    return SubingScopeActivationResult(
        status="published",
        readonly=False,
        rule_code=_SUBING_RULE,
        symbol_count=len(symbols),
        scope_sha256=scope_sha256,
        enabled=True,
    )


def _normalize_operational_products(products: tuple[str, ...]) -> tuple[str, ...]:
    if type(products) is not tuple:
        raise SubingScopeActivationError("SUBING_SCOPE_ACTIVATION_PREFLIGHT_FAILED")
    normalized = tuple(normalize_symbol(item) for item in products)
    if (
        not normalized
        or len(normalized) != len(set(normalized))
        or any(_SYMBOL_PATTERN.fullmatch(symbol) is None for symbol in normalized)
    ):
        raise SubingScopeActivationError("SUBING_SCOPE_ACTIVATION_PREFLIGHT_FAILED")
    return tuple(sorted(normalized))


def _scope_sha256(scope: dict[str, list[str]]) -> str:
    payload = json.dumps(
        scope,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _preflight(session: Session) -> tuple[_RuleSnapshot, AlertRule]:
    _require_alembic_0044(session)
    htdy, subing = _exact_rules(_rules(session, for_update=False))
    if not _valid_htdy_rule(htdy) or not _subing_is_disabled_empty(subing):
        raise SubingScopeActivationError("SUBING_SCOPE_ACTIVATION_PREFLIGHT_FAILED")
    return _snapshot(htdy), subing


def _require_alembic_0044(session: Session) -> None:
    try:
        versions = tuple(session.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalars())
    except SQLAlchemyError:
        raise SubingScopeActivationError("SUBING_SCOPE_ACTIVATION_PREFLIGHT_FAILED") from None
    if versions != (_ALEMBIC_REVISION,):
        raise SubingScopeActivationError("SUBING_SCOPE_ACTIVATION_PREFLIGHT_FAILED")


def _rules(session: Session, *, for_update: bool) -> tuple[AlertRule, ...]:
    statement = select(AlertRule).order_by(AlertRule.rule_code)
    if for_update:
        statement = statement.with_for_update()
    try:
        return tuple(session.scalars(statement).all())
    except SQLAlchemyError:
        raise SubingScopeActivationError("SUBING_SCOPE_ACTIVATION_PREFLIGHT_FAILED") from None


def _exact_rules(rules: Sequence[AlertRule]) -> tuple[AlertRule, AlertRule]:
    by_code = {rule.rule_code: rule for rule in rules}
    if (
        len(rules) != 2
        or frozenset(by_code) != {_HTDY_RULE, _SUBING_RULE}
        or len(by_code) != 2
    ):
        raise SubingScopeActivationError("SUBING_SCOPE_ACTIVATION_PREFLIGHT_FAILED")
    return by_code[_HTDY_RULE], by_code[_SUBING_RULE]


def _valid_htdy_rule(rule: AlertRule) -> bool:
    return type(rule.enabled) is bool and isinstance(rule.scope_product_frequencies, dict)


def _subing_is_disabled_empty(rule: AlertRule) -> bool:
    return rule.enabled is False and rule.scope_product_frequencies == {}


def _snapshot(rule: AlertRule) -> _RuleSnapshot:
    scope = rule.scope_product_frequencies
    if not isinstance(scope, dict):
        raise SubingScopeActivationError("SUBING_SCOPE_ACTIVATION_PREFLIGHT_FAILED")
    return _RuleSnapshot(
        id=rule.id,
        rule_code=rule.rule_code,
        enabled=rule.enabled,
        scope_product_frequencies=json.dumps(
            scope,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )
