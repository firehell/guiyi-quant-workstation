from __future__ import annotations

from datetime import date, datetime
import json
from math import isclose
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backtest.drawdown_curve_generator import generate_drawdown_curve
from app.backtest.equity_curve_generator import generate_equity_curve
from app.models.backtest import BacktestReportModel, BacktestTradeModel
from app.vnpy_integration.execution_policy import DEFAULT_EXECUTION_TIMING


AuditStatus = Literal["passed", "warning", "failed"]

ALLOWED_DATA_SOURCES = {"rqdata", "local_parquet"}
SENSITIVE_KEYS = {
    "api_key",
    "authorization",
    "cookie",
    "license",
    "password",
    "qywx",
    "qywx_webhook_url",
    "secret",
    "token",
    "webhook",
}
SENSITIVE_TEXT_MARKERS = (
    "/Users/",
    "/Volumes/",
    "/private/",
    "\\Users\\",
    "QYWX_WEBHOOK_URL",
    "webhook",
    "token",
    "password",
    "license",
    "secret",
)


class BacktestTrustAuditError(ValueError):
    """Raised when a requested backtest report cannot be audited."""


def build_backtest_trust_audit(
    session: Session,
    *,
    report_id: int | None = None,
    task_no: str | None = None,
    strict_quality: bool = True,
) -> dict[str, Any]:
    """Build a readonly trust audit for a persisted backtest report."""
    report = _resolve_report(session, report_id=report_id, task_no=task_no)
    checks = [
        _data_lineage_check(report, strict_quality=strict_quality),
        _execution_policy_check(report),
        _lineage_mapping_check(report),
        _trade_order_consistency_check(report),
        _equity_consistency_check(report),
        _fee_slippage_check(report),
        _contract_multiplier_check(report),
        _trusted_metrics_check(report),
        _reproducibility_check(report),
    ]
    blocked_reasons = [reason for check in checks if check["status"] == "failed" for reason in check["reasons"]]
    warnings = [reason for check in checks if check["status"] == "warning" for reason in check["reasons"]]
    audit = {
        "audit_status": _overall_status(checks),
        "readonly": True,
        "would_write_db": False,
        "would_run_rqdata": False,
        "would_run_backtest": False,
        "would_send_notifications": False,
        "report_id": report.id,
        "report_no": report.report_no,
        "task_id": report.task_id,
        "task_no": report.task_no,
        "strategy_code": report.strategy_code,
        "strategy_version": report.strategy_version,
        "symbol": report.symbol,
        "contract": report.contract,
        "period": report.period,
        "engine_type": report.engine_type,
        "data_source": report.data_source,
        "data_role": report.data_role,
        "data_version": report.data_version,
        "quality_status": _quality_status(report),
        "research_only": report.research_only,
        "consistency_hash": report.consistency_hash,
        "checks": {check["name"]: check for check in checks},
        "blocked_reasons": blocked_reasons,
        "warnings": warnings,
    }
    audit = _sanitize_payload(audit)
    sensitive_check = _sensitive_output_check(audit)
    audit["checks"]["sensitive_output"] = sensitive_check
    if sensitive_check["status"] == "failed":
        audit["audit_status"] = "failed"
        audit["blocked_reasons"].extend(sensitive_check["reasons"])
    return audit


def render_audit_markdown(audit: dict[str, Any]) -> str:
    lines = [
        f"# Backtest Trust Audit: report_id={audit.get('report_id')}",
        "",
        f"- audit_status: {audit.get('audit_status')}",
        f"- task_no: {audit.get('task_no')}",
        f"- strategy: {audit.get('strategy_code')} / {audit.get('strategy_version')}",
        f"- contract: {audit.get('contract')} / {audit.get('period')}",
        f"- data: {audit.get('data_source')} / {audit.get('data_role')} / {audit.get('quality_status')}",
        f"- readonly: {audit.get('readonly')}",
        "",
        "## Checks",
    ]
    for name, check in (audit.get("checks") or {}).items():
        lines.append(f"- {name}: {check.get('status')}")
        for reason in check.get("reasons") or []:
            lines.append(f"  - {reason}")
    if audit.get("blocked_reasons"):
        lines.extend(["", "## Blocked Reasons"])
        lines.extend(f"- {reason}" for reason in audit["blocked_reasons"])
    if audit.get("warnings"):
        lines.extend(["", "## Warnings"])
        lines.extend(f"- {reason}" for reason in audit["warnings"])
    return "\n".join(lines) + "\n"


def _resolve_report(session: Session, *, report_id: int | None, task_no: str | None) -> BacktestReportModel:
    if report_id is None and not task_no:
        raise BacktestTrustAuditError("report_id or task_no is required")
    if report_id is not None:
        report = session.get(BacktestReportModel, report_id)
        if report is None:
            raise BacktestTrustAuditError(f"backtest report not found: report_id={report_id}")
        return report
    stmt = (
        select(BacktestReportModel)
        .where(BacktestReportModel.task_no == task_no)
        .order_by(BacktestReportModel.created_at.desc(), BacktestReportModel.id.desc())
        .limit(1)
    )
    report = session.scalars(stmt).first()
    if report is None:
        raise BacktestTrustAuditError(f"backtest report not found: task_no={task_no}")
    return report


def _data_lineage_check(report: BacktestReportModel, *, strict_quality: bool) -> dict[str, Any]:
    reasons: list[str] = []
    status: AuditStatus = "passed"
    data_source = (report.data_source or "").strip()
    if data_source not in ALLOWED_DATA_SOURCES:
        status = "failed"
        reasons.append(f"data_source must be rqdata/local_parquet, got {data_source or '<blank>'}")
    if report.data_role != "primary":
        status = "failed"
        reasons.append(f"data_role must be primary, got {report.data_role or '<blank>'}")
    quality_status = _quality_status(report)
    if quality_status == "failed":
        status = "failed"
        reasons.append("quality_status is failed")
    elif strict_quality and quality_status != "passed":
        status = _max_status(status, "warning")
        reasons.append(f"strict quality expects passed, got {quality_status or '<blank>'}")
    if not report.data_version:
        status = _max_status(status, "warning")
        reasons.append("data_version is missing")
    return _check("data_lineage", status, reasons)


def _execution_policy_check(report: BacktestReportModel) -> dict[str, Any]:
    reasons: list[str] = []
    status: AuditStatus = "passed"
    metadata = _metadata(report)
    execution_timing = metadata.get("execution_timing")
    if execution_timing != DEFAULT_EXECUTION_TIMING:
        status = "warning"
        reasons.append(f"execution_timing is not confirmed as {DEFAULT_EXECUTION_TIMING}")
    for trade in report.trades:
        if trade.entry_signal_time is None:
            status = _max_status(status, "warning")
            reasons.append(f"trade {trade.trade_no} missing entry_signal_time; next-bar fill cannot be fully confirmed")
            continue
        if not trade.entry_signal_source:
            status = _max_status(status, "warning")
            reasons.append(f"trade {trade.trade_no} missing entry_signal_source; signal timestamp source cannot be confirmed")
        if trade.open_time <= trade.entry_signal_time:
            status = "failed"
            reasons.append(f"trade {trade.trade_no} open_time must be after entry_signal_time")
    return _check("execution_policy", status, reasons)


def _lineage_mapping_check(report: BacktestReportModel) -> dict[str, Any]:
    reasons: list[str] = []
    status: AuditStatus = "passed"
    trades = list(report.trades)
    orders = list(report.order_rows)
    lineage_summary = (report.summary or {}).get("lineage_summary")
    if trades and not isinstance(lineage_summary, dict):
        status = _max_status(status, "warning")
        reasons.append("lineage_summary is missing; trade/order mapping cannot be summarized")

    for trade in trades:
        if trade.lineage_status in {None, "", "missing"}:
            status = _max_status(status, "warning")
            reasons.append(f"trade {trade.trade_no} lineage_status is missing")
        elif trade.lineage_status == "ambiguous":
            status = _max_status(status, "warning")
            reasons.append(f"trade {trade.trade_no} lineage mapping is ambiguous")
        elif trade.lineage_status == "partial":
            status = _max_status(status, "warning")
            reasons.append(f"trade {trade.trade_no} lineage mapping is partial")
        if trade.entry_signal_time is not None and not trade.entry_signal_source:
            status = _max_status(status, "warning")
            reasons.append(f"trade {trade.trade_no} has entry_signal_time but no entry_signal_source")
        if orders and not trade.entry_order_no and not _trade_has_strategy_event_lineage(trade):
            status = _max_status(status, "warning")
            reasons.append(f"trade {trade.trade_no} has order rows but no mapped entry_order_no")

    for order in orders:
        if order.mapping_status != "mapped":
            status = _max_status(status, "warning")
            reasons.append(f"order {order.order_no} mapping_status is {order.mapping_status or '<blank>'}")
        if order.mapping_status == "mapped" and (not order.trade_no or not order.leg):
            status = _max_status(status, "warning")
            reasons.append(f"order {order.order_no} mapped without trade_no/leg")
    return _check(
        "lineage_mapping",
        status,
        reasons,
        details={
            "lineage_summary": lineage_summary if isinstance(lineage_summary, dict) else {},
            "order_count": len(orders),
            "trade_count": len(trades),
        },
    )


def _trade_order_consistency_check(report: BacktestReportModel) -> dict[str, Any]:
    reasons: list[str] = []
    status: AuditStatus = "passed"
    trades = list(report.trades)
    orders = list(report.order_rows)
    if report.trade_count != len(trades):
        status = "failed"
        reasons.append(f"summary trade_count={report.trade_count} differs from trade rows={len(trades)}")
    if trades and not orders and not all(_trade_has_strategy_event_lineage(trade) for trade in trades):
        status = _max_status(status, "warning")
        reasons.append("report has trades but no order rows or complete strategy-event lineage")
    for trade in trades:
        if trade.direction not in {"long", "short", "多", "空", "buy", "sell"}:
            status = "failed"
            reasons.append(f"trade {trade.trade_no} has invalid direction={trade.direction}")
        if trade.volume <= 0:
            status = "failed"
            reasons.append(f"trade {trade.trade_no} volume must be positive")
        if trade.open_price <= 0 or trade.close_price <= 0:
            status = "failed"
            reasons.append(f"trade {trade.trade_no} price must be positive")
        if trade.close_time < trade.open_time:
            status = "failed"
            reasons.append(f"trade {trade.trade_no} close_time is earlier than open_time")
        if not trade.contract:
            status = "failed"
            reasons.append(f"trade {trade.trade_no} contract is missing")
    return _check("trade_order_consistency", status, reasons)


def _trade_has_strategy_event_lineage(trade: BacktestTradeModel) -> bool:
    return bool(trade.entry_signal_time and trade.entry_signal_source == "strategy_execution_event")


def _equity_consistency_check(report: BacktestReportModel) -> dict[str, Any]:
    reasons: list[str] = []
    status: AuditStatus = "passed"
    try:
        trade_payloads = [_trade_payload(trade) for trade in report.trades]
        equity_curve = generate_equity_curve(trade_payloads, initial_capital=report.initial_capital)
        drawdown_result = generate_drawdown_curve(equity_curve)
    except ValueError as exc:
        return _check("equity_consistency", "failed", [str(exc)])
    final_equity = _last_equity(equity_curve)
    if final_equity is not None and not _near(final_equity, report.final_equity):
        status = "failed"
        reasons.append(f"final_equity mismatch: recomputed={final_equity}, summary={report.final_equity}")
    if not _near(drawdown_result["max_drawdown_amount"], report.max_drawdown_amount):
        status = "failed"
        reasons.append(
            "max_drawdown_amount mismatch: "
            f"recomputed={drawdown_result['max_drawdown_amount']}, summary={report.max_drawdown_amount}"
        )
    if not _near(drawdown_result["max_drawdown_pct"], report.max_drawdown_pct):
        status = "failed"
        reasons.append(f"max_drawdown_pct mismatch: recomputed={drawdown_result['max_drawdown_pct']}, summary={report.max_drawdown_pct}")
    return _check(
        "equity_consistency",
        status,
        reasons,
        details={
            "recomputed_final_equity": final_equity,
            "recomputed_max_drawdown_amount": drawdown_result["max_drawdown_amount"],
            "recomputed_max_drawdown_pct": drawdown_result["max_drawdown_pct"],
        },
    )


def _fee_slippage_check(report: BacktestReportModel) -> dict[str, Any]:
    reasons: list[str] = []
    status: AuditStatus = "passed"
    metadata = _metadata(report)
    if metadata.get("rate") is None:
        status = _max_status(status, "warning")
        reasons.append("metadata rate is missing")
    if metadata.get("slippage") is None:
        status = _max_status(status, "warning")
        reasons.append("metadata slippage is missing")
    trades = list(report.trades)
    total_commission = sum(float(trade.commission or 0) for trade in trades)
    total_slippage = sum(float(trade.slippage or 0) for trade in trades)
    if trades and total_commission == 0:
        status = _max_status(status, "warning")
        reasons.append("trades exist but total commission is 0")
    if trades and total_slippage == 0:
        status = _max_status(status, "warning")
        reasons.append("trades exist but total slippage is 0")
    if not _near(total_commission, report.total_commission):
        status = "failed"
        reasons.append(f"total_commission mismatch: trades={total_commission}, summary={report.total_commission}")
    if not _near(total_slippage, report.total_slippage):
        status = "failed"
        reasons.append(f"total_slippage mismatch: trades={total_slippage}, summary={report.total_slippage}")
    return _check("fee_slippage", status, reasons)


def _contract_multiplier_check(report: BacktestReportModel) -> dict[str, Any]:
    reasons: list[str] = []
    status: AuditStatus = "passed"
    metadata = _metadata(report)
    if metadata.get("size") is None:
        status = _max_status(status, "warning")
        reasons.append("metadata size/contract multiplier is missing")
    if metadata.get("pricetick") is None:
        status = _max_status(status, "warning")
        reasons.append("metadata pricetick is missing")
    for trade in report.trades:
        if not trade.contract_multiplier or trade.contract_multiplier <= 0:
            status = "failed"
            reasons.append(f"trade {trade.trade_no} contract_multiplier is missing or invalid")
        if not trade.price_tick or trade.price_tick <= 0:
            status = "failed"
            reasons.append(f"trade {trade.trade_no} price_tick is missing or invalid")
    if report.strategy_code in {"jm_v1b_daily_direction_fast_entry", "su_bing_jm_v1b_short_hold"} and report.trades:
        missing_real_contract = [
            trade.trade_no
            for trade in report.trades
            if not trade.entry_contract or not trade.exit_contract or not trade.fee_rule_source or not trade.main_contract_source
        ]
        if missing_real_contract:
            status = _max_status(status, "warning")
            reasons.append(f"JM V1-B trades missing real-contract cost lineage: {', '.join(missing_real_contract[:5])}")
    return _check("contract_multiplier", status, reasons)


def _trusted_metrics_check(report: BacktestReportModel) -> dict[str, Any]:
    reasons: list[str] = []
    status: AuditStatus = "passed"
    summary_hash = (report.summary or {}).get("consistency_hash")
    if not report.consistency_hash:
        status = "failed"
        reasons.append("report consistency_hash is missing")
    if summary_hash != report.consistency_hash:
        status = "failed"
        reasons.append("summary consistency_hash does not match report consistency_hash")
    metric_units = (report.summary or {}).get("metric_units")
    if not isinstance(metric_units, dict):
        status = _max_status(status, "warning")
        reasons.append("metric_units is missing; raw/trusted metric units are less explicit")
    return _check("trusted_metrics", status, reasons)


def _reproducibility_check(report: BacktestReportModel) -> dict[str, Any]:
    reasons: list[str] = []
    status: AuditStatus = "passed"
    metadata = _metadata(report)
    required = {
        "task_no": report.task_no,
        "strategy_code": report.strategy_code,
        "strategy_version": report.strategy_version,
        "data_version": report.data_version,
        "start": metadata.get("start"),
        "end": metadata.get("end"),
    }
    for key, value in required.items():
        if value is None or value == "":
            status = _max_status(status, "warning")
            reasons.append(f"reproducibility field missing: {key}")
    task = report.task
    request_payload = task.request_payload if task is not None else {}
    return _check(
        "reproducibility",
        status,
        reasons,
        details={
            "metadata": _sanitize_payload(metadata),
            "request_payload": _sanitize_payload(request_payload),
        },
    )


def _sensitive_output_check(audit: dict[str, Any]) -> dict[str, Any]:
    encoded = json.dumps(audit, ensure_ascii=False, sort_keys=True, default=_json_default)
    leaked = sorted({marker for marker in SENSITIVE_TEXT_MARKERS if marker in encoded})
    if leaked:
        return _check("sensitive_output", "failed", [f"audit output contains sensitive marker: {marker}" for marker in leaked])
    return _check("sensitive_output", "passed", [])


def _metadata(report: BacktestReportModel) -> dict[str, Any]:
    metadata = (report.summary or {}).get("report_metadata")
    return dict(metadata) if isinstance(metadata, dict) else {}


def _quality_status(report: BacktestReportModel) -> str:
    value = report.quality_status.get("status") if isinstance(report.quality_status, dict) else None
    return str(value or "").strip().lower()


def _trade_payload(trade: BacktestTradeModel) -> dict[str, Any]:
    return {
        "trade_id": trade.trade_no,
        "trade_no": trade.trade_no,
        "sequence": trade.sequence,
        "exit_time": trade.close_time,
        "gross_pnl": trade.gross_pnl,
        "commission": trade.commission,
        "slippage": trade.slippage,
        "net_pnl": trade.net_pnl,
    }


def _last_equity(equity_curve: list[dict[str, Any]]) -> float | None:
    if not equity_curve:
        return None
    value = equity_curve[-1].get("equity")
    return float(value) if value is not None else None


def _check(name: str, status: AuditStatus, reasons: list[str], details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"name": name, "status": status, "reasons": reasons, "details": details or {}}


def _overall_status(checks: list[dict[str, Any]]) -> AuditStatus:
    if any(check["status"] == "failed" for check in checks):
        return "failed"
    if any(check["status"] == "warning" for check in checks):
        return "warning"
    return "passed"


def _max_status(left: AuditStatus, right: AuditStatus) -> AuditStatus:
    order = {"passed": 0, "warning": 1, "failed": 2}
    return left if order[left] >= order[right] else right


def _near(left: float, right: float, *, abs_tol: float = 0.01, rel_tol: float = 1e-6) -> bool:
    return isclose(float(left or 0), float(right or 0), rel_tol=rel_tol, abs_tol=abs_tol)


def _sanitize_payload(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized = {}
        for key, item in value.items():
            key_text = str(key)
            if _is_sensitive_key(key_text):
                sanitized["redacted"] = "<redacted>"
            else:
                sanitized[key_text] = _sanitize_payload(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_payload(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_payload(item) for item in value]
    if isinstance(value, str):
        return _sanitize_text(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower()
    return any(marker in normalized for marker in SENSITIVE_KEYS)


def _sanitize_text(value: str) -> str:
    sanitized = value
    for marker in ("/Volumes/", "/Users/", "/private/", "\\Users\\"):
        if marker in sanitized:
            sanitized = sanitized.replace(marker, "<local-path>/")
    lowered = sanitized.lower()
    if any(marker in lowered for marker in ("webhook", "token", "password", "license", "secret")):
        return "<redacted>"
    return sanitized


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    return str(value)


__all__ = ["BacktestTrustAuditError", "build_backtest_trust_audit", "render_audit_markdown"]
