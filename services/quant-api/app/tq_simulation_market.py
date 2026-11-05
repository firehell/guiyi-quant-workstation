"""Private stdio authority bridge: RQData/MDS only, no broker or mutations."""

from datetime import datetime, UTC, timedelta
from dataclasses import asdict
import json
import re
import sys
from sqlalchemy import select
from app.db.session import SessionLocal
from app.db.readonly import readonly_transaction
from app.models import Contract
from app.market_data.market_phase import MarketPhaseResolver, MarketPhase
from app.market_data.operational_universe import load_operational_products
from app.simnow_portfolio_market import PortfolioMarket
from guiyi_quant.htdy_account_execution import codec

MAX_REQUEST = 16 * 1024 * 1024
BATCH_PRODUCTS = 4


def recovery_batch(state, cursor):
    """Partial proofs never grant permission to products without authority."""
    eligible = [
        p.product
        for p in state.products
        if p.owner is not None
        and (state.phase != "READY" or p.product in state.blocked_products)
    ]
    held = {p.product for p in state.positions}
    urgent = [p for p in eligible if p in held]
    rest = [p for p in eligible if p not in held]
    ordered = urgent + rest
    if not ordered:
        return (), 0
    # Full account recovery sees held products first. Subsequent READY batches
    # rotate even when a held product's proof remains unavailable.
    start = 0 if state.phase != "READY" else cursor % len(ordered)
    chosen = (ordered[start:] + ordered[:start])[:BATCH_PRODUCTS]
    return tuple(chosen), (start + len(chosen)) % len(ordered)


def authority(market, product, now, contract=None):
    with SessionLocal() as db, readonly_transaction(db, timeout_seconds=10):
        resolver = MarketPhaseResolver(db)
        phase = resolver.resolve(product.lower(), now)
        if phase.phase is MarketPhase.UNKNOWN:
            raise ValueError("TQ_MARKET_PHASE_UNKNOWN")
        day = phase.trading_day
        if day is None:
            if phase.next_session_start is None:
                raise ValueError("TQ_SESSION_UNAVAILABLE")
            future = resolver.resolve(
                product.lower(), phase.next_session_start + timedelta(microseconds=1)
            )
            day = future.trading_day
        if day is None:
            raise ValueError("TQ_TRADING_DAY_UNPROVEN")
        fact = market.authority(product, day, now, contract)
        row = db.scalar(
            select(Contract).where(
                Contract.contract_code == fact.contract,
                Contract.instrument_symbol == product.lower(),
                Contract.provider == "rqdata",
            )
        )
        if row is None or not row.contract_multiplier or row.contract_multiplier <= 0:
            raise ValueError("TQ_CONTRACT_METADATA_UNAVAILABLE")
        return {
            **asdict(fact),
            "session": codec.encode(fact.session),
            "trading_day": day.isoformat(),
            "multiplier": str(row.contract_multiplier),
            "trading_code": row.trading_code,
            "maturity_date": None
            if row.maturity_date is None
            else row.maturity_date.isoformat(),
        }


def main():
    products = tuple(p.upper() for p in load_operational_products())
    market = PortfolioMarket(products)
    market.activate(datetime.now(UTC))
    recovery_cursor = 0
    try:
        while True:
            line = sys.stdin.buffer.readline(MAX_REQUEST + 1)
            if not line:
                return 0
            request_id = None
            try:
                if len(line) > MAX_REQUEST:
                    raise ValueError("TQ_MARKET_REQUEST_TOO_LARGE")
                request = json.loads(line)
                if set(request) - {"mode", "state", "contracts", "request_id"}:
                    raise ValueError("TQ_MARKET_REQUEST_INVALID")
                request_id = request.get("request_id")
                if (
                    type(request_id) is not str
                    or re.fullmatch(r"[0-9a-f]{32}", request_id) is None
                ):
                    raise ValueError("TQ_MARKET_REQUEST_INVALID")
                mode = request.get("mode")
                now = datetime.now(UTC)
                if mode not in {"hello", "poll", "inspect"}:
                    raise ValueError("TQ_MARKET_MODE_INVALID")
                state = (
                    codec.load(request["state"])
                    if request.get("state") is not None
                    else None
                )
                after = (
                    {
                        p.product: p.last_bar or state.activated_at
                        for p in state.products
                    }
                    if state
                    else market.started
                )
                signals = (
                    market.poll(now, after, max_products=BATCH_PRODUCTS)
                    if mode == "poll"
                    else ()
                )
                selected = {}
                for item in request.get("contracts", []):
                    if (
                        set(item) != {"product", "contract"}
                        or item["product"] not in products
                        or not re.fullmatch(
                            item["product"] + r"\d{3,4}", item["contract"]
                        )
                    ):
                        raise ValueError("TQ_MARKET_CONTRACT_INVALID")
                    selected[(item["product"], item["contract"])] = None
                for signal in signals:
                    selected[(signal.product, signal.contract)] = None
                if mode == "inspect":
                    for product in products:
                        selected[(product, None)] = None
                facts = []
                issues = {}
                for product, contract in sorted(
                    selected, key=lambda p: (p[0], p[1] or "")
                ):
                    try:
                        facts.append(authority(market, product, now, contract))
                    except Exception:
                        issues[product] = "TQ_MARKET_AUTHORITY_UNAVAILABLE"
                recovery = ()
                if state is not None and (
                    state.phase != "READY" or state.blocked_products
                ):
                    batch, recovery_cursor = recovery_batch(state, recovery_cursor)
                    recovery = market.recovery(state, datetime.now(UTC), products=batch)
                result = {
                    "status": "ok",
                    "request_id": request_id,
                    "at": now.isoformat(),
                    "products": products,
                    "signals": [codec.encode(s) for s in signals],
                    "facts": facts,
                    "recovery": [codec.encode(p) for p in recovery],
                    "issues": {**market.issues, **issues},
                }
                print(
                    json.dumps(
                        result,
                        default=lambda v: (
                            v.isoformat() if hasattr(v, "isoformat") else str(v)
                        ),
                        allow_nan=False,
                    ),
                    flush=True,
                )
            except Exception:
                print(
                    json.dumps(
                        {
                            "status": "blocked",
                            "request_id": request_id,
                            "code": "TQ_MARKET_AUTHORITY_UNAVAILABLE",
                        }
                    ),
                    flush=True,
                )
    finally:
        market.close()


if __name__ == "__main__":
    raise SystemExit(main())
