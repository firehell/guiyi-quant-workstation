from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
from time import perf_counter
from typing import Any, Iterable, Mapping, Sequence

import pyarrow.parquet as pq
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backtest.contract_resolver import resolve_jm_contract
from app.backtest.drawdown_curve_generator import generate_drawdown_curve
from app.backtest.equity_curve_generator import generate_equity_curve
from app.backtest.report_metrics import compute_report_metrics
from app.models.data_center import MarketDataFile, ProfileActiveBinding
from app.services.data_profile_registry import ACTIVE_BINDING_STATUS
from app.services.profile_lineage import INTRADAY_RESEARCH_PROFILE, PASSED_ONLY_POLICY, ProfileLineageResolver
from guiyi_quant.strategies.huotian_dayou_strict import (
    HuoTianDaYouStrictStrategy,
    build_normalized_result,
    build_strict_snapshot_series,
    validate_params,
)


TASK_ID = "HTDY-TRUSTED-REPORT-APPLY-PACKET-X502"
GATE = "HTDY_TRUSTED_REPORT_APPLY_PACKET_READY"
SYMBOL = "jm"
CONTRACT = "jm.MAIN"
PERIOD = "15m"
PROTOCOL_RELATIVE_PATH = Path("configs/oos/htdy_strict_validation_protocol_v1.json")
PARAMS_RELATIVE_PATH = Path("packages/quant-core/guiyi_quant/strategies/huotian_dayou_strict/default_params.json")


def packet_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class FrozenProfileSelection:
    profile_id: str
    profile_active_binding_id: int
    market_data_file_id: int
    data_version: str
    relative_path: str
    file_sha256: str
    start: str
    end: str
    row_count: int
    source_interval: str
    provider: str
    data_role: str
    quality_status: str
    quality_policy: str
    binding_status: str
    snapshot_hash: str = ""

    def payload_without_hash(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("snapshot_hash", None)
        return payload

    def payload(self) -> dict[str, Any]:
        return asdict(self)


def freeze_profile_selection(
    session: Session,
    *,
    project_root: Path,
) -> FrozenProfileSelection:
    lineage = ProfileLineageResolver(session, project_root=project_root).resolve(
        consumer="backtest",
        symbol=SYMBOL,
        contract=CONTRACT,
        period=PERIOD,
        profile_id=INTRADAY_RESEARCH_PROFILE,
        allow_warning_quality=False,
    )
    if lineage.blocked:
        raise ValueError(f"formal Profile selection blocked: {lineage.blocked_reason}")
    market_file = lineage.market_file
    if market_file is None:
        raise ValueError("formal Profile selection has no MarketDataFile")
    if lineage.quality_policy != PASSED_ONLY_POLICY:
        raise ValueError(f"formal Profile quality policy must be passed_only, got {lineage.quality_policy}")
    if market_file.data_role != "primary":
        raise ValueError(f"formal Profile file must be primary, got {market_file.data_role}")
    if market_file.quality_status != "passed":
        raise ValueError(f"formal Profile file must be passed, got {market_file.quality_status}")

    bindings = session.scalars(
        select(ProfileActiveBinding).where(
            ProfileActiveBinding.profile_id == INTRADAY_RESEARCH_PROFILE,
            ProfileActiveBinding.instrument_symbol == SYMBOL,
            ProfileActiveBinding.contract_code == CONTRACT,
            ProfileActiveBinding.period == PERIOD,
            ProfileActiveBinding.binding_status == ACTIVE_BINDING_STATUS,
            ProfileActiveBinding.market_data_file_id == market_file.id,
        )
    ).all()
    if len(bindings) != 1:
        raise ValueError(f"formal Profile selection requires exactly one active binding, got {len(bindings)}")
    binding = bindings[0]
    raw_path = Path(market_file.file_path)
    physical_path = raw_path if raw_path.is_absolute() else project_root / raw_path
    if not physical_path.is_file():
        raise ValueError("formal Profile file is missing")

    selection = FrozenProfileSelection(
        profile_id=INTRADAY_RESEARCH_PROFILE,
        profile_active_binding_id=int(binding.id),
        market_data_file_id=int(market_file.id),
        data_version=str(market_file.data_version),
        relative_path=_repository_relative_path(physical_path, project_root),
        file_sha256=file_sha256(physical_path),
        start=market_file.start_time.isoformat(),
        end=market_file.end_time.isoformat(),
        row_count=int(market_file.row_count),
        source_interval=str(lineage.source_interval),
        provider=str(market_file.provider),
        data_role=str(market_file.data_role),
        quality_status=str(market_file.quality_status),
        quality_policy=str(lineage.quality_policy),
        binding_status=str(binding.binding_status),
    )
    return replace(selection, snapshot_hash=packet_hash(selection.payload_without_hash()))


def assert_profile_selection_unchanged(
    before: FrozenProfileSelection,
    after: FrozenProfileSelection,
) -> None:
    if before.payload_without_hash() != after.payload_without_hash() or before.snapshot_hash != after.snapshot_hash:
        raise ValueError("active Profile binding or file changed during X5-02 dry-run")


def _repository_relative_path(path: Path, project_root: Path) -> str:
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        parts = path.resolve().parts
        if "data" in parts:
            return Path(*parts[parts.index("data") :]).as_posix()
        return path.name


@dataclass(frozen=True)
class CanonicalCostDay:
    trading_day: date
    actual_contract: str
    exchange: str
    contract_multiplier: int
    price_tick: float
    margin_rate: float
    fee_type: str
    open_fee: float
    close_fee: float
    close_today_fee: float | None
    parameter_source: str
    main_contract_map_id: int
    main_contract_provider: str
    main_contract_data_version: str
    main_contract_rule: str
    main_contract_rank: int

    def payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["trading_day"] = self.trading_day.isoformat()
        return payload


def build_canonical_cost_timeline(
    session: Session,
    trading_days: Iterable[date],
) -> dict[date, CanonicalCostDay]:
    timeline: dict[date, CanonicalCostDay] = {}
    for trading_day in sorted(set(trading_days)):
        resolved = resolve_jm_contract(session, trading_day=trading_day)
        rule = resolved.commission_rule
        source = resolved.main_contract_source
        timeline[trading_day] = CanonicalCostDay(
            trading_day=trading_day,
            actual_contract=str(resolved.actual_contract),
            exchange=str(resolved.exchange),
            contract_multiplier=int(resolved.contract_multiplier),
            price_tick=float(resolved.price_tick),
            margin_rate=float(resolved.margin_ratio),
            fee_type=str(rule.fee_type),
            open_fee=float(rule.open_fee),
            close_fee=float(rule.close_fee),
            close_today_fee=None if rule.close_today_fee is None else float(rule.close_today_fee),
            parameter_source=str(resolved.parameter_source),
            main_contract_map_id=int(source.map_id),
            main_contract_provider=str(source.provider),
            main_contract_data_version=str(source.data_version),
            main_contract_rule=str(source.rule),
            main_contract_rank=int(source.rank),
        )
    return timeline


def cost_timeline_payload(timeline: Mapping[date, CanonicalCostDay]) -> dict[str, Any]:
    rows = [timeline[day].payload() for day in sorted(timeline)]
    return {
        "schema_version": "htdy_canonical_cost_timeline_x502_v1",
        "task_id": TASK_ID,
        "resolver": "resolve_jm_contract",
        "row_count": len(rows),
        "rows": rows,
        "timeline_hash": packet_hash(rows),
    }


@dataclass
class CandidateBar:
    datetime: datetime
    trading_day: date
    open: float
    high: float
    low: float
    close: float
    volume: float
    price_tick: float
    contract_multiplier: int
    commission_rate: float | None
    commission_per_contract: float | None
    margin_rate: float
    symbol: str
    exchange: str
    contract: str
    fee_type: str
    open_fee: float
    close_fee: float
    close_today_fee: float | None
    parameter_source: str
    main_contract_map_id: int
    main_contract_data_version: str


def build_candidate_bars(
    rows: Sequence[Mapping[str, Any]],
    timeline: Mapping[date, CanonicalCostDay],
    *,
    data_version: str,
) -> list[CandidateBar]:
    bars: list[CandidateBar] = []
    seen_datetimes: set[datetime] = set()
    for index, row in enumerate(rows):
        _validate_source_row(row, data_version=data_version, index=index)
        bar_datetime = _naive_datetime(row["datetime"])
        if bar_datetime in seen_datetimes:
            raise ValueError(f"formal input contains duplicate datetime: {bar_datetime.isoformat()}")
        seen_datetimes.add(bar_datetime)
        trading_day = _as_date(row.get("trading_day"))
        cost = timeline.get(trading_day)
        if cost is None:
            raise ValueError(f"canonical cost timeline missing trading_day={trading_day}")
        open_, high, low, close, volume = (float(row[name]) for name in ("open", "high", "low", "close", "volume"))
        if high < max(open_, close) or low > min(open_, close) or high < low or volume < 0:
            raise ValueError(f"formal input has invalid OHLCV at index {index}")
        bars.append(
            CandidateBar(
                datetime=bar_datetime,
                trading_day=trading_day,
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=volume,
                price_tick=cost.price_tick,
                contract_multiplier=cost.contract_multiplier,
                commission_rate=cost.open_fee if cost.fee_type == "rate" else None,
                commission_per_contract=cost.open_fee if cost.fee_type == "fixed" else None,
                margin_rate=cost.margin_rate,
                symbol=SYMBOL,
                exchange=cost.exchange,
                contract=cost.actual_contract,
                fee_type=cost.fee_type,
                open_fee=cost.open_fee,
                close_fee=cost.close_fee,
                close_today_fee=cost.close_today_fee,
                parameter_source=cost.parameter_source,
                main_contract_map_id=cost.main_contract_map_id,
                main_contract_data_version=cost.main_contract_data_version,
            )
        )
    bars.sort(key=lambda bar: bar.datetime)
    if not bars:
        raise ValueError("formal input window is empty")
    return bars


def _validate_source_row(row: Mapping[str, Any], *, data_version: str, index: int) -> None:
    expected = {
        "provider": "rqdata",
        "source": "rqdata",
        "data_role": "primary",
        "quality_status": "passed",
        "data_version": data_version,
        "symbol": SYMBOL,
        "contract": CONTRACT,
        "period": PERIOD,
    }
    for field, value in expected.items():
        if str(row.get(field)) != value:
            raise ValueError(
                f"formal input lineage mismatch at index {index}: {field} expected={value!r} actual={row.get(field)!r}"
            )


def evaluate_full_window(
    bars: Sequence[CandidateBar],
    *,
    execution_snapshot: FrozenProfileSelection,
    protocol_hash: str,
    parameter_hash: str,
) -> dict[str, Any]:
    started = perf_counter()
    params = validate_params()
    snapshots = build_strict_snapshot_series(bars, params)
    strategy = HuoTianDaYouStrictStrategy(
        None,
        "htdy-trusted-report-x502-dry-run",
        "jm_MAIN.DCE",
        {"_guiyi_strict_snapshots": snapshots},
    )
    for bar in bars:
        strategy.on_bar(bar)
    strategy.finalize_sample_end()
    normalized = build_normalized_result(strategy)
    trades = list(normalized["trades"])
    orders = list(normalized["orders"])
    equity_curve = generate_equity_curve(trades, initial_capital=params.initial_capital)
    drawdown_result = generate_drawdown_curve(equity_curve)
    metrics = compute_report_metrics(
        summary=normalized["summary"],
        trades=trades,
        equity_curve=equity_curve,
        drawdown_curve=drawdown_result["drawdown_curve"],
        start=bars[0].datetime,
        end=bars[-1].datetime,
        default_initial_capital=params.initial_capital,
    )
    losses = [float(trade["net_pnl"]) for trade in trades if float(trade["net_pnl"]) < 0]
    gains = [float(trade["net_pnl"]) for trade in trades if float(trade["net_pnl"]) > 0]
    metrics.update(
        {
            "total_return_pct": metrics["total_return"],
            "profit_factor": sum(gains) / abs(sum(losses)) if losses else 0.0,
            "largest_loss_trade": min(losses) if losses else 0.0,
            "signal_count": sum(
                1 for event in normalized["strategy_execution_events"] if event.get("action") in {"open_long", "open_short"}
            ),
            "no_trade_reasons": _count_values(normalized["warnings"]),
            "fee_totals": metrics["total_commission"],
            "slippage_totals": metrics["total_slippage"],
        }
    )
    return {
        "schema_version": "htdy_trusted_report_full_window_dry_run_x502_v1",
        "task_id": TASK_ID,
        "status": "htdy_trusted_report_full_window_dry_run",
        "strategy_code": params.strategy_code,
        "strategy_version": params.strategy_version,
        "candidate_policy": params.candidate_policy,
        "protocol_hash": protocol_hash,
        "parameter_hash": parameter_hash,
        "execution_snapshot_hash": execution_snapshot.snapshot_hash,
        "data": {
            "row_count": len(bars),
            "start": bars[0].datetime.isoformat(timespec="seconds"),
            "end": bars[-1].datetime.isoformat(timespec="seconds"),
            "trading_days": sorted({bar.trading_day.isoformat() for bar in bars}),
            "data_version": execution_snapshot.data_version,
            "market_data_file_id": execution_snapshot.market_data_file_id,
            "profile_active_binding_id": execution_snapshot.profile_active_binding_id,
        },
        "summary": metrics,
        "trades": trades,
        "orders": orders,
        "strategy_execution_events": normalized["strategy_execution_events"],
        "warnings": normalized["warnings"],
        "equity_curve": equity_curve,
        "drawdown_curve": drawdown_result["drawdown_curve"],
        "runner": {
            "complexity_mode": "single_full_window_vector_then_linear_event_loop",
            "strict_vector_evaluations": 1,
            "duration_ms": round((perf_counter() - started) * 1000, 3),
        },
        "boundaries": {
            "readonly": True,
            "would_write_db": False,
            "would_create_backtest_report": False,
            "would_touch_report14": False,
            "would_run_oos": False,
            "would_send_notification": False,
            "would_place_order": False,
        },
    }


def build_preapply_audit(
    dry_run: Mapping[str, Any],
    *,
    execution_snapshot: FrozenProfileSelection,
    cost_payload: Mapping[str, Any],
    expected_trading_days: set[date],
) -> dict[str, Any]:
    blocked: list[str] = []
    trades = list(dry_run.get("trades") or [])
    orders = list(dry_run.get("orders") or [])
    summary = dict(dry_run.get("summary") or {})
    if summary.get("trade_count") != len(trades):
        blocked.append(f"trade_count mismatch: summary={summary.get('trade_count')} rows={len(trades)}")
    if len(orders) != len(trades) * 2:
        blocked.append(f"order_count mismatch: orders={len(orders)} trades={len(trades)}")
    total_commission = sum(float(trade.get("commission") or 0) for trade in trades)
    total_slippage = sum(float(trade.get("slippage") or 0) for trade in trades)
    if not _near(total_commission, summary.get("total_commission")):
        blocked.append("total_commission does not match trade rows")
    if not _near(total_slippage, summary.get("total_slippage")):
        blocked.append("total_slippage does not match trade rows")
    expected_day_text = {day.isoformat() for day in expected_trading_days}
    data_days = set((dry_run.get("data") or {}).get("trading_days") or [])
    cost_days = {str(row.get("trading_day")) for row in cost_payload.get("rows") or []}
    if data_days != expected_day_text or cost_days != expected_day_text:
        blocked.append("canonical cost timeline does not cover the exact full-window trading days")
    if execution_snapshot.data_role != "primary" or execution_snapshot.quality_status != "passed":
        blocked.append("execution snapshot is not primary/passed")
    if execution_snapshot.binding_status != "active":
        blocked.append("execution snapshot binding is not active")
    boundaries = dict(dry_run.get("boundaries") or {})
    for field in ("would_write_db", "would_touch_report14", "would_run_oos", "would_send_notification", "would_place_order"):
        if boundaries.get(field) is not False:
            blocked.append(f"boundary violation: {field} must be false")
    encoded = json.dumps(dry_run, ensure_ascii=False, sort_keys=True, default=str)
    for marker in ("/Users/", "/Volumes/", "/private/", "QYWX_WEBHOOK_URL", "password", "token", "secret"):
        if marker in encoded:
            blocked.append(f"sensitive output marker present: {marker}")
    checks = {
        "profile_binding": "passed" if execution_snapshot.binding_status == "active" else "failed",
        "data_lineage": "passed" if execution_snapshot.data_role == "primary" and execution_snapshot.quality_status == "passed" else "failed",
        "canonical_cost_coverage": "passed" if data_days == expected_day_text == cost_days else "failed",
        "trade_order_consistency": "passed" if summary.get("trade_count") == len(trades) and len(orders) == len(trades) * 2 else "failed",
        "fee_slippage_consistency": "passed" if _near(total_commission, summary.get("total_commission")) and _near(total_slippage, summary.get("total_slippage")) else "failed",
        "zero_write_boundary": "passed" if not any(boundaries.get(field) for field in boundaries if field.startswith("would_")) else "failed",
        "sensitive_output": "passed" if not any("sensitive output" in reason for reason in blocked) else "failed",
    }
    return {
        "schema_version": "htdy_preapply_audit_x502_v1",
        "task_id": TASK_ID,
        "audit_status": "passed" if not blocked else "failed",
        "checks": checks,
        "blocked_reasons": blocked,
        "readonly": True,
        "would_write_db": False,
        "post_apply_backtest_trust_audit_required": True,
    }


def _count_values(values: Sequence[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value)
        counts[key] = counts.get(key, 0) + 1
    return counts


def _naive_datetime(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    return parsed.replace(tzinfo=None)


def _as_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value is None:
        raise ValueError("formal input missing trading_day")
    return date.fromisoformat(str(value)[:10])


def _near(left: Any, right: Any, tolerance: float = 1e-8) -> bool:
    try:
        return abs(float(left) - float(right)) <= tolerance
    except (TypeError, ValueError):
        return False


def build_apply_packet(
    *,
    source_commit: str,
    protocol_hash: str,
    parameter_hash: str,
    execution_snapshot_hash: str,
    cost_timeline_hash: str,
    dry_run_hash: str,
    preapply_audit_hash: str,
) -> dict[str, Any]:
    packet: dict[str, Any] = {
        "schema_version": "htdy_trusted_report_apply_packet_x502_v1",
        "task_id": TASK_ID,
        "handbook_task": "X5-02",
        "gate": GATE,
        "packet_status": "READY_FOR_USER_APPROVAL",
        "source_commit": source_commit,
        "protocol_hash": protocol_hash,
        "parameter_hash": parameter_hash,
        "execution_snapshot_hash": execution_snapshot_hash,
        "cost_timeline_hash": cost_timeline_hash,
        "dry_run_hash": dry_run_hash,
        "preapply_audit_hash": preapply_audit_hash,
        "expected_writes": {
            "would_write_db": False,
            "would_modify_profile_binding": False,
            "would_modify_parquet": False,
            "would_touch_report14": False,
            "would_run_oos": False,
            "would_send_notification": False,
            "would_place_order": False,
        },
        "next_gate": {
            "requires_separate_task": True,
            "requires_explicit_database_write_approval": True,
            "requires_post_write_backtest_trust_audit": True,
        },
    }
    packet["packet_hash"] = packet_hash(packet)
    return packet


def verify_packet_hash(packet: Mapping[str, Any]) -> bool:
    payload = dict(packet)
    expected = str(payload.pop("packet_hash", ""))
    return bool(expected) and expected == packet_hash(payload)


def load_protocol_context(repo_root: Path) -> dict[str, Any]:
    protocol_path = repo_root / PROTOCOL_RELATIVE_PATH
    params_path = repo_root / PARAMS_RELATIVE_PATH
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    params = json.loads(params_path.read_text(encoding="utf-8"))
    protocol_hash = hashlib.sha256(protocol_path.read_bytes()).hexdigest()
    parameter_hash = packet_hash(params)
    if protocol.get("freeze_status") != "final_frozen":
        raise ValueError("HTDY validation protocol must remain final_frozen")
    if protocol.get("parameter_hash") != parameter_hash:
        raise ValueError("HTDY parameter hash does not match frozen validation protocol")
    frozen = protocol.get("frozen_strategy") or {}
    if frozen.get("strategy_code") != "huotian_dayou_strict" or frozen.get("period") != PERIOD:
        raise ValueError("HTDY frozen strategy identity is invalid")
    return {
        "protocol": protocol,
        "protocol_hash": protocol_hash,
        "parameter_hash": parameter_hash,
    }


def generate_trusted_report_bundle(
    session: Session,
    *,
    repo_root: Path,
) -> dict[str, Any]:
    context = load_protocol_context(repo_root)
    protocol = context["protocol"]
    before = freeze_profile_selection(session, project_root=repo_root)
    market_file = session.get(MarketDataFile, before.market_data_file_id)
    if market_file is None:
        raise ValueError("frozen MarketDataFile disappeared before dry-run")
    raw_path = Path(market_file.file_path)
    source_path = raw_path if raw_path.is_absolute() else repo_root / raw_path
    rows = _read_full_window_rows(
        source_path,
        start=_naive_datetime(protocol["frozen_data_policy"]["full_window_start"]),
        end=_naive_datetime(protocol["frozen_data_policy"]["full_window_end"]),
    )
    trading_days = {_as_date(row.get("trading_day")) for row in rows}
    timeline = build_canonical_cost_timeline(session, trading_days)
    if set(timeline) != trading_days:
        raise ValueError("canonical cost timeline is incomplete")
    bars = build_candidate_bars(rows, timeline, data_version=before.data_version)
    dry_run = evaluate_full_window(
        bars,
        execution_snapshot=before,
        protocol_hash=context["protocol_hash"],
        parameter_hash=context["parameter_hash"],
    )
    cost_payload = cost_timeline_payload(timeline)
    audit = build_preapply_audit(
        dry_run,
        execution_snapshot=before,
        cost_payload=cost_payload,
        expected_trading_days=trading_days,
    )
    session.expire_all()
    after = freeze_profile_selection(session, project_root=repo_root)
    assert_profile_selection_unchanged(before, after)
    if audit["audit_status"] != "passed":
        raise ValueError(f"X5-02 pre-apply audit failed: {audit['blocked_reasons']}")
    return {
        "protocol_hash": context["protocol_hash"],
        "parameter_hash": context["parameter_hash"],
        "execution_snapshot": before,
        "cost_payload": cost_payload,
        "dry_run": dry_run,
        "preapply_audit": audit,
    }


def _read_full_window_rows(path: Path, *, start: datetime, end: datetime) -> list[dict[str, Any]]:
    columns = [
        "datetime",
        "trading_day",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "provider",
        "source",
        "data_role",
        "quality_status",
        "data_version",
        "symbol",
        "contract",
        "period",
    ]
    table = pq.ParquetFile(path).read(columns=columns)
    rows = [
        row
        for row in table.to_pylist()
        if start <= _naive_datetime(row["datetime"]) <= end
    ]
    if not rows:
        raise ValueError("HTDY frozen full window has no bars")
    return rows


def write_artifact_bundle(
    output_dir: Path,
    *,
    source_commit: str,
    protocol_hash: str,
    parameter_hash: str,
    execution_snapshot: FrozenProfileSelection,
    cost_payload: Mapping[str, Any],
    dry_run: Mapping[str, Any],
    preapply_audit: Mapping[str, Any],
) -> dict[str, Any]:
    if preapply_audit.get("audit_status") != "passed":
        raise ValueError("cannot write Ready apply packet when pre-apply audit is not passed")
    output_dir.mkdir(parents=True, exist_ok=True)
    payloads: dict[str, tuple[str, Mapping[str, Any]]] = {
        "execution_snapshot": ("execution_input_snapshot.json", execution_snapshot.payload()),
        "canonical_cost_timeline": ("canonical_cost_timeline.json", cost_payload),
        "full_window_dry_run": ("full_window_dry_run.json", dry_run),
        "preapply_audit": ("preapply_audit.json", preapply_audit),
    }
    artifacts: dict[str, dict[str, str]] = {}
    for name, (filename, payload) in payloads.items():
        path = output_dir / filename
        _write_json(path, payload)
        artifacts[name] = {"path": filename, "sha256": file_sha256(path)}

    markdown_path = output_dir / "HTDY_TRUSTED_REPORT_APPLY_PACKET.md"
    markdown_path.write_text(_render_markdown(dry_run, preapply_audit), encoding="utf-8")
    artifacts["review_markdown"] = {
        "path": markdown_path.name,
        "sha256": file_sha256(markdown_path),
    }
    packet = build_apply_packet(
        source_commit=source_commit,
        protocol_hash=protocol_hash,
        parameter_hash=parameter_hash,
        execution_snapshot_hash=execution_snapshot.snapshot_hash,
        cost_timeline_hash=packet_hash(cost_payload),
        dry_run_hash=packet_hash(dry_run),
        preapply_audit_hash=packet_hash(preapply_audit),
    )
    packet.pop("packet_hash")
    packet["artifacts"] = artifacts
    packet["packet_hash"] = packet_hash(packet)
    packet_path = output_dir / "HTDY_TRUSTED_REPORT_APPLY_PACKET.json"
    _write_json(packet_path, packet)
    return packet


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False, default=str) + "\n",
        encoding="utf-8",
    )


def _render_markdown(dry_run: Mapping[str, Any], audit: Mapping[str, Any]) -> str:
    summary = dry_run.get("summary") or {}
    data = dry_run.get("data") or {}
    return "\n".join(
        [
            "# HTDY X5-02 Trusted Report Apply Packet",
            "",
            f"- Gate: `{GATE}`",
            "- Packet status: `READY_FOR_USER_APPROVAL`",
            f"- Pre-apply audit: `{audit.get('audit_status')}`",
            f"- Data version: `{data.get('data_version')}`",
            f"- Window: `{data.get('start')}` -> `{data.get('end')}`",
            f"- Bars: `{data.get('row_count')}`",
            f"- Trades: `{summary.get('trade_count')}`",
            f"- Total return: `{summary.get('total_return')}`",
            f"- Max drawdown: `{summary.get('max_drawdown_pct')}`",
            f"- Total commission: `{summary.get('total_commission')}`",
            f"- Total slippage: `{summary.get('total_slippage')}`",
            "",
            "## Boundary",
            "",
            "- Read-only dry-run; no BacktestTask or BacktestReport was created.",
            "- No canonical DB, Profile binding, Parquet, report14, OOS, live, notification, or order write is authorized.",
            "- Formal report apply requires a separate task, explicit database-write approval, and post-write trust audit.",
            "",
        ]
    )


__all__ = [
    "CanonicalCostDay",
    "CandidateBar",
    "FrozenProfileSelection",
    "GATE",
    "TASK_ID",
    "build_apply_packet",
    "assert_profile_selection_unchanged",
    "build_candidate_bars",
    "build_canonical_cost_timeline",
    "cost_timeline_payload",
    "build_preapply_audit",
    "evaluate_full_window",
    "file_sha256",
    "freeze_profile_selection",
    "packet_hash",
    "verify_packet_hash",
    "generate_trusted_report_bundle",
    "load_protocol_context",
    "write_artifact_bundle",
]
