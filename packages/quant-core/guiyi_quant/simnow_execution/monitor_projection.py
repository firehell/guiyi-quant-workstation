"""Sanitized financial read model. Reuses account/fee policy; no trading effects."""

from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo
import base64
import json
import re
from ..htdy_account_execution import model as m
from ..htdy_account_execution.codec import digest
from ..htdy_account_execution.reducer import local_occupancy
from .inventory import number
from .finance import performance
from .monitor import MonitorError, VERSION

SHANGHAI = ZoneInfo("Asia/Shanghai")
LABELS = {
    "PROPOSED": "待提交",
    "LOCAL_ABORTED": "本地未发送",
    "WORKING": "已受理",
    "CANCEL_PENDING": "撤单待核",
    "CANCELLED": "已撤单",
    "REJECTED": "已拒绝",
    "FILLED": "成交回报",
    "UNKNOWN": "结果未知",
    "SIGNAL_CONFLICT": "同Bar信号冲突",
    "OBSERVATION_GAP": "自然输入存在缺口",
    "OWNER_MISMATCH": "主力合约不匹配",
    "RISK_MARGIN_CAP": "保证金上限拒绝",
    "RISK_AVAILABLE": "可用资金不足",
    "INPUT_BLOCKED": "输入资格待核",
    "FEE_PENDING": "成交费用或身份待核",
    "ACCOUNT_RECOVERY": "账户待恢复核验",
    "ACCOUNT_BLOCKED": "账户阻断",
    "OPEN_RESERVATION": "未释放资金预留",
}


def _decimal(value):
    return format(value, "f")


def _text(value):
    if value is None:
        return None
    value = format(value, "f") if isinstance(value, Decimal) else str(value)
    return (
        value
        if len(value) <= 256 and not any(ord(c) < 32 for c in value)
        else "UNKNOWN"
    )


def _blank(now, status="not_connected"):
    return dict(
        version=VERSION,
        status=status,
        snapshot=None,
        generated_at=now.isoformat(),
        account=None,
        observer=None,
        readback_at=None,
        trading_day=None,
        readback_status="unknown",
        position_projection_complete=False,
        metrics={
            k: None
            for k in (
                "equity",
                "available",
                "used_margin",
                "frozen_margin",
                "frozen_fee",
                "margin_limit",
                "occupied_margin",
                "margin_ratio",
                "local_reserved_margin",
                "local_reserved_fee",
                "daily_fee",
                "attributed_fee",
                "net_profit",
                "return_ratio",
            )
        },
        positions=[],
        curve=[],
        issues=[],
        issue_count=None,
        coverage="unavailable",
        source_times={},
        performance_status="EVIDENCE_REQUIRED",
    )


def _pending(data):
    receipts = dict(data["state"].receipts)
    return [
        (identity, p, at)
        for identity, p, at in data["events"]
        if identity not in receipts
        and p.get("kind") in ("trade", "quarantine", "fault", "disconnect", "uncertain")
    ]


def _positions(data):
    native = data["snapshots"][-1]
    state = data["state"]
    rows = []
    mapping = {}
    for action in data["actions"]:
        p = action["payload"]
        mapping.setdefault((p.get("exchange"), p.get("native")), set()).add(
            p.get("contract")
        )
    for p in native.data["positions"]:
        qty = p.get("Position")
        frozen = (p.get("LongFrozen", 0), p.get("ShortFrozen", 0))
        if (
            type(qty) is not int
            or qty < 0
            or any(type(v) is not int or v < 0 for v in frozen)
        ):
            raise MonitorError("MONITOR_NATIVE_POSITION_INVALID")
        if qty == 0 and not any(frozen):
            continue
        contract = p["InstrumentID"]
        exchange = p["ExchangeID"]
        if re.fullmatch(r"[A-Za-z]{1,3}\d{3,4}", contract) is None:
            raise MonitorError("MONITOR_NATIVE_POSITION_INVALID")
        product = re.match(r"[A-Za-z]+", contract)[0].upper()
        names = mapping.get((exchange, contract), set())
        canonical = next(iter(names)) if len(names) == 1 else None
        model = next(
            (
                x
                for x in state.positions
                if x.product == product and canonical == x.contract
            ),
            None,
        )
        side = p.get("PosiDirection")
        signed = qty if side == "2" else -qty if side == "3" else None
        matched = (
            model is not None
            and model.quantity == signed
            and state.readback_valid
            and state.readback.source_id == native.source_id
        )
        profit = number(p["PositionProfit"], True) if "PositionProfit" in p else None
        rows.append(
            dict(
                id=digest(
                    (
                        exchange,
                        contract,
                        side,
                        p.get("PositionDate"),
                        p.get("HedgeFlag"),
                    )
                ),
                product=product,
                contract=canonical or contract,
                side="LONG" if side == "2" else "SHORT" if side == "3" else "UNKNOWN",
                quantity=qty,
                today=p.get("TodayPosition"),
                yesterday=p.get("YdPosition"),
                frozen_long=frozen[0],
                frozen_short=frozen[1],
                position_profit=_decimal(profit) if profit is not None else None,
                status="matched" if matched else "pending",
                as_of=native.at.isoformat(),
            )
        )
    return rows


def _issues(data):
    state = data["state"]
    result = []

    def add(code, at, product="", contract="", link=None):
        result.append(
            dict(
                id=digest(("issue", code, product, contract, link)),
                code=code,
                label=LABELS.get(code, "待核事项"),
                at=at.isoformat(),
                product=product,
                contract=contract,
                link=link,
            )
        )

    if state.phase != "READY":
        add(
            "ACCOUNT_BLOCKED" if state.phase == "BLOCKED" else "ACCOUNT_RECOVERY",
            state.clock,
        )
    for product in state.blocked_products:
        add("INPUT_BLOCKED", state.clock, product)
    for identity, p, at in _pending(data):
        order = next((o for o in state.orders if o.order_id == p.get("order_id")), None)
        add(
            "FEE_PENDING" if p.get("kind") == "trade" else "ACCOUNT_RECOVERY",
            at,
            order.product if order else "",
            order.contract if order else "",
            digest(("order", order.order_id)) if order else None,
        )
    for fill in state.fills:
        if fill.trade_id in state.unresolved_fill_ids:
            add("ACCOUNT_BLOCKED", fill.recorded_at, contract=fill.contract)
    for order in state.orders:
        if not order.reconciled and order.status in (
            "UNKNOWN",
            "CANCEL_PENDING",
            "FILLED",
        ):
            add(
                order.status,
                order.terminal_at or order.created_at,
                order.product,
                order.contract,
                digest(("order", order.order_id)),
            )
    return result


def overview(data, now, error=False):
    if data is None:
        return _blank(now, "unavailable" if error else "not_connected")
    state = data["state"]
    native = data["snapshots"][-1]
    index = data["index"]
    funds = native.data["funds"][0]
    pending = _pending(data)
    positions = _positions(data)
    matching = state.readback.source_id == native.source_id
    complete = (
        state.readback_valid
        and state.phase == "READY"
        and not state.unresolved_fill_ids
        and not pending
        and matching
        and all(p["status"] == "matched" for p in positions)
    )
    fresh = now < native.at + timedelta(seconds=30)
    age = (now - datetime.fromisoformat(index["published_at"])).total_seconds()
    observer_status = (
        "stopped"
        if index["status"] == "STOPPED"
        else "error"
        if index["status"] == "ERROR"
        else "stale"
        if age > 30
        else "running"
    )
    metrics = {k: None for k in _blank(now)["metrics"]}
    metrics.update(
        equity=_decimal(number(funds["Balance"], True)),
        available=_decimal(number(funds["Available"], True)),
        used_margin=_decimal(number(funds["CurrMargin"])),
        frozen_margin=_decimal(number(funds["FrozenMargin"])),
        frozen_fee=_decimal(number(funds["FrozenCommission"])),
        daily_fee=_decimal(number(funds["Commission"])),
        attributed_fee=_decimal(
            sum(
                (
                    f.fee
                    for f in state.fills
                    if f.trade_id not in state.unresolved_fill_ids
                ),
                Decimal(0),
            )
        ),
    )
    if complete:
        local_margin, local_fee = local_occupancy(state)
        balance = state.readback.snapshot.balance
        occupied = (
            state.readback.used_margin + state.readback.frozen_margin + local_margin
        )
        metrics.update(
            margin_limit=_decimal(max(Decimal(0), balance) * m.CAP),
            occupied_margin=_decimal(occupied),
            margin_ratio=_decimal(occupied / balance) if balance > 0 else None,
            local_reserved_margin=_decimal(local_margin),
            local_reserved_fee=_decimal(local_fee),
        )
    else:
        # Raw unreleased sums are shown separately, never a guessed de-duplicated budget.
        metrics.update(
            local_reserved_margin=_decimal(
                sum(
                    (r.margin for r in state.reservations if not r.released), Decimal(0)
                )
            ),
            local_reserved_fee=_decimal(
                sum((r.fee for r in state.reservations if not r.released), Decimal(0))
            ),
        )
    perf = performance(data["baseline"], native)
    metrics.update(
        net_profit=_decimal(perf.net_profit) if perf.net_profit is not None else None,
        return_ratio=_decimal(perf.return_ratio)
        if perf.return_ratio is not None
        else None,
    )
    curve = []
    cutoff = now - timedelta(days=7)
    for snapshot in data["snapshots"]:
        if snapshot.at < cutoff:
            continue
        p = performance(data["baseline"], snapshot)
        curve.append(
            dict(
                at=snapshot.at.isoformat(),
                equity=_decimal(p.equity),
                net_profit=_decimal(p.net_profit) if p.net_profit is not None else None,
                trading_day=snapshot.trading_day,
            )
        )
    issues = _issues(data)
    for position in positions:
        if position["status"] != "matched":
            issues.append(
                dict(
                    id=digest(("position-issue", position["id"])),
                    code="NATIVE_POSITION_PENDING",
                    label="原生持仓与本地投影待核",
                    at=native.at.isoformat(),
                    product=position["product"],
                    contract=position["contract"],
                    link=None,
                )
            )
    if perf.status == "CASHFLOW_CONTINUITY_REQUIRED":
        issues.append(
            dict(
                id=digest(("cashflow", native.trading_day)),
                code="CASHFLOW_CONTINUITY_REQUIRED",
                label="跨日现金流连续性待核",
                at=native.at.isoformat(),
                product="",
                contract="",
                link=None,
            )
        )

    return dict(
        version=VERSION,
        status="available" if complete else "partial",
        snapshot=data["snapshot"],
        generated_at=now.isoformat(),
        account=dict(
            key=digest(("monitor-account", state.account_id)),
            alias="HTDY60m模拟账户",
            environment="SimNow第一套",
            strategy="火天大有 · 60分钟",
            scope_product=_text(index.get("product")),
            policy_version=m.POLICY_VERSION,
        ),
        observer=dict(
            status=observer_status,
            stage=index["status"],
            published_at=index["published_at"],
            connection=index["connection"]
            if observer_status == "running"
            else "RELEASED"
            if observer_status == "stopped"
            else "UNKNOWN",
        ),
        readback_at=native.at.isoformat(),
        trading_day=native.trading_day,
        readback_status="verified"
        if complete and fresh
        else "last_verified"
        if complete
        else "pending",
        position_projection_complete=complete,
        metrics=metrics,
        positions=positions,
        curve=curve,
        issues=issues,
        issue_count=len(issues),
        coverage="partial" if data["truncated"] else "complete",
        source_times=dict(
            account=native.at.isoformat(), ledger=state.clock.isoformat()
        ),
        performance_status=perf.status,
    )


def all_records(data):
    if data is None:
        return []
    state = data["state"]
    rows = []
    manual_tests = {
        audit.command.test_id: (audit.command.product, audit.command.contract)
        for audit in state.audit
        if type(audit.command) is m.ManualBeginV1
    }

    def row(
        kind,
        identity,
        when,
        product,
        contract,
        status,
        label,
        signal_id=None,
        order_id=None,
        **facts,
    ):
        manual = manual_tests.get(signal_id)
        if (
            kind in ("risk", "order", "fill")
            and manual is not None
            and product == manual[0]
            and (not contract or contract == manual[1])
        ):
            label = "人工验收·" + label
            facts["origin"] = "人工验收交易"
        rows.append(
            dict(
                id=digest((kind, identity)),
                kind=kind,
                at=when.isoformat(),
                product=product,
                contract=contract,
                status=status,
                label=label,
                signal_id=_text(signal_id),
                order_id=_text(order_id),
                facts={k: _text(v) for k, v in facts.items()},
            )
        )

    reasons = {
        a.command.source_id: a.reason
        for a in state.audit
        if type(a.command) is m.Signal
    }
    for signal in state.signals:
        status = (
            "CONFLICT"
            if len(signal.directions) > 1
            else "BUY"
            if signal.directions == ("buy",)
            else "SELL"
            if signal.directions == ("sell",)
            else "HOLD"
        )
        reason = reasons.get(signal.source_id, "TARGET_UPDATED")
        row(
            "signal",
            signal.source_id,
            signal.observed_at,
            signal.product,
            signal.contract,
            status,
            {
                "CONFLICT": "信号冲突",
                "BUY": "买信号",
                "SELL": "卖信号",
                "HOLD": "无新方向",
            }[status],
            signal.source_id,
            bar_end=signal.bar_end.isoformat(),
            observed_at=signal.observed_at.isoformat(),
            reason=reason,
            input_hash=signal.input_hash,
        )
    for risk in state.risk_decisions:
        row(
            "risk",
            digest(risk),
            risk.at,
            risk.product,
            "",
            "APPROVED" if risk.approved else "REJECTED",
            "风控通过" if risk.approved else "风控拒绝",
            risk.signal_id,
            reason=risk.reason,
            margin=risk.margin,
            projected_margin=risk.projected_margin,
            margin_limit=risk.margin_limit,
            funding_source_id=risk.funding_source_id,
        )
    for order in state.orders:
        row(
            "order",
            order.order_id,
            order.created_at,
            order.product,
            order.contract,
            order.status,
            LABELS.get(order.status, "订单待核"),
            order.signal_id,
            order.order_id,
            side=order.side,
            offset=order.offset,
            quantity=order.quantity,
            price=order.price,
            accepted_at=order.accepted_at.isoformat() if order.accepted_at else None,
            reconciled="true" if order.reconciled else "false",
            predecessor_id=order.predecessor_id,
        )
    orders = {o.order_id: o for o in state.orders}
    for fill in state.fills:
        order = orders.get(fill.order_id)
        row(
            "fill",
            fill.trade_id,
            fill.recorded_at,
            order.product if order else "",
            fill.contract,
            "PENDING" if fill.trade_id in state.unresolved_fill_ids else "RECORDED",
            "成交待核"
            if fill.trade_id in state.unresolved_fill_ids
            else "实际成交入账",
            order.signal_id if order else None,
            fill.order_id,
            price=fill.price,
            fee=fill.fee,
            quantity=fill.quantity,
            filled_at=fill.filled_at.isoformat(),
            recorded_at=fill.recorded_at.isoformat(),
            native_precision_seconds=getattr(fill, "native_precision_seconds", 0),
        )
    days = {}
    for action in data["actions"]:
        value = action["payload"].get("trading_day")
        if isinstance(value, str) and re.fullmatch(r"\d{8}", value):
            days.setdefault(action["order_id"], set()).add(value)
    for record in rows:
        known = days.get(record["order_id"], set())
        if len(known) == 1:
            record["facts"]["trading_day"] = next(iter(known))
    return sorted(rows, key=lambda r: (r["at"], r["id"]), reverse=True)


def records_page(data, kind, product, status, start_day, end_day, cursor):
    if kind not in ("all", "signal", "risk", "order", "fill"):
        raise MonitorError("MONITOR_QUERY_INVALID")
    query = [
        kind,
        product.upper(),
        status,
        start_day.isoformat() if start_day else None,
        end_day.isoformat() if end_day else None,
    ]
    offset = 0
    snapshot = data["snapshot"] if data else None
    if cursor:
        try:
            value = json.loads(base64.urlsafe_b64decode(cursor))
            if (
                value["snapshot"] != snapshot
                or value["query"] != query
                or type(value["offset"]) is not int
                or value["offset"] < 0
            ):
                raise ValueError()
            offset = value["offset"]
        except Exception:
            raise MonitorError("MONITOR_SNAPSHOT_CHANGED") from None
    rows = all_records(data)

    def include(row):
        day = datetime.fromisoformat(row["at"]).astimezone(SHANGHAI).date()
        return (
            (kind == "all" or row["kind"] == kind)
            and (not product or row["product"] == product.upper())
            and (not status or row["status"] == status)
            and (start_day is None or day >= start_day)
            and (end_day is None or day <= end_day)
        )

    filtered = [r for r in rows if include(r)]
    capped = len(filtered) > 5000
    filtered = filtered[:5000]
    items = filtered[offset : offset + 50]
    more = offset + 50 < len(filtered)
    next_cursor = (
        base64.urlsafe_b64encode(
            json.dumps(
                dict(snapshot=snapshot, query=query, offset=offset + 50), sort_keys=True
            ).encode()
        ).decode()
        if more
        else None
    )
    return dict(
        version=VERSION,
        snapshot=snapshot,
        items=items,
        next_cursor=next_cursor,
        available_count=len(filtered),
        coverage="partial"
        if capped or data and data["truncated"]
        else "complete"
        if data
        else "unavailable",
    )


def detail(data, identity):
    rows = all_records(data)
    selected = next((r for r in rows if r["id"] == identity), None)
    if selected is None:
        raise MonitorError("MONITOR_RECORD_NOT_FOUND")
    related = [
        r
        for r in rows
        if r["id"] == identity
        or selected["signal_id"]
        and r["signal_id"] == selected["signal_id"]
        or selected["order_id"]
        and r["order_id"] == selected["order_id"]
    ]
    return dict(
        version=VERSION,
        snapshot=data["snapshot"],
        selected=selected,
        chain=sorted(related, key=lambda r: (r["at"], r["id"])),
    )
