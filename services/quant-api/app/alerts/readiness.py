"""Read-only SuBing input/Scope readiness, without evaluator or transport composition."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.alerts.models import AlertRule
from app.alerts.registry import SUBING_THS_ALERT_RULE_CODE
from guiyi_quant.indicators.subing_ths import SUBING_THS_FORMULA_VERSION
from app.alerts.service import AlertService
from app.market_data.market_read_service import MarketReadService


def subing_readiness(
    session: Session, *, market_read: MarketReadService, products: tuple[str, ...],
    trading_day: date, as_of: datetime,
) -> dict[str, object]:
    rule = session.scalar(select(AlertRule).where(AlertRule.rule_code == SUBING_THS_ALERT_RULE_CODE))
    service = AlertService(session, operational_products=products)
    rows = []
    for symbol in products:
        try:
            row = market_read.contract_input_readiness(symbol, trading_day=trading_day, as_of=as_of)
        except Exception:
            row = {"symbol": symbol, "status": "blocked", "error_codes": ["INPUT_DIAGNOSIS_UNAVAILABLE"]}
        allowed = False
        try:
            allowed = rule is not None and bool(rule.enabled) and service.rule_allows_event(rule, symbol=symbol, frequency="15m")
        except Exception:
            row["status"] = "blocked"
        row["scope_enabled"] = allowed
        if not allowed:
            row["status"] = "blocked"
            row["error_codes"] = [*row.get("error_codes", []), "SUBING_SCOPE_UNAVAILABLE"]
        rows.append(row)
    ready = sum(row["status"] == "ready" for row in rows)
    return {
        "schema_version": 1, "command": "runtime.subing-readiness", "readonly": True,
        "status": "passed" if rows and ready == len(rows) else "blocked",
        "trading_day": trading_day, "as_of": as_of, "product_count": len(rows),
        "ready_count": ready, "products": rows,
        "rule_code": SUBING_THS_ALERT_RULE_CODE, "formula_version": SUBING_THS_FORMULA_VERSION,
        "notification_sent": False, "natural_delivery_proven": False,
    }


def build_subing_readiness(session: Session, *, trading_day: date, as_of: datetime) -> dict[str, object]:
    from app.market_data.composition import build_market_read_service
    from app.market_data.operational_universe import load_operational_products

    # This CLI owns a fresh transaction; make accidental writes fail at the DB boundary.
    if session.get_bind().dialect.name == "postgresql":
        session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
    elif session.get_bind().dialect.name == "sqlite":
        session.execute(text("PRAGMA query_only = ON"))
    with session.no_autoflush:
        return subing_readiness(session, market_read=build_market_read_service(session),
                                products=load_operational_products(), trading_day=trading_day, as_of=as_of)
