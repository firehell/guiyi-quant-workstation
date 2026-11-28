"""Read the journal's active case evidence with its original plan revision."""

from datetime import timedelta
from decimal import Decimal

from fastapi.encoders import jsonable_encoder

from app.api.trade_journal import project_timeline
from app.db.readonly import readonly_transaction
from app.market_data.catalog import MarketCatalog
from app.market_data.composition import canonical_root
from app.market_data.domain import BarFrequency, ContractTradingDayQuery
from app.market_data.market_data_service import MarketDataError, MarketDataService
from app.market_data.storage import CanonicalMonthlyStore
from app.trade_journal.sources import read_evidence
from app.trade_journal.store import JournalStore

CLOSING = frozenset(("CLOSE", "CLOSETODAY", "CLOSEYESTERDAY", "REDUCE", "EXIT"))


def execution_path(events, direction, contract):
    if not events:
        return [], "NO_LINKED_EXECUTION"
    rows, seen = [], set()
    position = fees = average = realized = Decimal(0)
    side = 1 if direction == "LONG" else -1
    scope = events[0]["source"], events[0]["scope"]
    for event in events:
        mark = (event["source"], event["scope"], event["native_id"])
        evidence = event.get("evidence")
        if (not evidence or mark in seen or mark[:2] != scope or evidence["direction"] != direction
                or evidence["contract"].upper() != contract.upper()):
            return rows, "EXECUTION_LINKS_INCOMPLETE"
        seen.add(mark)
        action = evidence["action"]
        try:
            quantity, price = (Decimal(str(evidence[name])) for name in ("quantity", "price"))
            fee = Decimal(str(evidence["fee"])) if evidence.get("fee") is not None else None
            if quantity <= 0 or price <= 0 or fee is None or fee < 0 or not all(
                value.is_finite() for value in (quantity, price, fee)
            ):
                return rows, "EXECUTION_COST_OR_QUANTITY_UNPROVEN"
        except (ArithmeticError, KeyError, TypeError):
            return rows, "EXECUTION_COST_OR_QUANTITY_UNPROVEN"
        delta = quantity if action == "OPEN" else -quantity if action in CLOSING else None
        if delta is None or position + delta < 0 or rows and position == 0:
            return rows, "EXECUTION_PAIRING_UNPROVEN"
        if delta > 0:
            average = (average * position + price * delta) / (position + delta)
        else:
            realized += (price - average) * quantity * side
        position += delta
        fees += fee
        rows.append({"at": event["occurred_at"], "trading_day": event["trading_day"], "action": action,
                     "native_id": event["native_id"], "source": event["source"], "scope": event["scope"],
                     "price": str(price), "quantity": str(quantity), "remaining": str(position),
                     "fees_to_date": str(fees), "remaining_average_price": str(average),
                     "gross_realized_points_contracts": str(realized)})
    return rows, None


def excursions(rows, bars, direction):
    sign = 1 if direction == "LONG" else -1
    favorable = adverse = Decimal(0)
    used, excluded, cursor = 0, 0, 0
    for current, following in zip(rows, rows[1:]):
        quantity, basis = Decimal(current["remaining"]), Decimal(current["remaining_average_price"])
        realized = Decimal(current["gross_realized_points_contracts"])
        while cursor < len(bars) and bars[cursor].bar_end <= following["at"]:
            bar = bars[cursor]
            cursor += 1
            if bar.bar_end <= current["at"]:
                continue
            if bar.bar_end - timedelta(minutes=5) < current["at"] or bar.is_strict_no_trade or bar.low <= 0:
                excluded += 1
                continue
            high, low = (realized + (bar.high - basis) * quantity * sign,
                         realized + (bar.low - basis) * quantity * sign)
            used += 1
            favorable = max(favorable, high, low)
            adverse = min(adverse, high, low)
    if not used:
        return None
    return {"mfe": str(favorable), "mae": str(adverse), "unit": "price_points_times_contracts",
            "frequency": "5m", "used_bars": used, "excluded_boundary_or_quality": excluded,
            "basis": "position_weighted_average_open_price", "cost": "gross_realized_plus_floating_without_fees",
            "coverage": "complete_5m_bars_wholly_inside_each_fill_interval"}


def price_path(db, case, rows):
    if len(rows) < 2:
        return None
    first, last = rows[0]["trading_day"], rows[-1]["trading_day"]
    if last - first > timedelta(days=31):
        return None
    root = canonical_root()
    try:
        with readonly_transaction(db, timeout_seconds=5):
            market = MarketDataService(MarketCatalog(db, root), CanonicalMonthlyStore(root))
            result = market.query_contract_trading_days(ContractTradingDayQuery(
                case["product"], case["contract"], BarFrequency("5m"), first, last
            ))
            if result.requested_trading_day_window != (first, last):
                return None
    except (MarketDataError, ValueError):
        return None
    path = excursions(rows, result.bars, case["direction"])
    if path:
        from app.backtest_center.codec import digest
        from app.market_data.domain import canonical_bar_source_sha256

        path["data_revision"] = digest([canonical_bar_source_sha256(bar) for bar in result.bars])
    return path


def journal_input(db, request, case_id):
    store = JournalStore(db)
    with readonly_transaction(db, timeout_seconds=5):
        case = store.case(case_id)
        plan = store.plan_revision(case["plan_id"], case["plan_version"]) if case["plan_id"] else None
        timeline = store.timeline(case_id)
    active = [event for event in timeline if event["kind"] == "FILL" and not event["removed_at"]]
    rows, reason = execution_path(project_timeline(request, active, case["contract"]), case["direction"],
                                  case["contract"])
    closed = None if reason else bool(rows and Decimal(rows[-1]["remaining"]) == 0 and case["closed"])
    path = price_path(db, case, rows) if closed else None
    planned_direction = (plan["content"].get("direction") if plan and rows and plan["recorded_at"] <= rows[0]["at"]
                         else None)
    direction_match = case["direction"] == planned_direction if planned_direction in ("LONG", "SHORT") else None
    return jsonable_encoder({
        "source": {"kind": "case", "case_id": case_id, "case_version": case["version"],
                   "contract": case["contract"], "direction": case["direction"], "product": case["product"],
                   "plan_id": case["plan_id"], "plan_version": case["plan_version"]},
        "policy": {"version": "journal_native_path_v1", "samples": "active_native_fill_links"},
        "coverage": {"linked_fills": len(active), "reconciled_fills": len(rows),
                     "reason": reason, "plan_available": plan is not None},
        "trade_path": {
            "closed": closed, "closed_trades": int(closed) if closed is not None else None,
            "open_trading_day": rows[0]["trading_day"] if rows else None,
            "close_trading_day": rows[-1]["trading_day"] if closed else None,
            "remaining": rows[-1]["remaining"] if rows and not reason else None,
            "plan_direction_matches": direction_match,
            "price_excursion": path,
            "unavailable": {
                "plan_adherence": "STRUCTURED_RULE_PROOF_REQUIRED",
                "profit_retention": "COMMON_NET_MARK_AND_FEE_POLICY_REQUIRED",
                **({"price_excursion": "HOLDING_PATH_UNPROVEN"} if path is None else {}),
            },
        },
        "samples": rows,
    })


def fills_input(request, selection):
    read = read_evidence(request, selection.book, selection.day, selection.scope, contract=selection.contract)
    label = "reference" if selection.book == "NEWOW_REFERENCE" else "native_fill"
    rows = [{**item, "record_type": label, "trading_day": selection.day.isoformat()} for item in read["items"] if item["contract"].upper() == selection.contract.upper()]
    confirmed = read["status"] in ("AVAILABLE", "VERIFIED_EMPTY") and read["scope"] == selection.scope
    reason = ("SOURCE_PAGE_INCOMPLETE" if read["has_more"] else None) if confirmed else read["status"]
    return jsonable_encoder({
        "source": {"kind": "fills", "book": selection.book, "scope": selection.scope,
                   "contract": selection.contract, "day": selection.day,
                   "fact_kind": "PAGE_REFERENCE" if label == "reference" else "SIMULATED_EXECUTION"},
        "policy": {"version": "owner_evidence_v1", "executable": False,
                   "account_return": "VERIFIED_ACCOUNT_SETTLEMENT_REQUIRED"},
        "coverage": {"reason": reason, "page_rows": len(rows), "complete": confirmed and not read["has_more"],
                     "total": len(rows) if confirmed and not read["has_more"] else None},
        "samples": rows,
    })
