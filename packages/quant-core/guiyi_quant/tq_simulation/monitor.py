"""Sanitized TqKq monitor projection, independent of historical SimNow readers."""

from decimal import Decimal
from ..htdy_account_execution.reducer import local_occupancy
from .journal import digest
from ..htdy_account_execution.tq_types import TQ_RISK_VERSION, TQ_EXECUTION_VERSION

VERSION = "simulation_monitor_v1"
METRICS = (
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
LABELS = {
    "WORKING": "已受理",
    "FILLED": "成交已确认",
    "CANCELLED": "已撤单",
    "REJECTED": "已拒绝",
    "UNKNOWN": "结果未知",
    "PROPOSED": "待提交",
    "CANCEL_PENDING": "撤单待确认",
    "LOCAL_ABORTED": "本地未发送",
}


def blank(now, code=None):
    return dict(
        version=VERSION,
        status="not_connected",
        snapshot=None,
        generated_at=now.isoformat(),
        account=None,
        observer=None,
        readback_at=None,
        trading_day=None,
        readback_status="unknown",
        position_projection_complete=False,
        metrics={k: None for k in METRICS},
        positions=[],
        curve=[],
        issues=[],
        issue_count=0,
        coverage="unavailable",
        performance_status="UNAVAILABLE",
        source_times={},
        block_code=code,
    )


def projection(
    controller,
    snapshot,
    now,
    *,
    mode,
    opening,
    code=None,
    trading_day=None,
    source_issues=None,
):
    state = controller.store.current() if controller.store else None
    out = blank(now, code)
    out["snapshot"] = digest(
        {
            "native": snapshot["snapshot_id"] if snapshot else None,
            "at": now.isoformat(),
            "code": code,
        }
    )
    out["account"] = {
        "key": controller.account_id,
        "alias": "快期模拟主账户",
        "environment": "TQKQ",
        "strategy": "火天大有 · 60分钟",
        "scope_product": None,
        "policy_version": "htdy_tqkq_v1",
        "risk_profile_version": TQ_RISK_VERSION,
        "execution_profile_version": TQ_EXECUTION_VERSION,
    }
    out["observer"] = {
        "status": "error" if code else "running",
        "stage": code or ("AUTO_TRADING" if opening else "OBSERVING"),
        "published_at": now.isoformat(),
        "connection": "LOGGED_IN" if snapshot else "NOT_CONNECTED",
        "mode": mode,
        "opening_enabled": opening,
        "account_takeover_pending": mode == "trade" and state is None,
        "host_status": state.phase if state else "READ_ONLY",
    }
    out["status"] = "partial" if code or state is None else "available"
    out["trading_day"] = trading_day
    out["coverage"] = "complete" if state else "partial"
    out["readback_at"] = snapshot["observed_at"] if snapshot else None
    fresh = bool(
        state
        and state.readback_valid
        and state.readback.at <= now < state.readback.valid_until
    )
    out["readback_status"] = "verified" if fresh else "unverified"
    out["position_projection_complete"] = fresh
    out["performance_status"] = "ACCOUNT_EQUITY_ONLY"
    if code:
        out["issues"] = [
            {
                "id": "tq-issue:" + code,
                "code": code,
                "label": code,
                "at": now.isoformat(),
                "product": "",
                "contract": "",
                "link": None,
            }
        ]
        out["issue_count"] = 1
    for product, issue in sorted((source_issues or {}).items()):
        out["issues"].append(
            dict(
                id="tq-source:" + product + ":" + issue,
                code=issue,
                label=issue,
                at=now.isoformat(),
                product=product,
                contract="",
                link=None,
            )
        )
    out["issue_count"] = len(out["issues"])
    if snapshot:
        a = snapshot["account"]
        balance = Decimal(a["balance"])
        margin = Decimal(a["margin"])
        frozen = Decimal(a["frozen_margin"])
        local, fees = local_occupancy(state) if state else (Decimal(0), Decimal(0))
        metrics = {
            "equity": a["balance"],
            "available": a["available"],
            "used_margin": a["margin"],
            "frozen_margin": a["frozen_margin"],
            "frozen_fee": a["frozen_commission"],
            "margin_limit": str(balance * Decimal(".70")),
            "occupied_margin": str(margin + frozen + local),
            "margin_ratio": str((margin + frozen + local) / balance),
            "local_reserved_margin": str(local),
            "local_reserved_fee": str(fees),
            "daily_fee": a["commission"],
        }
        # Per-fill commission is unavailable in public TqSdk Trade. Never turn
        # missing cash-flow continuity into attributed fees or a return.
        out["metrics"].update(metrics)
        for p in snapshot["positions"]:
            product, contract = controller.symbols.get(p["symbol"], ("", p["symbol"]))
            for side in ("long", "short"):
                qty = p["pos_" + side + "_today"] + p["pos_" + side + "_his"]
                if qty:
                    out["positions"].append(
                        dict(
                            id="tq-position:" + p["symbol"] + ":" + side,
                            product=product,
                            contract=contract,
                            side="LONG" if side == "long" else "SHORT",
                            quantity=qty,
                            today=p["pos_" + side + "_today"],
                            yesterday=p["pos_" + side + "_his"],
                            frozen_long=p.get("frozen_long"),
                            frozen_short=p.get("frozen_short"),
                            position_profit=None,
                            status="VERIFIED" if fresh else "UNVERIFIED",
                            as_of=snapshot["observed_at"],
                        )
                    )
        curve = controller.journal.events("equity")[-168:]
        out["curve"] = [
            dict(
                at=p["at"],
                equity=p["equity"],
                net_profit=None,
                trading_day=p["trading_day"],
            )
            for p in curve
        ]
    records = []

    def add(
        kind,
        identity,
        at,
        product,
        contract,
        status,
        label,
        facts,
        signal=None,
        order=None,
    ):
        records.append(
            dict(
                id=kind + ":" + identity,
                kind=kind,
                at=at.isoformat(),
                product=product,
                contract=contract,
                status=status,
                label=label,
                signal_id=signal,
                order_id=order,
                facts={k: None if v is None else str(v) for k, v in facts.items()},
            )
        )

    if state:
        for s in state.signals:
            add(
                "signal",
                s.source_id,
                s.observed_at,
                s.product,
                s.contract,
                "OBSERVED",
                "策略信号",
                {"direction": ",".join(s.directions), "bar_end": s.bar_end.isoformat()},
                s.source_id,
            )
        for i, r in enumerate(state.risk_decisions):
            add(
                "risk",
                str(i),
                r.at,
                r.product,
                "",
                "APPROVED" if r.approved else "REJECTED",
                r.reason,
                {
                    "reason": r.reason,
                    "margin": r.margin,
                    "margin_limit": r.margin_limit,
                },
                r.signal_id,
            )
        for o in state.orders:
            add(
                "order",
                o.order_id,
                o.created_at,
                o.product,
                o.contract,
                o.status,
                LABELS[o.status],
                {
                    "side": o.side,
                    "offset": o.offset,
                    "quantity": o.quantity,
                    "price": o.price,
                },
                o.signal_id,
                o.order_id,
            )
        for f in state.fills:
            o = next(o for o in state.orders if o.order_id == f.order_id)
            add(
                "fill",
                f.trade_id,
                f.recorded_at,
                o.product,
                f.contract,
                "RECORDED",
                "模拟成交已确认",
                {
                    "price": f.price,
                    "filled_at": f.filled_at.isoformat(),
                    "native_precision_seconds": "0.000001",
                    "quantity": f.quantity,
                    "fee": f.fee,
                    "fee_status": "UNKNOWN" if f.fee is None else "VERIFIED",
                },
                o.signal_id,
                o.order_id,
            )
    out["snapshot"] = digest(records)
    return {
        "overview": out,
        "records": sorted(records, key=lambda r: (r["at"], r["id"]), reverse=True),
    }
