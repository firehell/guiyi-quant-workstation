from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import logging
from pathlib import Path
import sys
import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.data_center import Contract, DataQualityReport, MarketDataFile
from app.schemas.market import (
    MarketMacdIndicatorPoint,
    MarketBarsCoverage,
    MarketBarsQuality,
    MarketBarsRequest,
    MarketBarsResponse,
    MarketMacdIndicatorResponse,
    MarketReadLineage,
    MarketCoverageContract,
    MarketCoverageInstrument,
    MarketCoverageItem,
    MarketCoveragePeriod,
    MarketCoverageSummary,
    MarketWorkbenchCoverage,
    MarketWorkbenchSelection,
)
from app.services.market_data_reader import MarketDataReader
from app.services.futures_contract_utils import continuous_contract_for, is_continuous_contract
from app.services.market_dominant_reader import DEFAULT_QUOTE_PERIOD, validate_quote_contract
from app.services.profile_lineage import ProfileLineage, ProfileLineageResolver

QUANT_CORE_ROOT = Path(__file__).resolve().parents[4] / "packages" / "quant-core"
if QUANT_CORE_ROOT.exists() and str(QUANT_CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(QUANT_CORE_ROOT))

PERIOD_ORDER = {"1m": 0, "5m": 1, "15m": 2, "30m": 3, "60m": 4, "1d": 5, "1w": 6}
WEB_MACD_LEGACY_V1_POLICY = "web_macd_legacy_v1"
logger = logging.getLogger(__name__)

MARKET_ACCESS_MODES = frozenset({"browser", "research"})


class MarketAccessError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 422, context: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.context = context or {}

    def detail(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "context": self.context}


@dataclass(frozen=True)
class MarketReadContext:
    access_mode: str
    profile_lineage: ProfileLineage | None
    market_files: list[MarketDataFile]
    lineage: MarketReadLineage


def get_workbench_coverage(
    session: Session,
    *,
    symbol: str | None = None,
    contract: str | None = None,
    period: str | None = None,
    include_paths: bool = False,
    summary: bool = False,
    profile_id: str | None = None,
    access_mode: str = "browser",
) -> MarketWorkbenchCoverage | MarketCoverageSummary:
    started = time.perf_counter()
    reader = MarketDataReader(session)
    db_started = time.perf_counter()
    if access_mode == "research" and not (symbol and contract and period):
        raise MarketAccessError(
            "MARKET_RESEARCH_PROFILE_REQUIRED",
            "strict market research coverage requires symbol, contract, period and profile_id",
            context={"profile_id": profile_id},
        )
    if (profile_id or access_mode == "research") and symbol and contract and period:
        context = resolve_market_read_context(
            session,
            symbol=symbol,
            contract=contract,
            period=period,
            provider=None,
            data_role=None,
            profile_id=profile_id,
            access_mode=access_mode,
        )
        lineage = context.profile_lineage
        files = context.market_files
    else:
        lineage = None
        files = reader.get_coverage(symbol=symbol, contract=contract, period=period)
    db_ms = (time.perf_counter() - db_started) * 1000
    files = [item for item in files if item.instrument_symbol and item.contract_code and item.period]
    items = _aggregate_items(session, files, include_paths=include_paths, lineage=lineage)

    if summary and symbol and contract and period:
        result = _coverage_summary(symbol=symbol, contract=contract, period=period, items=items, lineage=lineage)
        _log_workbench_coverage(
            symbol=symbol,
            contract=contract,
            period=period,
            file_count=len(files),
            item_count=len(items),
            db_ms=db_ms,
            started=started,
            summary=True,
        )
        return result

    result = MarketWorkbenchCoverage(
        instruments=_group_instruments(items, include_paths=include_paths),
        items=items,
        default_selection=_default_selection(items),
    )
    _log_workbench_coverage(
        symbol=symbol,
        contract=contract,
        period=period,
        file_count=len(files),
        item_count=len(items),
        db_ms=db_ms,
        started=started,
        summary=False,
    )
    return result


def _coverage_summary(
    *,
    symbol: str,
    contract: str,
    period: str,
    items: list[MarketCoverageItem],
    lineage: ProfileLineage | None = None,
) -> MarketCoverageSummary:
    if not items:
        return MarketCoverageSummary(
            symbol=symbol,
            contract=contract,
            period=period,
            available=False,
            profile_id=lineage.profile_id if lineage else None,
            quality_policy=lineage.quality_policy if lineage else None,
            market_data_file_id=lineage.market_data_file_id if lineage else None,
            binding_snapshot=lineage.binding_snapshot if lineage else None,
            blocked_reason=lineage.blocked_reason if lineage else None,
        )
    item = items[0]
    return MarketCoverageSummary(
        symbol=item.symbol,
        contract=item.contract,
        period=item.period,
        available=True,
        provider=item.provider,
        start_time=item.start_time,
        end_time=item.end_time,
        row_count=item.row_count,
        quality_status=item.quality_status,
        profile_id=item.profile_id,
        quality_policy=item.quality_policy,
        market_data_file_id=item.market_data_file_id,
        binding_snapshot=item.binding_snapshot,
    )


def _log_workbench_coverage(
    *,
    symbol: str | None,
    contract: str | None,
    period: str | None,
    file_count: int,
    item_count: int,
    db_ms: float,
    started: float,
    summary: bool,
) -> None:
    total_ms = (time.perf_counter() - started) * 1000
    logger.info(
        "workbench_coverage symbol=%s contract=%s period=%s summary=%s files=%d items=%d db_ms=%.1f total_ms=%.1f",
        symbol,
        contract,
        period,
        summary,
        file_count,
        item_count,
        db_ms,
        total_ms,
    )
    if total_ms >= 5000:
        logger.warning(
            "slow workbench_coverage total_ms=%.1f symbol=%s contract=%s period=%s",
            total_ms,
            symbol,
            contract,
            period,
        )
    elif total_ms >= 1000:
        logger.info(
            "slow workbench_coverage total_ms=%.1f symbol=%s contract=%s period=%s",
            total_ms,
            symbol,
            contract,
            period,
        )


def get_market_bars(
    session: Session,
    *,
    symbol: str,
    contract: str,
    period: str,
    start: datetime | None,
    end: datetime | None,
    provider: str | None,
    data_role: str | None,
    limit: int,
    quote_mode: bool = False,
    allow_continuous: bool = False,
    tail: bool = True,
    profile_id: str | None = None,
    access_mode: str = "browser",
    expected_market_data_file_id: int | None = None,
    expected_lineage_token: str | None = None,
) -> MarketBarsResponse:
    if quote_mode and not allow_continuous:
        validate_quote_contract(contract)
    context = resolve_market_read_context(
        session,
        symbol=symbol,
        contract=contract,
        period=period,
        provider=provider,
        data_role=data_role,
        profile_id=profile_id,
        access_mode=access_mode,
        expected_market_data_file_id=expected_market_data_file_id,
        expected_lineage_token=expected_lineage_token,
    )
    lineage = context.profile_lineage
    coverage = _coverage_for_request(
        session,
        symbol=symbol,
        contract=contract,
        period=period,
        provider=provider,
        data_role=data_role,
        lineage=lineage,
        market_files=context.market_files,
    )
    start_time = start or coverage.start_time if coverage else start
    end_time = end or coverage.end_time if coverage else end
    query_start = _naive(start_time or datetime.min)
    query_end = _naive(end_time or datetime.max)
    if access_mode == "research":
        research_file = context.market_files[0]
        _validate_research_range(
            research_file,
            query_start,
            query_end,
            symbol=symbol,
            contract=contract,
            period=period,
            profile_id=profile_id,
        )
        if query_start.time() == datetime.min.time() and query_start.date() == _naive(research_file.start_time).date():
            query_start = _naive(research_file.start_time)
        if query_end.time() == datetime.max.time() and query_end.date() == _naive(research_file.end_time).date():
            query_end = _naive(research_file.end_time)
    reader = MarketDataReader(session)
    if len(context.market_files) == 1 and profile_id:
        market_file = context.market_files[0]
        bars = reader.load_bars_from_market_file(
            market_data_file_id=market_file.id,
            symbol=symbol,
            contract=contract,
            period=period,
            start=query_start,
            end=query_end,
            passed_only=access_mode == "research",
            expected_provider=market_file.provider,
            expected_data_role="primary",
            expected_quality_status=market_file.quality_status,
            expected_data_version=market_file.data_version,
            expected_checksum=market_file.checksum,
            limit=limit,
            tail=tail,
        )
    else:
        bars = reader.load_bars(
            symbol=symbol,
            contract=contract,
            period=period,
            start=query_start,
            end=query_end,
            provider=provider,
            data_role=data_role,
            limit=limit,
            tail=tail,
        )
    quality = _quality_for_lineage(session, lineage) if lineage else MarketDataReader(session).get_quality_status(
        symbol=symbol,
        contract=contract,
        period=period,
        start=query_start,
        end=query_end,
        provider=provider,
        data_role=data_role,
    )
    message = None if bars else "当前选择没有可展示的 K 线"
    if lineage and lineage.blocked:
        message = f"profile binding blocked: {lineage.blocked_reason}"
    if bars and quality.get("status") == "warning":
        reasons = quality.get("warning_reasons") or []
        cross_conflicts = quality.get("cross_file_conflicts", 0)
        conflict_reason = f"cross_file_conflicts={cross_conflicts}"
        if cross_conflicts > 0 and conflict_reason not in reasons:
            reasons = list(reasons) + [conflict_reason]
        reason_text = f"（{', '.join(reasons)}）" if reasons else ""
        message = f"数据质量 warning{reason_text}，仅供观察，不可用于严格研究/回测/信号"
    elif bars and quality.get("cross_file_conflicts", 0) > 0:
        cross_conflicts = quality.get("cross_file_conflicts", 0)
        message = f"检测到 {cross_conflicts} 个跨文件数据冲突，请检查数据源"
    return MarketBarsResponse(
        bars=bars,
        quality=MarketBarsQuality(**quality),
        coverage=coverage,
        request=MarketBarsRequest(
            symbol=symbol,
            contract=contract,
            period=period,
            start=start_time,
            end=end_time,
            provider=provider,
            data_role=data_role,
            profile_id=profile_id,
            access_mode=access_mode,
            expected_market_data_file_id=expected_market_data_file_id,
            expected_lineage_token=expected_lineage_token,
            limit=limit,
            tail=tail,
        ),
        lineage=context.lineage,
        strict_research_ready=context.lineage.strict_research_ready,
        message=message,
    )


def get_market_macd_indicator(
    session: Session,
    *,
    symbol: str,
    contract: str,
    period: str,
    start: datetime | None,
    end: datetime | None,
    provider: str | None,
    data_role: str | None,
    limit: int,
    quote_mode: bool = False,
    allow_continuous: bool = False,
    tail: bool = True,
    profile_id: str | None = None,
    access_mode: str = "browser",
    expected_market_data_file_id: int | None = None,
    expected_lineage_token: str | None = None,
) -> MarketMacdIndicatorResponse:
    bars_response = get_market_bars(
        session,
        symbol=symbol,
        contract=contract,
        period=period,
        start=start,
        end=end,
        provider=provider,
        data_role=data_role,
        limit=limit,
        quote_mode=quote_mode,
        allow_continuous=allow_continuous,
        tail=tail,
        profile_id=profile_id,
        access_mode=access_mode,
        expected_market_data_file_id=expected_market_data_file_id,
        expected_lineage_token=expected_lineage_token,
    )
    bars = bars_response.bars
    closes = [_bar_close(bar) for bar in bars]
    bar_ends = [_bar_time(bar) for bar in bars]
    result = _macd_series()(
        closes,
        12,
        26,
        9,
        ema_seed_policy="sma_window",
        histogram_scale=2,
        bar_ends=bar_ends,
        round_digits=6,
    )
    histogram_points = _market_indicator_points(result.histogram.points)
    return MarketMacdIndicatorResponse(
        policy=WEB_MACD_LEGACY_V1_POLICY,
        indicator_code=result.indicator_code,
        indicator_version=result.indicator_version,
        parameters=result.parameters,
        basis=result.calculation_basis,
        dif=_market_indicator_points(result.dif.points, ready_mask=result.dea.points),
        dea=_market_indicator_points(result.dea.points),
        histogram=histogram_points,
        source_bar_count=len(bars),
        ready_count=sum(1 for point in histogram_points if point.ready and point.valid and point.value is not None),
        coverage=bars_response.coverage,
        request=bars_response.request,
        lineage=bars_response.lineage,
        strict_research_ready=bars_response.strict_research_ready,
        message=bars_response.message,
    )


def _macd_series():
    from guiyi_quant.indicators import macd_series

    return macd_series


def _bar_close(bar: dict[str, Any]) -> float | None:
    value = bar.get("close")
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and number not in (float("inf"), float("-inf")) else None


def _bar_time(bar: dict[str, Any]) -> str | None:
    value = bar.get("time") or bar.get("datetime")
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _market_indicator_points(points, *, ready_mask=None) -> list[MarketMacdIndicatorPoint]:
    response_points: list[MarketMacdIndicatorPoint] = []
    for index, point in enumerate(points):
        mask = ready_mask[index] if ready_mask is not None else None
        if mask is not None and point.valid and not (mask.ready and mask.valid and mask.value is not None):
            response_points.append(
                MarketMacdIndicatorPoint(
                    time=point.bar_end,
                    value=None,
                    ready=False,
                    valid=True,
                    reason=mask.reason or "warming_up",
                )
            )
            continue
        response_points.append(
            MarketMacdIndicatorPoint(
                time=point.bar_end,
                value=point.value,
                ready=point.ready,
                valid=point.valid,
                reason=point.reason,
            )
        )
    return response_points


def _aggregate_items(
    session: Session,
    files: list[MarketDataFile],
    *,
    include_paths: bool = False,
    lineage: ProfileLineage | None = None,
) -> list[MarketCoverageItem]:
    contracts = {
        item.contract_code: item
        for item in session.scalars(select(Contract).where(Contract.contract_code.in_({file.contract_code for file in files})))
    }
    grouped: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    for file in files:
        key = (file.instrument_symbol or "", file.contract_code or "", file.period or "", file.provider, file.data_type)
        record = grouped.setdefault(
            key,
            {
                "symbol": file.instrument_symbol or "",
                "contract": file.contract_code or "",
                "period": file.period or "",
                "provider": file.provider,
                "data_type": file.data_type,
                "start_time": file.start_time,
                "end_time": file.end_time,
                "row_count": 0,
                "statuses": [],
                "data_versions": [],
                "data_roles": [],
                "file_paths": [],
                "profile_id": lineage.profile_id if lineage else None,
                "quality_policy": lineage.quality_policy if lineage else None,
                "market_data_file_id": lineage.market_data_file_id if lineage else None,
                "binding_snapshot": lineage.binding_snapshot if lineage else None,
            },
        )
        record["start_time"] = min(record["start_time"], file.start_time)
        record["end_time"] = max(record["end_time"], file.end_time)
        record["row_count"] += file.row_count or 0
        record["statuses"].append(file.quality_status)
        record["data_versions"].append(file.data_version)
        record["data_roles"].append(file.data_role)
        record["file_paths"].append(file.file_path)

    items: list[MarketCoverageItem] = []
    for record in grouped.values():
        contract = contracts.get(record["contract"])
        view = _contract_view_metadata(record["symbol"], record["contract"])
        items.append(
            MarketCoverageItem(
                symbol=record["symbol"],
                contract=record["contract"],
                period=record["period"],
                provider=record["provider"],
                data_type=record["data_type"],
                view_role=view["view_role"],
                continuous_contract=view["continuous_contract"],
                actual_contract=view["actual_contract"],
                exchange=contract.exchange_code if contract else None,
                name=contract.name if contract else None,
                start_time=record["start_time"],
                end_time=record["end_time"],
                latest_bar_time=record["end_time"],
                row_count=record["row_count"],
                quality_status=_aggregate_status(record["statuses"]),
                data_version=_join_distinct(record["data_versions"]),
                data_role=_join_distinct(record["data_roles"]),
                file_path=_join_distinct(record["file_paths"]) if include_paths else None,
                profile_id=record["profile_id"],
                quality_policy=record["quality_policy"],
                market_data_file_id=record["market_data_file_id"],
                binding_snapshot=record["binding_snapshot"],
            )
        )
    return sorted(items, key=lambda item: (item.symbol, item.contract, _period_rank(item.period), item.start_time))


def _group_instruments(items: list[MarketCoverageItem], *, include_paths: bool = False) -> list[MarketCoverageInstrument]:
    by_symbol: dict[str, list[MarketCoverageItem]] = defaultdict(list)
    for item in items:
        by_symbol[item.symbol].append(item)

    instruments: list[MarketCoverageInstrument] = []
    for symbol, symbol_items in sorted(by_symbol.items()):
        contract_groups: dict[str, list[MarketCoverageItem]] = defaultdict(list)
        for item in symbol_items:
            contract_groups[item.contract].append(item)
        contracts = [
            MarketCoverageContract(
                contract=contract,
                name=contract_items[0].name,
                exchange=contract_items[0].exchange,
                provider=contract_items[0].provider,
                status=None,
                view_role=contract_items[0].view_role,
                continuous_contract=contract_items[0].continuous_contract,
                actual_contract=contract_items[0].actual_contract,
                periods=[
                    MarketCoveragePeriod(
                        period=item.period,
                        provider=item.provider,
                        data_type=item.data_type,
                        source_mode=item.source_mode,
                        view_role=item.view_role,
                        continuous_contract=item.continuous_contract,
                        actual_contract=item.actual_contract,
                        start_time=item.start_time,
                        end_time=item.end_time,
                        latest_bar_time=item.latest_bar_time,
                        row_count=item.row_count,
                        quality_status=item.quality_status,
                        data_version=item.data_version,
                        data_role=item.data_role,
                        file_path=item.file_path if include_paths else None,
                    )
                    for item in sorted(contract_items, key=lambda value: _period_rank(value.period))
                ],
            )
            for contract, contract_items in sorted(contract_groups.items())
        ]
        instruments.append(
            MarketCoverageInstrument(
                symbol=symbol,
                name=symbol_items[0].name,
                exchange=symbol_items[0].exchange,
                sector=None,
                contracts=contracts,
            )
        )
    return instruments


def _default_selection(items: list[MarketCoverageItem]) -> MarketWorkbenchSelection | None:
    if not items:
        return None
    actual_items = [item for item in items if not is_continuous_contract(item.contract)]
    preferred = next(
        (
            item
            for item in actual_items
            if item.symbol == "jm" and item.period == DEFAULT_QUOTE_PERIOD and item.quality_status == "passed"
        ),
        None,
    )
    fallback_actual = next((item for item in actual_items if item.period == DEFAULT_QUOTE_PERIOD), None)
    fallback_period = next((item for item in actual_items if item.period == "5m"), None)
    selected = preferred or fallback_actual or fallback_period or (actual_items[0] if actual_items else None)
    if selected is None:
        selected = next((item for item in items if item.symbol == "rb" and item.contract == "rb.MAIN" and item.period == "5m"), None)
    selected = selected or next((item for item in items if item.period == "5m"), None) or items[0]
    return MarketWorkbenchSelection(
        symbol=selected.symbol,
        contract=selected.contract,
        period=selected.period,
        provider=selected.provider,
        profile_id=selected.profile_id,
        start=selected.start_time,
        end=selected.end_time,
    )


def resolve_market_read_context(
    session: Session,
    *,
    symbol: str,
    contract: str,
    period: str,
    provider: str | None,
    data_role: str | None,
    profile_id: str | None,
    access_mode: str,
    expected_market_data_file_id: int | None = None,
    expected_lineage_token: str | None = None,
) -> MarketReadContext:
    if access_mode not in MARKET_ACCESS_MODES:
        raise MarketAccessError("MARKET_ACCESS_MODE_INVALID", "unsupported market access mode", context={"access_mode": access_mode})
    if access_mode == "research" and not profile_id:
        raise MarketAccessError(
            "MARKET_RESEARCH_PROFILE_REQUIRED",
            "strict market research requires an explicit profile_id",
            context={"symbol": symbol, "contract": contract, "period": period},
        )

    reader = MarketDataReader(session)
    profile_lineage: ProfileLineage | None = None
    if profile_id:
        profile_lineage = ProfileLineageResolver(session).resolve(
            consumer="market",
            symbol=symbol,
            contract=contract,
            period=period,
            profile_id=profile_id,
            allow_non_failed_market_quality=access_mode == "browser",
        )
        if profile_lineage.blocked or profile_lineage.market_file is None:
            raise _market_lineage_error(profile_lineage, symbol=symbol, contract=contract, period=period)
        market_files = [profile_lineage.market_file]
    else:
        market_files = reader.find_market_files(
            symbol=symbol,
            contract=contract,
            period=period,
            start=datetime.min,
            end=datetime.max,
            provider=provider,
            data_role=data_role,
        )

    for market_file in market_files:
        _validate_market_file(market_file, reader=reader, symbol=symbol, contract=contract, period=period)
    if access_mode == "research" and market_files:
        market_file = market_files[0]
        if provider is not None and provider != market_file.provider:
            raise _identity_error(symbol, contract, period, profile_id)
        if data_role is not None and data_role != market_file.data_role:
            raise _identity_error(symbol, contract, period, profile_id)

    lineage = _market_read_lineage(
        reader=reader,
        access_mode=access_mode,
        symbol=symbol,
        contract=contract,
        profile_lineage=profile_lineage,
        market_files=market_files,
    )
    if expected_market_data_file_id is not None and lineage.market_data_file_id != expected_market_data_file_id:
        raise _lineage_changed(symbol, contract, period, profile_id)
    if expected_lineage_token is not None and lineage.lineage_token != expected_lineage_token:
        raise _lineage_changed(symbol, contract, period, profile_id)
    if access_mode == "research" and expected_lineage_token is None and expected_market_data_file_id is not None:
        raise _lineage_changed(symbol, contract, period, profile_id)
    return MarketReadContext(
        access_mode=access_mode,
        profile_lineage=profile_lineage,
        market_files=market_files,
        lineage=lineage,
    )


def _market_read_lineage(
    *,
    reader: MarketDataReader,
    access_mode: str,
    symbol: str,
    contract: str,
    profile_lineage: ProfileLineage | None,
    market_files: list[MarketDataFile],
) -> MarketReadLineage:
    assets = [reader.asset_evidence(item) for item in market_files]
    view = _contract_view_metadata(symbol, contract)
    token_payload = {
        "assets": assets,
        "binding_snapshot": profile_lineage.binding_snapshot if profile_lineage else None,
        "profile_id": profile_lineage.profile_id if profile_lineage else None,
    }
    token = hashlib.sha256(json.dumps(token_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    versions = sorted({item.data_version for item in market_files if item.data_version})
    providers = sorted({item.provider for item in market_files})
    roles = sorted({item.data_role for item in market_files})
    statuses = [item.quality_status for item in market_files]
    source_intervals = sorted({str(item["source_interval"]) for item in assets if item.get("source_interval")})
    source_interval_bases = sorted(
        {str(item["source_interval_basis"]) for item in assets if item.get("source_interval_basis")}
    )
    market_file = market_files[0] if len(market_files) == 1 else None
    return MarketReadLineage(
        access_mode=access_mode,
        strict_research_ready=access_mode == "research" and bool(market_files),
        profile_id=profile_lineage.profile_id if profile_lineage else None,
        quality_policy=profile_lineage.quality_policy if profile_lineage else None,
        market_data_file_id=market_file.id if market_file else None,
        market_data_file_ids=[item.id for item in market_files],
        data_version=market_file.data_version if market_file else _join_distinct(versions),
        data_versions=versions,
        provider=providers[0] if len(providers) == 1 else _join_distinct(providers),
        data_role=roles[0] if len(roles) == 1 else _join_distinct(roles),
        quality_status=_aggregate_status(statuses),
        source_interval=(source_intervals[0] if len(source_intervals) == 1 else _join_distinct(source_intervals)),
        source_intervals=source_intervals,
        source_interval_basis=(
            source_interval_bases[0] if len(source_interval_bases) == 1 else _join_distinct(source_interval_bases)
        ),
        binding_snapshot=profile_lineage.binding_snapshot if profile_lineage else None,
        lineage_token=token,
        source_mode="historical",
        view_role=view["view_role"] or "unknown",
        continuous_contract=view["continuous_contract"],
        actual_contract=view["actual_contract"],
        asset_evidence=assets,
    )


def _validate_market_file(
    market_file: MarketDataFile,
    *,
    reader: MarketDataReader,
    symbol: str,
    contract: str,
    period: str,
) -> None:
    if (
        market_file.instrument_symbol != symbol
        or market_file.contract_code != contract
        or market_file.period != period
        or market_file.provider not in {"rqdata", "local_parquet"}
        or market_file.data_role != "primary"
    ):
        raise _identity_error(symbol, contract, period, None)
    if not reader._market_file_path(market_file).is_file():
        raise MarketAccessError(
            "MARKET_PROFILE_FILE_MISSING",
            "market Profile physical file is missing",
            context={"symbol": symbol, "contract": contract, "period": period},
        )


def _validate_research_range(
    market_file: MarketDataFile,
    start: datetime,
    end: datetime,
    *,
    symbol: str,
    contract: str,
    period: str,
    profile_id: str | None,
) -> None:
    file_start = _naive(market_file.start_time)
    file_end = _naive(market_file.end_time)
    start_covered = file_start <= start or (
        start.time() == datetime.min.time() and file_start.date() == start.date()
    )
    end_covered = file_end >= end or (
        end.time() == datetime.max.time() and file_end.date() == end.date()
    )
    if start_covered and end_covered:
        return
    raise MarketAccessError(
        "MARKET_PROFILE_RANGE_NOT_COVERED",
        "market Profile asset does not cover the requested range",
        context={"profile_id": profile_id, "symbol": symbol, "contract": contract, "period": period},
    )


def _market_lineage_error(lineage: ProfileLineage, *, symbol: str, contract: str, period: str) -> MarketAccessError:
    reason_to_code = {
        "profile_not_found": "MARKET_PROFILE_NOT_FOUND",
        "profile_binding_missing": "MARKET_PROFILE_BINDING_MISSING",
        "profile_market_file_missing": "MARKET_PROFILE_FILE_MISSING",
        "profile_quality_failed": "MARKET_PROFILE_QUALITY_BLOCKED",
        "profile_quality_policy_blocked": "MARKET_PROFILE_QUALITY_BLOCKED",
        "profile_identity_mismatch": "MARKET_PROFILE_IDENTITY_MISMATCH",
        "profile_file_missing": "MARKET_PROFILE_FILE_MISSING",
        "profile_lineage_incomplete": "MARKET_PROFILE_LINEAGE_INCOMPLETE",
    }
    code = reason_to_code.get(lineage.blocked_reason or "", "MARKET_PROFILE_IDENTITY_MISMATCH")
    return MarketAccessError(
        code,
        "market Profile lineage resolution was blocked",
        context={"profile_id": lineage.profile_id, "symbol": symbol, "contract": contract, "period": period},
    )


def _identity_error(symbol: str, contract: str, period: str, profile_id: str | None) -> MarketAccessError:
    return MarketAccessError(
        "MARKET_PROFILE_IDENTITY_MISMATCH",
        "market Profile asset identity does not match the request",
        context={"profile_id": profile_id, "symbol": symbol, "contract": contract, "period": period},
    )


def _lineage_changed(symbol: str, contract: str, period: str, profile_id: str | None) -> MarketAccessError:
    return MarketAccessError(
        "MARKET_LINEAGE_CHANGED",
        "market lineage changed after the bars snapshot",
        status_code=409,
        context={"profile_id": profile_id, "symbol": symbol, "contract": contract, "period": period},
    )


def _coverage_for_request(
    session: Session,
    *,
    symbol: str,
    contract: str,
    period: str,
    provider: str | None,
    data_role: str | None,
    lineage: ProfileLineage | None = None,
    market_files: list[MarketDataFile] | None = None,
) -> MarketBarsCoverage | None:
    if market_files is not None:
        files = market_files
    elif lineage is not None:
        files = [] if lineage.market_file is None else [lineage.market_file]
    else:
        files = MarketDataReader(session).get_coverage(symbol=symbol, contract=contract, period=period, data_role=data_role)
    if provider is not None:
        files = [file for file in files if file.provider == provider]
    items = _aggregate_items(session, files, include_paths=True, lineage=lineage)
    if not items:
        return None
    item = items[0]
    return MarketBarsCoverage(
        symbol=item.symbol,
        contract=item.contract,
        period=item.period,
        provider=item.provider,
        data_type=item.data_type,
        view_role=item.view_role,
        continuous_contract=item.continuous_contract,
        actual_contract=item.actual_contract,
        start_time=item.start_time,
        end_time=item.end_time,
        latest_bar_time=item.latest_bar_time,
        row_count=item.row_count,
        quality_status=item.quality_status,
        data_version=item.data_version,
        data_role=item.data_role,
        file_path=item.file_path,
        profile_id=item.profile_id,
        quality_policy=item.quality_policy,
        market_data_file_id=item.market_data_file_id,
        binding_snapshot=item.binding_snapshot,
    )


def _quality_for_lineage(session: Session, lineage: ProfileLineage | None) -> dict[str, Any]:
    market_file = lineage.market_file if lineage else None
    if market_file is None:
        return {
            "status": "blocked" if lineage and lineage.blocked else "unchecked",
            "missing_bars": 0,
            "duplicated_bars": 0,
            "abnormal_price_count": 0,
            "abnormal_volume_count": 0,
            "report_count": 0,
            "warning_reasons": [lineage.blocked_reason] if lineage and lineage.blocked_reason else [],
            "cross_file_conflicts": 0,
            "conflict_details": None,
        }
    reports = list(session.scalars(select(DataQualityReport).where(DataQualityReport.file_id == market_file.id)))
    if not reports:
        return {
            "status": market_file.quality_status,
            "missing_bars": 0,
            "duplicated_bars": 0,
            "abnormal_price_count": 0,
            "abnormal_volume_count": 0,
            "report_count": 0,
            "warning_reasons": [],
            "cross_file_conflicts": 0,
            "conflict_details": None,
        }
    status = "failed" if any(report.status == "failed" for report in reports) else "warning" if any(report.status == "warning" for report in reports) else "passed"
    warning_reasons = []
    if status == "warning":
        warning_reasons = [reason for report in reports for reason in (report.details or {}).get("warning_reasons", [])]
        if not warning_reasons:
            warning_reasons = ["quality_report_warning"]
    return {
        "status": status,
        "missing_bars": sum(report.missing_bars for report in reports),
        "duplicated_bars": sum(report.duplicated_bars for report in reports),
        "abnormal_price_count": sum(report.abnormal_price_count for report in reports),
        "abnormal_volume_count": sum(report.abnormal_volume_count for report in reports),
        "report_count": len(reports),
        "warning_reasons": warning_reasons,
        "cross_file_conflicts": 0,
        "conflict_details": None,
    }


def _aggregate_status(statuses: list[str]) -> str:
    if "failed" in statuses:
        return "failed"
    if "warning" in statuses:
        return "warning"
    if "unchecked" in statuses:
        return "unchecked"
    return "passed" if statuses else "unchecked"


def _period_rank(period: str) -> int:
    return PERIOD_ORDER.get(period, 99)


def _naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _contract_view_metadata(symbol: str, contract: str) -> dict[str, str | None]:
    continuous_contract = continuous_contract_for(symbol) if symbol else None
    if is_continuous_contract(contract):
        return {
            "view_role": "continuous",
            "continuous_contract": contract,
            "actual_contract": None,
        }
    return {
        "view_role": "actual_contract",
        "continuous_contract": continuous_contract,
        "actual_contract": contract,
    }


def _join_distinct(values: list[str | None]) -> str | None:
    normalized = sorted({value for value in values if value})
    if not normalized:
        return None
    return ", ".join(normalized)
